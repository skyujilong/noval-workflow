// volumes 专用可编辑审核表单——`review_type=volumes` 时替代只读卡片。滚动生成卷架构下
// 一次只规划**一卷**（开书=卷1 / 滚动=下一卷），草稿是单个 JSON 对象，只含 4 个内容字段
// title/summary/setup_for_next/chapters（本卷章数）。index/chapter_start/planned_end/status
// 由后端 save_volumes 权威赋值，前端不碰绝对章号。
//
// 数据通路：
//   1. 从 payload.current_draft 解析单卷对象 → 编辑态 VolumeDraft（chapters 载入即夹到松护栏）
//   2. 用户编辑 title/summary/setup_for_next/chapters；chapters 可突破 [15,50]（LLM 夹、人可破）
//   3. 「通过」→ updateThreadState 覆写 current_draft 为编辑后 JSON（带 human_confirmed 标记，
//       save_volumes 据此不再夹章数）→ onSubmit(approve resume)
//   4. 「提出修改意见」→ 走原 HumanReviewForm 语义（feedback 文本 + thinking）
//
// 手改安全性：状态 last-value-wins，无 reducer；save_volumes 从 current_draft 解析后权威落库到
// state.volumes（覆盖语义）。走 update_state 覆写 current_draft 与「编辑当前状态」抽屉同款模式。

import { useEffect, useMemo, useState } from "react";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import { updateThreadState } from "../../lib/langgraph";
import { ThinkingSwitch } from "./ThinkingSwitch";

// 章数松护栏（镜像后端 config.VOLUME_MIN/MAX_CHAPTERS 默认值 env NOVEL_VOLUME_MIN/MAX_CHAPTERS）。
// 前端仅用于「载入时夹默认值 + 越界软警告」；后端才是真护栏（LLM 自主输出无 human_confirmed 时夹）。
const VOLUME_MIN_CHAPTERS = 15;
const VOLUME_MAX_CHAPTERS = 50;

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
  threadId: string;
}

/** 单卷草稿（LLM/人工编辑的 4 个内容字段）。 */
interface VolumeDraft {
  title: string;
  summary: string;
  setup_for_next: string;
  chapters: number;
}

const clampChapters = (n: number): number =>
  Math.min(VOLUME_MAX_CHAPTERS, Math.max(VOLUME_MIN_CHAPTERS, n));

/** 宽松解析单卷对象：允许 markdown 围栏、前后冗余文本，只提取首个 {...}。chapters 载入即夹护栏。 */
function tryParseVolumeDraft(raw: string): VolumeDraft | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  const start = body.indexOf("{");
  const end = body.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const o = JSON.parse(body.slice(start, end + 1)) as Record<string, unknown>;
    if (typeof o !== "object" || o === null) return null;
    const rawChapters = typeof o.chapters === "number" ? Math.round(o.chapters) : NaN;
    return {
      title: typeof o.title === "string" ? o.title : "",
      summary: typeof o.summary === "string" ? o.summary : "",
      setup_for_next: typeof o.setup_for_next === "string" ? o.setup_for_next : "",
      // 载入即夹到松护栏，让 rubber-stamp（不改直接通过）也落在合理区间；人工可在下方 input 再突破。
      chapters: Number.isFinite(rawChapters) ? clampChapters(rawChapters) : VOLUME_MIN_CHAPTERS,
    };
  } catch {
    return null;
  }
}

/** 校验（阻断「通过」）：title 非空 + chapters 正整数。越界 [15,50] 只软警告不阻断（人可破）。 */
function validate(d: VolumeDraft | null): string[] {
  if (!d) return ["未解析到有效的单卷 JSON（可提修改意见让 AI 重生成）"];
  const issues: string[] = [];
  if (!d.title.trim()) issues.push("缺 卷名(title)");
  if (!Number.isInteger(d.chapters) || d.chapters <= 0) issues.push("本卷章数必须是正整数");
  return issues;
}

export function VolumesReviewForm({ payload, onSubmit, disabled, threadId }: Props) {
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const llmReviewCount = payload.llm_review_count ?? 0;
  const round = Math.floor((history.length || 0) / 2);

  const initialDraft = useMemo(
    () => tryParseVolumeDraft(payload.current_draft ?? ""),
    [payload.current_draft],
  );

  const [draft, setDraft] = useState<VolumeDraft | null>(initialDraft);
  const [mode, setMode] = useState<"approve" | "revise">("approve");
  const [feedback, setFeedback] = useState("");
  const [thinkingOn, setThinkingOn] = useState(payload.default_thinking !== "disabled");
  const [submitting, setSubmitting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // 新 interrupt / disabled 解锁时重置
  useEffect(() => {
    setSubmitting(false);
    setSaveError(null);
    setMode("approve");
    setFeedback("");
    setThinkingOn(payload.default_thinking !== "disabled");
    setDraft(tryParseVolumeDraft(payload.current_draft ?? ""));
  }, [payload, disabled]);

  const issues = useMemo(() => validate(draft), [draft]);
  const outOfRange =
    draft != null && (draft.chapters < VOLUME_MIN_CHAPTERS || draft.chapters > VOLUME_MAX_CHAPTERS);

  const patch = (p: Partial<VolumeDraft>) => setDraft((prev) => (prev ? { ...prev, ...p } : prev));

  const handleSubmit = async () => {
    if (mode === "approve" && (issues.length > 0 || !draft)) return;
    setSubmitting(true);
    setSaveError(null);

    if (mode === "approve" && draft) {
      // 覆写 current_draft 为编辑后的单卷对象 JSON（带 human_confirmed 标记：save_volumes 据此
      // 视为人工终裁、不再夹章数）。保持字符串形态，后端从中解析。
      try {
        await updateThreadState(threadId, {
          current_draft: JSON.stringify(
            {
              title: draft.title,
              summary: draft.summary,
              setup_for_next: draft.setup_for_next,
              chapters: draft.chapters,
              human_confirmed: true,
            },
            null,
            2,
          ),
        });
      } catch (e) {
        setSubmitting(false);
        setSaveError(`保存草稿失败：${(e as Error).message}`);
        return;
      }
    }

    onSubmit(buildReviewResume(mode === "approve" ? "" : feedback, thinkingOn));
  };

  const isDisabled = disabled || submitting;
  const canApprove = mode === "approve" && issues.length === 0 && draft != null;
  const canRevise = mode === "revise" && feedback.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">人工审核 · 分卷规划（单卷）</h3>
        {round > 0 && (
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            第 {round} 轮迭代（AI 自审 {llmReviewCount} 次）
          </span>
        )}
      </div>

      {aiFeedback && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="mb-1 text-xs font-medium text-amber-700">AI 自审意见</div>
          <div className="whitespace-pre-wrap text-sm text-amber-900">{aiFeedback}</div>
        </div>
      )}

      {saveError && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          ⚠ {saveError}
        </div>
      )}

      {issues.length > 0 && (
        <ul className="space-y-0.5 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {issues.map((msg, i) => (
            <li key={i}>❌ {msg}</li>
          ))}
        </ul>
      )}

      {/* 单卷编辑卡片 */}
      {draft ? (
        <div className="space-y-3 rounded-lg border border-gray-200 bg-white px-3 py-3 shadow-sm">
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">卷名 (title)</label>
            <input
              type="text"
              value={draft.title}
              onChange={(e) => patch({ title: e.target.value })}
              disabled={isDisabled}
              placeholder="第 X 卷 · XXX"
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">
              本卷主线 (summary，≤80 字)
            </label>
            <textarea
              value={draft.summary}
              onChange={(e) => patch({ summary: e.target.value })}
              disabled={isDisabled}
              rows={2}
              placeholder="本卷主线目标 + 情绪基调 + 收尾状态"
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">
              卷尾 setup（为下一卷埋钩；终卷可空）
            </label>
            <textarea
              value={draft.setup_for_next}
              onChange={(e) => patch({ setup_for_next: e.target.value })}
              disabled={isDisabled}
              rows={2}
              placeholder="卷尾要为下一卷埋的钩子/悬念/角色转折"
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">
              本卷章数 (chapters)
              <span className="ml-1 text-[10px] text-gray-400">
                松护栏 {VOLUME_MIN_CHAPTERS}-{VOLUME_MAX_CHAPTERS}，可突破
              </span>
            </label>
            <input
              type="number"
              min={1}
              value={draft.chapters}
              onChange={(e) => patch({ chapters: parseInt(e.target.value) || 0 })}
              disabled={isDisabled}
              className="w-32 rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
            {outOfRange && (
              <span className="ml-2 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                ⚠ 超出松护栏 {VOLUME_MIN_CHAPTERS}-{VOLUME_MAX_CHAPTERS}（人工突破，将予以尊重）
              </span>
            )}
            <p className="mt-1 text-[10px] text-gray-400">
              起始章号 / 末章号 / 卷号由系统按上一卷末章权威顺延，此处只定本卷章数。
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded border border-dashed border-amber-300 bg-amber-50 px-3 py-4 text-center text-xs text-amber-700">
          未解析到有效的单卷 JSON 对象。请走「提出修改意见」让 AI 重新输出合规 JSON。
        </div>
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
            ✓ 通过（保存编辑并推进）
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
            ✎ 提出修改意见（让 AI 重生成）
          </button>
        </div>

        {mode === "revise" && (
          <>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={isDisabled}
              placeholder="输入修改意见，AI 会据此重新生成本卷规划…"
              rows={4}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <ThinkingSwitch checked={thinkingOn} onChange={setThinkingOn} disabled={isDisabled} />
          </>
        )}

        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isDisabled || (mode === "approve" ? !canApprove : !canRevise)}
          className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : mode === "approve" ? "确认通过" : "提交修改意见"}
        </button>

        {mode === "approve" && issues.length > 0 && (
          <div className="text-xs text-red-600">⚠ 存在 {issues.length} 项校验问题，请先修复再通过。</div>
        )}
      </div>
    </div>
  );
}
