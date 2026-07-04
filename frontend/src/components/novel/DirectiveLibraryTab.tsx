// 「题材整改库」页：上半从本书精炼拆条入库；下半按题材/关键词浏览全库，勾选导入本书。
// 数据逻辑在 useDirectiveLibrary。

import { Button } from "@/components/ui/button";
import { useDirectiveLibrary } from "../../hooks/useDirectiveLibrary";
import type { DirectiveItem } from "../../lib/langgraph";
import { EditableDirectiveCard } from "./EditableDirectiveCard";

interface Props {
  novelName: string;
  genre: string;
  open: boolean;
}

export function DirectiveLibraryTab({ novelName, genre, open }: Props) {
  const lib = useDirectiveLibrary(novelName, genre, open);

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-gray-700">从本书精炼入库</h3>
        <p className="text-[11px] text-gray-400">
          把本书累积的「历史整改要点」拆成独立、去重、可复用的条目，勾选后入题材整改库。
        </p>
        <Button variant="outline" onClick={() => void lib.refine()} disabled={lib.refining}>
          {lib.refining ? "精炼中…" : "精炼本书整改"}
        </Button>
        {lib.candidates.length > 0 && (
          <div className="space-y-2">
            {lib.candidates.map((c, i) => (
              <EditableDirectiveCard
                key={i}
                title={c.title || "（未命名）"}
                badge={c.tags.length ? c.tags.join(" · ") : undefined}
                text={c.text}
                selected={c.selected}
                disabled={lib.committing}
                onToggle={() => lib.toggleCandidate(i)}
                onChange={(t) => lib.editCandidateText(i, t)}
              />
            ))}
            <Button onClick={() => void lib.commit()} disabled={lib.committing}>
              {lib.committing ? "入库中…" : "入库选中项"}
            </Button>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-gray-700">整改库</h3>
          <label className="ml-auto flex items-center gap-1 text-[11px] text-gray-500">
            <input
              type="checkbox"
              checked={lib.showAll}
              onChange={(e) => lib.setShowAll(e.target.checked)}
            />
            放宽到全部题材
          </label>
        </div>
        <input
          value={lib.query}
          onChange={(e) => lib.setQuery(e.target.value)}
          placeholder={`搜索${lib.showAll ? "全部题材" : `【${genre || "通用"}】`}整改条目…`}
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-xs"
        />

        {lib.loading ? (
          <p className="text-xs text-gray-400">加载中…</p>
        ) : lib.items.length === 0 ? (
          <p className="text-xs text-gray-400">暂无条目。</p>
        ) : (
          <div className="space-y-2">
            {lib.items.map((it) => (
              <LibraryRow
                key={it.id}
                item={it}
                selected={lib.selectedIds.has(it.id)}
                onToggle={() => lib.toggleSelect(it.id)}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button
            onClick={() => void lib.importSelected()}
            disabled={lib.importing || lib.selectedIds.size === 0}
          >
            {lib.importing ? "导入中…" : `导入本书（${lib.selectedIds.size}）`}
          </Button>
          <span className="text-[11px] text-gray-400">导入即去重追加到本书，下一章生效。</span>
        </div>
      </section>

      {lib.status && (
        <div className="rounded bg-green-50 p-2 text-xs text-green-700">{lib.status}</div>
      )}
      {lib.error && <div className="rounded bg-red-50 p-2 text-xs text-red-600">{lib.error}</div>}
    </div>
  );
}

function LibraryRow({
  item,
  selected,
  onToggle,
}: {
  item: DirectiveItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <label
      className={
        "flex cursor-pointer gap-2 rounded border p-2.5 text-xs " +
        (selected ? "border-blue-300 bg-blue-50/40" : "border-gray-200")
      }
    >
      <input type="checkbox" checked={selected} onChange={onToggle} className="mt-0.5 h-4 w-4" />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-700">{item.title || "（未命名）"}</span>
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
            {item.genre || "通用"}
          </span>
          {item.usage_count > 0 && (
            <span className="text-[10px] text-gray-400">已用 {item.usage_count}</span>
          )}
        </div>
        <p className="mt-0.5 text-gray-600">{item.text}</p>
      </div>
    </label>
  );
}
