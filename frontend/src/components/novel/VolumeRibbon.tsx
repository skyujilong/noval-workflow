// 顶部 4 卷横条：向用户一眼呈现「当前小说横向大结构」——从 state.volumes 读取。
// 显示：卷号 + title + 状态徽章 + 章号区间/target range。当前卷高亮,已收卷 ✓,未开启虚线。
//
// 交互：点击某卷 → 弹出只读详情对话框（title / summary / setup_for_next / 章号窗口）。
// 编辑入口一律走审核表单/gate 表单，不在此处提供编辑（避免与 volumes review 语义冲突）。
//
// 兼容：volumes 为空数组时整体不渲染（老小说 / 未启用分卷特性 → 返回 null，占位不留白）。

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { NovelState, Volume } from "../../lib/types";

interface Props {
  state: NovelState;
}

/** 当前卷显示的「已 N/(target_min~target_max) 章」中的 N，
 * 语义：total_chapters_written 在本卷起始章之后已完成的章数。 */
function chaptersDoneInVolume(volume: Volume, totalWritten: number): number {
  return Math.max(0, totalWritten - volume.chapter_start + 1);
}

/** 已收卷的「实际卷长」= actual_end - chapter_start + 1。 */
function actualLength(volume: Volume): number {
  return volume.actual_end != null ? volume.actual_end - volume.chapter_start + 1 : 0;
}

function statusPill(status: Volume["status"]) {
  switch (status) {
    case "in_progress":
      return { cardCls: "border-blue-400 bg-blue-50", badge: "进行中", badgeCls: "bg-blue-100 text-blue-700" };
    case "closed":
      return { cardCls: "border-green-300 bg-green-50", badge: "已收卷 ✓", badgeCls: "bg-green-100 text-green-700" };
    default:
      return { cardCls: "border-dashed border-gray-300 bg-white", badge: "未开启", badgeCls: "bg-gray-100 text-gray-500" };
  }
}

function VolumeChip({
  volume,
  totalWritten,
  onClick,
}: {
  volume: Volume;
  totalWritten: number;
  onClick: () => void;
}) {
  const meta = statusPill(volume.status);
  const isCurrent = volume.status === "in_progress";
  const isClosed = volume.status === "closed";

  // 章号范围文案：已收卷显示实际范围；否则显示 chapter_start-窗口末（target_max）。
  const rangeLabel = isClosed
    ? `${volume.chapter_start}-${volume.actual_end}`
    : `${volume.chapter_start}-${volume.chapter_start + volume.target_max - 1}`;

  // 进度/长度徽章：进行中「已 N/(min~max) 章」；已收卷「N 章」；未开启「target min~max」。
  const doneN = chaptersDoneInVolume(volume, totalWritten);
  const progressLabel = isCurrent
    ? `已 ${doneN}/(${volume.target_min}~${volume.target_max}) 章`
    : isClosed
      ? `${actualLength(volume)} 章`
      : `${volume.target_min}~${volume.target_max} 章`;

  return (
    <button
      type="button"
      onClick={onClick}
      title={volume.summary || volume.title}
      className={
        "flex min-w-[180px] flex-1 flex-col gap-0.5 rounded-lg border px-3 py-2 text-left transition-all hover:shadow-sm " +
        meta.cardCls +
        (isCurrent ? " font-medium ring-1 ring-blue-200" : "")
      }
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500">卷 {volume.index}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${meta.badgeCls}`}>{meta.badge}</span>
      </div>
      <div className="truncate text-sm text-gray-800">
        {volume.title || <span className="text-gray-300">（无标题）</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[11px] text-gray-500">
        <span className="rounded bg-white/60 px-1 py-0.5">{rangeLabel}</span>
        <span className="rounded bg-white/60 px-1 py-0.5">{progressLabel}</span>
      </div>
    </button>
  );
}

function VolumeDetailDialog({
  volume,
  open,
  onClose,
}: {
  volume: Volume | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!volume) return null;
  const winEnd = volume.chapter_start + volume.target_max - 1;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            卷 {volume.index}
            {volume.title ? `：${volume.title}` : ""}
          </DialogTitle>
          <DialogDescription>
            第 {volume.chapter_start} 章起 · 目标 {volume.target_min}-{volume.target_max} 章 · 窗口 [
            {volume.chapter_start}, {winEnd}]
            {volume.actual_end != null && ` · 实际收卷第 ${volume.actual_end} 章`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <div className="mb-1 text-xs font-medium text-gray-500">本卷主线</div>
            <div className="whitespace-pre-wrap rounded bg-gray-50 px-3 py-2 leading-relaxed text-gray-800">
              {volume.summary?.trim() || <em className="text-gray-300">（空）</em>}
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-gray-500">卷尾 setup</div>
            <div className="whitespace-pre-wrap rounded bg-gray-50 px-3 py-2 leading-relaxed text-gray-800">
              {volume.setup_for_next?.trim() || <em className="text-gray-300">（空）</em>}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function VolumeRibbon({ state }: Props) {
  const volumes = state.volumes ?? [];
  const [selected, setSelected] = useState<Volume | null>(null);

  // 空数组 → 整块不渲染（老小说 / 未启用分卷）
  if (volumes.length === 0) return null;

  return (
    <>
      <div className="border-b border-gray-200 bg-gray-50 px-4 py-2">
        <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
          <span>分卷规划</span>
          <span className="rounded bg-white px-1.5 py-0.5 text-gray-500">共 {volumes.length} 卷</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {volumes.map((v) => (
            <VolumeChip
              key={v.index}
              volume={v}
              totalWritten={state.total_chapters_written || 0}
              onClick={() => setSelected(v)}
            />
          ))}
        </div>
      </div>

      <VolumeDetailDialog
        volume={selected}
        open={selected !== null}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
