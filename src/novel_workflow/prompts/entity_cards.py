"""章前「登场实体卡（EntityCard）」提示词与组装函数。

entity_cards 是章前节拍表（scene_beats）之后、写正文之前的可跳步骤：读已定稿 beats +
本章弧线大纲 + 已有实体清单，自动识别本章登场实体，只为**新**实体建结构化卡，供 prepare_chapter
按「本章登场名单」触发式注入 chapter_prompt，防止已知实体写飘。

覆盖边界（章前 vs 章末分工）：
- 章前以**人物**为主（beats 的 scene 字段稳定携带出场人物），物品/装备只登记 beats/大纲
  **显式点名的关键道具**，不脑补——正文临场新增的实体由章末 entity_discover_step 补卡。

数据落地：LLM 输出严格 JSON 对象 {"cast": [...], "new_cards": [EntityCard...]} →
repair_and_parse(kind=dict) 解析 → _save_entity_cards 逐条造 EntityCard、name+aliases 归一化
去重 merge 进卡库。解析失败当场抛 JsonParseError（新字段无历史包袱，fail-fast）。
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from noval_workflow.prompts.base import _extract_arc_chapter_block
from noval_workflow.prompts.scene_beats import format_beats_for_chapter_prompt
from noval_workflow.state import EntityType

if TYPE_CHECKING:
    from noval_workflow.state import EntityCard, NovelState


# 合法 type 值集合——渲染/审核文案里用字符串枚举值即可（EntityType 是 str 枚举，等值）。
ENTITY_TYPES = tuple(e.value for e in EntityType)


def _text(v) -> str:
    """取值的字符串形态——str 枚举成员 f-string 插值会漏出 'EntityType.CHARACTER'，故取其 value。

    卡库条目 type/role 在新建（parse_card）后是枚举、checkpoint roundtrip 后是字符串，
    渲染函数插值 type/role 前一律经此归一，两种形态都安全。
    """
    return v.value if isinstance(v, Enum) else ("" if v is None else v)


# ── 共享 spec 块（生成/审核唯一真源）─────────────────────────────────────────
#
# 字段规范 + type 分段 + 硬约束抽成共享文本，生成端与审核端都用 str.replace 拼进去。
# JSON 字面花括号用 {{ }} 转义，拼进最终 prompt 后被 .format() 归一为字面 { }。

_CARD_SPEC = """## 输出结构（严格 JSON 对象，顶层两个键）

```json
{{
  "cast": ["本章登场的所有实体名（含已有 + 新增），只列 name"],
  "new_cards": [ /* 只放【新】实体的完整卡；已有实体不要放这里 */ ]
}}
```

## 单张 new_card 的字段（严格 JSON）

```json
{{
  "name": "实体名（唯一，作主键）",
  "type": "人物 / 物品 / 装备 / 势力 / 地点（只能选其一）",
  "aliases": ["别称/绰号/尊称，无则空数组——务必收全，防后续误判为新实体"],
  "summary": "一句话定位（≤30字）",
  "first_appear_chapter": <本章章号，整数>,
  "role": "【人物·必填】角色定位,只能填:主角/主要配角/功能性反派/根源反派/感情线角色/次要角色（非人物留空）",
  "appearance": "【人物】体貌基线:身形/气质/年龄段/大致长相,供正文外貌一致性+可选1个识别特征（≤60字，非人物留空）",
  "speech_style": "【人物】说话风格/口吻/口头禅/温度:健谈/毒舌/寡言/温和…（≤30字，非人物留空）",
  "personality": "【人物】性格（非人物留空）",
  "abilities": "【人物】能力底牌，须落【力量体系】框架（非人物留空）",
  "motivation": "【人物·动态】当前动机/目标（非人物留空）",
  "current_state": "【人物·动态】当前处境:位置/情绪/状态（≤30字，非人物留空）",
  "relations": "【人物·动态】与主角/他人关系（非人物留空）",
  "owner": "【物品/装备·动态】归属人（非物品留空）",
  "effect": "【物品/装备】效果/能力（非物品留空）",
  "status": "【物品/装备·动态】当前状态:完好/损坏/消耗/遗失（非物品留空）",
  "rank": "【物品/装备】品阶/等级,须落力量体系（非物品留空）",
  "standing": "【势力·动态】当前强弱/格局（非势力留空）"
}}
```

## 硬约束（必须满足，否则不合格重来）

1. **只建新实体**：`new_cards` 只放【已有实体清单】里**没有**的实体。已有实体（名字或别称
   命中清单）**只写进 `cast`，禁止放进 `new_cards`**——重复建卡不合格。
2. **cast 完整**：`cast` 必须列出本章登场的**所有**实体名（已有 + 新增），供下游注入卡片。
3. **人物为主**：以本章登场**人物**为主。物品/装备**只登记 beats/大纲里显式点名的关键道具**
   （有名字、有戏份的法宝/功法/信物等），不要把一句话带过的杂物写成卡。
4. **反幻觉**：只登记 beats / 本章弧线大纲里**显式出现**的实体，禁止凭空虚构本章未提及的人/物。
5. **type 合法**：type 只能是 人物/物品/装备/势力/地点 之一。
6. **别称收全**：`aliases` 尽量收全已知别称/绰号/尊称——这是后续判定「新/旧」不误判的关键。
7. **能力落体系**：人物 abilities、物品 rank 涉及能力/境界/品阶时，必须落入系统提示【力量体系】
   框架，禁止自造新体系。
8. **人物必填 role**：人物卡必须给 `role`，取值限主角/主要配角/功能性反派/根源反派/感情线角色/
   次要角色六者之一，禁止自造或留空（用于反派分层 + 触发式注入防写扁）。"""


# ── 生成提示词 ────────────────────────────────────────────────────────────────

_ENTITY_CARDS_TEMPLATE = """请识别本章**登场实体**（人物/物品/装备/势力/地点），为其中的【新】实体建立结构化属性卡。

【本章定位】第 {chapter_num} 章《{title}》{batch_pos_desc}{arc_section}

【本章节拍表（scene beats，登场实体的主要依据）】
{beats_section}

【已有实体清单（这些是已建过卡 / 已在人物档案里的，禁止重复建卡）】
{existing_roster}

---

## 任务

对照上文，把本章登场实体分成两类处理：

1. **已有实体**（名字或别称命中【已有实体清单】）：**只写进 `cast` 名单**，不建新卡。
2. **新实体**（清单里没有的）：写进 `cast`，同时在 `new_cards` 里建一张完整卡。

新实体以**人物**为主；物品/装备只登记 beats/大纲里**显式点名的关键道具**。

__CARD_SPEC__

## 输出格式（严格 JSON 对象，无 markdown 围栏）

直接输出如下结构，不要包裹在 ```json 里，不要有解释文字：

```
{{"cast": ["张三", "灵剑"], "new_cards": [{{"name": "张三", "type": "人物", "aliases": ["三哥"], "summary": "...", "first_appear_chapter": {chapter_num}, "role": "主角", "appearance": "...", "speech_style": "...", "personality": "...", "abilities": "...", "motivation": "...", "current_state": "...", "relations": "...", "owner": "", "effect": "", "status": "", "rank": "", "standing": ""}}]}}
```

请直接输出 JSON 对象。"""

ENTITY_CARDS_PROMPT = _ENTITY_CARDS_TEMPLATE.replace("__CARD_SPEC__", _CARD_SPEC)


# ── 审核提示词 ────────────────────────────────────────────────────────────────
#
# 与生成 prompt 共用 _CARD_SPEC：审核端不再重述字段/枚举/硬约束，只保留「逐项如何判定」。

_ENTITY_CARDS_REVIEW_TEMPLATE = """请审核以下「本章登场实体卡」草稿，逐条检查是否符合硬性规则；无问题则回复「无问题」，有问题则列出具体条目。

【草稿】
{draft}

---

以下是本环节必须遵守的规范（生成端使用同一份规范，请对照草稿判定）：

__CARD_SPEC__

---

## 逐项检查（发现任何一项不合格都要指出，并给出改法）

1. **JSON 合法性**：能否解析为顶层 dict、含 `cast`（list）+ `new_cards`（list）两键？每张 new_card
   字段是否齐全（name/type/aliases/summary/first_appear_chapter + 人物段 + 物品段）？

2. **不重复建卡**（最重要）：`new_cards` 里是否混入了【已有实体清单】里已存在的实体（名字或别称
   命中）？只要有一张重复卡即不合格，必须移到 `cast`、从 `new_cards` 删除。

3. **cast 完整性**：`cast` 是否列全了本章登场的所有实体（已有 + 新增）？漏列会导致下游注入不到卡。

4. **人物为主 / 物品克制**：物品/装备是否只登记了 beats/大纲显式点名的关键道具？有没有把一句话
   带过的杂物或背景摆设写成卡？

5. **反幻觉**：new_cards 的实体是否都来自 beats / 本章弧线大纲的显式描写？有无凭空虚构的人/物？

6. **type 合法性**：每张卡 type 是否是 人物/物品/装备/势力/地点 之一？

7. **别称收全**：人物/关键实体的 aliases 是否收了已知别称/绰号？漏收会导致后续误判为新实体。

8. **能力落体系**：人物 abilities、物品 rank 是否落入系统提示【力量体系】框架，未自造新体系？

---

严格判定，缺一即为不合格。若全部通过，直接回复「无问题」；否则逐条列出问题并给改法。"""

ENTITY_CARDS_REVIEW_PROMPT = _ENTITY_CARDS_REVIEW_TEMPLATE.replace("__CARD_SPEC__", _CARD_SPEC)


# ── 已有实体清单渲染（喂给生成 prompt，让 LLM 判定新/旧）──────────────────────

def _format_existing_roster(cards: list["EntityCard"]) -> str:
    """把已有卡库渲染成紧凑清单（name〔type〕别名: a/b），供生成 prompt 判定新旧。

    只列 name/type/aliases——判新旧够用，不灌全字段（省 token）。人物档案里的已有人物
    另经 system_context 的【人物档案】段进入，故这里只列结构化卡库。
    """
    if not cards:
        return "（卡库为空，本章登场实体多半都是新的；但人物档案里的已有角色仍算已有，勿重复建卡）"
    lines: list[str] = []
    for card in cards:
        name = card.get("name", "") if isinstance(card, dict) else getattr(card, "name", "")
        etype = _text(card.get("type", "") if isinstance(card, dict) else getattr(card, "type", ""))
        aliases = card.get("aliases", []) if isinstance(card, dict) else getattr(card, "aliases", [])
        alias_str = f"（别名:{'/'.join(aliases)}）" if aliases else ""
        lines.append(f"- {name}〔{etype}〕{alias_str}")
    return "\n".join(lines)


# ── 组装函数 ──────────────────────────────────────────────────────────────────

def entity_cards_prompt(state: "NovelState") -> str:
    """组装本章「登场实体卡」生成提示词。

    Args:
        state: NovelState 或 EntityCardsSubState，需含 chapter loop 上下文字段
            （total_chapters_written / current_batch_titles / current_chapter_index /
            current_arc_outline / current_chapter_beats / entity_cards）。
    """
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index] if state.current_batch_titles else ""
    batch_pos = state.current_chapter_index + 1
    batch_total = len(state.current_batch_titles)
    batch_pos_desc = f"，本批第 {batch_pos}/{batch_total} 章。" if batch_total else "。"

    # 本章弧线大纲锚点（复用 base.py 工具，与 scene_beats 一致）
    arc_section = ""
    if state.current_arc_outline and batch_pos:
        block = _extract_arc_chapter_block(state.current_arc_outline, batch_pos)
        if block:
            arc_section = f"\n【本章弧线大纲锚点】\n{block}"

    # 已定稿 beats（本章登场实体的主要依据）——严格核对章号，防跳 gate 时残留串章
    beats_section = "（本章未生成 scene beats，请依据本章标题 + 弧线大纲推断登场实体）"
    if state.current_chapter_beats and state.beats_chapter_index == chapter_num:
        beats_section = format_beats_for_chapter_prompt(state.current_chapter_beats)

    existing_roster = _format_existing_roster(state.entity_cards)

    # 首版不接自进化桶（entity_cards 未登记 evolved 桶，硬接会回退到 chapter 桶污染本 prompt）。
    return ENTITY_CARDS_PROMPT.format(
        chapter_num=chapter_num,
        title=title,
        batch_pos_desc=batch_pos_desc,
        arc_section=arc_section,
        beats_section=beats_section,
        existing_roster=existing_roster,
    )


# ── 结构化卡 → markdown（供 prepare_chapter 触发式注入 chapter_prompt）──────────

def format_cards_for_chapter_prompt(cards: list, cast: list) -> str:
    """把「本章登场」的实体卡渲染成 markdown，注入 chapter_prompt 作为防写飘锚点。

    只渲染 name/aliases 命中 cast 名单的卡（触发式注入，不灌全卡库）。人物卡突出外貌/口吻，
    物品卡突出归属/状态——这些是最容易写飘的维度。

    Args:
        cards: 全书卡库 list[EntityCard|dict]。
        cast:  本章登场实体名单 list[str]（已核对 cast_chapter_index，由调用方保证）。
    """
    if not cards or not cast:
        return ""
    cast_set = {normalize_entity_name(n) for n in cast}
    lines: list[str] = []
    for card in cards:
        get = (lambda k: card.get(k, "")) if isinstance(card, dict) else (lambda k: getattr(card, k, ""))
        aliases = get("aliases") or []
        keys = {normalize_entity_name(get("name"))} | {normalize_entity_name(a) for a in aliases}
        if not (keys & cast_set):
            continue
        etype = get("type")
        name = get("name")
        alias_str = f"（{'/'.join(aliases)}）" if aliases else ""
        if etype == "人物":
            detail = (
                f"  - 定位:{get('summary')} ｜ 外貌:{get('appearance')} ｜ 口吻:{get('speech_style')}\n"
                f"  - 性格:{get('personality')} ｜ 动机:{get('motivation')} ｜ 关系:{get('relations')}\n"
                f"  - 能力:{get('abilities')}"
            )
        elif etype in ("物品", "装备"):
            detail = (
                f"  - 定位:{get('summary')} ｜ 归属:{get('owner')} ｜ 状态:{get('status')}\n"
                f"  - 效果:{get('effect')} ｜ 品阶:{get('rank')}"
            )
        else:  # 势力/地点等
            detail = f"  - 定位:{get('summary')}"
        lines.append(f"- **{name}〔{_text(etype)}〕{alias_str}**\n{detail}")
    return "\n".join(lines)


def normalize_entity_name(name: str) -> str:
    """实体名归一化——去重查重的唯一真源规则（save 端 merge、注入端匹配 cast 都用它）。

    放在 prompts 层作单一真源，nodes 层 import 复用（分层方向：nodes 依赖 prompts，不反过来），
    避免两处各写一份规则漂移。规则：去首尾空白 + 去半/全角空格 + 转小写。
    """
    return (name or "").strip().replace(" ", "").replace("　", "").lower()


# ── 装备/物品全局真源渲染（供 build_foundation_context 注入，替代 phase_summary 装备段）──

# 视为「已退场」的物品状态——不再注入正文上下文（遗失/消耗后不该继续出现在设定锚点里）。
_RETIRED_STATUS = frozenset({"遗失", "已遗失", "消耗", "已消耗", "损毁", "已损毁"})


def format_equipment_for_context(cards: list) -> str:
    """把卡库里未退场的 type∈{装备,物品} 渲染成**按归属人归组**的 markdown，作为装备/物品真源注入。

    phase_summary 已移除装备段，装备真源改由本函数从 ItemCard 渲染——所有下游（写正文/一致性
    审计）看到同一份卡库真源，消除双源。按 owner 归组（"张三 携带:灵剑(完好·上品)、护身符(损坏)"），
    让 LLM 从人物侧直接看到谁持有什么，比平铺列表更贴写作视角。已遗失/已消耗的物品不再注入。
    """
    if not cards:
        return ""
    groups: dict[str, list[str]] = {}
    order: list[str] = []  # 保持首次出现顺序，输出稳定（不依赖 dict 插入序的隐含约定）
    for card in cards:
        get = (lambda k: card.get(k, "")) if isinstance(card, dict) else (lambda k: getattr(card, k, ""))
        if get("type") not in ("装备", "物品"):
            continue
        if (get("status") or "").strip() in _RETIRED_STATUS:
            continue
        bucket = (get("owner") or "").strip() or "无归属"
        if bucket not in groups:
            groups[bucket] = []
            order.append(bucket)
        tags = [t for t in (get("status"), get("rank")) if t]
        tag_str = f"（{'·'.join(tags)}）" if tags else ""
        desc = get("effect") or get("summary")
        groups[bucket].append(f"{get('name')}{tag_str}" + (f":{desc}" if desc else ""))
    if not order:
        return ""
    lines: list[str] = []
    for bucket in order:
        label = f"{bucket} 携带" if bucket != "无归属" else "无归属"
        lines.append(f"- **{label}**：" + "、".join(groups[bucket]))
    return "\n".join(lines)


def resolve_owner(owner_name: str, cards: list) -> str | None:
    """把 owner 名字解析绑定到卡库里规范实体的 name——引用完整性 + 链接不随别名漂移断掉。

    复用 normalize_entity_name 的「名/别名→规范 name」索引匹配 owner：
    - 空 owner → 返回 ""（无归属是合法状态，不告警）。
    - 命中 → 返回规范 name（存规范名，别名改动不影响链接）。
    - 未命中 → 返回 None（调用方 fail-loud 告警，揪出编造/错名的 owner，不静默兜底）。
    """
    owner_name = (owner_name or "").strip()
    if not owner_name:
        return ""
    key = normalize_entity_name(owner_name)
    for card in cards:
        get = (lambda k: card.get(k, "")) if isinstance(card, dict) else (lambda k: getattr(card, k, ""))
        names = {normalize_entity_name(get("name"))} | {normalize_entity_name(a) for a in (get("aliases") or [])}
        if key in names:
            return get("name")
    return None


# ── 章末「实体发现 + 动态更新」提示词（读已写正文，补新卡 + 更新已有卡动态字段）──────

# 章末 update 按实体 type 分派可改字段白名单——canon（name/type/role/外貌/口吻/人设/能力/
# 深层设计/effect/rank）代码层锁定禁改，save 端只 apply 对应 type 白名单里的键（不依赖 LLM 听话）。
UPDATABLE_FIELDS: dict[EntityType, tuple[str, ...]] = {
    EntityType.CHARACTER: ("motivation", "current_state", "relations"),
    EntityType.ITEM: ("owner", "status"),
    EntityType.EQUIPMENT: ("owner", "status"),
    EntityType.FACTION: ("standing",),
    EntityType.LOCATION: (),
}

_ENTITY_DISCOVER_TEMPLATE = """请根据**本章已写正文**，对实体卡库做两件事：① 发现正文里新冒出、卡库还没有的实体并建卡；② 用当下真相**覆盖更新**已有卡的**动态字段**（人物处境/动机/关系、装备归属/状态、势力格局）。

【本章号】第 {chapter_num} 章

【已有实体卡库】
{existing_roster}

【本章正文】
{chapter_draft}

---

## 任务

1. **发现新实体**：正文里出现、【已有实体卡库】里没有的有名有戏份的人物/物品/装备/势力/地点 → 建完整卡（字段规范同下）。
2. **覆盖更新已有卡动态字段**（按实体 type 各有白名单）：
   - 人物：`current_state`(处境:位置/情绪/状态) / `motivation`(动机) / `relations`(关系，**含立场翻转/叛变**)
   - 装备/物品：`owner`(易主) / `status`(损坏/消耗/遗失)
   - 势力：`standing`(强弱/格局变化)

__CARD_SPEC_DISCOVER__

## 输出格式（严格 JSON 对象，无 markdown 围栏）

```
{{"new_cards": [ /* 新实体完整卡，无则空数组 */ ], "updates": [ /* 已有卡动态变更，无则空数组 */ {{"name": "灵剑", "owner": "李四", "status": "损坏"}} ]}}
```

- `updates` 每条必须含 `name`（定位已有卡），其余键**按该实体 type 的白名单**：
  人物只能含 `current_state`/`motivation`/`relations`；装备/物品只能含 `owner`/`status`；势力只能含 `standing`。
- **覆盖语义（关键）**：动态字段是「现在」的快照，直接用当下真相**覆盖**旧值；禁止把「原为X、现为Y」
  两句并列堆叠——那会让后续章节的 LLM 分不清哪个才是当下有效状态。
- **禁止改** canon（`name`/`type`/`role`/`appearance`/`speech_style`/`personality`/`abilities`/
  `hidden_persona`/`arc_trajectory`/`ability_contract`/`effect`/`rank`）——建卡时锁定的设定，只能改动态字段。
- **反幻觉**：只登记正文显式描写的实体与变化，禁止推测演绎。
- 本章无新实体、无动态变化（如纯过场章）→ 输出 `{{"new_cards": [], "updates": []}}`。

请直接输出 JSON 对象。"""

# discover 端复用章前 _CARD_SPEC 里「单张卡字段」那一段（new_cards 结构与章前一致），
# 去掉章前特有的 cast 输出结构与硬约束（discover 有自己的双键结构与宽松约束）。
_CARD_SPEC_DISCOVER = "## 单张卡的字段（严格 JSON）" + (
    _CARD_SPEC.split("## 单张 new_card 的字段（严格 JSON）", 1)[-1].split("## 硬约束")[0]
)

ENTITY_DISCOVER_PROMPT = _ENTITY_DISCOVER_TEMPLATE.replace("__CARD_SPEC_DISCOVER__", _CARD_SPEC_DISCOVER)


ENTITY_DISCOVER_REVIEW_PROMPT = """请审核以下「章末实体发现 + 动态更新」草稿。这是每章正文完成后的增量补录，审核标准宽松。

【草稿】
{draft}

---

## 审核范围（只查以下几点）

1. **JSON 合法性**：顶层 dict、含 `new_cards`(list) + `updates`(list)？每张 new_card 字段齐全、type 合法（人物/物品/装备/势力/地点）、人物 new_card 是否给了合法 `role`？每条 update 是否含 name？
2. **按 type 白名单**：每条 update 的字段是否落在该实体 type 的白名单内——人物只能改 current_state/motivation/relations，装备/物品只能改 owner/status，势力只能改 standing？越权即打回。
3. **覆盖语义**：动态字段是否用当下真相直接覆盖，而非「原为X现为Y」并列堆叠（堆叠会误导后续 LLM）？
4. **反幻觉**：new_cards / updates 是否都来自本章正文的显式描写，而非推测演绎？
5. **canon 保护**：updates 是否试图改 canon（name/type/role/外貌/口吻/人设/能力/深层设计/effect/rank）？若有必须打回——只能改动态字段。
6. **克制**：是否把一句话带过的路人/杂物写成卡？次要实体允许留白。

若本章无新实体无变化（空数组）→ 只要反幻觉无失即放行。

各项全通过 → 回复「无问题」；否则逐条列出问题 + 改法。"""


def entity_discover_prompt(state, chapter_context: str = "") -> str:
    """组装章末「实体发现 + 动态更新」生成提示词。

    Args:
        state: NovelState 或 ChapterEditSubState，需含 total_chapters_written / entity_cards。
        chapter_context: build_chapter_context(state) 产出的本章正文（章末 current_draft 已被
            前序 discover 步骤覆盖，不可靠，故本章正文从 chapter_context 读）。
    """
    chapter_num = state.total_chapters_written
    existing_roster = _format_existing_roster(state.entity_cards)
    chapter_draft = chapter_context or "（本章正文缺失）"
    return ENTITY_DISCOVER_PROMPT.format(
        chapter_num=chapter_num,
        existing_roster=existing_roster,
        chapter_draft=chapter_draft,
    )


# ── Phase-1 结构化卡司 → 人物档案 markdown（取代原 character_profiles 散文注入）─────

def format_character_profiles_from_cards(cards: list, *, deep: bool = False) -> str:
    """把卡库里的人物卡（type=人物）渲染成【人物档案】markdown，取代原 character_profiles 散文。

    两档视图治上下文膨胀（原 bible 每次全量灌，这里默认有界）：
    - deep=False（默认，写正文/常规 context）：操作视图——role/外貌/口吻/性格/能力/动机/处境/关系。
    - deep=True（outline/arc/consistency 规划）：追加深层视图——隐藏人设/四卷弧光/底牌契约
      （这些按 role 条件触发，次要/非战斗角色可留空，空值不渲染标签行）。
    非人物卡忽略（装备/物品走 format_equipment_for_context）。
    """
    if not cards:
        return ""
    blocks: list[str] = []
    for card in cards:
        get = (lambda k: card.get(k, "")) if isinstance(card, dict) else (lambda k: getattr(card, k, ""))
        if _text(get("type")) != "人物":
            continue
        aliases = get("aliases") or []
        alias_str = f"（{'/'.join(aliases)}）" if aliases else ""
        lines = [
            f"- **{get('name')}〔{_text(get('role'))}〕{alias_str}**",
            f"  - 定位:{get('summary')} ｜ 外貌:{get('appearance')} ｜ 口吻:{get('speech_style')}",
            f"  - 性格:{get('personality')} ｜ 能力:{get('abilities')}",
            f"  - 动机:{get('motivation')} ｜ 处境:{get('current_state')} ｜ 关系:{get('relations')}",
        ]
        if deep:
            # 深层字段现按 role 条件触发（次要/非战斗角色可留空）——空值跳过，
            # 不渲染「隐藏人设:」这类空标签行污染 outline/consistency 上下文。
            if _text(get("hidden_persona")):
                lines.append(f"  - 隐藏人设:{get('hidden_persona')}")
            if _text(get("arc_trajectory")):
                lines.append(f"  - 四卷弧光:{get('arc_trajectory')}")
            if _text(get("ability_contract")):
                lines.append(f"  - 底牌契约:{get('ability_contract')}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


# Phase-1 结构化卡司审核 prompt（取代原 bible 的 CHARACTER_PROFILES_REVIEW_PROMPT）。
# 静态常量，不含题材 flavor——卡司配额/双层人设/落体系/深层设计的合规检查与题材无关。
CHARACTER_CARDS_REVIEW_PROMPT = """请审核以下 Phase-1「全套核心人物卡（结构化 JSON）」草稿。这是全书卡司的一次性建卡，标准从严。

【草稿】
{draft}

---

## 逐项检查（发现任何一项不合格都要指出，并给出改法）

1. **JSON 合法性**：能否解析为顶层 dict、含 `new_cards`(list)？每张卡字段齐全（name/type/aliases/summary/first_appear_chapter + 人物段）？
2. **卡司配额**：是否覆盖主角 1 / 核心配角 3-5 / 功能性反派 2-3 / 根源反派 1 / 感情线 1-2？主角是否唯一？有无工具人凑数？
3. **role 合法**：每张人物卡是否给了 `role`，且是主角/主要配角/功能性反派/根源反派/感情线角色/次要角色之一？
4. **双层人设（按需）**：该写 `hidden_persona` 的角色（主角/根源反派/关键反转角色）是否写了、其余角色是否**没硬凑**？避免「全员藏秘密/藏铁证」式套路化雷同；写了的两层不冲突、可后期反转。
5. **能力落体系**：`abilities` / `ability_contract` 是否归属【力量体系】的层级/流派，初始锚点与四卷天花板都落在境界阶梯上，未越界自造？
6. **四卷弧光 + 底牌契约（按需）**：`arc_trajectory`（四卷心性/立场/认知迭代大势，反派含阶段作用+闭环退场）核心角色是否完整？`ability_contract` 只对**战力相关的关键角色**查完整（初始锚点+四卷天花板+隐藏杀手锏触发/反噬）；非战斗/次要/纯功能角色**不应**硬塞契约。
7. **关系闭环**：`relations` 是否围绕主角构建、无游离孤点？
8. **反派分层**：功能性反派与根源反派是否区分，动机根源/阶段作用/闭环退场是否清晰？
9. **外貌基线**：`appearance` 是否给了体貌基线（身形/气质/年龄段/大致长相，供正文外貌一致），而非只有单个配饰/印记？
10. **说话风格差异**：全卡司 `speech_style` 是否拉开差异、有足够健谈/外放角色带动对话？主角是否未被写成寡言话少？是否避免全员冷/沉默？
11. **命名**：是否避开烂大街网文姓（叶/萧/林/楚/苏/慕容）与生僻拗口字？配角彼此区分得开、语域贴世界观？（血缘同姓属正常，不算撞名）

---

逐条判定：条件字段（`hidden_persona` / `ability_contract`）按角色定位「该有则查、不该有别硬凑」，不是缺一即死。若全部通过，直接回复「无问题」；否则逐条列出问题并给改法。"""


__all__ = [
    "CHARACTER_CARDS_REVIEW_PROMPT",
    "ENTITY_CARDS_PROMPT",
    "ENTITY_CARDS_REVIEW_PROMPT",
    "ENTITY_DISCOVER_PROMPT",
    "ENTITY_DISCOVER_REVIEW_PROMPT",
    "ENTITY_TYPES",
    "UPDATABLE_FIELDS",
    "entity_cards_prompt",
    "entity_discover_prompt",
    "format_cards_for_chapter_prompt",
    "format_character_profiles_from_cards",
    "format_equipment_for_context",
    "normalize_entity_name",
    "resolve_owner",
]
