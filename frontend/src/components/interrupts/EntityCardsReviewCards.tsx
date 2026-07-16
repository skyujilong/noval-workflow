// 实体卡类审核（character_cards / entity_cards / entity_discover）的结构化只读展示。
//
// 这三种 review_type 的 draft 都是 JSON 对象（非散文）：
//   - character_cards（Phase-1 建卡）：{"new_cards": [人物卡...]}
//   - entity_cards（章前登场）：       {"cast": [已有实体名...], "new_cards": [新卡...]}
//   - entity_discover（章末发现+更新）：{"new_cards": [新卡...], "updates": [{name, 动态字段...}]}
// 三者共有 new_cards（完整 EntityCard 数组），故复用 EntityCardsReadonly 渲染卡片，
// cast/updates 各自补一小块。JSON 解析失败时降级为原纯文本（用户仍可看原文 + 提修改意见）。

import type { EntityCard } from "../../lib/types";
import { EntityCardsReadonly } from "../state/EntityCardsReadonly";
import { ArticleParagraphs } from "../ArticleParagraphs";

/** 章末 entity_discover 的一条动态更新：定位名 name + 若干被改字段（owner/status/current_state…）。 */
interface CardUpdate {
  name: string;
  [field: string]: unknown;
}

interface CardDraft {
  new_cards: EntityCard[];
  cast?: string[];
  updates?: CardUpdate[];
}

interface Props {
  /** LLM 生成的原始 draft 字符串（应为 JSON 对象）。解析失败时降级到纯文本视图。 */
  draft: string;
}

/**
 * 解析 draft：容忍 markdown 围栏（```json ... ```）+ 首尾杂散文字，定位第一个 { 到最后一个 }。
 * 与 SceneBeatsCards 的 tryParseBeats 同思路——前端只读展示，失败降级即可，不 fail-fast。
 * 要求顶层是 dict 且 new_cards 为数组（三种 review_type 的共有键）。
 */
function tryParseCardDraft(raw: string): CardDraft | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  const start = body.indexOf("{");
  const end = body.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const parsed = JSON.parse(body.slice(start, end + 1)) as Record<string, unknown>;
    if (typeof parsed !== "object" || parsed === null) return null;
    if (!Array.isArray(parsed.new_cards)) return null;
    return {
      new_cards: parsed.new_cards as EntityCard[],
      cast: Array.isArray(parsed.cast) ? (parsed.cast as string[]) : undefined,
      updates: Array.isArray(parsed.updates) ? (parsed.updates as CardUpdate[]) : undefined,
    };
  } catch {
    return null;
  }
}

/** 一条动态更新渲染成 "实体名 · 字段=值 / 字段=值"（跳过 name 本身）。 */
function UpdateRow({ update }: { update: CardUpdate }) {
  const changes = Object.entries(update)
    .filter(([k, v]) => k !== "name" && v !== "" && v != null)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" / ");
  return (
    <div className="text-[11px] text-gray-600">
      <span className="font-medium text-gray-700">{update.name}</span>
      {changes ? <span className="text-gray-400"> · {changes}</span> : null}
    </div>
  );
}

export function EntityCardsReviewCards({ draft }: Props) {
  const parsed = tryParseCardDraft(draft);

  // 解析失败：降级为原纯文本 + 顶部黄条，用户仍可看原文并提修改意见
  if (!parsed) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
          ⚠ 无法解析为实体卡 JSON，降级显示原文
        </div>
        {draft ? <ArticleParagraphs text={draft} /> : <p className="text-gray-400">（无草稿内容）</p>}
      </div>
    );
  }

  const { new_cards, cast, updates } = parsed;
  return (
    <div className="space-y-3">
      {/* 本章登场的【已有】实体（entity_cards 才有）：只是名字清单，不重复建卡 */}
      {cast && cast.length > 0 && (
        <div className="text-[11px] text-gray-500">
          本章登场（已有）：<span className="text-gray-700">{cast.join(" / ")}</span>
        </div>
      )}

      {/* 新建/发现的实体卡：复用只读卡库视图，按 type 分组展示 */}
      {new_cards.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-600">新建实体卡（{new_cards.length}）</div>
          <EntityCardsReadonly cards={new_cards} />
        </div>
      ) : (
        <div className="text-[11px] text-gray-400">本次无新建实体卡</div>
      )}

      {/* 章末动态更新（entity_discover 才有）：对已有卡的 owner/status/处境等变更 */}
      {updates && updates.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-600">动态更新（{updates.length}）</div>
          <div className="space-y-1 rounded-md border border-gray-200 bg-gray-50/70 p-2">
            {updates.map((u, i) => (
              <UpdateRow key={`${u.name}-${i}`} update={u} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
