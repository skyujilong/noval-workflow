# 前端对齐「人物档案结构化卡」改造方案

> 背景：后端已完成 `docs/character-profile-refactor-plan.md` 的改造——删 `character_profiles`/
> `character_status`/`character_relations` 三字段与 status/relations/discover 三条腿，人物档案
> 真源并入 `entity_cards` 的 CharacterCard（新增 role/current_state/深层 canon 字段）。前端
> （`frontend/`，TS/React）仍引用这些已删物，运行时「人物档案」空、相关 review 表单变死代码。
> 本方案让前端与后端契约对齐。**无历史包袱**：直接删旧字段，不做双读兼容。

---

## 一、改动总览（5 个文件）

| 文件 | 改动性质 |
|---|---|
| `src/lib/types.ts` | EntityCard 接口补 6 字段；NovelState/EMPTY 删 3 字段；REVIEW_TYPE_LABELS 改名+删 |
| `src/lib/editableState.ts` | 可编辑字段表删 3 项（character_profiles/status/relations） |
| `src/lib/interruptTypes.ts` | 删 9 个中断类型成员 + 各分类 map 里对应条目 |
| `src/components/novel/NovelDetail.tsx` | `character_profiles` 散文 Field → 复用 `EntityCardsReadonly` 展示卡库 |
| `src/components/state/EntityCardsReadonly.tsx` | 卡片渲染补新字段（role/current_state/深层 canon/standing） |

`EntityCardsEditor.tsx` 是**原始 JSON 文本框**（非逐字段表单），无需逐字段改；仅把占位示例
JSON 更新为含 `role` 的样例（可选）。`StateEditPanel.tsx` 由 `EDITABLE_FIELDS` 驱动，删表项后
自动少渲染两个 snapshot 输入框，无需单独改。

---

## 二、`types.ts`

### 2.1 EntityCard 接口补字段（镜像后端判别联合的并集）

```ts
export interface EntityCard {
  name: string;
  type: string; // 人物 / 物品 / 装备 / 势力 / 地点
  aliases?: string[];
  summary?: string;
  first_appear_chapter?: number;
  // 人物段（CharacterCard）
  role?: string;              // 新增：角色定位（主角/主要配角/功能性反派/根源反派/感情线角色/次要角色）
  appearance?: string;
  speech_style?: string;
  personality?: string;
  abilities?: string;
  hidden_persona?: string;    // 新增：深层隐藏人设（canon·深层视图）
  arc_trajectory?: string;    // 新增：四卷成长弧光（canon·深层视图）
  ability_contract?: string;  // 新增：能力底牌契约（canon·深层视图）
  motivation?: string;        // 动态
  current_state?: string;     // 新增：当前处境（动态，吸收原 character_status）
  relations?: string;         // 动态
  // 物品/装备段（ItemCard）
  owner?: string;
  effect?: string;
  status?: string;
  rank?: string;
  // 势力段（SimpleEntityCard）
  standing?: string;          // 新增：势力强弱/格局（动态，吸收原 character_relations 势力部分）
}
```

> 前端仍用「扁平并集接口」镜像后端判别联合（type 不适用的字段为 `undefined`）——够用，不必在
> 前端也搞 union，渲染时按 `type` 分支取字段即可。

### 2.2 NovelState 删 3 字段（`:105`/`:117`/`:118`）

删 `character_profiles: string;`、`character_status: string;`、`character_relations: string;`。
在原 `character_profiles` 处留一行注释：人物档案真源已并入 `entity_cards`。

### 2.3 EMPTY_NOVEL_STATE 删 3 默认值（`:167`/`:175`/`:176`）

删 `character_profiles: ""`、`character_status: ""`、`character_relations: ""`。

### 2.4 REVIEW_TYPE_LABELS 改名 + 删（`:193`/`:199`/`:200`/`:204`）

- `character_profiles: "人物档案"` → `character_cards: "人物档案（结构化卡司）"`（key 对齐后端 review_type）
- 删 `character_status: "人物动态状态"`、`character_relations: "人物关系/势力格局"`、
  `character_profiles_discover: "角色档案发现"`

---

## 三、`editableState.ts`

删可编辑字段联合类型里的 3 个 key（`:18`/`:19`/`:27`）与 `EDITABLE_FIELDS` 列表里的 3 条
（`:55`/`:56`/`:65`）：`character_profiles`、`character_status`、`character_relations`。

> 人物档案不再是「可整段编辑的散文字段」——它现在是结构化卡库，改动走 `EntityCardsEditor`
> （StateEditPanel 里已挂载）。snapshot 组删两项后只剩 foreshadowing/phase_summary。

---

## 四、`interruptTypes.ts`

### 4.1 删枚举成员（`:32-34`/`:36-38`/`:52-54`）

删 `STATUS_ENTRY_GATE`/`STATUS_DIRECTION_INPUT`/`STATUS_REVIEW`、
`RELATIONS_ENTRY_GATE`/`RELATIONS_DIRECTION_INPUT`/`RELATIONS_REVIEW`、
`CHARACTER_PROFILES_DISCOVER_ENTRY_GATE`/`_DIRECTION_INPUT`/`_REVIEW`（共 9 个）。

### 4.2 删各分类/标签 map 里的对应条目

- entry_gate 分类：`:294`（STATUS）、`:295`（RELATIONS）、`:299`（DISCOVER）
- direction 分类：`:310`（DISCOVER）
- human_review 分类：`:314`（STATUS）、`:315`（RELATIONS）、`:319`（DISCOVER）
- 标签 map：`:367`（DISCOVER direction 标签）；若另有 STATUS_REVIEW/RELATIONS_REVIEW 的中文标签条目一并删

> 实施时以「删完再全局搜 STATUS_REVIEW/RELATIONS_REVIEW/CHARACTER_PROFILES_DISCOVER 应零命中」
> 为准，逐个 map 清干净（本文件有多张按成员建的 Record，逐一核对）。

---

## 五、`NovelDetail.tsx`（`:50`）

原 `<Field label="人物档案" value={state.character_profiles} />` 删掉，改为复用现成的
`EntityCardsReadonly` 只渲染**人物卡**（或整卡库）：

```tsx
import { EntityCardsReadonly } from "../state/EntityCardsReadonly";
// …整体大纲 Field 之后：
{state.entity_cards?.length > 0 && (
  <div>
    <div className="mb-0.5 text-xs font-medium text-gray-500">人物档案 / 实体卡库</div>
    <EntityCardsReadonly cards={state.entity_cards} />
  </div>
)}
```

> 也可只传人物卡（`cards={state.entity_cards.filter(c => c.type === "人物")}`）保持详情页轻量，
> 但 `EntityCardsReadonly` 已按 type 分组、装备/物品也是真源信息，直接整卡库展示更完整。二选一，
> 施工时定（倾向整卡库，与 StateEditPanel 观测口一致）。

---

## 六、`EntityCardsReadonly.tsx` 卡片补字段

`Card` 人物段（`:49-58`）补 role（作徽标或首行）/current_state/深层 canon；势力/地点段补 standing：

```tsx
{isPerson && (
  <>
    <Row label="定位" value={card.role} />        {/* 或把 role 做成 name 旁徽标 */}
    <Row label="外貌" value={card.appearance} />
    <Row label="口吻" value={card.speech_style} />
    <Row label="性格" value={card.personality} />
    <Row label="能力" value={card.abilities} />
    <Row label="动机" value={card.motivation} />
    <Row label="处境" value={card.current_state} />
    <Row label="关系" value={card.relations} />
    <Row label="隐藏人设" value={card.hidden_persona} />
    <Row label="四卷弧光" value={card.arc_trajectory} />
    <Row label="底牌契约" value={card.ability_contract} />
  </>
)}
{/* 势力/地点段（原无专属字段，新增 standing）*/}
{card.type === "势力" && <Row label="格局" value={card.standing} />}
```

> `role` 更适合做成 `name` 右侧徽标（像 type 徽标那样），一眼看出主角/反派分层——施工时可选
> 徽标或 Row，二选一。深层 canon（隐藏人设/弧光/契约）字段长，考虑默认折叠或小字，避免卡片过高。

---

## 七、验证

1. `pnpm build` / `tsc --noEmit`：TS 编译零错（删字段后无 `state.character_profiles` 之类的类型引用残留）。
2. 全局搜索零命中：`character_profiles`（除 `character_profiles_focus` 题材聚焦保留）、
   `character_status`、`character_relations`、`STATUS_REVIEW`、`RELATIONS_REVIEW`、
   `character_profiles_discover`。
3. 手动/截图核对：详情页「人物档案」区渲染出结构化人物卡（含 role/处境）；编辑面板 snapshot 组
   只剩伏笔/阶段固化；实体卡只读视图新字段正常显示。
4. 与后端联调一章：跑到 Phase-1 建卡后详情页能看到卡司；跑一章确认 entity_discover 更新的
   current_state/owner 在只读视图刷新。
