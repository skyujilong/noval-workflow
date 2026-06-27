// human_review 富审稿表单。
// 草稿/AI 自审意见/修改历史/review_type 均来自 payload（后端 subgraph.py:human_review 自描述），
// 前端直接读，不再依赖 getSubgraphState（避免嵌套子图冒泡选错 task）。
// resume 值："" = 通过，非空文本 = 修改意见（驱动重新生成）。

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { HumanReviewPayload } from "../../lib/interruptTypes";
import { reviewTypeLabel } from "../../lib/types";

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function HumanReviewForm({ payload, onSubmit, disabled }: Props) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"approve" | "revise">("approve");
  const [submitting, setSubmitting] = useState(false);

  // 全部上下文直接取自 payload（用 ?? 兜底缺失，空字符串是有效草稿状态）
  const draft = payload.current_draft ?? "";
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const reviewType = payload.review_type ?? "foundation";
  const llmReviewCount = payload.llm_review_count ?? 0;
  // 每轮 2 条历史（human + ai）；轮次 = 已完成的 generate 次数
  const round = Math.floor((history.length || 0) / 2);

  // 提交结束（disabled false）或新 interrupt（payload 变化）时重置状态
  useEffect(() => {
    setSubmitting(false);
    setFeedback("");
    setMode("approve");
  }, [disabled, payload]);

  const handleSubmit = () => {
    setSubmitting(true);
    onSubmit(mode === "approve" ? "" : feedback.trim());
  };

  // 本地 submitting 优先于上层 disabled，确保点击后立即禁用所有控件
  const isDisabled = disabled || submitting;

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
        <div className="prose prose-sm max-w-none overflow-y-auto max-h-96 [&_p]:text-indent-[2em] [&_p]:whitespace-pre-wrap">
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

      {/* 操作区 - 分层设计：模式选择在上，提交按钮单独一行突出 */}
      <div className="space-y-3 border-t pt-3">
        {/* 模式选择 - 视觉上是选择器，不是操作按钮 */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("approve")}
            disabled={isDisabled}
            className={
              "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
              (mode === "approve"
                ? "border-green-600 bg-green-50 text-green-700"
                : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
            }
          >
            ✓ 通过
          </button>
          <button
            type="button"
            onClick={() => setMode("revise")}
            disabled={isDisabled}
            className={
              "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
              (mode === "revise"
                ? "border-blue-600 bg-blue-50 text-blue-700"
                : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
            }
          >
            ✎ 提出修改意见
          </button>
        </div>

        {mode === "revise" && (
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={isDisabled}
            placeholder="输入修改意见，AI 会据此重新生成…"
            rows={4}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        )}

        {/* 提交按钮 - 单独一行，视觉突出，是唯一的「最终确认」按钮 */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isDisabled || (mode === "revise" && !feedback.trim())}
          className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "⏳ 提交中..." : mode === "approve" ? "确认通过" : "提交修改意见"}
        </button>
      </div>
    </div>
  );
}
