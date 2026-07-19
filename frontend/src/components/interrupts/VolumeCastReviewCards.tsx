// volume_cast（本卷花名册）只读展示——review_type=volume_cast 但无 threadId（降级路径）时用。
// 前端**只读**：想改走「提出修改意见」文本打回重跑（可编辑走 VolumeCastReviewForm）。
// 契约 {"introducing":[完整卡...], "returning":[{name,role_in_volume}...], "focus":"..."}。
// introducing 完整卡复用 EntityCardsReadonly 渲染；JSON 解析失败降级为原文 + 黄条。

import type { EntityCard } from "../../lib/types";
import { EntityCardsReadonly } from "../state/EntityCardsReadonly";
import { ArticleParagraphs } from "../ArticleParagraphs";

interface Props {
  draft: string;
}

interface ReturningEntry {
  name: string;
  role_in_volume: string;
}
interface RosterView {
  introducing: EntityCard[];
  returning: ReturningEntry[];
  focus: string;
}

const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

/** 宽松解析花名册草稿 → RosterView；容忍 markdown 围栏 + 首尾杂散文字，失败返回 null 降级。 */
function tryParseRoster(raw: string): RosterView | null {
  if (!raw || !raw.trim()) return null;
  const fenced = raw.trim().match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = (fenced ? fenced[1] : raw).trim();
  const start = body.indexOf("{");
  const end = body.lastIndexOf("}");
  if (start === -1 || end <= start) return null;
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(body.slice(start, end + 1)) as Record<string, unknown>;
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const introducing = Array.isArray(parsed.introducing) ? (parsed.introducing as EntityCard[]) : [];
  const returning = Array.isArray(parsed.returning)
    ? (parsed.returning as unknown[])
        .map((r): ReturningEntry | null => {
          if (typeof r !== "object" || r === null) return null;
          const ro = r as Record<string, unknown>;
          return { name: str(ro.name), role_in_volume: str(ro.role_in_volume) };
        })
        .filter((r): r is ReturningEntry => r !== null && r.name.trim() !== "")
    : [];
  return { introducing, returning, focus: str(parsed.focus) };
}

export function VolumeCastReviewCards({ draft }: Props) {
  const roster = tryParseRoster(draft);

  if (!roster) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
          ⚠ 无法解析为花名册 JSON，降级显示原文
        </div>
        {draft ? <ArticleParagraphs text={draft} /> : <p className="text-gray-400">（无草稿内容）</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {roster.focus.trim() && (
        <div className="text-[11px] text-gray-500">
          本卷阵容主线：<span className="text-gray-700">{roster.focus}</span>
        </div>
      )}

      {roster.returning.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-600">本卷返场阵容（{roster.returning.length}）</div>
          <div className="space-y-1 rounded-md border border-gray-200 bg-gray-50/70 p-2">
            {roster.returning.map((r, i) => (
              <div key={`${r.name}-${i}`} className="text-[11px] text-gray-600">
                <span className="font-medium text-gray-700">{r.name}</span>
                {r.role_in_volume ? <span className="text-gray-400"> · {r.role_in_volume}</span> : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {roster.introducing.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-600">
            本卷新登场（完整设定卡，{roster.introducing.length}）
          </div>
          <EntityCardsReadonly cards={roster.introducing} />
        </div>
      ) : (
        <div className="text-[11px] text-gray-400">本卷无新登场实体（全为返场）</div>
      )}
    </div>
  );
}
