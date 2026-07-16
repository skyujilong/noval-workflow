// 章末长线章节规划调整 · 方向输入表单（cp_direction）。
// 顶部用 ChapterPlanCards 展示「当前未写窗口锚点」，下方输入调整方向。
// resume 值："" = 取消；非空 = 调整方向（AI 据此重规划后续章节，弧线与剩余标题自动跟随）。

import { useEffect, useState } from "react";
import type { ChapterPlanEditDirectionPayload } from "../../lib/interruptTypes";
import type { NovelState } from "../../lib/types";
import { ChapterPlanCards } from "./ChapterPlanCards";

interface Props {
  payload: ChapterPlanEditDirectionPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  novelState?: NovelState;
}

export function ChapterPlanEditDirectionForm({ payload, onSubmit, disabled, novelState }: Props) {
  const [direction, setDirection] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const window = payload.chapter_plan_window ?? [];
  const [start, end] = payload.range ?? [0, 0];

  useEffect(() => {
    setSubmitting(false);
    setDirection("");
  }, [disabled, payload]);

  const handleSubmit = (value: string) => {
    setSubmitting(true);
    onSubmit(value);
  };

  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">后续章节规划调整方向</h3>
      <p className="text-xs text-gray-500">
        调整远端章节规划（第 {start}-{end} 章），弧线大纲与剩余章节标题将据此自动重生成，二者始终一致。
      </p>

      {window.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-2 text-xs font-medium text-gray-500">当前未写章节规划（可调整）</div>
          <ChapterPlanCards draft={JSON.stringify(window)} novelState={novelState} />
        </div>
      )}

      <textarea
        value={direction}
        onChange={(e) => setDirection(e.target.value)}
        disabled={isDisabled}
        placeholder="输入调整方向（直接回车/留空 → 取消）"
        rows={4}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      />
      <div className="flex gap-2">
        <button
          onClick={() => handleSubmit("")}
          disabled={isDisabled}
          className="rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "取消"}
        </button>
        <button
          onClick={() => handleSubmit(direction.trim())}
          disabled={isDisabled || !direction.trim()}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : "提交调整方向"}
        </button>
      </div>
    </div>
  );
}
