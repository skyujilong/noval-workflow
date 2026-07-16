// 章末长线章节规划调整 · 是否执行闸门（cp_entry）。
// 顶部用 ChapterPlanCards 结构化展示「当前未写窗口锚点」（与方向输入/状态编辑抽屉同款），
// 下方跳过/执行按钮。resume 值：""（SKIP_VALUE）= 跳过；"yes"（EXECUTE_VALUE）= 执行。

import { useEffect, useState } from "react";
import type { ChapterPlanEditEntryGatePayload } from "../../lib/interruptTypes";
import { EXECUTE_VALUE, SKIP_VALUE } from "../../lib/interruptTypes";
import type { NovelState } from "../../lib/types";
import { ChapterPlanCards } from "./ChapterPlanCards";

interface Props {
  payload: ChapterPlanEditEntryGatePayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  title?: string;
  novelState?: NovelState;
}

export function ChapterPlanEditEntryGateForm({
  payload,
  onSubmit,
  disabled,
  title,
  novelState,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  // 优先用 payload 的结构化窗口；旧 checkpoint 缺该字段时，从 novelState.chapter_plan
  // 退导未写段（章号 > 已写章数），保证老中断也能即时渲染成卡片（与状态编辑抽屉同源）。
  const written = novelState?.total_chapters_written ?? 0;
  const derived = (novelState?.chapter_plan ?? []).filter((c) => c.chapter > written);
  const window = payload.chapter_plan_window?.length ? payload.chapter_plan_window : derived;
  const [start, end] = payload.range?.length
    ? payload.range
    : window.length
      ? [window[0].chapter, window[window.length - 1].chapter]
      : [0, 0];

  // 提交结束或新 interrupt 时重置状态
  useEffect(() => {
    setSubmitting(false);
  }, [disabled, payload]);

  const handleSubmit = (value: string) => {
    setSubmitting(true);
    onSubmit(value);
  };

  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        {title ?? "后续章节规划调整（弧线自动跟随）· 是否执行"}
      </h3>
      <p className="text-xs text-gray-500">
        调整远端章节规划（第 {start}-{end} 章），弧线大纲与剩余章节标题将据此自动重生成，二者始终一致。
        执行后先输入调整方向，AI 重规划；跳过则本环节不改动。
      </p>

      {window.length > 0 ? (
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-2 text-xs font-medium text-gray-500">当前未写章节规划（可调整）</div>
          <ChapterPlanCards draft={JSON.stringify(window)} novelState={novelState} />
        </div>
      ) : (
        <div className="whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
          {payload.message}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => handleSubmit(SKIP_VALUE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "跳过"}
        </button>
        <button
          onClick={() => handleSubmit(EXECUTE_VALUE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : "执行"}
        </button>
      </div>
    </div>
  );
}
