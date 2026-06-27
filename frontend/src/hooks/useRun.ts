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
  getSubgraphState,
  getThreadState,
  joinRunStream,
  listActiveRuns,
  replayFromCheckpoint,
  runStream,
  type CurrentInterrupt,
  type SubgraphState,
} from "../lib/langgraph";
import { detectInterruptKind } from "../lib/interruptTypes";
import { EMPTY_NOVEL_STATE, type NovelState } from "../lib/types";

export interface UseRunResult {
  state: NovelState;
  currentNode: string;
  interrupt: CurrentInterrupt | null;
  /** 中断所在子图的 state（human_review 时含草稿/AI意见/历史）；非子图中断为 null */
  subgraphState: SubgraphState | null;
  running: boolean;
  error: string | null;
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
  const [subgraphState, setSubgraphState] = useState<SubgraphState | null>(null);
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
        // 仅 human_review 富表单消费子图 state；其他中断（user_inputs/ask_continue 等）
        // 非子图中断，调用 getSubgraphState 必然返回 null，故跳过以免多余网络往返。
        if (detectInterruptKind(it.payload) === "human_review") {
          try {
            const sub = await getSubgraphState(threadId);
            setSubgraphState(sub);
          } catch (e) {
            // 子图 state 获取失败不阻断主流程，富表单回退到 message 解析；
            // 但须保留错误上下文以便排查，不可静默吞掉（CLAUDE.md：关键错误尽早暴露）。
            console.warn("获取子图 state 失败，回退到 message 解析", e);
            setSubgraphState(null);
          }
        } else {
          setSubgraphState(null);
        }
      } else {
        setSubgraphState(null);
        // 无中断 — 检查后台是否有正在运行的 run（页面刷新后恢复 running 状态）
        const activeRuns = await listActiveRuns(threadId);
        if (activeRuns.length > 0) {
          setRunning(true);
          runningRef.current = true;
          try {
            await joinRunStream(threadId, activeRuns[0].run_id, (e) => {
              if (e.event === "updates") setCurrentNode(e.node);
              if (e.event === "error") setError(`运行错误：${JSON.stringify(e.data)}`);
            });
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
  }, [threadId]);

  // 切换 thread 时刷新
  useEffect(() => {
    setState(EMPTY_NOVEL_STATE);
    setCurrentNode("");
    setInterrupt(null);
    setSubgraphState(null);
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
      // 不提前清空 interrupt/subgraphState：重复提交已由 runningRef + disabled={running} 防止，
      // 提前清空会导致 resume 失败时（catch 中 refresh() 还原前）UI 闪现「无中断」。
      // 运行期间保留旧中断（表单 disabled），成功后由 refresh() 更新或清空，失败时 refresh() 还原。
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

  const replay = useCallback(
    async (checkpointId: string) => {
      if (!threadId || runningRef.current) return;
      runningRef.current = true;
      setRunning(true);
      setError(null);
      setInterrupt(null);
      setSubgraphState(null);
      try {
        await replayFromCheckpoint(threadId, checkpointId, (e) => {
          if (e.event === "updates") setCurrentNode(e.node);
          if (e.event === "error") setError(`运行错误：${JSON.stringify(e.data)}`);
        });
        await refresh();
      } catch (e) {
        setError(`重跑失败：${(e as Error).message}`);
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
    setSubgraphState(null);
    setError(null);
  }, []);

  return { state, currentNode, interrupt, subgraphState, running, error, refresh, start, resume, replay, reset };
}
