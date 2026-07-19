// 顶部分卷横条：向用户一眼呈现「当前小说横向大结构」——从 state.volumes 读取。
// 紧凑单行设计（右侧面板窄，避免占高）：每卷压成一小块 chip（状态色点 + 卷号 + 标题截断
// + 进度），表头内联，整行横向滚动不换行。当前卷蓝高亮、已收卷绿、未开启虚线。
// 章号区间等详情挪进点击弹窗。
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

/** 当前卷显示的「已 N/共M 章」中的 N，语义：total_chapters_written 在本卷起始章之后已完成的章数。 */
function chaptersDoneInVolume(volume: Volume, totalWritten: number): number {
  return Math.max(0, totalWritten - volume.chapter_start + 1);
}

/** 本卷规划总章数 = planned_end - chapter_start + 1。 */
function plannedLength(volume: Volume): number {
  return volume.planned_end > 0 ? volume.planned_end - volume.chapter_start + 1 : 0;
}

/** 本卷末章号（绝对章号）= planned_end。 */
function plannedEndOf(volume: Volume): number {
  return volume.planned_end;
}

/** 已收卷的「实际卷长」= actual_end - chapter_start + 1。 */
function actualLength(volume: Volume): number {
  return volume.actual_end != null ? volume.actual_end - volume.chapter_start + 1 : 0;
}

// 状态 → 紧凑 chip 的边框/底色 + 状态圆点色。
function statusStyle(status: Volume["status"]) {
  switch (status) {
    case "in_progress":
      return { cardCls: "border-blue-300 bg-blue-50 ring-1 ring-blue-200", dotCls: "bg-blue-500" };
    case "closed":
      return { cardCls: "border-green-200 bg-green-50/70", dotCls: "bg-green-500" };
    default:
      return { cardCls: "border-dashed border-gray-300 bg-white", dotCls: "bg-gray-300" };
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
  const meta = statusStyle(volume.status);
  const isCurrent = volume.status === "in_progress";
  const isClosed = volume.status === "closed";

  // 紧凑进度文案（章号区间挪进详情弹窗）：进行中「N/共M」；已收卷「✓ N章」；未开启「共M章」。
  const doneN = chaptersDoneInVolume(volume, totalWritten);
  const planLen = plannedLength(volume);
  const progressLabel = isCurrent
    ? `${doneN}/${planLen}`
    : isClosed
      ? `✓ ${actualLength(volume)}章`
      : `共${planLen}章`;

  return (
    <button
      type="button"
      onClick={onClick}
      title={volume.summary || volume.title}
      className={
        "flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-left transition-colors hover:brightness-95 " +
        meta.cardCls +
        (isCurrent ? " font-medium" : "")
      }
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dotCls}`} />
      <span className="shrink-0 text-[10px] text-gray-500">卷{volume.index}</span>
      <span className="max-w-[96px] truncate text-xs text-gray-800">
        {volume.title || <span className="text-gray-300">无标题</span>}
      </span>
      <span className="shrink-0 rounded bg-white/70 px-1 text-[10px] tabular-nums text-gray-500">
        {progressLabel}
      </span>
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
  const winEnd = plannedEndOf(volume);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            卷 {volume.index}
            {volume.title ? `：${volume.title}` : ""}
          </DialogTitle>
          <DialogDescription>
            第 {volume.chapter_start}-{winEnd} 章 · 共 {plannedLength(volume)} 章
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
      {/* 单行横向滚动的紧凑内容块：表头内联 + chip 横向滚动。外框（border/bg/padding/sticky）
          由父容器统一提供——分卷横条与「阅读章节」按钮合并成同一行，见 NovelWorkspace。 */}
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
          分卷 · {volumes.length}
        </span>
        <div className="flex flex-1 gap-1.5 overflow-x-auto">
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
