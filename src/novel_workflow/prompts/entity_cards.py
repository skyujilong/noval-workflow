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

from typing import TYPE_CHECKING

from noval_workflow.prompts.base import _extract_arc_chapter_block
from noval_workflow.prompts.scene_beats import format_beats_for_chapter_prompt

if TYPE_CHECKING:
    from noval_workflow.state import EntityCard, NovelState


# 合法 type 枚举——save/review 拿它做校验，与 state.EntityCard.type 注释同步。
ENTITY_TYPES = ("人物", "物品", "装备", "势力", "地点")


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
  "appearance": "【人物】外貌锚点（≤40字，非人物留空）",
  "speech_style": "【人物】说话风格/口吻/口头禅（≤30字，非人物留空）",
  "personality": "【人物】性格（非人物留空）",
  "motivation": "【人物】当前动机/目标（非人物留空）",
  "relations": "【人物】与主角/他人关系（非人物留空）",
  "abilities": "【人物】能力底牌，须落【力量体系】框架（非人物留空）",
  "owner": "【物品/装备】归属人（非物品留空）",
  "effect": "【物品/装备】效果/能力（非物品留空）",
  "status": "【物品/装备】当前状态:完好/损坏/消耗/遗失（非物品留空）",
  "rank": "【物品/装备】品阶/等级,须落力量体系（非物品留空）"
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
   框架，禁止自造新体系。"""


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
{{"cast": ["张三", "灵剑"], "new_cards": [{{"name": "张三", "type": "人物", "aliases": ["三哥"], "summary": "...", "first_appear_chapter": {chapter_num}, "appearance": "...", "speech_style": "...", "personality": "...", "motivation": "...", "relations": "...", "abilities": "...", "owner": "", "effect": "", "status": "", "rank": ""}}]}}
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
        etype = card.get("type", "") if isinstance(card, dict) else getattr(card, "type", "")
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
        lines.append(f"- **{name}〔{etype}〕{alias_str}**\n{detail}")
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
    """把卡库里 type∈{装备,物品} 且未退场的卡渲染成 markdown，作为装备/物品全局真源注入。

    phase_summary 已移除【装备/道具】字段，装备真源改由本函数从 EntityCard 渲染——所有下游
    （写正文/一致性审计）看到的是同一份卡库真源，消除双源。已遗失/已消耗的物品不再注入。
    """
    if not cards:
        return ""
    lines: list[str] = []
    for card in cards:
        get = (lambda k: card.get(k, "")) if isinstance(card, dict) else (lambda k: getattr(card, k, ""))
        if get("type") not in ("装备", "物品"):
            continue
        if (get("status") or "").strip() in _RETIRED_STATUS:
            continue
        owner = f" ｜ 归属:{get('owner')}" if get("owner") else ""
        status = f" ｜ 状态:{get('status')}" if get("status") else ""
        rank = f" ｜ 品阶:{get('rank')}" if get("rank") else ""
        lines.append(f"- **{get('name')}**：{get('effect') or get('summary')}{owner}{status}{rank}")
    return "\n".join(lines)


# ── 章末「实体发现 + 动态更新」提示词（读已写正文，补新卡 + 更新已有卡动态字段）──────

# 章末 update 只允许改这几个「动态字段」——核心设定（name/type/appearance/speech_style/
# abilities 上限）canon 锁定禁止改，save 端也只 apply 这几个键（代码层兜底）。
UPDATABLE_FIELDS = ("status", "owner", "motivation")

_ENTITY_DISCOVER_TEMPLATE = """请根据**本章已写正文**，对实体卡库做两件事：① 发现正文里新冒出、卡库还没有的实体并建卡；② 更新已有卡的**动态字段**（装备状态/归属、人物动机）。

【本章号】第 {chapter_num} 章

【已有实体卡库】
{existing_roster}

【本章正文】
{chapter_draft}

---

## 任务

1. **发现新实体**：正文里出现、【已有实体卡库】里没有的有名有戏份的人物/物品/装备/势力 → 建完整卡（字段规范同下）。
2. **更新已有卡动态字段**：正文里已有实体发生的**动态变化**——装备易主(`owner`)/损坏消耗(`status`)、人物动机转变(`motivation`)。

__CARD_SPEC_DISCOVER__

## 输出格式（严格 JSON 对象，无 markdown 围栏）

```
{{"new_cards": [ /* 新实体完整卡，无则空数组 */ ], "updates": [ /* 已有卡动态变更，无则空数组 */ {{"name": "灵剑", "owner": "李四", "status": "损坏"}} ]}}
```

- `updates` 每条必须含 `name`（定位已有卡），其余只能是 status/owner/motivation 之一或多个。
- **禁止改**已有卡的核心设定（name/type/外貌/口吻/能力上限）——那些是 canon，只能改动态字段。
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

1. **JSON 合法性**：顶层 dict、含 `new_cards`(list) + `updates`(list)？每张 new_card 字段齐全、type 合法（人物/物品/装备/势力/地点）？每条 update 含 name 且只改 status/owner/motivation？
2. **反幻觉**：new_cards / updates 是否都来自本章正文的显式描写，而非推测演绎？
3. **canon 保护**：updates 是否试图改已有卡的核心设定（外貌/口吻/能力上限/name/type）？若有必须打回——只能改动态字段。
4. **克制**：是否把一句话带过的路人/杂物写成卡？次要实体允许留白。

若本章无新实体无变化（空数组）→ 只要反幻觉无失即放行。

三点全通过 → 回复「无问题」；否则逐条列出问题 + 改法。"""


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


__all__ = [
    "ENTITY_CARDS_PROMPT",
    "ENTITY_CARDS_REVIEW_PROMPT",
    "ENTITY_DISCOVER_PROMPT",
    "ENTITY_DISCOVER_REVIEW_PROMPT",
    "ENTITY_TYPES",
    "UPDATABLE_FIELDS",
    "entity_cards_prompt",
    "entity_discover_prompt",
    "format_cards_for_chapter_prompt",
    "format_equipment_for_context",
    "normalize_entity_name",
]
