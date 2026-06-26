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
  /** 拉取当前 thread state 并提取 interrupt */
  refresh: () => Promise<void>;
  /** 启动一次新 run（新 thread 会立刻在 collect_user_inputs 中断） */
  start: () => Promise<void>;
  /** 从当前 interrupt 恢复 */
  resume: (value: unknown) => Promise<void>;
  /** 清空状态（切换小说时） */
  reset: () => void;
}

export function useRun(threadId: string | null): UseRunResult {
  const [state, setState] = useState<NovelState>(EMPTY_NOVEL_STATE);
  const [currentNode, setCurrentNode] = useState("");
  const [interrupt, setInterrupt] = useState<CurrentInterrupt | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 防止并发 run
  const runningRef = useRef(false);

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
      }
      setError(null);
    } catch (e) {
      setError(`获取状态失败：${(e as Error).message}`);
    }
  }, [threadId]);

  // 切换 thread 时刷新
  useEffect(() => {
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setError(null);
    if (threadId) void refresh();
  }, [threadId, refresh]);

  const start = useCallback(async () => {
    if (!threadId || runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setError(null);
    try {
      // 新 run 必须传非 null 的 input（{}），否则平台报 EmptyInputError
      await runStream(
        threadId,
        (e) => {
          if (e.event === "updates") setCurrentNode(e.node);
          if (e.event === "error") setError(`运行错误：${JSON.stringify(e.data)}`);
        },
        { input: {} }
      );
      await refresh();
    } catch (e) {
      setError(`启动失败：${(e as Error).message}`);
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }, [threadId, refresh]);

  const resume = useCallback(
    async (value: unknown) => {
      if (!threadId || runningRef.current) return;
      runningRef.current = true;
      setRunning(true);
      setError(null);
      setInterrupt(null); // 提交后先清空，避免重复提交
      try {
        await runStream(threadId, (e) => {
          if (e.event === "updates") setCurrentNode(e.node);
          if (e.event === "error") setError(`运行错误：${JSON.stringify(e.data)}`);
        }, { resumeValue: value });
        await refresh();
      } catch (e) {
        setError(`恢复失败：${(e as Error).message}`);
        // 恢复失败时重新拉取，还原 interrupt
        await refresh();
      } finally {
        runningRef.current = false;
        setRunning(false);
      }
    },
    [threadId, refresh]
  );

  const reset = useCallback(() => {
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setError(null);
  }, []);

  return { state, currentNode, interrupt, running, error, refresh, start, resume, reset };
}
