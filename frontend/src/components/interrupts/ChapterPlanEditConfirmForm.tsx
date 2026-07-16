// 章末长线章节规划调整 · AI 结果确认表单（cp_confirm / cp_confirm_error）。
// 正常分支 payload: {message, ai_chapter_plan: ChapterPlanEditItem[]}；
// 失败分支 payload: {message, error}（需手动粘贴完整 JSON 数组）。
// resume 值（与后端 cp_confirm 对齐）：
//   ""            = 接受 AI 版本
//   "=<JSON数组>" = 手动替换（跳过 AI；错误分支也容忍「=」前缀）
//   "<方向文本>"  = 让 AI 按新方向重新生成（可多次迭代；仅正常分支）

import { useEffect, useState } from "react";
import type {
  ChapterPlanEditConfirmErrorPayload,
  ChapterPlanEditConfirmPayload,
} from "../../lib/interruptTypes";
import { buildManualReplaceValue } from "../../lib/interruptTypes";
import type { NovelState } from "../../lib/types";
import { ChapterPlanCards } from "./ChapterPlanCards";

interface Props {
  payload: ChapterPlanEditConfirmPayload | ChapterPlanEditConfirmErrorPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  novelState?: NovelState;
}

type Mode = "accept" | "regen" | "manual";

export function ChapterPlanEditConfirmForm({ payload, onSubmit, disabled, novelState }: Props) {
  const aiPlan = (payload as ChapterPlanEditConfirmPayload).ai_chapter_plan ?? [];
  const isError = typeof (payload as ChapterPlanEditConfirmErrorPayload).error === "string";
  const aiPlanJson = aiPlan.length > 0 ? JSON.stringify(aiPlan, null, 2) : "";
  const [mode, setMode] = useState<Mode>(isError ? "manual" : "accept");
  const [regenText, setRegenText] = useState("");
  const [manualText, setManualText] = useState(aiPlanJson);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setSubmitting(false);
    setMode(isError ? "manual" : "accept");
    setRegenText("");
    setManualText(aiPlanJson);
  }, [disabled, payload, aiPlanJson, isError]);

  const handleSubmit = () => {
    setSubmitting(true);
    if (mode === "accept") onSubmit("");
    else if (mode === "regen") onSubmit(regenText.trim());
    else onSubmit(buildManualReplaceValue(manualText));
  };

  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        后续章节规划确认{isError ? "（AI 重规划失败，需手动输入）" : ""}
      </h3>
      <p className="text-xs text-gray-500">确认后，弧线大纲与剩余章节标题将据此自动重生成。</p>

      {isError && (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          AI 重规划失败：{(payload as ChapterPlanEditConfirmErrorPayload).error}
        </div>
      )}

      {!isError && aiPlan.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-2 text-xs font-medium text-gray-500">AI 重规划的后续章节规划</div>
          <ChapterPlanCards draft={JSON.stringify(aiPlan)} novelState={novelState} />
        </div>
      )}

      {/* 模式选择 */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode("accept")}
          disabled={isDisabled || isError}
          className={
            "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
            (mode === "accept" && !isError
              ? "border-green-600 bg-green-50 text-green-700"
              : "border-gray-200 bg-white text-gray-400 hover:bg-gray-50 hover:text-gray-600")
          }
        >
          ✓ 接受
        </button>
        <button
          type="button"
          onClick={() => setMode("regen")}
          disabled={isDisabled || isError}
          className={
            "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
            (mode === "regen"
              ? "border-blue-600 bg-blue-50 text-blue-700"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50 disabled:text-gray-300")
          }
        >
          🔄 按新方向重规划
        </button>
        <button
          type="button"
          onClick={() => setMode("manual")}
          disabled={isDisabled}
          className={
            "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
            (mode === "manual"
              ? "border-amber-600 bg-amber-50 text-amber-700"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
          }
        >
          ✏️ 手动替换
        </button>
      </div>

      {mode === "regen" && (
        <textarea
          value={regenText}
          onChange={(e) => setRegenText(e.target.value)}
          disabled={isDisabled}
          placeholder="输入新的调整方向，AI 会据此重新规划后续章节…"
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}
      {mode === "manual" && (
        <textarea
          value={manualText}
          onChange={(e) => setManualText(e.target.value)}
          disabled={isDisabled}
          rows={10}
          placeholder='粘贴完整的未写段章节规划 JSON 数组，如 [{"chapter":5,"purpose":"…","key_turn":"…","ending_hook":"…","intensity":"推进"}]'
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={
          isDisabled ||
          (mode === "regen" && !regenText.trim()) ||
          (mode === "manual" && !manualText.trim())
        }
        className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        {submitting ? "⏳ 提交中..." : "确认提交"}
      </button>
    </div>
  );
}
