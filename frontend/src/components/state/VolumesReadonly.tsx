// 分卷规划(volumes) 只读展示——「编辑当前状态」抽屉里的观测入口(与可编辑 JSON 编辑器 VolumesEditor 配套)。
//
// 与 ChapterPlanReadonly / EntityCardsReadonly 同款范式:关键字段横排/纵排展示,状态徽章 + 章号窗口徽章。
// 滚动生成卷语义:planned_end 是本卷末章号(绝对章号),窗口 = [chapter_start, planned_end];
// actual_end 在滚动到下一卷时由上一卷收口写入,未写入时不显示。

import type { Volume } from "../../lib/types";

interface Props {
  volumes: Volume[];
}

function statusMeta(status: Volume["status"]) {
  switch (status) {
    case "planning":
      return { label: "未开启", cls: "border-gray-200 bg-gray-50 text-gray-500" };
    case "in_progress":
      return { label: "进行中", cls: "border-blue-300 bg-blue-50 text-blue-700" };
    case "closed":
      return { label: "已收卷 ✓", cls: "border-green-300 bg-green-50 text-green-700" };
    default:
      return { label: status, cls: "border-red-300 bg-red-50 text-red-700" };
  }
}

export function VolumesReadonly({ volumes }: Props) {
  if (!volumes || volumes.length === 0) {
    return (
      <div className="rounded border border-dashed border-gray-200 bg-gray-50 px-3 py-2 text-[11px] text-gray-400">
        （分卷规划为空——尚未走到 prepare_volumes 节点，或后端未开启分卷特性）
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {volumes.map((v) => {
        // planned_end 权威末章号（过渡期老数据回退 target_max 换算）
        const winEnd = v.planned_end > 0 ? v.planned_end : v.chapter_start + v.target_max - 1;
        const planLen = winEnd - v.chapter_start + 1;
        const meta = statusMeta(v.status);
        return (
          <div
            key={v.index}
            className="rounded border border-gray-200 bg-white px-3 py-2 shadow-sm"
          >
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-gray-800">
                卷 {v.index}
                {v.title ? `：${v.title}` : ""}
              </span>
              <span className={`rounded border px-1.5 py-0.5 text-[10px] ${meta.cls}`}>
                {meta.label}
              </span>
              <span className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                第 {v.chapter_start}-{winEnd} 章 · 共 {planLen} 章
              </span>
              {v.actual_end != null && (
                <span className="rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[10px] text-green-700">
                  实际收卷第 {v.actual_end} 章
                </span>
              )}
            </div>
            {v.summary && (
              <div className="text-[11px] leading-snug text-gray-600 whitespace-pre-wrap">
                <span className="text-gray-400">主线 · </span>
                {v.summary}
              </div>
            )}
            {v.setup_for_next && (
              <div className="mt-1 text-[11px] leading-snug text-gray-600 whitespace-pre-wrap">
                <span className="text-gray-400">卷尾 setup · </span>
                {v.setup_for_next}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
