// 分卷边界闸门（VOLUME_BOUNDARY_GATE）三选一表单：
//   - 继续本卷（不改边界）→ {action: "continue_current"}
//   - 在第 X 章收卷 → {action: "close_at", chapter: X}
//   - 延长本卷 target_max 到 N → {action: "extend_target_max", target_max: N}
//
// 后端 nodes/volume_gate.py::volume_boundary_gate 在 chapter_plan 前判定本次前瞻窗口
// [total_chapters_written+1, +CHAPTER_PLAN_WINDOW] 是否穿越任一卷的 target_min/target_max，
// 穿越即弹 interrupt。此表单展示穿越点 + 当前卷卡片 + 后续卷概览，让用户三选一。
//
// 弹性 range 语义提醒：target_min/target_max 是**章数**（数量，软约束），不是绝对章号；
// 卷内窗口 = [chapter_start, chapter_start + target_max - 1]。close_at.chapter 是绝对章号。

import { useEffect, useMemo, useState } from "react";
import {
  buildVolumeCloseAtResume,
  buildVolumeContinueResume,
  buildVolumeExtendResume,
  type VolumeBoundaryGatePayload,
  type VolumeBoundaryOption,
  type VolumeDictSnapshot,
  type VolumeGateResume,
} from "../../lib/interruptTypes";

interface Props {
  payload: VolumeBoundaryGatePayload;
  onSubmit: (value: VolumeGateResume) => void;
  disabled?: boolean;
}

type Action = "continue_current" | "close_at" | "extend_target_max";

/** 从 options 里按 action 取默认建议值；找不到则 fallback 到入参 fallback。 */
function suggestedOf(
  options: VolumeBoundaryOption[],
  action: Action,
  key: "suggested_chapter" | "suggested_target_max",
  fallback: number
): number {
  const opt = options.find((o) => o.action === action);
  const v = opt?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}

function VolumeSnapshotCard({
  volume,
  emphasis,
}: {
  volume: VolumeDictSnapshot;
  emphasis?: boolean;
}) {
  const winEnd = volume.chapter_start + volume.target_max - 1;
  return (
    <div
      className={
        "rounded border px-3 py-2 " +
        (emphasis
          ? "border-blue-300 bg-blue-50"
          : "border-gray-200 bg-gray-50")
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-sm font-semibold text-gray-800">
          卷 {volume.index}
          {volume.title ? `：${volume.title}` : ""}
        </span>
        <span className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
          第 {volume.chapter_start} 章起 · 目标 {volume.target_min}-{volume.target_max} 章
        </span>
        <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
          窗口 [{volume.chapter_start}, {winEnd}]
        </span>
        {volume.actual_end != null && (
          <span className="rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[10px] text-green-700">
            实际收卷第 {volume.actual_end} 章
          </span>
        )}
      </div>
      {volume.summary && (
        <div className="mt-1 text-[11px] leading-snug text-gray-600 whitespace-pre-wrap">
          <span className="text-gray-400">主线 · </span>
          {volume.summary}
        </div>
      )}
      {volume.setup_for_next && (
        <div className="mt-1 text-[11px] leading-snug text-gray-600 whitespace-pre-wrap">
          <span className="text-gray-400">卷尾 setup · </span>
          {volume.setup_for_next}
        </div>
      )}
    </div>
  );
}

export function VolumeBoundaryGateForm({ payload, onSubmit, disabled }: Props) {
  const cur = payload.current_volume;
  const nextVolumes = payload.next_volumes ?? [];
  const options = payload.options ?? [];
  const [windowStart, windowEnd] = payload.window ?? [0, 0];

  // 默认建议值（来自 options[]，穿越即 close_at 中位、extend +5）——AI 已在 volume_gate.py 计算过。
  // 前端再兜底一层：cur.target 中位 + cur.target_max + 5，避免后端 payload 字段名漂移导致空。
  const defaultCloseChapter = useMemo(
    () =>
      suggestedOf(
        options,
        "close_at",
        "suggested_chapter",
        cur.chapter_start + Math.floor((cur.target_min + cur.target_max) / 2) - 1
      ),
    [options, cur]
  );
  const defaultExtendMax = useMemo(
    () =>
      suggestedOf(options, "extend_target_max", "suggested_target_max", cur.target_max + 5),
    [options, cur]
  );

  const [action, setAction] = useState<Action>("continue_current");
  const [closeChapter, setCloseChapter] = useState<number>(defaultCloseChapter);
  const [extendMax, setExtendMax] = useState<number>(defaultExtendMax);
  const [submitting, setSubmitting] = useState(false);

  // 新 interrupt 或 disabled 解锁时重置
  useEffect(() => {
    setSubmitting(false);
    setAction("continue_current");
    setCloseChapter(defaultCloseChapter);
    setExtendMax(defaultExtendMax);
  }, [payload, disabled, defaultCloseChapter, defaultExtendMax]);

  // 校验：close_at.chapter 必须 >= cur.chapter_start；extend.target_max 必须 >= cur.target_min。
  // 与 volume_gate.py::_apply_close_at / _apply_extend_target_max 的约束一致，提前拦截。
  const closeErr =
    action === "close_at" && !(Number.isInteger(closeChapter) && closeChapter >= cur.chapter_start)
      ? `收卷章号必须 ≥ 本卷起始章 ${cur.chapter_start}`
      : null;
  const extendErr =
    action === "extend_target_max" &&
    !(Number.isInteger(extendMax) && extendMax >= cur.target_min)
      ? `新 target_max 必须 ≥ 本卷 target_min=${cur.target_min}`
      : null;
  const hasErr = !!(closeErr || extendErr);

  const handleSubmit = () => {
    if (hasErr) return;
    setSubmitting(true);
    if (action === "continue_current") {
      onSubmit(buildVolumeContinueResume());
    } else if (action === "close_at") {
      onSubmit(buildVolumeCloseAtResume(closeChapter));
    } else {
      onSubmit(buildVolumeExtendResume(extendMax));
    }
  };

  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">分卷边界闸门</h3>

      {/* 穿越点说明 */}
      <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <div className="mb-1 font-medium">
          {payload.message ??
            `本次长期规划窗口 [${windowStart}, ${windowEnd}] 将穿越卷边界，请确认下一步：`}
        </div>
        {payload.crossings && payload.crossings.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-xs">
            {payload.crossings.map((c, i) => (
              <li key={i}>
                · 卷 {c.volume_index} 的{" "}
                <code className="rounded bg-amber-100 px-1 py-0.5 font-mono text-[11px]">
                  {c.kind}
                </code>{" "}
                = 第 {c.chapter} 章 落入本次窗口
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 当前卷 + 后续未开启卷概览 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-gray-500">当前卷</div>
        <VolumeSnapshotCard volume={cur} emphasis />
        {nextVolumes.length > 0 && (
          <>
            <div className="mt-2 text-xs font-medium text-gray-500">后续卷（供参考）</div>
            <div className="space-y-2">
              {nextVolumes.map((v) => (
                <VolumeSnapshotCard key={v.index} volume={v} />
              ))}
            </div>
          </>
        )}
      </div>

      {/* 三选一 radio 组 */}
      <div className="space-y-2 border-t pt-3">
        <div className="text-xs font-medium text-gray-500">请选择处置方式</div>

        {/* 选项 1：继续本卷 */}
        <label
          className={
            "flex cursor-pointer items-start gap-2 rounded border px-3 py-2 transition-colors " +
            (action === "continue_current"
              ? "border-blue-500 bg-blue-50"
              : "border-gray-200 bg-white hover:bg-gray-50")
          }
        >
          <input
            type="radio"
            name="volume-gate-action"
            checked={action === "continue_current"}
            onChange={() => setAction("continue_current")}
            disabled={isDisabled}
            className="mt-1"
          />
          <div className="flex-1">
            <div className="text-sm font-medium text-gray-800">继续本卷（不改边界）</div>
            <div className="mt-0.5 text-xs text-gray-500">
              不改动 volumes；chapter_plan 直接生成 40 章跨卷条目，LLM 拿到卷位置卡自行处理跨卷节奏。
            </div>
          </div>
        </label>

        {/* 选项 2：在第 X 章收卷 */}
        <label
          className={
            "flex cursor-pointer items-start gap-2 rounded border px-3 py-2 transition-colors " +
            (action === "close_at"
              ? "border-blue-500 bg-blue-50"
              : "border-gray-200 bg-white hover:bg-gray-50")
          }
        >
          <input
            type="radio"
            name="volume-gate-action"
            checked={action === "close_at"}
            onChange={() => setAction("close_at")}
            disabled={isDisabled}
            className="mt-1"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-800">
              <span>在第</span>
              <input
                type="number"
                min={cur.chapter_start}
                value={closeChapter}
                onChange={(e) => setCloseChapter(parseInt(e.target.value) || 0)}
                onFocus={() => setAction("close_at")}
                disabled={isDisabled}
                className="w-20 rounded border border-gray-300 px-2 py-0.5 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
              <span>章收卷</span>
              <span className="text-xs font-normal text-gray-400">
                （AI 建议 {defaultCloseChapter}）
              </span>
            </div>
            <div className="mt-0.5 text-xs text-gray-500">
              本卷 actual_end 写入此章号 + status=closed；下一未开启卷 chapter_start 顺移 + status=in_progress。
            </div>
            {closeErr && action === "close_at" && (
              <div className="mt-1 text-xs text-red-600">⚠ {closeErr}</div>
            )}
          </div>
        </label>

        {/* 选项 3：延长本卷 target_max */}
        <label
          className={
            "flex cursor-pointer items-start gap-2 rounded border px-3 py-2 transition-colors " +
            (action === "extend_target_max"
              ? "border-blue-500 bg-blue-50"
              : "border-gray-200 bg-white hover:bg-gray-50")
          }
        >
          <input
            type="radio"
            name="volume-gate-action"
            checked={action === "extend_target_max"}
            onChange={() => setAction("extend_target_max")}
            disabled={isDisabled}
            className="mt-1"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-800">
              <span>延长本卷 target_max 到</span>
              <input
                type="number"
                min={cur.target_min}
                value={extendMax}
                onChange={(e) => setExtendMax(parseInt(e.target.value) || 0)}
                onFocus={() => setAction("extend_target_max")}
                disabled={isDisabled}
                className="w-20 rounded border border-gray-300 px-2 py-0.5 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100"
              />
              <span>章</span>
              <span className="text-xs font-normal text-gray-400">
                （AI 建议 {defaultExtendMax}）
              </span>
            </div>
            <div className="mt-0.5 text-xs text-gray-500">
              本卷 target_max 增大；后续未开启卷 chapter_start 顺移，避免章号错位。
            </div>
            {extendErr && action === "extend_target_max" && (
              <div className="mt-1 text-xs text-red-600">⚠ {extendErr}</div>
            )}
          </div>
        </label>
      </div>

      {/* 提交按钮 */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={isDisabled || hasErr}
        className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
      >
        {submitting ? "⏳ 提交中..." : "确认"}
      </button>
    </div>
  );
}
