// human_review 富审稿表单。
// 草稿/AI 自审意见/修改历史/review_type 均来自 payload（后端 subgraph.py:human_review 自描述），
// 前端直接读，不再依赖 getSubgraphState（避免嵌套子图冒泡选错 task）。
// resume 值："" = 通过，非空文本 = 修改意见（驱动重新生成）。

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { ArticleParagraphs } from "../ArticleParagraphs";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import type { NovelState } from "../../lib/types";
import { EVOLVABLE_REVIEW_TYPES, reviewTypeLabel } from "../../lib/types";
import { recordReject } from "../../lib/langgraph";
import { ChapterReviewReference } from "./ChapterReviewReference";
import { SceneBeatsCards } from "./SceneBeatsCards";
import { ChapterPlanCards } from "./ChapterPlanCards";
import { VolumesReviewCards } from "./VolumesReviewCards";
import { VolumesReviewForm } from "./VolumesReviewForm";
import { ThinkingSwitch } from "./ThinkingSwitch";

interface Props {
  payload: HumanReviewPayload;
  // 统一结构化 resume：approve → feedback=""，revise → feedback=修改意见；thinking 始终携带。
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
  // 父图 NovelState 快照：章节正文审核时用于展示上一章 / 近期弧线大纲等参考资料。
  novelState?: NovelState;
  // 当前 thread ID：volumes review 表单需要在「通过」时通过 update_state 覆写 current_draft。
  // 未传（普通 review 类型）→ volumes 分支回退到 VolumesReviewCards 只读展示。
  threadId?: string;
}

export function HumanReviewForm({ payload, onSubmit, disabled, novelState, threadId }: Props) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"approve" | "revise">("approve");
  // 深度思考开关初值跟随后端给的默认值（创作类开 / 快照类关），未带则按开处理
  const [thinkingOn, setThinkingOn] = useState(payload.default_thinking !== "disabled");
  const [submitting, setSubmitting] = useState(false);
  // 复制草稿到剪贴板后短暂显示「已复制」反馈
  const [copied, setCopied] = useState(false);

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
    setThinkingOn(payload.default_thinking !== "disabled");
  }, [disabled, payload]);

  // volumes 是结构化 JSON + 需要就地编辑,直接 delegate 到专用表单;要求 threadId 才能覆写
  // current_draft(update_state 通道)。无 threadId 时降级为默认展示,继续走通用只读 + 打回。
  if (reviewType === "volumes" && threadId) {
    return (
      <VolumesReviewForm
        payload={payload}
        onSubmit={onSubmit}
        disabled={disabled}
        threadId={threadId}
      />
    );
  }

  const handleSubmit = () => {
    setSubmitting(true);
    // 打回（提出修改意见）时，把意见落一条 REJECT 记录，供「提示词进化」抽屉逐条提炼。
    // 仅限会重复生成的正文/弧线环节；fire-and-forget，落库失败不影响审核 resume。
    if (
      mode === "revise" &&
      feedback.trim() &&
      novelState?.novel_name &&
      EVOLVABLE_REVIEW_TYPES.has(reviewType)
    ) {
      void recordReject(novelState.novel_name, novelState.genre, {
        review_type: reviewType,
        feedback: feedback.trim(),
        // chapter / scene_beats 都是「每章一次」的环节，落库时带章号让台账可按章检索;
        // arc_outline 是每批一次，与章号不 1:1 绑定，故不带。
        chapter_index:
          reviewType === "chapter" || reviewType === "scene_beats"
            ? novelState.total_chapters_written + 1
            : null,
      }).catch(() => {
        // 落库是辅助功能，失败静默降级，不打断打回重跑
      });
    }
    onSubmit(buildReviewResume(mode === "approve" ? "" : feedback, thinkingOn));
  };

  // 把当前草稿正文复制到剪贴板；剪贴板不可用时静默降级
  const handleCopyDraft = async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 忽略：部分环境（非 https / 无权限）无法访问剪贴板
    }
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
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-medium text-gray-500">当前草稿</div>
          <button
            type="button"
            onClick={handleCopyDraft}
            disabled={!draft}
            title="复制草稿到剪贴板"
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-600" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "已复制" : "复制"}
          </button>
        </div>
        <div className="max-w-none overflow-y-auto max-h-[70vh] text-sm leading-relaxed text-gray-800 [&_p]:[text-indent:2em] [&_p]:mb-4 [&_p]:whitespace-pre-wrap">
          {reviewType === "scene_beats" ? (
            // scene beats 是结构化 JSON,用卡片视图代替散文渲染,让 device_tags 分组可扫、
            // 打脸四拍/钩子位置违规在顶部一眼可见。解析失败自动降级到纯文本。
            <SceneBeatsCards draft={draft} />
          ) : reviewType === "chapter_plan" ? (
            // chapter_plan 也是结构化 JSON（ChapterPlanItem[]），走专用卡片视图，
            // 让「第 N 章 / 本章目标 / 关键转折 / 章末钩子」分区可扫，并用 chip 区分锁定 vs 新增段。
            <ChapterPlanCards draft={draft} novelState={novelState} />
          ) : reviewType === "volumes" ? (
            // volumes 是结构化 JSON（Volume[]），走专用卡片视图，让 4 卷 title/summary/
            // setup_for_next 分卡展示，卷标题条突出 chapter_start + target range + status。
            // 前端只读——想改仍走「提出修改意见」文本打回重跑。
            <VolumesReviewCards draft={draft} />
          ) : draft ? (
            <ArticleParagraphs text={draft} />
          ) : (
            <p className="text-gray-400">（无草稿内容）</p>
          )}
        </div>
      </div>

      {/* 参考资料（仅章节正文审核）：近期弧线大纲 + 上一章正文 */}
      {reviewType === "chapter" && novelState && (
        <ChapterReviewReference novelState={novelState} />
      )}

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
