// 自动模式的 5s 倒计时 + 自动开火 hook。
// 职责只有两件：算「什么时候该自动 resume」和「倒计时刻度」；真正的 resume 由传入的
// onAutoResume 完成（= NovelWorkspace 现有的手动 onSubmit，单一路径，天然不重复触发）。

import { useEffect, useMemo, useRef, useState } from "react";
import type { CurrentInterrupt } from "../lib/langgraph";
import { getLazyResume, type LazyResume } from "../lib/lazyMode";

interface Params {
  /** 当前中断（null=无中断） */
  interrupt: CurrentInterrupt | null;
  /** 自动模式开关是否打开 */
  enabled: boolean;
  /** 并发闸：running || summaryBusy 时不得自动触发 */
  inputDisabled: boolean;
  /** 自动 resume 的落地回调（与手动共用一条路径） */
  onAutoResume: (value: unknown) => void;
  /** 倒计时秒数，默认 5 */
  seconds?: number;
}

interface Result {
  /** 当前中断的自动处置（null=不自动） */
  plan: LazyResume | null;
  /** 倒计时进行中（banner 是否显示） */
  active: boolean;
  remainingMs: number;
  totalMs: number;
  /** 「立即执行」：跳过剩余倒计时直接开火 */
  fireNow: () => void;
  /** 「手动接管」：只停本次倒计时，不关开关；下个中断仍会重新计时 */
  cancel: () => void;
}

export function useLazyAutoResume({
  interrupt,
  enabled,
  inputDisabled,
  onAutoResume,
  seconds = 5,
}: Params): Result {
  const totalMs = seconds * 1000;
  const [remainingMs, setRemainingMs] = useState(totalMs);

  // 本中断是否已被用户「手动接管」/ 已开火——同步守卫，interrupt 变化时复位
  const cancelledRef = useRef(false);
  const firedRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const plan = useMemo(
    () => (enabled && interrupt ? getLazyResume(interrupt.payload) : null),
    [enabled, interrupt]
  );

  // 进入新环节（interrupt 引用变化）：复位守卫与秒数
  useEffect(() => {
    cancelledRef.current = false;
    firedRef.current = false;
    setRemainingMs(totalMs);
  }, [interrupt, totalMs]);

  const active =
    !!plan?.auto &&
    enabled &&
    !inputDisabled &&
    !cancelledRef.current &&
    !firedRef.current;

  // 用 ref 兜住最新的开火参数，避免 interval 闭包读到旧的 plan/回调
  const fireArgsRef = useRef<{ value: unknown; cb: (v: unknown) => void }>({
    value: plan?.value,
    cb: onAutoResume,
  });
  fireArgsRef.current = { value: plan?.value, cb: onAutoResume };

  const clearTimer = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const fire = () => {
    if (firedRef.current) return; // 单次守卫
    firedRef.current = true;
    clearTimer();
    setRemainingMs(0);
    fireArgsRef.current.cb(fireArgsRef.current.value);
  };

  useEffect(() => {
    if (!active) return;
    const start = Date.now();
    setRemainingMs(totalMs);
    intervalRef.current = setInterval(() => {
      const left = totalMs - (Date.now() - start);
      if (left <= 0) fire();
      else setRemainingMs(left);
    }, 100);
    return clearTimer;
    // fire/clearTimer 稳定读 ref，无需入依赖；active 起落即启停倒计时
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, interrupt, totalMs]);

  return {
    plan,
    active,
    remainingMs,
    totalMs,
    fireNow: fire,
    cancel: () => {
      cancelledRef.current = true;
      clearTimer();
      setRemainingMs(totalMs);
    },
  };
}
