// human_review 审稿表单。
// 草稿在子图 state 中，父 thread state 不暴露；但 human_review 的 interrupt payload
// 的 message 形如「{current_draft}\n\n---\n· 直接回车 → 通过\n· 输入修改意见 → 重新生成」，
// 因此草稿从 message 的 "\n\n---\n" 之前部分解析。review_type 从父 state 取（已写回）。
// resume 值："" = 通过，非空文本 = 修改意见（驱动重新生成）。

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { MessageOnlyPayload } from "../../lib/interruptTypes";
import { reviewTypeLabel } from "../../lib/types";

interface Props {
  payload: MessageOnlyPayload;
  reviewType: string;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

/** 从 interrupt message 解析草稿正文（分隔符 \n\n---\n 之前的部分） */
function parseDraft(message: string): string {
  const idx = message.indexOf("\n\n---\n");
  return idx >= 0 ? message.slice(0, idx) : message;
}

export function HumanReviewForm({ payload, reviewType, onSubmit, disabled }: Props) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"approve" | "revise">("approve");

  const draft = parseDraft(payload.message ?? "");

  const submit = () => {
    onSubmit(mode === "approve" ? "" : feedback.trim());
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        人工审核 · {reviewTypeLabel(reviewType || "foundation")}
      </h3>

      {/* 当前草稿 */}
      <div className="rounded border border-gray-200 bg-white p-3">
        <div className="mb-2 text-xs font-medium text-gray-500">当前草稿</div>
        <div className="prose prose-sm max-w-none overflow-y-auto max-h-96">
          <ReactMarkdown>{draft || "（无草稿内容）"}</ReactMarkdown>
        </div>
      </div>

      {/* 操作区 */}
      <div className="space-y-2 border-t pt-3">
        <div className="flex gap-2">
          <button
            onClick={() => setMode("approve")}
            disabled={disabled}
            className={
              "flex-1 rounded px-3 py-2 text-sm font-medium " +
              (mode === "approve"
                ? "bg-green-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200")
            }
          >
            ✓ 通过
          </button>
          <button
            onClick={() => setMode("revise")}
            disabled={disabled}
            className={
              "flex-1 rounded px-3 py-2 text-sm font-medium " +
              (mode === "revise"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200")
            }
          >
            ✎ 提出修改意见
          </button>
        </div>
        {mode === "revise" && (
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={disabled}
            placeholder="输入修改意见，AI 会据此重新生成…"
            rows={4}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        )}
        <button
          onClick={submit}
          disabled={disabled || (mode === "revise" && !feedback.trim())}
          className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
        >
          {mode === "approve" ? "确认通过" : "提交修改意见"}
        </button>
      </div>
    </div>
  );
}
