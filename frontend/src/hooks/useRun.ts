// 管理 thread 的运行、状态、当前节点与中断。
//
// 核心流程：
//   start(threadId)  → 启动新 run（无 resume），graph 会在首个 interrupt 暂停
//   refresh()        → 拉取 state，提取 interrupt，更新当前节点
//   resume(value)    → 用 Command(resume=value) 恢复 run，结束后再 refresh
//
// 当前执行节点来自流式 updates 事件；中断来自 getState().tasks[].interrupts。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  extractInterrupt,
  getThreadState,
  joinRunStream,
  listActiveRuns,
  replayFromCheckpoint,
  runStream,
  type CurrentInterrupt,
  type StreamEvent,
} from "../lib/langgraph";
import { EMPTY_NOVEL_STATE, type NovelState } from "../lib/types";

export interface UseRunResult {
  state: NovelState;
  currentNode: string;
  interrupt: CurrentInterrupt | null;
  running: boolean;
  error: string | null;
  /** LLM 流式输出的增量内容（打字机效果） */
  streamingContent: string;
  /** 当前正在输出内容的节点名 */
  streamingNode: string;
  /** 当前已加载的 state 属于哪个 thread（用于上层判断 state 归属，避免串台回填） */
  stateThreadId: string | null;
  /** 拉取当前 thread state 并提取 interrupt */
  refresh: () => Promise<void>;
  /** 启动一次新 run（新 thread 会立刻在 collect_user_inputs 中断） */
  start: () => Promise<void>;
  /** 从当前 interrupt 恢复 */
  resume: (value: unknown) => Promise<void>;
  /** 从指定 checkpoint 重跑（同线程 replay） */
  replay: (checkpointId: string) => Promise<void>;
  /** 清空状态（切换小说时） */
  reset: () => void;
}

export function useRun(threadId: string | null): UseRunResult {
  const [state, setState] = useState<NovelState>(EMPTY_NOVEL_STATE);
  const [currentNode, setCurrentNode] = useState("");
  const [interrupt, setInterrupt] = useState<CurrentInterrupt | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingNode, setStreamingNode] = useState("");
  // 上一次渲染的 threadId，用于在 render 期检测小说切换并同步重置展示状态
  const [prevThreadId, setPrevThreadId] = useState(threadId);
  // 🔒 运行状态隔离：记录当前正在运行的 threadId
  // 防止小说 A 在运行时，切换到小说 B 却显示 running 状态
  const runningThreadIdRef = useRef<string | null>(null);
  // 防止并发 run
  const runningRef = useRef(false);
  // 用 ref 存储流式状态的最新值，避免闭包捕获过时状态（解决 P0 stale closure）
  const streamingStateRef = useRef({ node: "", content: "" });
  // 🔒 记录最新选中的 threadId（render 期赋值），供异步回调判断是否已切换小说
  const latestThreadIdRef = useRef<string | null>(threadId);
  latestThreadIdRef.current = threadId;
  // 当前已加载的 state 属于哪个 thread；用于上层回填时判断归属
  const stateThreadIdRef = useRef<string | null>(null);

  // 切换小说时同步重置展示状态（render 期），避免本次提交残留上一本小说的 state 污染回填
  if (threadId !== prevThreadId) {
    setPrevThreadId(threadId);
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setError(null);
    setStreamingContent("");
    setStreamingNode("");
    streamingStateRef.current = { node: "", content: "" };
    stateThreadIdRef.current = null;
    // 不是正在运行此 thread → 重置 running 展示
    if (threadId !== runningThreadIdRef.current) {
      setRunning(false);
      runningRef.current = false;
    }
  }

  /**
   * 共享的流式事件处理器（解决 P2 代码重复）
   * 所有流式入口（start/resume/replay/join）都使用这个统一的处理器
   * 使用 ref 读取最新值，避免闭包捕获问题
   */
  const handleStreamEvent = useCallback((e: StreamEvent) => {
    if (e.event === "updates") {
      setCurrentNode(e.node);
      // 节点切换时清空流式内容
      if (e.node && e.node !== streamingStateRef.current.node) {
        streamingStateRef.current.node = e.node;
        streamingStateRef.current.content = "";
        setStreamingNode(e.node);
        setStreamingContent("");
      }
    }
    if (e.event === "message_chunk") {
      // 如果节点变了，先清空再追加
      if (e.node && e.node !== streamingStateRef.current.node) {
        streamingStateRef.current.node = e.node;
        streamingStateRef.current.content = e.data.content;
        setStreamingNode(e.node);
        setStreamingContent(e.data.content);
      } else {
        streamingStateRef.current.content += e.data.content;
        setStreamingContent(streamingStateRef.current.content);
      }
    }
    if (e.event === "error") {
      setError(`运行错误：${JSON.stringify(e.data)}`);
    }
  }, []); // 无外部依赖 — 使用 ref 读取最新值，彻底解决 stale closure

  const refresh = useCallback(async () => {
    if (!threadId) return;
    try {
      const st = await getThreadState(threadId);
      // 🔒 await 期间可能已切换小说，丢弃陈旧结果，避免污染当前选中小说
      if (latestThreadIdRef.current !== threadId) return;
      const values = (st.values ?? {}) as Partial<NovelState>;
      setState({ ...EMPTY_NOVEL_STATE, ...values });
      stateThreadIdRef.current = threadId;
      const it = extractInterrupt(st);
      setInterrupt(it);
      // 中断时，当前节点取 next（待执行的节点）；运行中由 updates 维护
      if (it) {
        const next = (st as { next?: string[] }).next ?? [];
        if (next.length) setCurrentNode(next[0]);
        // payload 自描述（带 type + 富表单上下文），无需再调 getSubgraphState 取子图 state。
      } else {
        // 此 thread 已在流式中，避免重复 join
        if (runningThreadIdRef.current === threadId) return;
        // 无中断 — 检查后台是否有正在运行的 run（页面刷新后恢复 running 状态）
        const activeRuns = await listActiveRuns(threadId);
        // 🔒 await 期间可能已切换小说
        if (latestThreadIdRef.current !== threadId) return;
        if (activeRuns.length > 0) {
          setRunning(true);
          runningRef.current = true;
          runningThreadIdRef.current = threadId;
          // 切换小说后丢弃旧 run 的流式事件，避免串台
          const onEvent = (e: StreamEvent) => {
            if (latestThreadIdRef.current !== threadId) return;
            handleStreamEvent(e);
          };
          try {
            await joinRunStream(threadId, activeRuns[0].run_id, onEvent);
          } catch (e) {
            if (latestThreadIdRef.current === threadId) {
              setError(`等待运行完成失败：${(e as Error).message}`);
            }
          } finally {
            // 清运行标记按运行身份判断；改 running 展示按当前查看判断
            if (runningThreadIdRef.current === threadId) {
              runningRef.current = false;
              runningThreadIdRef.current = null;
            }
            if (latestThreadIdRef.current === threadId) setRunning(false);
          }
          // run 结束后重新拉取状态（可能已产生新中断）
          await refresh();
          return;
        }
      }
      if (latestThreadIdRef.current === threadId) setError(null);
    } catch (e) {
      if (latestThreadIdRef.current === threadId) {
        setError(`获取状态失败：${(e as Error).message}`);
      }
    }
  }, [threadId, handleStreamEvent]);

  // 切换 thread 时拉取新小说状态（展示状态的重置已在 render 期同步完成）
  useEffect(() => {
    if (threadId) void refresh();
  }, [threadId, refresh]);

  const start = useCallback(async () => {
    if (!threadId || runningRef.current) return;
    runningRef.current = true;
    runningThreadIdRef.current = threadId;
    setRunning(true);
    setError(null);
    // 重置流式状态（包括 ref）
    streamingStateRef.current = { node: "", content: "" };
    setStreamingContent("");
    setStreamingNode("");
    // 切换小说后丢弃旧 run 的流式事件，避免串台
    const onEvent = (e: StreamEvent) => {
      if (latestThreadIdRef.current !== threadId) return;
      handleStreamEvent(e);
    };
    try {
      // 新 run 必须传非 null 的 input（{}），否则平台报 EmptyInputError
      await runStream(threadId, onEvent, { input: {} });
      await refresh();
    } catch (e) {
      if (latestThreadIdRef.current === threadId) {
        setError(`启动失败：${(e as Error).message}`);
      }
    } finally {
      // 清运行标记按运行身份判断；改 running 展示按当前查看判断
      if (runningThreadIdRef.current === threadId) {
        runningRef.current = false;
        runningThreadIdRef.current = null;
      }
      if (latestThreadIdRef.current === threadId) setRunning(false);
    }
  }, [threadId, refresh, handleStreamEvent]);

  const resume = useCallback(
    async (value: unknown) => {
      if (!threadId || runningRef.current) return;
      runningRef.current = true;
      runningThreadIdRef.current = threadId;
      setRunning(true);
      setError(null);
      // 重置流式状态（包括 ref）
      streamingStateRef.current = { node: "", content: "" };
      setStreamingContent("");
      setStreamingNode("");
      // 不提前清空 interrupt：重复提交已由 runningRef + disabled={running} 防止，
      // 提前清空会导致 resume 失败时（catch 中 refresh() 还原前）UI 闪现「无中断」。
      // 运行期间保留旧中断（表单 disabled），成功后由 refresh() 更新或清空，失败时 refresh() 还原。
      // 切换小说后丢弃旧 run 的流式事件，避免串台
      const onEvent = (e: StreamEvent) => {
        if (latestThreadIdRef.current !== threadId) return;
        handleStreamEvent(e);
      };
      try {
        await runStream(threadId, onEvent, { resumeValue: value });
        await refresh();
      } catch (e) {
        if (latestThreadIdRef.current === threadId) {
          setError(`恢复失败：${(e as Error).message}`);
        }
        // 恢复失败时重新拉取，还原 interrupt
        await refresh();
      } finally {
        // 清运行标记按运行身份判断；改 running 展示按当前查看判断
        if (runningThreadIdRef.current === threadId) {
          runningRef.current = false;
          runningThreadIdRef.current = null;
        }
        if (latestThreadIdRef.current === threadId) setRunning(false);
      }
    },
    [threadId, refresh, handleStreamEvent]
  );

  const replay = useCallback(
    async (checkpointId: string) => {
      if (!threadId || runningRef.current) return;
      runningRef.current = true;
      runningThreadIdRef.current = threadId;
      setRunning(true);
      setError(null);
      setInterrupt(null);
      // 重置流式状态（包括 ref）
      streamingStateRef.current = { node: "", content: "" };
      setStreamingContent("");
      setStreamingNode("");
      // 切换小说后丢弃旧 run 的流式事件，避免串台
      const onEvent = (e: StreamEvent) => {
        if (latestThreadIdRef.current !== threadId) return;
        handleStreamEvent(e);
      };
      try {
        await replayFromCheckpoint(threadId, checkpointId, onEvent);
        await refresh();
      } catch (e) {
        if (latestThreadIdRef.current === threadId) {
          setError(`重跑失败：${(e as Error).message}`);
        }
        await refresh();
      } finally {
        // 清运行标记按运行身份判断；改 running 展示按当前查看判断
        if (runningThreadIdRef.current === threadId) {
          runningRef.current = false;
          runningThreadIdRef.current = null;
        }
        if (latestThreadIdRef.current === threadId) setRunning(false);
      }
    },
    [threadId, refresh, handleStreamEvent]
  );

  const reset = useCallback(() => {
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setError(null);
    streamingStateRef.current = { node: "", content: "" };
    setStreamingContent("");
    setStreamingNode("");
    setRunning(false);
    runningRef.current = false;
    runningThreadIdRef.current = null;
    stateThreadIdRef.current = null;
  }, []);

  return {
    state,
    currentNode,
    interrupt,
    running,
    error,
    streamingContent,
    streamingNode,
    stateThreadId: stateThreadIdRef.current,
    refresh,
    start,
    resume,
    replay,
    reset,
  };
}
