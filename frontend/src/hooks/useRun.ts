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
  // 🔒 运行状态隔离：记录当前正在运行的 threadId
  // 防止小说 A 在运行时，切换到小说 B 却显示 running 状态
  const runningThreadIdRef = useRef<string | null>(null);
  // 防止并发 run
  const runningRef = useRef(false);
  // 用 ref 存储流式状态的最新值，避免闭包捕获过时状态（解决 P0 stale closure）
  const streamingStateRef = useRef({ node: "", content: "" });

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
      const values = (st.values ?? {}) as Partial<NovelState>;
      setState({ ...EMPTY_NOVEL_STATE, ...values });
      const it = extractInterrupt(st);
      setInterrupt(it);
      // 中断时，当前节点取 next（待执行的节点）；运行中由 updates 维护
      if (it) {
        const next = (st as { next?: string[] }).next ?? [];
        if (next.length) setCurrentNode(next[0]);
        // payload 自描述（带 type + 富表单上下文），无需再调 getSubgraphState 取子图 state。
      } else {
        // 无中断 — 检查后台是否有正在运行的 run（页面刷新后恢复 running 状态）
        const activeRuns = await listActiveRuns(threadId);
        if (activeRuns.length > 0) {
          setRunning(true);
          runningRef.current = true;
          runningThreadIdRef.current = threadId;
          try {
            await joinRunStream(threadId, activeRuns[0].run_id, handleStreamEvent);
          } catch (e) {
            setError(`等待运行完成失败：${(e as Error).message}`);
          } finally {
            runningRef.current = false;
            runningThreadIdRef.current = null;
            setRunning(false);
          }
          // run 结束后重新拉取状态（可能已产生新中断）
          await refresh();
          return;
        }
      }
      setError(null);
    } catch (e) {
      setError(`获取状态失败：${(e as Error).message}`);
    }
  }, [threadId, handleStreamEvent]);

  // 切换 thread 时刷新并重置运行状态
  useEffect(() => {
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setError(null);
    streamingStateRef.current = { node: "", content: "" };
    setStreamingContent("");
    setStreamingNode("");
    // 🔒 运行状态隔离：切换小说时，如果当前不是正在运行此 thread，则重置 running
    // 防止小说 A 运行时，切换到小说 B 却显示"正在生成"
    if (threadId !== runningThreadIdRef.current) {
      setRunning(false);
      runningRef.current = false;
    }
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
    try {
      // 新 run 必须传非 null 的 input（{}），否则平台报 EmptyInputError
      await runStream(threadId, handleStreamEvent, { input: {} });
      await refresh();
    } catch (e) {
      setError(`启动失败：${(e as Error).message}`);
    } finally {
      runningRef.current = false;
      runningThreadIdRef.current = null;
      setRunning(false);
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
      try {
        await runStream(threadId, handleStreamEvent, { resumeValue: value });
        await refresh();
      } catch (e) {
        setError(`恢复失败：${(e as Error).message}`);
        // 恢复失败时重新拉取，还原 interrupt
        await refresh();
      } finally {
        runningRef.current = false;
        runningThreadIdRef.current = null;
        setRunning(false);
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
      try {
        await replayFromCheckpoint(threadId, checkpointId, handleStreamEvent);
        await refresh();
      } catch (e) {
        setError(`重跑失败：${(e as Error).message}`);
        await refresh();
      } finally {
        runningRef.current = false;
        runningThreadIdRef.current = null;
        setRunning(false);
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
  }, []);

  return {
    state,
    currentNode,
    interrupt,
    running,
    error,
    streamingContent,
    streamingNode,
    refresh,
    start,
    resume,
    replay,
    reset,
  };
}
