// thread 快照：从平台拉取 state.values 与当前 interrupt。
// 不含任何跨 thread 守卫——隔离由承载 hook 的子树以 key 重挂载保证。

import { useCallback, useState } from "react";
import {
  extractInterrupt,
  getThreadInterrupts,
  getThreadState,
  type CurrentInterrupt,
} from "../lib/langgraph";
import { EMPTY_NOVEL_STATE, type NovelState } from "../lib/types";

export interface UseThreadSnapshot {
  state: NovelState;
  interrupt: CurrentInterrupt | null;
  /** 首次快照尚未拉回（挂载后到第一次 load 完成前为 true），用于区分「加载中」与「确实是空的」 */
  loading: boolean;
  /** 直接设置 interrupt（replay 前清空） */
  setInterrupt: (it: CurrentInterrupt | null) => void;
  /**
   * 拉取 thread 快照：写入 state + interrupt，返回 { interrupt, next } 供编排层决定后续。
   * 中断提取双源：state.tasks[].interrupts（主源） + threads.get().interrupts（兜底，
   * 应对 langgraph dev 重启后 tasks 里 interrupts 被清空但 thread 表上的 dict 仍保留的情形）。
   */
  load: (
    threadId: string
  ) => Promise<{ interrupt: CurrentInterrupt | null; next: string[] }>;
  /**
   * 只重新拉取 values 写入 state，**不碰 interrupt / loading**。
   * 专供「就地 update_state 后」刷新：update_state 会清空中断两源，跑常规 load 会把
   * interrupt 置 null（表单消失）；此方法只更新展示用的 values，保留内存里的中断。
   */
  reloadValues: (threadId: string) => Promise<void>;
}

export function useThreadSnapshot(): UseThreadSnapshot {
  const [state, setState] = useState<NovelState>(EMPTY_NOVEL_STATE);
  const [interrupt, setInterrupt] = useState<CurrentInterrupt | null>(null);
  // 初次快照加载中：第一次 load 结束（成功或失败）后置 false 且不再翻转。
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (threadId: string) => {
    try {
      // 主/兜底源并行拉取，减少一轮 RTT
      const [st, threadInterrupts] = await Promise.all([
        getThreadState(threadId),
        getThreadInterrupts(threadId).catch(() => ({})),
      ]);
      const values = (st.values ?? {}) as Partial<NovelState>;
      setState({ ...EMPTY_NOVEL_STATE, ...values });
      const it = extractInterrupt(st, threadInterrupts);
      setInterrupt(it);
      // 中断时当前节点取 next（待执行的节点）；运行中由 updates 维护
      const next = (st as { next?: string[] }).next ?? [];
      return { interrupt: it, next };
    } finally {
      setLoading(false);
    }
  }, []);

  const reloadValues = useCallback(async (threadId: string) => {
    const st = await getThreadState(threadId);
    const values = (st.values ?? {}) as Partial<NovelState>;
    setState({ ...EMPTY_NOVEL_STATE, ...values });
  }, []);

  return { state, interrupt, loading, setInterrupt, load, reloadValues };
}
