// arc_confirm 表单。
// payload: {message, ai_generated_arc}；失败分支 {message, error}（要求手动输入）。
// resume 值：
//   ""           = 接受 AI 版本
//   "=<内容>"     = 手动替换（跳过 AI）
//   "<方向文本>"  = 让 AI 按新方向重新生成（可多次迭代）

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  ArcConfirmErrorPayload,
  ArcConfirmPayload,
} from "../../lib/interruptTypes";
import { buildManualReplaceValue } from "../../lib/interruptTypes";

interface Props {
  payload: ArcConfirmPayload | ArcConfirmErrorPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

type Mode = "accept" | "regen" | "manual";

export function ArcConfirmForm({ payload, onSubmit, disabled }: Props) {
  const aiArc = (payload as ArcConfirmPayload).ai_generated_arc ?? "";
  const isError = typeof (payload as ArcConfirmErrorPayload).error === "string";
  const [mode, setMode] = useState<Mode>(isError ? "manual" : "accept");
  const [regenText, setRegenText] = useState("");
  const [manualText, setManualText] = useState(aiArc);
  const [submitting, setSubmitting] = useState(false);

  // 提交结束（disabled false）或新 interrupt（payload 变化）时重置状态
  useEffect(() => {
    setSubmitting(false);
    setMode(isError ? "manual" : "accept");
    setRegenText("");
    setManualText(aiArc);
  }, [disabled, payload, aiArc, isError]);

  const handleSubmit = () => {
    setSubmitting(true);
    if (mode === "accept") onSubmit("");
    else if (mode === "regen") onSubmit(regenText.trim());
    else onSubmit(buildManualReplaceValue(manualText));
  };

  // 本地 submitting 优先于上层 disabled，确保点击后立即禁用所有控件
  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        弧线大纲确认{isError ? "（AI 重写失败，需手动输入）" : ""}
      </h3>

      {isError && (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          AI 重写失败：{(payload as ArcConfirmErrorPayload).error}
        </div>
      )}

      {!isError && aiArc && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-1 text-xs font-medium text-gray-500">AI 生成的新弧线大纲</div>
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{aiArc}</ReactMarkdown>
          </div>
        </div>
      )}

      {/* 模式选择 - 分层设计：选择器使用 border 样式，与底部提交按钮区分 */}
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
          disabled={isDisabled}
          className={
            "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
            (mode === "regen"
              ? "border-blue-600 bg-blue-50 text-blue-700"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
          }
        >
          🔄 按新方向重生成
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
          placeholder="输入新的调整方向，AI 会据此重新生成…"
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}
      {mode === "manual" && (
        <textarea
          value={manualText}
          onChange={(e) => setManualText(e.target.value)}
          disabled={isDisabled}
          rows={8}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}

      {/* 提交按钮 - 单独一行，视觉突出 */}
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
