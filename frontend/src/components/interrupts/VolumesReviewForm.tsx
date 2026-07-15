// volumes 专用可编辑审核表单——`review_type=volumes` 时替代 HumanReviewForm 里的只读卡片，
// 每卷可就地编辑 title/summary/setup_for_next/target_min/target_max，chapter_start 前卷推算只读。
//
// 数据通路：
//   1. 从 payload.current_draft 解析 JSON → 编辑态 Volume[]
//   2. 用户编辑；chapter_start 随前卷 target_max 变化自动重算（拼接规则：start[i+1]=start[i]+target_max[i]）
//   3. 校验合法（严格对齐后端 save_volumes：index 顺次 / range 合法 / status 枚举）
//   4a. 「通过」→ updateThreadState 覆写 current_draft 为编辑后的 JSON → onSubmit(approve resume)
//   4b. 「提出修改意见」→ 走原 HumanReviewForm 语义（feedback 文本 + thinking）
//
// 手改安全性：状态是 last-value-wins，无 reducer；save_volumes 会解析 current_draft 直接落库到
// state.volumes。走 update_state 覆盖 current_draft 与直接放入 resume 不同（后者需要后端认识
// dict 型 resume 才能取代 JSON 字符串——目前 save_volumes 是从 current_draft 解析的），
// 与「编辑当前状态」抽屉的模式一致，见 useStateEditor.ts。

import { useEffect, useMemo, useState } from "react";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import { updateThreadState } from "../../lib/langgraph";
import type { Volume } from "../../lib/types";
import { ThinkingSwitch } from "./ThinkingSwitch";

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
  threadId: string;
}

/** 空卷模板——用于「新增」按钮。 */
function emptyVolume(index: number, chapter_start: number): Volume {
  return {
    index,
    title: "",
    summary: "",
    setup_for_next: "",
    chapter_start,
    target_min: 20,
    target_max: 25,
    actual_end: null,
    status: index === 1 ? "in_progress" : "planning",
  };
}

/** 宽松解析：允许 markdown 围栏、允许前后冗余文本、只提取首个 [...] 数组。 */
function tryParseVolumes(raw: string): Volume[] | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  const start = body.indexOf("[");
  const end = body.lastIndexOf("]");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const parsed = JSON.parse(body.slice(start, end + 1));
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    // 强制补齐字段（LLM 输出可能缺 actual_end / status 等；后端 save_volumes 是严格的）
    return parsed.map((raw: unknown, i: number): Volume => {
      const o = (raw ?? {}) as Record<string, unknown>;
      const status = typeof o.status === "string" ? o.status : i === 0 ? "in_progress" : "planning";
      return {
        index: typeof o.index === "number" ? o.index : i + 1,
        title: typeof o.title === "string" ? o.title : "",
        summary: typeof o.summary === "string" ? o.summary : "",
        setup_for_next: typeof o.setup_for_next === "string" ? o.setup_for_next : "",
        chapter_start: typeof o.chapter_start === "number" ? o.chapter_start : 1,
        target_min: typeof o.target_min === "number" ? o.target_min : 0,
        target_max: typeof o.target_max === "number" ? o.target_max : 0,
        actual_end:
          o.actual_end == null
            ? null
            : typeof o.actual_end === "number"
              ? o.actual_end
              : null,
        status: (status === "planning" || status === "in_progress" || status === "closed"
          ? status
          : "planning") as Volume["status"],
      };
    });
  } catch {
    return null;
  }
}

/** 按当前编辑值重算所有卷的 chapter_start（前卷 target_max 变化联动）。已收卷（actual_end != null）
 * 章号锁定不动。保持 index 顺次（1-based）。 */
function recomputeChapterStart(volumes: Volume[]): Volume[] {
  const out: Volume[] = [];
  let nextStart = 1;
  volumes.forEach((v, i) => {
    const start = v.actual_end != null ? v.chapter_start : nextStart;
    out.push({ ...v, index: i + 1, chapter_start: start });
    nextStart = start + v.target_max;
  });
  return out;
}

/** 校验：与后端 save_volumes 对齐——index 顺次、chapter_start 拼接、range 合法。 */
function validate(volumes: Volume[]): string[] {
  const issues: string[] = [];
  if (volumes.length === 0) {
    issues.push("至少需要 1 卷");
    return issues;
  }
  let expectedStart = 1;
  for (let i = 0; i < volumes.length; i++) {
    const v = volumes[i];
    const label = `第 ${i + 1} 卷`;
    if (!v.title.trim()) issues.push(`${label} 缺 title`);
    if (v.target_min <= 0 || v.target_max <= 0)
      issues.push(`${label} target_min/target_max 必须 > 0`);
    if (v.target_min > v.target_max)
      issues.push(`${label} target_min=${v.target_min} > target_max=${v.target_max}`);
    if (v.actual_end == null && v.chapter_start !== expectedStart)
      issues.push(`${label} chapter_start=${v.chapter_start}，应为 ${expectedStart}（拼接规则）`);
    if (v.index !== i + 1) issues.push(`${label} index=${v.index}，应为 ${i + 1}`);
    expectedStart = v.chapter_start + v.target_max;
  }
  return issues;
}

function StatusBadge({ status }: { status: Volume["status"] }) {
  const map: Record<Volume["status"], { label: string; cls: string }> = {
    planning: { label: "未开启", cls: "border-gray-200 bg-gray-50 text-gray-500" },
    in_progress: { label: "进行中", cls: "border-blue-300 bg-blue-50 text-blue-700" },
    closed: { label: "已收卷 ✓", cls: "border-green-300 bg-green-50 text-green-700" },
  };
  const meta = map[status] ?? { label: status, cls: "border-red-300 bg-red-50 text-red-700" };
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] ${meta.cls}`}>{meta.label}</span>;
}

interface VolumeEditorCardProps {
  volume: Volume;
  isLast: boolean;
  disabled: boolean;
  onChange: (patch: Partial<Volume>) => void;
  onRemove: () => void;
}

function VolumeEditorCard({ volume, isLast, disabled, onChange, onRemove }: VolumeEditorCardProps) {
  const winEnd = volume.chapter_start + volume.target_max - 1;
  const locked = volume.actual_end != null; // 已收卷：不允许改章号/range/状态（保护历史）
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="text-sm font-semibold text-gray-800">卷 {volume.index}</div>
        <span className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
          第 {volume.chapter_start} 章起 · 目标 {volume.target_min}-{volume.target_max} 章 · 窗口 [
          {volume.chapter_start}, {winEnd}]
        </span>
        <StatusBadge status={volume.status} />
        {locked && (
          <span className="rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[10px] text-green-700">
            实际收卷第 {volume.actual_end} 章（已锁定）
          </span>
        )}
        <div className="ml-auto">
          <button
            type="button"
            onClick={onRemove}
            disabled={disabled}
            className="text-xs text-gray-400 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
            title="删除本卷"
          >
            删除
          </button>
        </div>
      </div>
      <div className="space-y-3 px-3 py-3">
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">卷名 (title)</label>
          <input
            type="text"
            value={volume.title}
            onChange={(e) => onChange({ title: e.target.value })}
            disabled={disabled}
            placeholder="第 X 卷 · XXX"
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
          />
        </div>
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">
            本卷主线 (summary，≤80 字)
          </label>
          <textarea
            value={volume.summary}
            onChange={(e) => onChange({ summary: e.target.value })}
            disabled={disabled}
            rows={2}
            placeholder="本卷主线目标 & 情绪基调"
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
          />
        </div>
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">
            卷尾 setup {isLast ? "（终卷可空）" : "（≤60 字，为下一卷埋钩）"}
          </label>
          <textarea
            value={volume.setup_for_next}
            onChange={(e) => onChange({ setup_for_next: e.target.value })}
            disabled={disabled}
            rows={2}
            placeholder={isLast ? "（终卷可空）" : "卷尾要为下一卷埋的钩"}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">
              chapter_start<span className="text-[10px] text-gray-300">（只读）</span>
            </label>
            <input
              type="number"
              value={volume.chapter_start}
              readOnly
              className="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1 text-sm text-gray-500"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">target_min</label>
            <input
              type="number"
              min={1}
              value={volume.target_min}
              onChange={(e) => onChange({ target_min: parseInt(e.target.value) || 0 })}
              disabled={disabled || locked}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">target_max</label>
            <input
              type="number"
              min={1}
              value={volume.target_max}
              onChange={(e) => onChange({ target_max: parseInt(e.target.value) || 0 })}
              disabled={disabled || locked}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export function VolumesReviewForm({ payload, onSubmit, disabled, threadId }: Props) {
  const draft = payload.current_draft ?? "";
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const llmReviewCount = payload.llm_review_count ?? 0;
  const round = Math.floor((history.length || 0) / 2);

  // 初始化：从 draft 解析 → 每卷补齐字段
  const initialVolumes = useMemo(() => tryParseVolumes(draft) ?? [], [draft]);

  const [volumes, setVolumes] = useState<Volume[]>(initialVolumes);
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
    setVolumes(tryParseVolumes(payload.current_draft ?? "") ?? []);
  }, [payload, disabled]);

  const issues = useMemo(() => validate(volumes), [volumes]);

  // 编辑某卷字段。若改 target_max 需重算后续卷 chapter_start（拼接规则）。
  const patchVolume = (i: number, patch: Partial<Volume>) => {
    setVolumes((prev) => {
      const next = prev.map((v, idx) => (idx === i ? { ...v, ...patch } : v));
      // target_max 变化需要重算 chapter_start
      if ("target_max" in patch) return recomputeChapterStart(next);
      return next;
    });
  };

  const removeVolume = (i: number) => {
    setVolumes((prev) => recomputeChapterStart(prev.filter((_, idx) => idx !== i)));
  };

  const addVolume = () => {
    setVolumes((prev) => {
      const last = prev[prev.length - 1];
      const nextStart = last ? last.chapter_start + last.target_max : 1;
      const nextIndex = prev.length + 1;
      return [...prev, emptyVolume(nextIndex, nextStart)];
    });
  };

  const handleSubmit = async () => {
    if (mode === "approve" && issues.length > 0) return; // 通过前必须合规
    setSubmitting(true);
    setSaveError(null);

    if (mode === "approve") {
      // 覆写 current_draft 为编辑后的 JSON（保持字符串形态，后端 save_volumes 从中解析）。
      // 用 update_state 更新，不影响 interrupt（LangGraph 会清 interrupts 两源但 next 保留，
      // resume 仍然生效——与「编辑当前状态」抽屉同款模式）。
      try {
        await updateThreadState(threadId, {
          current_draft: JSON.stringify(volumes, null, 2),
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
  const canApprove = mode === "approve" && issues.length === 0;
  const canRevise = mode === "revise" && feedback.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">人工审核 · 分卷规划</h3>
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

      {/* 顶部摘要 + 校验问题 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">共 {volumes.length} 卷</span>
        {volumes.length > 0 && (
          <>
            <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-gray-600">
              总章数 {volumes.reduce((s, v) => s + v.target_max, 0)}
            </span>
            <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-gray-600">
              整书窗口 [1, {volumes[volumes.length - 1].chapter_start + volumes[volumes.length - 1].target_max - 1}]
            </span>
          </>
        )}
        {issues.length > 0 && (
          <span className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700">
            ⚠ {issues.length} 项校验问题
          </span>
        )}
      </div>
      {issues.length > 0 && (
        <ul className="space-y-0.5 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {issues.map((msg, i) => (
            <li key={i}>❌ {msg}</li>
          ))}
        </ul>
      )}

      {/* 可编辑卡片列表 */}
      <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        {volumes.length === 0 && (
          <div className="rounded border border-dashed border-gray-200 bg-gray-50 px-3 py-4 text-center text-xs text-gray-400">
            （未解析到有效卷；可点「新增一卷」手工构造）
          </div>
        )}
        {volumes.map((v, i) => (
          <VolumeEditorCard
            key={i}
            volume={v}
            isLast={i === volumes.length - 1}
            disabled={isDisabled}
            onChange={(patch) => patchVolume(i, patch)}
            onRemove={() => removeVolume(i)}
          />
        ))}
      </div>
      <button
        type="button"
        onClick={addVolume}
        disabled={isDisabled}
        className="w-full rounded border border-dashed border-gray-300 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
      >
        + 新增一卷
      </button>

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
              placeholder="输入修改意见，AI 会据此重新生成分卷规划…"
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
