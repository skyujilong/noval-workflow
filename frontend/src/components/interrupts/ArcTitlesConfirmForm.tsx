// arc_titles_confirm 表单。
// payload: {message, ai_generated_titles, shortage}
// resume 值：
//   ""               = 接受 AI 标题
//   "=<每行一个标题>" = 手动替换（跳过 AI），用 _clean_title 规则清理
//   "<方向文本>"      = 让 AI 按新方向重新生成

import { useState } from "react";
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

  const submit = () => {
    if (mode === "accept") onSubmit("");
    else if (mode === "regen") onSubmit(regenText.trim());
    else onSubmit(buildManualReplaceValue(manualText));
  };

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

      <div className="flex gap-2">
        <button
          onClick={() => setMode("accept")}
          disabled={disabled || aiTitles.length === 0}
          className={
            "flex-1 rounded px-3 py-2 text-sm font-medium " +
            (mode === "accept"
              ? "bg-green-600 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200")
          }
        >
          ✓ 接受
        </button>
        <button
          onClick={() => setMode("regen")}
          disabled={disabled}
          className={
            "flex-1 rounded px-3 py-2 text-sm font-medium " +
            (mode === "regen"
              ? "bg-blue-600 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200")
          }
        >
          🔄 按新方向重生成
        </button>
        <button
          onClick={() => setMode("manual")}
          disabled={disabled}
          className={
            "flex-1 rounded px-3 py-2 text-sm font-medium " +
            (mode === "manual"
              ? "bg-amber-600 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200")
          }
        >
          ✏️ 手动替换
        </button>
      </div>

      {mode === "regen" && (
        <textarea
          value={regenText}
          onChange={(e) => setRegenText(e.target.value)}
          disabled={disabled}
          placeholder="输入新的调整方向…"
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      )}
      {mode === "manual" && (
        <div>
          <div className="mb-1 text-xs text-gray-500">每行一个标题</div>
          <textarea
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            disabled={disabled}
            rows={Math.max(6, aiTitles.length)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
      )}

      <button
        onClick={submit}
        disabled={
          disabled ||
          (mode === "regen" && !regenText.trim()) ||
          (mode === "manual" && !manualText.trim())
        }
        className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
      >
        确认提交
      </button>
    </div>
  );
}
