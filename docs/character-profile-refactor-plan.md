# 人物/实体档案彻底改造方案（无历史包袱版）

> 前提：项目未上线，**不兼容老 checkpoint / 老 state 数据**。删掉所有 `_migrate_legacy_*`、
> `getattr` 兜底、双格式解析等 compat 分支。目标只有两个：**好用、好维护**。

---

## 一、当前的乱：四条重叠的人物动态腿

每章 `save_chapter` 之后，并排跑着 4 条记录同一批信息（人物处境/立场/动机/关系/能力）的腿：

| 腿 | 写入字段 | 形态 | 位置 | 可跳 |
|---|---|---|---|---|
| `character_profiles_discover_step` | `character_profiles`(str) | 散文全档案增量（只追加、无界膨胀、全量注入） | 顶层 graph | ❌ 自动 |
| `status_step` | `character_status`(str) | 半结构化 snapshot（整体覆盖） | chapter_edit 子图内 | ✅ |
| `relations_step` | `character_relations`(str) | 半结构化 snapshot（整体覆盖） | chapter_edit 子图内 | ✅ |
| `entity_discover_step` | `entity_cards`(list) | 结构化卡（字段级更新） | chapter_edit 子图内 | ✅ |

**这是一场做了一半的替换**：装备真源已从 `phase_summary` 迁到 `EntityCard`（`state.py:246` 已注明），
人物动态本该走同一条路，但没迁完——旧的 `status`/`relations`/散文 `discover` 都还在。

`foreshadowing`（伏笔）、`phase_summary`（非装备的固化数据：等级/技能/资源）与实体正交，**保留不动**。

---

## 二、目标架构：EntityCard 卡库 = 唯一真源（canon + 操作，彻底删 bible）

```
EntityCard 卡库   =  所有实体的唯一真源，一卡兼容 canon（深层设计）+ current（动态状态）
foreshadowing     =  伏笔台账（保留）
phase_summary     =  非实体固化数据：等级/技能/资源（保留；装备已移出）
【已删除】character_profiles 散文 bible —— 深层设计并入 CharacterCard 的 canon 字段
```

- **Phase-1 一次 LLM 直接出结构化卡**（不再先出 bible 散文再抽卡，省一跑）→ 核心卡司进 `entity_cards`
- **新登场角色/实体** → `entity_cards_step`（章前建卡，dedup 命中 Phase-1 卡即跳过）
- **已有实体的动态变化** → `entity_discover_step`（章末更新，唯一腿，仍可跳）
- **current 状态字段一律「覆盖」语义**（代表"现在"，不追加——追加会让 LLM 分不清哪句当下有效）
- **canon 字段建卡后锁定**（外貌/性格/双层人设/四卷弧光/底牌契约），`entity_discover` 禁改
- **选择性渲染治膨胀**：写正文触发注入**操作视图**（外貌/口吻/current_state/关系）；
  规划步骤（outline/arc/consistency）才渲染**深层视图**（四卷弧光/底牌契约）。比原 bible「每次全量注入」更省。

---

## 三、EntityCard 重构为判别联合（Character / Item / Simple）

纯 dataclass（项目无 pydantic）。基类 + 变体 + 一个 `parse_card(dict) -> EntityCard` 判别工厂，
按 `type` 分派构造。**无 compat**：老键直接不认，字段就是新 schema。

### 3.1 基类字段（所有类型）

```python
name: str                 # 主键（name+aliases 归一化去重）
type: EntityType          # Enum: 人物/物品/装备/势力/地点（不再是 magic string）
aliases: list[str]
summary: str              # 一句话定位
first_appear_chapter: int
```

### 3.2 CharacterCard（人物）

| 字段 | canon/动态 | 说明 |
|---|---|---|
| `role` | canon | **角色定位（Enum `CharacterRole`）**：主角/主要配角/功能性反派/根源反派/感情线角色/次要角色。同时回答"是否主角"与"正反派分层" |
| `appearance` | canon | 外貌锚点（防写飘，操作视图） |
| `speech_style` | canon | 口吻/口头禅（操作视图） |
| `personality` | canon | 表层公开人设/性格底色（操作视图） |
| `abilities` | canon | 能力底牌一句话摘要（落力量体系，操作视图注入用） |
| `hidden_persona` | canon | **深层隐藏人设（吸收自 bible）**：暗线预埋、可后期反转的隐藏面（深层视图） |
| `arc_trajectory` | canon | **四卷成长弧光（吸收自 bible）**：四卷心性/立场/认知迭代大势；反派写阶段作用 + 闭环退场逻辑（深层视图） |
| `ability_contract` | canon | **能力底牌契约（吸收自 bible）**：初始锚点 + 四卷成长天花板 + 隐藏杀手锏（触发/反噬）。phase_summary 战力校验红线（深层视图） |
| `motivation` | **动态·覆盖** | 当前动机/目标 |
| `current_state` | **动态·覆盖** | 当前处境（位置/情绪/状态）——吸收原 `character_status` |
| `relations` | **动态·覆盖** | 与主角/他人关系——吸收原 `character_relations` 人物部分。**立场翻转（叛变）由此字段承载**，不另开 alignment |

> **操作视图 vs 深层视图**：`format_character_profiles_from_cards(cards, *, deep=False)` 单一渲染函数。
> `deep=False`（默认，写正文/常规 context）：role/appearance/speech_style/personality/abilities/motivation/
> current_state/relations。`deep=True`（outline/arc/consistency 规划）：追加 hidden_persona/arc_trajectory/
> ability_contract。彻底取代原【人物档案】bible 注入，且默认视图有界、不再全量灌深层设计。

> `CharacterRole` Enum（英文成员名 + 中文值，与 `EntityType` 同风格）：
> `PROTAGONIST=主角 / MAIN_SUPPORTING=主要配角 / FUNCTIONAL_VILLAIN=功能性反派 /`
> `ROOT_VILLAIN=根源反派 / ROMANCE=感情线角色 / MINOR=次要角色`。建卡时定，基本不变（canon）；
> 触发式注入 chapter_prompt 时随卡带出（"这是根源反派"），防反派写扁/写飘。

### 3.3 ItemCard（物品/装备）

| 字段 | canon/动态 | 说明 |
|---|---|---|
| `effect` | canon | 效果/能力 |
| `rank` | canon | 品阶（落力量体系） |
| `owner` | **动态·覆盖·解析绑定** | 归属人（见 §四） |
| `status` | **动态·覆盖** | 完好/损坏/消耗/遗失 |

### 3.4 SimpleEntityCard（势力/地点）

只有基类字段。**新增可选** `standing`（**动态·覆盖**，势力强弱/格局）——吸收原 `character_relations`
的势力格局部分。地点暂无动态字段。

### 3.5 按变体的动态字段白名单

`UPDATABLE_FIELDS` 从单一元组改为**按 type 分派**：

```python
UPDATABLE_FIELDS: dict[EntityType, tuple[str, ...]] = {
    EntityType.人物: ("motivation", "current_state", "relations"),
    EntityType.物品: ("owner", "status"),
    EntityType.装备: ("owner", "status"),
    EntityType.势力: ("standing",),
    EntityType.地点: (),
}
```

`_apply_updates` 按卡的 `type` 取白名单，只覆盖对应字段，canon 字段代码层锁定。

---

## 四、物品从属关系（owner）：从裸字符串升级为解析绑定

现状：`owner` 只是名字字符串，无引用完整性、无反向查询、可挂空。改造：

1. **LLM 边界不变**：仍填 owner 名字（对 LLM 友好）。
2. **save 端解析绑定**：复用 `normalize_entity_name` 建的「名/别名→卡」索引，把 owner 匹配到规范
   人物/势力卡；**匹配不到 → fail-loud 告警**（揪出编造/错名 owner，符合 CLAUDE.md「fail-fast 不静默兜底」）。
   存规范名，链接不随别名漂移断掉。
3. **context 反向渲染**：`format_equipment_for_context` 增加按 owner 归组视角
   （"张三 携带：灵剑(完好)、护身符(损坏)"），让 LLM 从人物侧也能看到归属。

---

## 五、图 / 节点改线

### 5.1 `chapter_edit_subgraph.py`

- **删节点**：`status_step`、`relations_step`（及 `_prepare_status/_save_status/_prepare_relations/_save_relations`）
- **保留**：`arc_step`、`foreshadow_step`、`phase_step`、`entity_discover_step`
- **新边**：`arc_step → foreshadow_step → phase_step → entity_discover_step → chapter_edit_done`

### 5.2 顶层 `graph.py`

- **删节点**：`character_profiles_discover_step`
- **改边**：`generate_summary → chapter_edit_subgraph`（去掉中间的 discover）
- `entity_discover_step` 成为唯一人物/实体 current-state 更新腿（保留可跳 gate）
- **Phase-1 人物档案节点：从「生成 bible 散文」改为「直接出结构化卡」**（替换，非新增）：
  现有 `prepare_character_profiles → review_character_profiles → save_character_profiles` 三节点
  **重命名**为 `prepare_character_cards → review_character_cards → save_character_cards`（好维护），
  图边位置不变：`save_volumes → prepare_character_cards → review_character_cards → save_character_cards → prepare_initial_status`。
  - `prepare_character_cards`（`nodes/foundation.py`）：task_prompt = `character_cards_prompt(state)`（§7.8），review_type = `character_cards`。
  - `save_character_cards`：`parse_card`+`_merge_cards` 落 `entity_cards`（**不再写 `character_profiles`**）。
  - `subgraph.py`：`_REVIEW_PROMPTS`/`_HISTORY_MAX_ROUNDS` 把 `character_profiles` 项改为 `character_cards`（挂 `CHARACTER_CARDS_REVIEW_PROMPT`）。
  - `interrupt_types.py`：`character_profiles` review 类型改名 `character_cards`。
  > **命名区分（防混淆）**：`character_cards`（Phase-1 一次建全套核心卡司）与 `entity_cards`（章前逐章发现新登场实体）
  > 是**两个不同 review_type**，注册表/中断类型互不冲突；两者都落 `entity_cards` 字段是**故意的**——同一卡库，
  > 一个负责开局铺满卡司、一个负责增量补录。保持两名不合并。

### 5.3 删除文件

- `character_profiles_discover_subgraph.py`
- `nodes/character_profiles_discover.py`
- `prompts/character_profiles_discover.py`

---

## 六、字段 / prompt / 注册表清理（删干净，无残留）

| 位置 | 删除内容 |
|---|---|
| `state.py` | `character_status`、`character_relations`、**`character_profiles`** 三字段；三个子图 substate 的 `character_profiles`/`character_status`/`character_relations` 桥接字段（`edit_step_subgraph:79`、`arc_edit_subgraph:57,64-65`、`chapter_edit_subgraph:66,79-80`）；**订正 `phase_summary` 注释（`:268` 仍写「装备」，装备已移出真源改由卡库承载，删该词避免施工误判）** |
| `context.py` | status/relations 注入段（`:172-176`）、`character_profiles` 注入段（`:165-166`，改渲染，见 §6.1）、`_ContextState` 协议里三字段、`exclude_snapshots` 分支收敛；`foreshadowing` 协议类型收窄为 `dict` |
| `prompts/base.py` | `character_status_prompt`、`character_relations_prompt`、`CHARACTER_STATUS_REVIEW_PROMPT`、`CHARACTER_RELATIONS_REVIEW_PROMPT`、**`character_profiles_prompt`（bible）**、**`CHARACTER_PROFILES_REVIEW_PROMPT`**；`format_chapter_plan_state_snapshot`（`:817-820`）里 status/relations 两行 |
| `subgraph.py` `_REVIEW_PROMPTS`/`_HISTORY_MAX_ROUNDS` | 删 `character_status`、`character_relations`、`character_profiles_discover`；`character_profiles` → 改名 `character_cards`（挂 `CHARACTER_CARDS_REVIEW_PROMPT`） |
| `interrupt_types.py` | `STATUS_*`、`RELATIONS_*`、`CHARACTER_PROFILES_DISCOVER_*` gates；review-type map 三项删/改名 |
| `prompts/__init__.py` | 删对应导出（status/relations prompt + review、discover 三件、bible prompt + review）；加 `CHARACTER_CARDS_*`、`character_cards_prompt`、`format_character_profiles_from_cards` |
| `prompts/base.py` foreshadowing | 删 `_migrate_legacy_foreshadowing` + `_save_foreshadowing` 旧格式 fallback（无 compat，解析失败即 fail-loud） |
| `prompts/genres/*.py` | 5 个 `character_profiles_focus` 保留（复用给 `character_cards_prompt` 做题材聚焦），文案按需微调 |

### 6.1 `character_profiles` 消费点 → 改渲染 `format_character_profiles_from_cards(cards)`

删掉 `character_profiles` 字段后，原来读它的地方统一改为**从卡库渲染**（单一渲染函数，见 §3.2）：

| 消费点 | 现状 | 改为 |
|---|---|---|
| `context.py:165` | 注入 `state.character_profiles` | `format_character_profiles_from_cards(state.entity_cards)`（默认操作视图） |
| `edit_step_subgraph.py:201` | `character_profiles=state.character_profiles` | 同上（该 prompt 是 chapter_plan/scene_beats 输入） |
| `prompts/review_shared.py:333` | 模板 `{character_profiles}` | 改 `FORESHADOW_PRUNE_ANALYSIS_PROMPT` 的 `.format` 调用方，从 `entity_cards` 渲染后传参（字段删后不改 → `.format` KeyError） |
| `nodes/consistency.py:52` | 快照列表 `("character_profiles","人物档案")` | 从卡库渲染人物档案段 |
| `nodes/foundation.py:153` | `initial_status` 读 `character_profiles` | 从卡库渲染（`deep=True` 供战力基线校验） |
| outline/arc 规划 prompt | 经 `build_foundation_context` 拿 bible | `deep=True` 渲染深层视图（四卷弧光/底牌契约） |

> **深/浅视图分流（关键，否则 `:165` 与 outline/arc 冲突）**：`context.py:165` 与 outline/arc 走的是**同一个**
> `build_foundation_context`，但前者要操作视图、后者要深层视图。解法：`build_foundation_context` 新增
> `deep_character_view: bool = False` 形参，人物段渲染 `format_character_profiles_from_cards(cards, deep=deep_character_view)`。
> 写正文/常规 context 用默认 `False`（操作视图）；outline/arc/consistency 规划的调用方显式传 `True`（深层视图）。
> **不再依赖 `state.character_profiles` 字段**（已删）——数据一律来自 `state.entity_cards`。

> 实现时核对 `prepare_initial_status`/`consistency` 的完整引用链，确保无 `character_profiles`/`character_status`/`character_relations` 残留。

---

## 七、LLM 提示词改动明细（逐条 before→after）

所有实体相关 prompt 都在 `prompts/entity_cards.py`，共用 `_CARD_SPEC` 字段规范。

### 7.1 `_CARD_SPEC`（生成 + 审核共用的字段规范）

**人物段字段增补**：

| 动作 | 字段 | 规范文案 |
|---|---|---|
| **新增** | `role` | `"【人物·必填】角色定位，只能填：主角/主要配角/功能性反派/根源反派/感情线角色/次要角色"` |
| **新增** | `current_state` | `"【人物】当前处境:位置/情绪/状态（动态，≤30字，非人物留空）"` |
| 保留 | appearance/speech_style/personality/motivation/relations/abilities | 不变 |

**势力/地点段新增**：`standing` → `"【势力】当前强弱/格局（动态，非势力留空）"`

**硬约束新增一条**：`"人物必须给 role，取值限上述六个枚举之一，禁止自造或留空。"`

### 7.2 生成模板示例 JSON（`ENTITY_CARDS_PROMPT` 的 example 行）

示例 new_card 补上新字段：人物示例加 `"role": "主角", "current_state": "..."`；若示例含势力则加 `"standing": "..."`。

### 7.3 `ENTITY_CARDS_REVIEW_PROMPT`（章前建卡审核）

检查项新增：**role 合法性**——每张人物卡是否有 `role`、且是六个枚举值之一（缺失/自造即打回）。
> 卡司配额（主角唯一等）**不强查**——避免与增量补录语义冲突把流程打回死循环（沿用现有宽松基调）。

### 7.4 `ENTITY_DISCOVER_PROMPT`（章末更新，改动最大）

- **任务② 从**「装备状态/归属、人物动机」**扩为**：
  - 人物：`current_state`（处境）/`motivation`（动机）/`relations`（关系，**含立场翻转/叛变**）
  - 装备/物品：`owner`/`status`　　- 势力：`standing`
- **updates 字段说明改为「按 type 白名单」**：
  - 人物 update 只能含 `current_state`/`motivation`/`relations`
  - 装备/物品 update 只能含 `owner`/`status`　　- 势力 update 只能含 `standing`
- **新增覆盖语义强调**（关键，防追加误导 LLM）：
  > `"动态字段是「现在」的快照，直接用当下真相覆盖旧值；禁止把『原为X、现为Y』两句并列堆叠——`
  > `那会让后续章节的 LLM 分不清哪个是当下有效状态。"`
- **canon 保护清单更新**：`role`/`appearance`/`speech_style`/`personality`/`abilities`/`name`/`type` 禁改（新增 role）。
- **entry 文案**（`chapter_edit_subgraph._ENTITY_DISCOVER_STEP`）改为：
  `"是否更新本章实体动态（人物处境/动机/关系、装备归属/状态、势力格局）？"`

### 7.5 `ENTITY_DISCOVER_REVIEW_PROMPT`（章末更新审核）

- 检查 updates 是否越权改 canon（现在含 `role`）。
- 检查每条 update 是否落在该实体 type 的白名单内。

### 7.6 直接删除的 prompt（不修改，整体删）

- `character_status_prompt` / `character_relations_prompt`（`prompts/ledger.py`）
- `CHARACTER_STATUS_REVIEW_PROMPT` / `CHARACTER_RELATIONS_REVIEW_PROMPT`（`prompts/review_shared.py`）
- `CHARACTER_PROFILES_DISCOVER_PROMPT` / `_REVIEW_PROMPT`（`prompts/character_profiles_discover.py` 整文件删）

### 7.7 `character_profiles_prompt`（bible）→ **删除**

原 `base.py:353` 一次成型出 bible 散文的 prompt **整体删除**，由 §7.8 的结构化建卡 prompt 取代。
bible 的深层设计（双层人设/四卷弧光/底牌契约）改由 CharacterCard 的 canon 字段（hidden_persona/
arc_trajectory/ability_contract）承载。题材聚焦 `flavor.character_profiles_focus` 保留，复用给新 prompt。

### 7.8 **新增** `character_cards_prompt`（Phase-1 一次直接出结构化卡，取代 bible）

Phase-1 不再先出散文 bible——**直接**让 LLM 输出全套核心卡司的结构化 CharacterCard。

- **身份/聚焦**：沿用 `flavor.system_identity` + `flavor.character_profiles_focus`（题材聚焦）。
- **输入**：`world_building` + `power_system` + `core_conflicts` + `overall_outline`（据此定 role/能力落体系/四卷弧光）。
- **输出**：`{"new_cards": [CharacterCard...]}`——覆盖卡司配额的**全部**核心角色（主角 1/核心配角 3-5/
  功能性反派 2-3/根源反派 1/感情线 1-2），每张填齐：
  - **canon**：role、appearance、speech_style、personality、abilities、**hidden_persona**（深层隐藏人设）、
    **arc_trajectory**（四卷弧光；反派写阶段作用+闭环退场）、**ability_contract**（初始锚点+四卷天花板+杀手锏）
  - **初始动态**：motivation、current_state（开篇处境）、relations
  - bible 里点名的**关键势力**可一并建 SimpleEntityCard（填 standing）。
- **沿用 bible 的硬约束**（迁进本 prompt）：卡司配额、双层人设强制拆分、能力硬绑力量体系、人设自洽、
  反派分层、关系围绕主角闭环、视觉标识轻描淡写、留白规则。
- **落库**：`parse_card` + `_merge_cards` 写入 `entity_cards`（与章节建卡同一套解析/去重）。
- **审核**（`CHARACTER_CARDS_REVIEW_PROMPT`，替代原 bible review）：卡司配额是否齐全、role 合法、
  每人双层人设（personality + hidden_persona）是否都在、能力是否落体系、四卷弧光/底牌契约是否完整。
- **robustness**：一次出 6-10 张富卡司 JSON，走 `repair_and_parse`（容围栏/尾逗号/截断）；
  解析失败即 fail-loud 触发审核循环重生成。若实测频繁截断，再议分批（当前不预先分批）。

---

## 八、执行顺序（自底向上，每步可编译验证）

1. **schema 层**：`state.py` EntityCard→判别联合（`EntityType`/`CharacterRole` Enum + Character/Item/Simple + `parse_card`）；删 `character_status`/`character_relations`/**`character_profiles`** 三字段 + 各子图桥接字段。
2. **prompts 层**：`entity_cards.py` 卡 spec（加 role/current_state/standing + 人物深层 canon 字段）/ discover prompt（覆盖语义 + type 白名单）/ `UPDATABLE_FIELDS` 按 type 分派 / owner 解析 / 反向渲染 / **新增 `character_cards_prompt` + `CHARACTER_CARDS_REVIEW_PROMPT` + `format_character_profiles_from_cards`**；删 status/relations/discover 三组 prompt + **bible prompt+review** + foreshadowing 旧格式 fallback。
3. **节点层**：`nodes/entity_cards.py` 适配 union + owner 解析——**两处 `EntityCard(**raw)`（`:74`/`:177`）+ `_coerce_card`（`:132`）全部改走 `parse_card`**（字符串 `type`→`EntityType` 由工厂转换；checkpoint 反序列化的 dict 同走此路，`EntityType` 是 str 枚举故 roundtrip 安全，无需 `_migrate_legacy_*`）；`_apply_updates` 的 `for key in UPDATABLE_FIELDS` 改为 `for key in UPDATABLE_FIELDS[card.type]`（按卡 type 取白名单）；`nodes/foundation.py` `prepare/save_character_profiles` **改为 `prepare/save_character_cards`**（落 entity_cards）+ `initial_status` 改读卡渲染；删 `nodes/character_profiles_discover.py`。
4. **子图层**：`chapter_edit_subgraph.py` 删 status/relations 两步 + 改边；删 `character_profiles_discover_subgraph.py`；三个子图 substate 删 character_profiles/status/relations 桥接字段。
5. **顶层图**：`graph.py` 删 discover 节点 + 改边；Phase-1 三节点重命名 character_profiles→character_cards。
6. **context 层**：`context.py` 删 status/relations 注入段、`character_profiles` 注入改 `format_character_profiles_from_cards`、协议收窄、owner 反向渲染接入；其余 4 个消费点（§6.1）改渲染。
7. **注册表/导出/中断类型**：`subgraph.py`（`character_cards` review 注册 + snapshot 集）、`prompts/__init__.py`、`interrupt_types.py` 清理。
8. **验证**：`langgraph dev` 编译无错；跑基础流程确认 Phase-1 **一次**出结构化卡司落库、深层字段（弧光/底牌）齐全、章节 dedup 不重建；跑一章闭环确认 entity_discover 单腿覆盖更新人物 current-state、owner 解析绑定生效、无 `character_profiles`/status/relations 残留。

---

## 九、验收标准

- 每章章末只剩 **1 条**实体动态腿（entity_discover），不再有 status/relations/散文 discover。
- **Phase-1 一次 LLM 直接产出全套核心卡司的结构化 CharacterCard**（含 role + 双层人设 + 四卷弧光 + 底牌契约），落 `entity_cards`；无 `character_profiles` 散文 bible。
- 人物"当前处境/动机/关系"落在 `CharacterCard` 动态字段，覆盖语义、可演进不堆矛盾；canon 字段建卡后锁定。
- 章节写正文注入操作视图（紧凑）、规划步骤注入深层视图——不再每次全量灌整本档案。
- 物品 `owner` 解析绑定到规范实体，挂空时告警；context 有人物侧反向归属视图。
- 全代码库无 `character_profiles`/`character_status`/`character_relations`/`character_profiles_discover` 残留、无 `_migrate_legacy_*`。
