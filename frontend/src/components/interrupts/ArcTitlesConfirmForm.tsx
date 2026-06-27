// arc_titles_confirm 表单。
// payload: {message, ai_generated_titles, shortage}
// resume 值：
//   ""               = 接受 AI 标题
//   "=<每行一个标题>" = 手动替换（跳过 AI），用 _clean_title 规则清理
//   "<方向文本>"      = 让 AI 按新方向重新生成

import { useEffect, useState } from "react";
import type { ArcTitlesConfirmPayload } from "../../lib/interruptTypes";
import { buildManualReplaceValue } from "../../lib/interruptTypes";

interface Props {
  payload: ArcTitlesConfirmPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

type Mode = "accept" | "regen" | "manual";

export function ArcTitlesConfirmForm({ payload, onSubmit, disabled }: Props) {
  const aiTitles = payload.ai_generated_titles ?? [];
  const [mode, setMode] = useState<Mode>("accept");
  const [regenText, setRegenText] = useState("");
  const [manualText, setManualText] = useState(aiTitles.join("\n"));
  const [submitting, setSubmitting] = useState(false);

  // 提交结束（disabled false）或新 interrupt（payload 变化）时重置状态
  useEffect(() => {
    setSubmitting(false);
    setMode("accept");
    setRegenText("");
    setManualText(aiTitles.join("\n"));
  }, [disabled, payload, aiTitles]);

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
      <h3 className="text-lg font-semibold text-gray-800">剩余章节标题确认</h3>

      {payload.shortage > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-700">
          AI 仅生成 {aiTitles.length} 个，需要 {aiTitles.length + payload.shortage} 个；
          手动替换时请补全所有标题。
        </div>
      )}

      <div className="rounded border border-gray-200 bg-white p-3">
        <div className="mb-1 text-xs font-medium text-gray-500">
          AI 根据新大纲生成的标题
        </div>
        {aiTitles.length === 0 ? (
          <div className="text-sm text-gray-400">AI 未能生成任何标题</div>
        ) : (
          <ol className="list-inside list-decimal space-y-0.5 text-sm text-gray-700">
            {aiTitles.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ol>
        )}
      </div>

      {/* 模式选择 - 分层设计：选择器使用 border 样式，与底部提交按钮区分 */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode("accept")}
          disabled={isDisabled || aiTitles.length === 0}
          className={
            "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
            (mode === "accept"
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
          placeholder="输入新的调整方向…"
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}
      {mode === "manual" && (
        <div>
          <div className="mb-1 text-xs text-gray-500">每行一个标题</div>
          <textarea
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            disabled={isDisabled}
            rows={Math.max(6, aiTitles.length)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        </div>
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
