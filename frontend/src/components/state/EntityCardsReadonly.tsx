// 统一实体卡库(entity_cards) 只读展示——「编辑当前状态」抽屉中的观测入口。
//
// 参照 ChapterPlanReadonly：卡库由章前 entity_cards_step 建卡、章末 entity_discover_step
// 补卡/更新，人工手改易被下一章覆盖，故只做「状态观测窗口」。按 type 分组（人物/装备/物品/
// 势力/地点），装备/物品是本作真源（phase_summary 已不再存装备）。

import { useState } from "react";
import type { EntityCard } from "../../lib/types";
import { EntityCardEditForm } from "./EntityCardEditForm";

interface Props {
  cards: EntityCard[];
  /** 提供时，在「次要角色」人物卡上渲染「提升为重要角色」入口（仅「当前状态」视图传，审核草稿视图不传）。 */
  onPromote?: (card: EntityCard) => void;
  /** 提供时，在每张卡上渲染「删除」入口，供人工剔除噪音卡（仅「当前状态」视图传）。 */
  onDelete?: (card: EntityCard) => void;
  /** 提供时，在每张卡上渲染「编辑」入口——点开就地展开结构化字段表单，保存回写整卡
   * （仅 entity_cards JSON 编辑器预览传；readonly 展示不传）。updated 为编辑后的整卡。 */
  onEdit?: (card: EntityCard, updated: EntityCard) => void;
}

// type → 分组展示顺序 + 徽标样式。未知 type 兜底到「其他」组。
const TYPE_ORDER = ["人物", "装备", "物品", "势力", "地点"] as const;
const TYPE_BADGE: Record<string, string> = {
  人物: "border-indigo-200 bg-indigo-50 text-indigo-700",
  装备: "border-amber-200 bg-amber-50 text-amber-700",
  物品: "border-emerald-200 bg-emerald-50 text-emerald-700",
  势力: "border-rose-200 bg-rose-50 text-rose-700",
  地点: "border-sky-200 bg-sky-50 text-sky-700",
};

// 一行「标签 · 值」，值为空时不渲染，避免卡片堆一片空字段。
function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="text-[11px] text-gray-600">
      <span className="text-gray-400">{label} · </span>
      {value}
    </div>
  );
}

function Card({
  card,
  onPromote,
  onDelete,
  onEditStart,
  editing,
  onEditSave,
  onEditCancel,
}: {
  card: EntityCard;
  onPromote?: (card: EntityCard) => void;
  onDelete?: (card: EntityCard) => void;
  onEditStart?: () => void;
  editing?: boolean;
  onEditSave?: (updated: EntityCard) => void;
  onEditCancel?: () => void;
}) {
  const isPerson = card.type === "人物";
  const isItem = card.type === "装备" || card.type === "物品";
  const aliases = card.aliases?.length ? `（${card.aliases.join("/")}）` : "";
  const badge = TYPE_BADGE[card.type] ?? "border-gray-200 bg-gray-50 text-gray-600";
  // 次要角色 + 父层给了 onPromote → 可提升为重要角色
  const canPromote = isPerson && card.role === "次要角色" && !!onPromote;
  const canDelete = !!onDelete;
  const canEdit = !!onEditStart;
  // 任一动作存在 → 徽标不再靠 ml-auto 顶到最右（交给按钮组占位）
  const hasActions = canPromote || canDelete || canEdit;

  // 编辑态：整卡让位给结构化字段表单（表单自带 name/type 等主键字段）
  if (editing) {
    return (
      <EntityCardEditForm card={card} onSave={onEditSave!} onCancel={onEditCancel!} />
    );
  }

  return (
    <div className="space-y-1 rounded-md border border-gray-200 bg-gray-50/70 p-2">
      <div className="flex items-center gap-2">
        <span className="font-medium text-xs text-gray-800">{card.name}</span>
        {/* role（主角/反派分层）做成 name 旁徽标，一眼看出卡司定位 */}
        {isPerson && card.role ? (
          <span className="rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] leading-none text-indigo-700">
            {card.role}
          </span>
        ) : null}
        <span className="text-[10px] text-gray-400">{aliases}</span>
        {hasActions ? (
          <span className="ml-auto flex items-center gap-1">
            {canEdit ? (
              <button
                type="button"
                onClick={onEditStart}
                className="rounded border border-blue-200 bg-white px-1.5 py-0.5 text-[10px] leading-none text-blue-600 hover:bg-blue-50"
                title="就地编辑这张卡的字段"
              >
                编辑
              </button>
            ) : null}
            {canPromote ? (
              <button
                type="button"
                onClick={() => onPromote!(card)}
                className="rounded border border-indigo-200 bg-white px-1.5 py-0.5 text-[10px] leading-none text-indigo-600 hover:bg-indigo-50"
                title="补齐深层设计，提升为重要角色"
              >
                提升
              </button>
            ) : null}
            {canDelete ? (
              <button
                type="button"
                onClick={() => onDelete!(card)}
                className="rounded border border-rose-200 bg-white px-1.5 py-0.5 text-[10px] leading-none text-rose-600 hover:bg-rose-50"
                title="从卡库删除这张卡（用于剔除一次性碎屑/误建的噪音卡）"
              >
                删除
              </button>
            ) : null}
          </span>
        ) : null}
        <span className={`${hasActions ? "" : "ml-auto "}rounded border px-1.5 py-0.5 text-[10px] leading-none ${badge}`}>
          {card.type || "未分类"}
        </span>
      </div>
      <Row label="定位" value={card.summary} />
      {isPerson && (
        <>
          <Row label="外貌" value={card.appearance} />
          <Row label="口吻" value={card.speech_style} />
          <Row label="性格" value={card.personality} />
          <Row label="能力" value={card.abilities} />
          <Row label="动机" value={card.motivation} />
          <Row label="处境" value={card.current_state} />
          <Row label="关系" value={card.relations} />
          {/* 深层 canon（隐藏人设/弧光/底牌）——deep 视图才落库的长字段 */}
          <Row label="隐藏人设" value={card.hidden_persona} />
          <Row label="全书弧光" value={card.arc_trajectory} />
          <Row label="底牌契约" value={card.ability_contract} />
        </>
      )}
      {isItem && (
        <>
          <Row label="归属" value={card.owner} />
          <Row label="状态" value={card.status} />
          <Row label="效果" value={card.effect} />
          <Row label="品阶" value={card.rank} />
        </>
      )}
      {/* 势力/地点段：新增 standing（势力强弱/格局，动态） */}
      {card.type === "势力" ? <Row label="格局" value={card.standing} /> : null}
      {card.first_appear_chapter ? (
        <div className="text-[10px] text-gray-400">首登 · 第 {card.first_appear_chapter} 章</div>
      ) : null}
    </div>
  );
}

export function EntityCardsReadonly({ cards, onPromote, onDelete, onEdit }: Props) {
  // 正在编辑的卡按 name 记录（name 是主键、稳定）——重解析预览会换对象引用，用 name 才不丢编辑态。
  const [editingName, setEditingName] = useState<string | null>(null);

  if (!cards || cards.length === 0) {
    return (
      <div className="rounded border border-dashed border-gray-200 py-3 text-center text-[11px] text-gray-400">
        暂无实体卡(未运行到章前建卡，或本章尚未登场新实体)
      </div>
    );
  }

  // 已知 type 按 TYPE_ORDER 分组；其余归入「其他」组，稳序展示。
  const groups: Array<{ label: string; items: EntityCard[] }> = TYPE_ORDER.map((t) => ({
    label: t,
    items: cards.filter((c) => c.type === t),
  }));
  const others = cards.filter((c) => !TYPE_ORDER.includes(c.type as (typeof TYPE_ORDER)[number]));
  if (others.length > 0) groups.push({ label: "其他", items: others });

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-gray-500">
        共 <span className="font-semibold text-gray-700">{cards.length}</span> 张卡
        {groups
          .filter((g) => g.items.length > 0)
          .map((g) => ` · ${g.label} ${g.items.length}`)
          .join("")}
      </div>
      {groups
        .filter((g) => g.items.length > 0)
        .map((g) => (
          <div key={g.label}>
            <div className="mb-1 text-xs font-medium text-gray-600">
              {g.label}（{g.items.length}）
            </div>
            <div className="space-y-2">
              {g.items.map((c, i) => (
                <Card
                  key={`${g.label}-${c.name}-${i}`}
                  card={c}
                  onPromote={onPromote}
                  onDelete={onDelete}
                  onEditStart={onEdit ? () => setEditingName(c.name) : undefined}
                  editing={!!onEdit && editingName === c.name}
                  onEditSave={(updated) => {
                    onEdit?.(c, updated);
                    setEditingName(null);
                  }}
                  onEditCancel={() => setEditingName(null)}
                />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}
