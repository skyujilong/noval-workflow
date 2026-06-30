// 编排单个 thread 的运行：组合「流式展示」(useStreamingDisplay) 与「thread 快照」
// (useThreadSnapshot) 两个子 hook，负责 start / resume / replay / refresh 与
// running / error 状态。
//
// 核心流程：
//   start()          → 启动新 run（无 resume），graph 会在首个 interrupt 暂停
//   refresh()        → 拉取快照，提取 interrupt，必要时 join 后台 run
//   resume(value)    → 用 Command(resume=value) 恢复 run，结束后再 refresh
//   replay(id)       → 从指定 checkpoint 重跑（同线程 replay）
//
// 跨小说隔离由 React 协调负责：承载本 hook 的子树以 key={threadId} 重挂载，故每个
// 实例只服务一个 thread，threadId 在实例存活期内恒定——无需任何手写跨 thread 守卫。
// 唯一保留的是 aliveRef：实例卸载后，后台仍在跑的 run 会继续回调 onEvent，用它早退
// 避免对已卸载实例做无效 setState。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  joinRunStream,
  listActiveRuns,
  replayFromCheckpoint,
  runStream,
  type CurrentInterrupt,
  type StreamEvent,
} from "../lib/langgraph";
import type { NovelState } from "../lib/types";
import { useStreamingDisplay } from "./useStreamingDisplay";
import { useThreadSnapshot } from "./useThreadSnapshot";

export interface UseRunResult {
  state: NovelState;
  currentNode: string;
  interrupt: CurrentInterrupt | null;
  running: boolean;
  /** 首次快照尚未拉回——右侧据此显示「加载中」而非空态详情 */
  loading: boolean;
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
}

export function useRun(threadId: string): UseRunResult {
  const { state, interrupt, loading, setInterrupt, load } = useThreadSnapshot();
  const {
    currentNode,
    streamingNode,
    streamingContent,
    handleStreamEvent,
    setCurrentNode,
    resetStreaming,
  } = useStreamingDisplay();

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 防止同一小说并发 run
  const runningRef = useRef(false);
  // 实例存活标记：卸载后丢弃后台 run 仍在产生的流式回调。
  // ⚠️ 必须在 setup 里把它重新置 true（root-cause fix）：
  // React 18 StrictMode（dev）挂载会跑 setup→cleanup→setup，cleanup 把它置 false 后，
  // 若 setup 不重置，remount 后它将**永远**是 false → onEvent 的 `if (!aliveRef.current) return`
  // 丢弃所有流式事件 → 打字机永不更新，内容只在末尾 refresh 整段冒出。生产环境无此双调用，
  // 但仍应对称地在 setup 置位，保证语义正确、且 dev 行为与生产一致。
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  // 统一流式入口：实例已卸载则丢弃；error 事件转 error 态，其余交给展示层翻译。
  const onEvent = useCallback(
    (e: StreamEvent) => {
      if (!aliveRef.current) return;
      if (e.event === "error") {
        setError(`运行错误：${JSON.stringify(e.data)}`);
      } else {
        handleStreamEvent(e);
      }
    },
    [handleStreamEvent]
  );

  const refresh = useCallback(async () => {
    try {
      const { interrupt: it, next } = await load(threadId);
      if (it) {
        if (next.length) setCurrentNode(next[0]);
        // payload 自描述（带 type + 富表单上下文），无需再取子图 state。
      } else if (!runningRef.current) {
        // 无中断且本地未在流式 — 检查后台是否有正在运行的 run（刷新后恢复 running）
        const activeRuns = await listActiveRuns(threadId);
        if (activeRuns.length > 0) {
          runningRef.current = true;
          setRunning(true);
          try {
            await joinRunStream(threadId, activeRuns[0].run_id, onEvent);
          } catch (e) {
            setError(`等待运行完成失败：${(e as Error).message}`);
          } finally {
            runningRef.current = false;
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
  }, [threadId, load, setCurrentNode, onEvent]);

  // 挂载时拉取状态（key 重挂载保证一个实例只对应一个 threadId）
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // start / resume / replay 的共享骨架：并发守卫 → 置 running/清错/(可选清中断)/清流式
  // → 执行 → 成功后 refresh；失败 setError（resume/replay 还需 refresh 还原中断）→ 收尾。
  const runGuarded = useCallback(
    async (
      exec: () => Promise<void>,
      errLabel: string,
      opts?: { restoreOnError?: boolean; clearInterrupt?: boolean }
    ) => {
      if (runningRef.current) return;
      runningRef.current = true;
      setRunning(true);
      setError(null);
      if (opts?.clearInterrupt) setInterrupt(null);
      resetStreaming();
      try {
        await exec();
        await refresh();
      } catch (e) {
        setError(`${errLabel}：${(e as Error).message}`);
        if (opts?.restoreOnError) await refresh();
      } finally {
        runningRef.current = false;
        setRunning(false);
      }
    },
    [refresh, resetStreaming, setInterrupt]
  );

  // 新 run 必须传非 null 的 input（{}），否则平台报 EmptyInputError。
  const start = useCallback(
    () => runGuarded(() => runStream(threadId, onEvent, { input: {} }), "启动失败"),
    [runGuarded, threadId, onEvent]
  );

  // resume 不提前清空 interrupt：重复提交已由 runningRef + disabled={running} 防止；提前清会
  // 导致失败时（restoreOnError 的 refresh 还原前）UI 闪现「无中断」。运行期保留旧中断（表单
  // disabled），成功后由 refresh 更新/清空，失败时由 refresh 还原。
  const resume = useCallback(
    (value: unknown) =>
      runGuarded(() => runStream(threadId, onEvent, { resumeValue: value }), "恢复失败", {
        restoreOnError: true,
      }),
    [runGuarded, threadId, onEvent]
  );

  // replay 同线程从指定 checkpoint 重跑：先清旧中断（clearInterrupt），失败时 refresh 还原。
  const replay = useCallback(
    (checkpointId: string) =>
      runGuarded(
        () => replayFromCheckpoint(threadId, checkpointId, onEvent),
        "重跑失败",
        { restoreOnError: true, clearInterrupt: true }
      ),
    [runGuarded, threadId, onEvent]
  );

  return {
    state,
    currentNode,
    interrupt,
    running,
    loading,
    error,
    streamingContent,
    streamingNode,
    refresh,
    start,
    resume,
    replay,
  };
}
