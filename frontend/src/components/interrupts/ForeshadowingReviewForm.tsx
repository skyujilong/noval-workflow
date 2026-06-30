// 伏笔台账审核专用表单，将 JSON 格式的伏笔转为卡片展示。
// resume 值：结构化 {feedback, thinking}（与 human_review 统一）；feedback 空 = 通过。

import { useEffect, useState } from "react";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import { ThinkingSwitch } from "./ThinkingSwitch";

interface ForeshadowEntry {
  id: string;
  name: string;
  planted_batch: number;
  current_appearance: string;
  core_purpose: string;
  planned_recovery_range: string;
  freedom: string;
  recovered_at_chapter?: number;
}

interface ForeshadowData {
  pending: ForeshadowEntry[];
  collected: ForeshadowEntry[];
}

function parseForeshadowDraft(draft: string): ForeshadowData | null {
  try {
    const parsed = JSON.parse(draft.trim());
    if (parsed && (parsed.pending || parsed.collected)) {
      return {
        pending: Array.isArray(parsed.pending) ? parsed.pending : [],
        collected: Array.isArray(parsed.collected) ? parsed.collected : [],
      };
    }
    return null;
  } catch {
    return null;
  }
}

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
}

export function ForeshadowingReviewForm({
  payload,
  onSubmit,
  disabled,
}: Props) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"approve" | "revise">("approve");
  // 深度思考开关初值跟随后端默认（伏笔属快照类 → 默认关），可在打回时手动开启求质量
  const [thinkingOn, setThinkingOn] = useState(payload.default_thinking !== "disabled");
  const [submitting, setSubmitting] = useState(false);

  const draft = payload.current_draft ?? "";
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const llmReviewCount = payload.llm_review_count ?? 0;
  const round = Math.floor((history.length || 0) / 2);

  const foreshadowData = parseForeshadowDraft(draft);

  // 提交结束（disabled false）或新 interrupt 时重置状态
  useEffect(() => {
    setSubmitting(false);
    setFeedback("");
    setMode("approve");
    setThinkingOn(payload.default_thinking !== "disabled");
  }, [disabled, payload]);

  const handleSubmit = () => {
    setSubmitting(true);
    onSubmit(buildReviewResume(mode === "approve" ? "" : feedback, thinkingOn));
  };

  const isDisabled = disabled || submitting;

  const freedomColor = (freedom: string) => {
    if (freedom === "高") return "bg-rose-50 text-rose-700 border-rose-200";
    if (freedom === "中") return "bg-amber-50 text-amber-700 border-amber-200";
    return "bg-gray-50 text-gray-600 border-gray-200";
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">人工审核 · 伏笔台账</h3>
        {round > 0 && (
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            第 {round} 轮迭代（AI 自审 {llmReviewCount} 次）
          </span>
        )}
      </div>

      {/* AI 自审意见 */}
      {aiFeedback && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="mb-1 text-xs font-medium text-amber-700">AI 自审意见</div>
          <div className="whitespace-pre-wrap text-sm text-amber-900">{aiFeedback}</div>
        </div>
      )}

      {/* 伏笔台账 - 结构化展示 */}
      {foreshadowData ? (
        <div className="space-y-4">
          {/* 悬置伏笔 */}
          <div className="rounded border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-medium text-gray-700">
                📌 悬置伏笔（pending）— {foreshadowData.pending.length} 个
              </h4>
            </div>
            {foreshadowData.pending.length === 0 ? (
              <div className="text-sm text-gray-400 italic">暂无悬置伏笔</div>
            ) : (
              <div className="space-y-3">
                {foreshadowData.pending.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm"
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="font-semibold text-gray-800">
                        {entry.id} · {entry.name}
                      </span>
                      <div className="flex gap-2">
                        <span className="rounded border bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                          批次: {entry.planted_batch}
                        </span>
                        <span
                          className={`rounded border px-2 py-0.5 text-xs ${freedomColor(entry.freedom)}`}
                        >
                          自由度: {entry.freedom}
                        </span>
                      </div>
                    </div>
                    <div className="space-y-1 text-gray-600">
                      <div>
                        <span className="text-gray-400">潜伏表现：</span>
                        {entry.current_appearance}
                      </div>
                      <div>
                        <span className="text-gray-400">核心作用：</span>
                        {entry.core_purpose}
                      </div>
                      <div>
                        <span className="text-gray-400">预计回收：</span>
                        {entry.planned_recovery_range}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 已收伏笔 */}
          <div className="rounded border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-medium text-gray-700">
                ✅ 已收伏笔（collected）— {foreshadowData.collected.length} 个
              </h4>
            </div>
            {foreshadowData.collected.length === 0 ? (
              <div className="text-sm text-gray-400 italic">暂无已收伏笔</div>
            ) : (
              <div className="space-y-3">
                {foreshadowData.collected.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm opacity-80"
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="font-semibold text-gray-800">
                        {entry.id} · {entry.name}
                      </span>
                      <div className="flex gap-2">
                        <span className="rounded border bg-green-100 px-2 py-0.5 text-xs text-green-700">
                          ✅ 第{entry.recovered_at_chapter}章回收
                        </span>
                      </div>
                    </div>
                    <div className="space-y-1 text-gray-600">
                      <div>
                        <span className="text-gray-400">潜伏表现：</span>
                        {entry.current_appearance}
                      </div>
                      <div>
                        <span className="text-gray-400">核心作用：</span>
                        {entry.core_purpose}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        /* JSON 解析失败时兜底显示原始内容 */
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-2 text-xs font-medium text-gray-500">当前草稿（原始格式）</div>
          <div className="prose prose-sm max-w-none overflow-x-auto whitespace-pre-wrap text-sm text-gray-700">
            {draft || "（无草稿内容）"}
          </div>
        </div>
      )}

      {/* 修改历史 */}
      {history.length > 0 && (
        <details className="rounded border border-gray-200 p-2 text-sm">
          <summary className="cursor-pointer text-gray-600">修改历史（{history.length} 条）</summary>
          <div className="mt-2 space-y-2">
            {history.map((h, i) => {
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
      <div className="space-y-3 border-t pt-3">
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
          <>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={isDisabled}
              placeholder="输入修改意见，AI 会据此重新生成…"
              rows={4}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <ThinkingSwitch checked={thinkingOn} onChange={setThinkingOn} disabled={isDisabled} />
          </>
        )}

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
