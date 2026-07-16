// 单张实体卡的就地结构化字段编辑表单——「编辑当前状态」抽屉里 EntityCardsEditor 预览卡的展开态。
//
// 收本地草稿,保存时**按当前 type 收集对应字段**(切换 type 后不残留他类字段),回写给父层重排 JSON。
// name 必填非空、type 六选一;空字符串的可选字段保存时剔除,保持回写 JSON 干净。
// 只做结构化字段编辑,不校验业务语义(能力落体系等)——那是审核环节的事,这里给「手动纠正」入口。

import { useState } from "react";
import { CHARACTER_ROLES, ENTITY_CARD_TYPES } from "../../lib/editableState";
import type { EntityCard } from "../../lib/types";

interface Props {
  card: EntityCard;
  onSave: (updated: EntityCard) => void;
  onCancel: () => void;
}

// 按 type 决定展开哪些字段(与 EntityCardsReadonly 的分段显示口径一致)。
const PERSON_FIELDS: Array<{ key: keyof EntityCard; label: string; multiline?: boolean }> = [
  { key: "appearance", label: "外貌" },
  { key: "speech_style", label: "口吻" },
  { key: "personality", label: "性格" },
  { key: "abilities", label: "能力" },
  { key: "motivation", label: "动机" },
  { key: "current_state", label: "处境" },
  { key: "relations", label: "关系" },
  { key: "hidden_persona", label: "隐藏人设", multiline: true },
  { key: "arc_trajectory", label: "四卷弧光", multiline: true },
  { key: "ability_contract", label: "底牌契约", multiline: true },
];
const ITEM_FIELDS: Array<{ key: keyof EntityCard; label: string; multiline?: boolean }> = [
  { key: "owner", label: "归属" },
  { key: "status", label: "状态" },
  { key: "effect", label: "效果" },
  { key: "rank", label: "品阶" },
];
const FACTION_FIELDS: Array<{ key: keyof EntityCard; label: string; multiline?: boolean }> = [
  { key: "standing", label: "格局" },
];

function fieldsForType(type: string) {
  if (type === "人物") return PERSON_FIELDS;
  if (type === "物品" || type === "装备") return ITEM_FIELDS;
  if (type === "势力") return FACTION_FIELDS;
  return []; // 地点等：只有 summary，无额外分段字段
}

const inputCls =
  "w-full rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none";

export function EntityCardEditForm({ card, onSave, onCancel }: Props) {
  const [draft, setDraft] = useState<EntityCard>(() => ({ ...card }));
  // aliases / first_appear_chapter 走独立字符串态：前者需拆分、后者要允许空。
  const [aliasesText, setAliasesText] = useState((card.aliases ?? []).join("、"));
  const [chapterText, setChapterText] = useState(
    card.first_appear_chapter != null ? String(card.first_appear_chapter) : "",
  );

  const set = (k: keyof EntityCard, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const nameOk = (draft.name ?? "").trim().length > 0;
  const chapterOk = chapterText.trim() === "" || /^\d+$/.test(chapterText.trim());
  const canSave = nameOk && chapterOk;

  const handleSave = () => {
    if (!canSave) return;
    const type = draft.type;
    // 只保留 name/type + 当前 type 相关的非空字段——切换 type 后他类残留字段不回写。
    const out: EntityCard = { name: draft.name.trim(), type };
    const summary = (draft.summary ?? "").trim();
    if (summary) out.summary = summary;
    const aliases = aliasesText
      .split(/[,，、/]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (aliases.length) out.aliases = aliases;
    if (chapterText.trim() !== "") out.first_appear_chapter = Number(chapterText.trim());
    if (type === "人物" && (draft.role ?? "").trim()) out.role = draft.role;
    for (const f of fieldsForType(type)) {
      const v = ((draft[f.key] as string | undefined) ?? "").trim();
      if (v) (out as unknown as Record<string, unknown>)[f.key] = v;
    }
    onSave(out);
  };

  const typeFields = fieldsForType(draft.type);

  return (
    <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50/40 p-2">
      {/* 主键区：name + type + 首登章 */}
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-0.5 block text-[10px] text-gray-500">名称（主键，必填）</span>
          <input
            value={draft.name ?? ""}
            onChange={(e) => set("name", e.target.value)}
            className={inputCls + (nameOk ? "" : " border-red-400")}
            placeholder="实体名"
          />
        </label>
        <label className="block">
          <span className="mb-0.5 block text-[10px] text-gray-500">类型</span>
          <select
            value={draft.type}
            onChange={(e) => set("type", e.target.value)}
            className={inputCls}
          >
            {ENTITY_CARD_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-0.5 block text-[10px] text-gray-500">别名（用 、/ 分隔）</span>
          <input
            value={aliasesText}
            onChange={(e) => setAliasesText(e.target.value)}
            className={inputCls}
            placeholder="三哥、剑仙"
          />
        </label>
        <label className="block">
          <span className="mb-0.5 block text-[10px] text-gray-500">首登章（数字，可空）</span>
          <input
            value={chapterText}
            onChange={(e) => setChapterText(e.target.value)}
            className={inputCls + (chapterOk ? "" : " border-red-400")}
            placeholder="1"
            inputMode="numeric"
          />
        </label>
      </div>

      <label className="block">
        <span className="mb-0.5 block text-[10px] text-gray-500">定位（summary）</span>
        <input
          value={draft.summary ?? ""}
          onChange={(e) => set("summary", e.target.value)}
          className={inputCls}
          placeholder="一句话定位"
        />
      </label>

      {/* 人物专属：role 下拉 */}
      {draft.type === "人物" && (
        <label className="block">
          <span className="mb-0.5 block text-[10px] text-gray-500">角色定位（role）</span>
          <select
            value={draft.role ?? ""}
            onChange={(e) => set("role", e.target.value)}
            className={inputCls}
          >
            <option value="">（未定）</option>
            {CHARACTER_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      )}

      {/* type 相关的分段字段 */}
      {typeFields.map((f) =>
        f.multiline ? (
          <label key={f.key} className="block">
            <span className="mb-0.5 block text-[10px] text-gray-500">{f.label}</span>
            <textarea
              value={(draft[f.key] as string | undefined) ?? ""}
              onChange={(e) => set(f.key, e.target.value)}
              rows={2}
              className={inputCls}
            />
          </label>
        ) : (
          <label key={f.key} className="block">
            <span className="mb-0.5 block text-[10px] text-gray-500">{f.label}</span>
            <input
              value={(draft[f.key] as string | undefined) ?? ""}
              onChange={(e) => set(f.key, e.target.value)}
              className={inputCls}
            />
          </label>
        ),
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        {!chapterOk && <span className="mr-auto text-[10px] text-red-500">首登章须为数字</span>}
        {!nameOk && <span className="mr-auto text-[10px] text-red-500">名称不能为空</span>}
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-gray-300 bg-white px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50"
        >
          取消
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          className="rounded bg-blue-600 px-2 py-1 text-[11px] text-white hover:bg-blue-700 disabled:bg-gray-300"
        >
          保存改动
        </button>
      </div>
    </div>
  );
}
