// volumes 专用可编辑审核表单——`review_type=volumes` 时替代只读卡片。前瞻队列架构下一次规划
// 「1 个激活卷（要立即展开）+ N 个前瞻草稿卷」：草稿是对象 {"volumes":[激活卷, 草稿1, ...]}。
// 激活卷含 4 字段 title/summary/setup_for_next/chapters；草稿卷只 3 字段（无 chapters，不锁章号）。
// index/chapter_start/planned_end/status 由后端 save_volumes 权威赋值，前端不碰绝对章号。
//
// 数据通路：
//   1. 从 payload.current_draft 解析 {volumes:[...]} → 编辑态 DraftVolume[]（激活卷 chapters 载入即夹护栏）
//   2. 编辑激活卷 4 字段 + 各草稿卷 3 字段（可增删草稿卷）；chapters 可突破 [15,50]（LLM 夹、人可破）
//   3. 「通过」→ updateThreadState 覆写 current_draft 为 {volumes:[...], human_confirmed:true}
//       （save_volumes 据此不再夹激活卷章数）→ onSubmit(approve resume)
//   4. 「提出修改意见」→ 走原 HumanReviewForm 语义（feedback 文本 + thinking）
//
// 手改安全性：状态 last-value-wins，无 reducer；save_volumes 从 current_draft 解析后权威落库到
// state.volumes（覆盖语义）。走 update_state 覆写 current_draft 与「编辑当前状态」抽屉同款模式。

import { useEffect, useMemo, useState } from "react";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import { updateThreadState } from "../../lib/langgraph";
import { ThinkingSwitch } from "./ThinkingSwitch";

// 章数松护栏（镜像后端 config.VOLUME_MIN/MAX_CHAPTERS 默认值）。前端仅用于「载入时夹默认值 +
// 越界软警告」；后端才是真护栏（LLM 自主输出无 human_confirmed 时夹）。
const VOLUME_MIN_CHAPTERS = 15;
const VOLUME_MAX_CHAPTERS = 50;

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
  threadId: string;
}

/** 草稿卷编辑态：激活卷（第 0 项）带 chapters；前瞻草稿卷无 chapters。 */
interface DraftVolume {
  title: string;
  summary: string;
  setup_for_next: string;
  chapters?: number;
}

const clampChapters = (n: number): number =>
  Math.min(VOLUME_MAX_CHAPTERS, Math.max(VOLUME_MIN_CHAPTERS, n));

const emptyDraftVolume = (): DraftVolume => ({ title: "", summary: "", setup_for_next: "" });

/** 从原始文本提取 JSON（允许 markdown 围栏、前后冗余文本；支持对象 {volumes:[...]} 或裸数组）。 */
function extractJson(raw: string): unknown | null {
  if (!raw || !raw.trim()) return null;
  const fenced = raw.trim().match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = (fenced ? fenced[1] : raw).trim();
  const tryParse = (s: string): unknown | null => {
    try {
      return JSON.parse(s);
    } catch {
      return null;
    }
  };
  let parsed = tryParse(body);
  if (parsed == null) {
    // 提取更靠前的容器：裸数组 [...] 或对象 {...}
    const objStart = body.indexOf("{");
    const arrStart = body.indexOf("[");
    if (arrStart !== -1 && (objStart === -1 || arrStart < objStart)) {
      parsed = tryParse(body.slice(arrStart, body.lastIndexOf("]") + 1));
    } else if (objStart !== -1) {
      parsed = tryParse(body.slice(objStart, body.lastIndexOf("}") + 1));
    }
  }
  return parsed;
}

/** 宽松解析多卷草稿 → DraftVolume[]（第 0 项激活卷带 chapters）。契约 {"volumes":[...]}，也兼容裸数组。 */
function tryParseVolumesDraft(raw: string): DraftVolume[] | null {
  const parsed = extractJson(raw);
  if (parsed == null) return null;
  const arr: unknown = Array.isArray(parsed)
    ? parsed
    : typeof parsed === "object" && Array.isArray((parsed as Record<string, unknown>).volumes)
      ? (parsed as Record<string, unknown>).volumes
      : null;
  if (!Array.isArray(arr) || arr.length === 0) return null;
  return arr.map((item, i): DraftVolume => {
    const o = (typeof item === "object" && item !== null ? item : {}) as Record<string, unknown>;
    const base: DraftVolume = {
      title: typeof o.title === "string" ? o.title : "",
      summary: typeof o.summary === "string" ? o.summary : "",
      setup_for_next: typeof o.setup_for_next === "string" ? o.setup_for_next : "",
    };
    if (i === 0) {
      // 激活卷章数载入即夹护栏，让 rubber-stamp（不改直接通过）也落合理区间；人工可在 input 再突破。
      const rawCh = typeof o.chapters === "number" ? Math.round(o.chapters) : NaN;
      base.chapters = Number.isFinite(rawCh) ? clampChapters(rawCh) : VOLUME_MIN_CHAPTERS;
    }
    return base;
  });
}

/** 校验（阻断「通过」）：激活卷 title 非空 + chapters 正整数；各草稿卷 title 非空。越界只软警告。 */
function validate(vs: DraftVolume[] | null): string[] {
  if (!vs || vs.length === 0) return ["未解析到有效的分卷 JSON（可提修改意见让 AI 重生成）"];
  const issues: string[] = [];
  const active = vs[0];
  if (!active.title.trim()) issues.push("激活卷缺 卷名(title)");
  if (!Number.isInteger(active.chapters ?? NaN) || (active.chapters ?? 0) <= 0) {
    issues.push("激活卷 本卷章数必须是正整数");
  }
  vs.slice(1).forEach((d, i) => {
    if (!d.title.trim()) issues.push(`前瞻草稿卷 ${i + 1} 缺 卷名(title)`);
  });
  return issues;
}

/** 单卷字段编辑块——激活卷带 chapters（withChapters），草稿卷不带。 */
function VolumeFields({
  vol,
  disabled,
  onPatch,
  withChapters,
}: {
  vol: DraftVolume;
  disabled: boolean;
  onPatch: (p: Partial<DraftVolume>) => void;
  withChapters?: boolean;
}) {
  const outOfRange =
    withChapters &&
    vol.chapters != null &&
    (vol.chapters < VOLUME_MIN_CHAPTERS || vol.chapters > VOLUME_MAX_CHAPTERS);
  const inputCls =
    "w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100";
  return (
    <>
      <div>
        <label className="mb-0.5 block text-xs font-medium text-gray-500">卷名 (title)</label>
        <input
          type="text"
          value={vol.title}
          onChange={(e) => onPatch({ title: e.target.value })}
          disabled={disabled}
          placeholder="第 X 卷 · XXX"
          className={inputCls}
        />
      </div>
      <div>
        <label className="mb-0.5 block text-xs font-medium text-gray-500">
          本卷主线 (summary，≤80 字)
        </label>
        <textarea
          value={vol.summary}
          onChange={(e) => onPatch({ summary: e.target.value })}
          disabled={disabled}
          rows={2}
          placeholder="本卷主线目标 + 情绪基调 + 收尾状态"
          className={inputCls}
        />
      </div>
      <div>
        <label className="mb-0.5 block text-xs font-medium text-gray-500">
          卷尾 setup（为下一卷埋钩；终卷可空）
        </label>
        <textarea
          value={vol.setup_for_next}
          onChange={(e) => onPatch({ setup_for_next: e.target.value })}
          disabled={disabled}
          rows={2}
          placeholder="卷尾要为下一卷埋的钩子/悬念/角色转折"
          className={inputCls}
        />
      </div>
      {withChapters && (
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
            value={vol.chapters ?? VOLUME_MIN_CHAPTERS}
            onChange={(e) => onPatch({ chapters: parseInt(e.target.value) || 0 })}
            disabled={disabled}
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
      )}
    </>
  );
}

export function VolumesReviewForm({ payload, onSubmit, disabled, threadId }: Props) {
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const llmReviewCount = payload.llm_review_count ?? 0;
  const round = Math.floor((history.length || 0) / 2);

  const initial = useMemo(
    () => tryParseVolumesDraft(payload.current_draft ?? ""),
    [payload.current_draft],
  );

  const [volumes, setVolumes] = useState<DraftVolume[] | null>(initial);
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
    setVolumes(tryParseVolumesDraft(payload.current_draft ?? ""));
  }, [payload, disabled]);

  const issues = useMemo(() => validate(volumes), [volumes]);

  const patchVolume = (idx: number, p: Partial<DraftVolume>) =>
    setVolumes((prev) => (prev ? prev.map((v, i) => (i === idx ? { ...v, ...p } : v)) : prev));
  const addDraft = () =>
    setVolumes((prev) => (prev ? [...prev, emptyDraftVolume()] : [emptyDraftVolume()]));
  const removeDraft = (idx: number) =>
    setVolumes((prev) => (prev ? prev.filter((_, i) => i !== idx) : prev));

  const handleSubmit = async () => {
    if (mode === "approve" && (issues.length > 0 || !volumes)) return;
    setSubmitting(true);
    setSaveError(null);

    if (mode === "approve" && volumes) {
      // 覆写 current_draft 为 {volumes:[...], human_confirmed:true}（save_volumes 据此视为人工终裁、
      // 不再夹激活卷章数）。激活卷带 chapters，草稿卷不带。
      const payloadObj = {
        volumes: volumes.map((v, i) =>
          i === 0
            ? {
                title: v.title,
                summary: v.summary,
                setup_for_next: v.setup_for_next,
                chapters: v.chapters ?? VOLUME_MIN_CHAPTERS,
              }
            : { title: v.title, summary: v.summary, setup_for_next: v.setup_for_next },
        ),
        human_confirmed: true,
      };
      try {
        await updateThreadState(threadId, {
          current_draft: JSON.stringify(payloadObj, null, 2),
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
  const canApprove = mode === "approve" && issues.length === 0 && volumes != null;
  const canRevise = mode === "revise" && feedback.trim().length > 0;

  const active = volumes?.[0] ?? null;
  const drafts = volumes?.slice(1) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">
          人工审核 · 分卷规划（1 激活 + {drafts.length} 前瞻草稿）
        </h3>
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

      {volumes && active ? (
        <div className="space-y-3">
          {/* 激活卷（要立即展开，编 4 字段含章数）*/}
          <div className="space-y-3 rounded-lg border border-blue-300 bg-blue-50/40 px-3 py-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="rounded bg-blue-600 px-2 py-0.5 text-[10px] font-medium text-white">
                激活卷 · 即将展开
              </span>
              <span className="text-[10px] text-gray-400">卷号/章号由系统权威顺延</span>
            </div>
            <VolumeFields vol={active} disabled={isDisabled} onPatch={(p) => patchVolume(0, p)} withChapters />
          </div>

          {/* 前瞻草稿卷（只给方向，编 3 字段；可增删）*/}
          {drafts.map((d, i) => (
            <div
              key={i}
              className="space-y-3 rounded-lg border border-dashed border-gray-300 bg-white px-3 py-3 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                  前瞻草稿 {i + 1} · 未锁章号
                </span>
                <button
                  type="button"
                  onClick={() => removeDraft(i + 1)}
                  disabled={isDisabled}
                  className="text-[11px] text-red-500 hover:text-red-700 disabled:text-gray-300"
                >
                  删除
                </button>
              </div>
              <VolumeFields vol={d} disabled={isDisabled} onPatch={(p) => patchVolume(i + 1, p)} />
            </div>
          ))}

          <button
            type="button"
            onClick={addDraft}
            disabled={isDisabled}
            className="w-full rounded border border-dashed border-gray-300 px-3 py-2 text-xs text-gray-500 hover:bg-gray-50 disabled:text-gray-300"
          >
            + 添加前瞻草稿卷
          </button>
        </div>
      ) : (
        <div className="rounded border border-dashed border-amber-300 bg-amber-50 px-3 py-4 text-center text-xs text-amber-700">
          未解析到有效的分卷 JSON（含 volumes 数组）。请走「提出修改意见」让 AI 重新输出合规 JSON。
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
              placeholder="输入修改意见，AI 会据此重新生成前瞻队列（激活卷 + 草稿卷）…"
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
