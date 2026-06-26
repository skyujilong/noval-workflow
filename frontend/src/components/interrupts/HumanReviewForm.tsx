// human_review 富审稿表单。
// 草稿/AI 自审意见/修改历史来自子图 state（useRun 经 getSubgraphState 获取）。
// 子图 state 缺失时回退到从 interrupt message 的 "\n\n---\n" 之前解析草稿。
// resume 值："" = 通过，非空文本 = 修改意见（驱动重新生成）。

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { MessageOnlyPayload } from "../../lib/interruptTypes";
import type { SubgraphState } from "../../lib/langgraph";
import { reviewTypeLabel } from "../../lib/types";

interface Props {
  payload: MessageOnlyPayload;
  subgraphState: SubgraphState | null;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

/** 从 interrupt message 解析草稿正文（分隔符 \n\n---\n 之前的部分），作为子图 state 缺失时的回退 */
function parseDraftFromMessage(message: string): string {
  const idx = message.indexOf("\n\n---\n");
  return idx >= 0 ? message.slice(0, idx) : message;
}

export function HumanReviewForm({ payload, subgraphState, onSubmit, disabled }: Props) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"approve" | "revise">("approve");

  // 草稿优先取子图 state 的 current_draft，回退到 message 解析
  // 用 ?? 而非 ||：空字符串是有效草稿状态（生成失败/清空），不应被当作缺失而回退
  const draft = subgraphState?.current_draft ?? parseDraftFromMessage(payload.message ?? "");
  const aiFeedback = subgraphState?.review_feedback ?? "";
  const history = subgraphState?.review_history ?? [];
  const reviewType = subgraphState?.review_type ?? "foundation";
  const llmReviewCount = subgraphState?.llm_review_count ?? 0;
  // 每轮 2 条历史（human + ai）；轮次 = 已完成的 generate 次数
  const round = Math.floor((history.length || 0) / 2);

  const submit = () => {
    onSubmit(mode === "approve" ? "" : feedback.trim());
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">
          人工审核 · {reviewTypeLabel(reviewType)}
        </h3>
        {round > 0 && (
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            第 {round} 轮迭代（AI 自审 {llmReviewCount} 次）
          </span>
        )}
      </div>

      {/* AI 自审意见（若有） */}
      {aiFeedback && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="mb-1 text-xs font-medium text-amber-700">AI 自审意见</div>
          <div className="whitespace-pre-wrap text-sm text-amber-900">{aiFeedback}</div>
        </div>
      )}

      {/* 当前草稿 */}
      <div className="rounded border border-gray-200 bg-white p-3">
        <div className="mb-2 text-xs font-medium text-gray-500">当前草稿</div>
        <div className="prose prose-sm max-w-none overflow-y-auto max-h-96">
          <ReactMarkdown>{draft || "（无草稿内容）"}</ReactMarkdown>
        </div>
      </div>

      {/* 修改历史 */}
      {history.length > 0 && (
        <details className="rounded border border-gray-200 p-2 text-sm">
          <summary className="cursor-pointer text-gray-600">
            修改历史（{history.length} 条）
          </summary>
          <div className="mt-2 space-y-2">
            {history.map((h, i) => {
              // generate() 会把 AI 自审反馈也作为 human turn 写入 history，
              // 内容以 "[AI审稿意见]" 开头——据此区分展示标签
              const isAiReview = h.content?.startsWith("[AI审稿意见]");
              const label =
                h.role === "ai"
                  ? "AI 生成"
                  : isAiReview
                    ? "AI 审稿意见"
                    : "你的修改意见";
              return (
                <div
                  key={i}
                  className={
                    h.role === "ai"
                      ? "rounded bg-gray-50 p-2 text-gray-700"
                      : isAiReview
                        ? "rounded bg-amber-50 p-2 text-amber-900"
                        : "rounded bg-blue-50 p-2 text-blue-900"
                  }
                >
                  <div className="mb-1 text-xs font-medium opacity-70">{label}</div>
                  <div className="whitespace-pre-wrap">{h.content}</div>
                </div>
              );
            })}
          </div>
        </details>
      )}

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
