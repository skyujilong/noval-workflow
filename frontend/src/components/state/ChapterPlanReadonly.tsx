// 章节规划(chapter_plan) 只读展示——「编辑当前状态」抽屉中的观测入口。
//
// 参考伏笔台账(ForeshadowingEditor)的分组卡片形态,但只读:chapter_plan 按卷滚动生成、
// 会被 LLM 按卷覆盖重写,人工手改意义不大;这里作为「状态观测窗口」。
//
// 分成两组:
//   - 🔒 已锁定(chapter ≤ total_chapters_written):历史段,save_chapter_plan
//     合并时保证不覆盖已写章条目。
//   - 🆕 新规划:未来章条目,滚动到下一卷时会被覆盖。
//
// 视觉与 ChapterPlanCards.tsx(interrupt 抽屉视图) 保持一致——共用 INTENSITY_META。

import { INTENSITY_META } from "../../lib/chapterPlanMeta";
import type { ChapterPlanItem } from "../../lib/types";

interface Props {
  items: ChapterPlanItem[];
  plannedUpto: number;
  writtenUpto: number;
}

function ItemCard({ item, locked }: { item: ChapterPlanItem; locked: boolean }) {
  const intensity = item.intensity || "";
  const meta = INTENSITY_META[intensity];
  return (
    <div
      className={`space-y-1 rounded-md border p-2 ${
        locked ? "border-gray-200 bg-gray-50/70" : "border-blue-100 bg-blue-50/30"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`font-mono text-xs ${locked ? "text-gray-500" : "text-gray-700"}`}>
          {locked && <span className="mr-1">🔒</span>}第 {item.chapter} 章
        </span>
        {intensity ? (
          meta ? (
            <span className={`rounded border px-1.5 py-0.5 text-[10px] leading-none ${meta.cls}`}>
              {meta.label}
            </span>
          ) : (
            <span
              className="rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-[10px] leading-none text-red-700"
              title="intensity 非 7 档枚举"
            >
              ! {intensity}
            </span>
          )
        ) : null}
        {!locked && (
          <span className="ml-auto text-[10px] text-blue-500">下次滚动可能被覆盖</span>
        )}
      </div>
      <div className={`text-xs ${locked ? "text-gray-600" : "text-gray-800"}`}>
        <span className="text-gray-400">目标 · </span>
        {item.purpose || <span className="italic text-gray-400">(空)</span>}
      </div>
      <div className={`text-[11px] ${locked ? "text-gray-500" : "text-gray-700"}`}>
        <span className="text-gray-400">关键 · </span>
        {item.key_turn || <span className="italic text-gray-400">(空)</span>}
      </div>
      <div className={`text-[11px] ${locked ? "text-gray-500" : "text-gray-700"}`}>
        <span className="text-gray-400">钩子 · </span>
        {item.ending_hook || <span className="italic text-gray-400">(空)</span>}
      </div>
    </div>
  );
}

export function ChapterPlanReadonly({ items, plannedUpto, writtenUpto }: Props) {
  if (!items || items.length === 0) {
    return (
      <div className="rounded border border-dashed border-gray-200 py-3 text-center text-[11px] text-gray-400">
        暂无 chapter_plan 数据(未运行到 Phase 2.5,或本小说未开启滚动规划)
      </div>
    );
  }

  // 按章号升序;后端已保证不重不乱,但前端多做一层稳序以防手工快照错序。
  const sorted = [...items].sort((a, b) => a.chapter - b.chapter);
  const locked = sorted.filter((it) => writtenUpto > 0 && it.chapter <= writtenUpto);
  const fresh = sorted.filter((it) => !(writtenUpto > 0 && it.chapter <= writtenUpto));

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-gray-500">
        已规划到第 <span className="font-semibold text-gray-700">{plannedUpto || sorted[sorted.length - 1].chapter}</span> 章
        · 共 <span className="font-semibold text-gray-700">{sorted.length}</span> 条
        · 已锁定 <span className="font-semibold text-gray-700">{locked.length}</span> 条
        · 新规划 <span className="font-semibold text-blue-600">{fresh.length}</span> 条
      </div>

      {fresh.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-blue-700">🆕 新规划({fresh.length})</div>
          <div className="space-y-2">
            {fresh.map((it, i) => (
              <ItemCard key={`fresh-${it.chapter}-${i}`} item={it} locked={false} />
            ))}
          </div>
        </div>
      )}

      {locked.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-500">🔒 已锁定({locked.length})</div>
          <div className="space-y-2">
            {locked.map((it, i) => (
              <ItemCard key={`locked-${it.chapter}-${i}`} item={it} locked={true} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
