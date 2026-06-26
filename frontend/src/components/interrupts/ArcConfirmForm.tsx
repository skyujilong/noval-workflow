// arc_confirm 表单。
// payload: {message, ai_generated_arc}；失败分支 {message, error}（要求手动输入）。
// resume 值：
//   ""           = 接受 AI 版本
//   "=<内容>"     = 手动替换（跳过 AI）
//   "<方向文本>"  = 让 AI 按新方向重新生成（可多次迭代）

import { useState } from "react";
import ReactMarkdown from "react-markdown";
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

  const submit = () => {
    if (mode === "accept") onSubmit("");
    else if (mode === "regen") onSubmit(regenText.trim());
    else onSubmit(buildManualReplaceValue(manualText));
  };

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
            <ReactMarkdown>{aiArc}</ReactMarkdown>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => setMode("accept")}
          disabled={disabled || isError}
          className={
            "flex-1 rounded px-3 py-2 text-sm font-medium " +
            (mode === "accept" && !isError
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
          placeholder="输入新的调整方向，AI 会据此重新生成…"
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      )}
      {mode === "manual" && (
        <textarea
          value={manualText}
          onChange={(e) => setManualText(e.target.value)}
          disabled={disabled}
          rows={8}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
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
