"""EntityCard 三种 review_type 的 pydantic draft schema（Phase 1）。

覆盖：character_cards（Phase-1 开书建卡）/ entity_cards（章前登场）/ entity_discover（章末补/更新）。
volume_cast 也含 EntityCard 完整卡，Phase 2 再纳入。

关键契约：
- 卡片 str 字段用 pydantic 默认「严格模式」——LLM 出 dict/list 时抛 ValidationError，
  由 invoke_pydantic 回喂让 LLM 修正，不做静默收敛。
- 枚举字段（type / role）沿用 state.py 的 EntityType / CharacterRole，pydantic v2 原生支持
  str→Enum 收敛。
- extra="ignore"：LLM 若吐出跨类脏键（物品卡里塞 role）静默丢弃——与老 parse_card
  「valid_keys 过滤」语义等价，不因脏键把整卡打回 LLM 重生成（那更容易死循环）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from noval_workflow.state import CharacterRole, EntityType, coerce_character_role


class _CardBase(BaseModel):
    """所有卡片变体的共同基类——name/type/aliases/summary/first_appear_chapter。

    `extra="ignore"`：LLM 输出跨类字段（如给物品卡塞 role）不视为错误，与老 parse_card
    的 valid_keys 过滤语义一致；跨类字段被静默丢弃、其他字段照常校验。

    `strict=True` 未启用：pydantic 默认宽松模式对 int/str 少量互转（如 first_appear_chapter
    收到字符串 "3"）能自动收敛，但**对 dict→str 不做收敛**——这正是我们要 fail-fast 的场景。
    """

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    first_appear_chapter: int = 0


class CharacterCardDraft(_CardBase):
    """人物卡 draft——字段与 state.CharacterCard 严格一致，用于 LLM 输出契约校验。

    role 用 coerce_character_role 兜住 LLM「主要配角、感情线角色」这类多重定位——
    与老 parse_card 的收敛逻辑保持行为一致，不当作 LLM 错误回喂（那种漂移是人类可读的
    正确表述，LLM 修正也修不出更好的答案）。
    """

    role: CharacterRole
    appearance: str = ""
    speech_style: str = ""
    personality: str = ""
    abilities: str = ""
    hidden_persona: str = ""
    arc_trajectory: str = ""
    ability_contract: str = ""
    motivation: str = ""
    current_state: str = ""
    relations: str = ""

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, v):
        # 多重定位收敛：「主要配角、感情线角色」→ 优先级排序取最高——与老 parse_card 一致
        if v is None or v == "":
            raise ValueError("role 必填，六枚举之一")
        return coerce_character_role(v)


class ItemCardDraft(_CardBase):
    """物品/装备卡 draft——effect/rank/owner/status 与 state.ItemCard 一致。"""

    effect: str = ""
    rank: str = ""
    owner: str = ""
    status: str = ""


class SimpleEntityDraft(_CardBase):
    """势力/地点卡 draft——只有 standing 一个变体字段。"""

    standing: str = ""


# EntityCard 判别联合：按 type 字段分派——保持与 state.parse_card 一致的行为。
# 这里用「分派函数 + Union」而不是 pydantic Discriminator——因为 CharacterCard 独有
# coerce_character_role 逻辑，用 discriminator 时子类 validator 触发顺序不好控制。
def parse_card_draft(raw: dict) -> _CardBase:
    """按 raw["type"] 分派到具体卡片 draft 变体——LLM 输出 dict → pydantic 实例。

    与 state.parse_card 的分工：本函数只做「draft 层校验」（LLM 输出契约），返回 pydantic
    实例；state.parse_card 做「运行时归一」（dataclass 落库）。两者字段名严格对齐、
    但独立演进——draft 校验失败靠 invoke_pydantic 回喂，state 校验失败 fail-loud。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"卡片必须是对象(dict)，实际类型={type(raw).__name__}")
    raw_type = raw.get("type")
    if raw_type in (None, ""):
        raise ValueError(f"卡片缺 type 字段：{raw!r}")
    try:
        etype = EntityType(raw_type)
    except ValueError as exc:
        valid = "/".join(e.value for e in EntityType)
        raise ValueError(f"type={raw_type!r} 非法，须为 {valid} 之一") from exc

    cls_map: dict[EntityType, type[_CardBase]] = {
        EntityType.CHARACTER: CharacterCardDraft,
        EntityType.ITEM: ItemCardDraft,
        EntityType.EQUIPMENT: ItemCardDraft,
        EntityType.FACTION: SimpleEntityDraft,
        EntityType.LOCATION: SimpleEntityDraft,
    }
    return cls_map[etype].model_validate(raw)


# 判别联合别名——便于类型标注 & 外部 import
EntityCardDraft = _CardBase


# ── Draft 顶层壳：三种 review_type 各一 ────────────────────────────────────────


class _CardsDraftBase(BaseModel):
    """含 new_cards 数组的 draft 基类——共用 new_cards 分派校验逻辑。

    `new_cards: list[_CardBase]` 只是类型标注下限，实际存的是分派后的子类实例
    （CharacterCardDraft / ItemCardDraft / SimpleEntityDraft）。序列化时要用
    `serialize_as_any=True`（或调用方传入）才能按运行时子类 dump 出子类独有字段
    （role/ability_contract/effect/rank/standing 等），否则 pydantic 只按基类 dump。
    invoke_pydantic 的调用方要显式传 serialize_as_any=True，见 subgraph.generate。
    """

    model_config = ConfigDict(extra="ignore")

    new_cards: list[_CardBase] = Field(default_factory=list)

    @field_validator("new_cards", mode="before")
    @classmethod
    def _dispatch_new_cards(cls, v):
        """new_cards 是判别联合数组——每条 raw dict 按 type 分派到具体变体做字段校验。

        必须在 mode="before" 拦截 raw list，否则 pydantic 会用基类 _CardBase 直接
        validate 每一项、丢掉子类独有字段（如 role/appearance）。分派失败时保留 index
        让 ValidationError 定位到具体是第几张卡出问题。
        """
        if not isinstance(v, list):
            raise ValueError(f"new_cards 必须是数组，实际类型={type(v).__name__}")
        out: list[_CardBase] = []
        for idx, item in enumerate(v):
            if isinstance(item, _CardBase):
                out.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError(f"new_cards[{idx}] 必须是对象(dict)")
            try:
                out.append(parse_card_draft(item))
            except ValueError as exc:
                # 用 pydantic 报错时能识别的路径 wrap 上 index，让 loc 里含[idx]
                raise ValueError(f"new_cards[{idx}]: {exc}") from exc
        return out


class CharacterCardsDraft(_CardsDraftBase):
    """Phase-1 开书建全套核心人物卡——draft 顶层 `{"new_cards": [人物卡...]}`。"""


class EntityCardsDraft(_CardsDraftBase):
    """章前登场实体建卡——draft 顶层 `{"cast": [已有实体名], "new_cards": [新卡]}`。"""

    cast: list[str] = Field(default_factory=list)


class CardUpdate(BaseModel):
    """章末动态更新单条——name 是主键，其他都是白名单动态字段（str，可缺省）。

    动态字段允许 extra——LLM 可能只更新 owner 或 current_state 中的一部分，不强求全字段齐；
    但每个字段值必须是 str（同 EntityCard 契约）。
    """

    model_config = ConfigDict(extra="allow")

    name: str


class EntityDiscoverDraft(BaseModel):
    """章末实体发现——draft 顶层 `{"new_cards": [新卡], "updates": [动态更新]}`。

    与 EntityCardsDraft 的差异：多一层 updates（对已有卡的动态字段覆盖），无 cast。
    """

    model_config = ConfigDict(extra="ignore")

    new_cards: list[_CardBase] = Field(default_factory=list)
    updates: list[CardUpdate] = Field(default_factory=list)

    @field_validator("new_cards", mode="before")
    @classmethod
    def _dispatch_new_cards(cls, v):
        if not isinstance(v, list):
            raise ValueError(f"new_cards 必须是数组，实际类型={type(v).__name__}")
        out: list[_CardBase] = []
        for idx, item in enumerate(v):
            if isinstance(item, _CardBase):
                out.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError(f"new_cards[{idx}] 必须是对象(dict)")
            try:
                out.append(parse_card_draft(item))
            except ValueError as exc:
                raise ValueError(f"new_cards[{idx}]: {exc}") from exc
        return out


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2：剩余 5 种 JSON review_type 的 draft schema
# ══════════════════════════════════════════════════════════════════════════════
#
# 覆盖：volume_cast / volumes / chapter_plan / scene_beats / foreshadowing。
# 与 Phase 1 共享同一套「fail-fast + str 严格 + Literal 枚举」的字段级校验精神，
# 由 subgraph.generate 通过 _DRAFT_SCHEMAS（dict 顶层）或 _DRAFT_ITEM_SCHEMAS（list
# 顶层）分派到 invoke_pydantic / invoke_pydantic_list。


# ── volume_cast（卷级花名册）── dict 顶层 ─────────────────────────────────────


class ReturningEntry(BaseModel):
    """本卷返场角色单条——name 必填，role_in_volume 描述该角色在本卷的作用/弧线。

    与 nodes/volume_cast.py::save_volume_cast 里 `returning_clean` 归一后的数据形态严格
    对齐——LLM 直出可能带 aliases/summary 等多余字段，extra="ignore" 全部丢弃。
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    role_in_volume: str = ""


class VolumeCastDraft(BaseModel):
    """卷级花名册——draft 顶层 `{"introducing": [完整卡...], "returning": [...], "focus": "..."}`。

    introducing 复用 Phase 1 的 `_CardBase` 判别联合，走 `_dispatch_new_cards` 同款
    `mode="before"` 分派——LLM 出的完整卡（人物/物品/装备/势力/地点 5 变体）走字段级
    严格校验，`ability_contract`/`effect` 等 str 字段被出成 dict 立即回喂修正。
    """

    model_config = ConfigDict(extra="ignore")

    introducing: list[_CardBase] = Field(default_factory=list)
    returning: list[ReturningEntry] = Field(default_factory=list)
    focus: str = ""

    @field_validator("introducing", mode="before")
    @classmethod
    def _dispatch_introducing(cls, v):
        # 与 _CardsDraftBase._dispatch_new_cards 同款分派逻辑——只是字段名换了 introducing。
        if not isinstance(v, list):
            raise ValueError(f"introducing 必须是数组，实际类型={type(v).__name__}")
        out: list[_CardBase] = []
        for idx, item in enumerate(v):
            if isinstance(item, _CardBase):
                out.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError(f"introducing[{idx}] 必须是对象(dict)")
            try:
                out.append(parse_card_draft(item))
            except ValueError as exc:
                raise ValueError(f"introducing[{idx}]: {exc}") from exc
        return out


# ── volumes（分卷规划，滚动前瞻队列）── dict 顶层 ─────────────────────────────


class _VolumeCommon(BaseModel):
    """卷字段基类——激活卷/草稿卷共有 title/summary/setup_for_next。

    与 state.Volume dataclass 的字段名严格对齐（不含 index/chapter_start/planned_end/
    status/actual_end——那些是 save_volumes 权威赋值，LLM 不出、也不校验）。
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    summary: str = ""
    setup_for_next: str = ""

    @field_validator("title")
    @classmethod
    def _title_non_empty(cls, v: str) -> str:
        # 与 nodes/volumes.py::_parse_active_volume 语义一致：title 空/纯空白也算缺失。
        if not v or not v.strip():
            raise ValueError("title(卷名) 必填且不能为空白")
        return v.strip()


class VolumeActiveDraft(_VolumeCommon):
    """激活卷 draft——首个卷条目，含 chapters（要立即展开的本卷章数）。"""

    chapters: int = Field(gt=0)

    @field_validator("chapters", mode="before")
    @classmethod
    def _no_bool_chapters(cls, v):
        # bool 是 int 子类，pydantic 默认收；但"True 章"是 LLM 常见错，显式拒绝——
        # 与 nodes/volumes.py::_parse_active_volume 的 `isinstance(chapters, bool)` 排除对齐。
        if isinstance(v, bool):
            raise ValueError(
                "chapters(本卷章数) 必须是正整数，禁止用布尔值 True/False"
            )
        return v


class VolumePlanningDraft(_VolumeCommon):
    """草稿卷 draft——前瞻队列里的方向骨架，**不含 chapters**。

    extra="forbid" 严格禁止草稿卷带 chapters——LLM 常见错就是把整卷统一给章数，
    这里直接拒绝并回喂让 LLM 学着分栏输出（激活卷带 chapters、草稿卷不带）。
    """

    model_config = ConfigDict(extra="forbid")


class VolumesDraft(BaseModel):
    """分卷规划 draft——`{"volumes": [激活卷, 草稿1, ...], "human_confirmed"?: bool}`。

    volumes 数组第 1 项走 VolumeActiveDraft、第 2+ 项走 VolumePlanningDraft，与老
    `nodes/volumes.py::_parse_volume_drafts` 语义 1:1 对齐（激活卷含 chapters、
    草稿卷不含）。空数组拒绝。

    human_confirmed 是 review 表单"通过"时前端注入的人工终裁标记（LLM 原样无此字段），
    控激活卷章数是否夹护栏——见 nodes/volumes.py::_clamp_chapters。
    """

    model_config = ConfigDict(extra="ignore")

    volumes: list[_VolumeCommon] = Field(default_factory=list)
    human_confirmed: bool = False

    @field_validator("volumes", mode="before")
    @classmethod
    def _dispatch_volumes(cls, v):
        """按位分派：第 1 项 → VolumeActiveDraft（含 chapters），第 2+ 项 → VolumePlanningDraft。

        必须 mode="before" 拦截 raw list，否则 pydantic 会用基类 _VolumeCommon 直接
        validate、丢掉 chapters；同时草稿卷的 extra="forbid" 也在这一步生效——
        草稿卷位置塞了 chapters 立即被拒绝。
        """
        if not isinstance(v, list):
            raise ValueError(f"volumes 必须是数组，实际类型={type(v).__name__}")
        if not v:
            raise ValueError("volumes 数组不能为空（至少含 1 个激活卷）")
        out: list[_VolumeCommon] = []
        for idx, item in enumerate(v):
            if isinstance(item, _VolumeCommon):
                out.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError(
                    f"volumes[{idx}] 必须是对象(dict)，实际类型={type(item).__name__}"
                )
            try:
                if idx == 0:
                    out.append(VolumeActiveDraft.model_validate(item))
                else:
                    out.append(VolumePlanningDraft.model_validate(item))
            except ValidationError as exc:
                # 保留 index 让上层报错定位到具体第几卷（激活卷 or 草稿卷第 N 项）
                role = "激活卷" if idx == 0 else f"草稿卷(第 {idx + 1} 项)"
                raise ValueError(f"volumes[{idx}]({role}): {exc}") from exc
        return out


# ── chapter_plan（章节规划）── list 顶层 ──────────────────────────────────────


class ChapterPlanItemDraft(BaseModel):
    """章节规划单条 draft——字段与 state.ChapterPlanItem dataclass 严格对齐。

    intensity 有 7 档软枚举（铺垫/缓冲/推进/小转折/大转折/爆发/回落），但历史 checkpoint
    里有空串或方向性词汇——保持 str 而不加 Literal，避免打回死循环；跨 item 的章号
    连续升序校验由 nodes/chapter_plan.py::parse_chapter_plan_items 落库时兜底。
    """

    model_config = ConfigDict(extra="ignore")

    chapter: int = Field(gt=0)
    purpose: str
    key_turn: str
    ending_hook: str
    intensity: str = ""

    @field_validator("chapter", mode="before")
    @classmethod
    def _no_bool_chapter(cls, v):
        # 与 VolumeActiveDraft._no_bool_chapters 同款——bool 是 int 子类需显式拒绝。
        if isinstance(v, bool):
            raise ValueError("chapter(章号) 必须是正整数，禁止用布尔值")
        return v


# ── scene_beats（章内节拍表）── list 顶层 ─────────────────────────────────────

# device_tags 严格枚举——从 prompts/scene_beats.ALL_DEVICE_TAGS 单点定义反出 Literal
# 联合。LLM 出"slap_taunt2"/"高潮爆点"等脏 tag 立即被 pydantic 拒绝、回喂修正；
# 跨 beat 的结构约束（打脸四拍完整性、hook 位置）仍由 validate_beats 兜底。
_DeviceTagLiteral = Literal[
    "slap_taunt",
    "slap_silence",
    "slap_crush",
    "slap_witness",
    "setup",
    "buildup",
    "release",
    "hook_opening",
    "hook_chapter_end",
    "foreshadow_plant",
    "foreshadow_recover",
    "buffer",
]


class BeatDraft(BaseModel):
    """章内 scene beat 单条 draft——字段与 prompts/scene_beats.py 的 prompt 契约对齐。

    goal/obstacle/outcome/cost/emotion_arc 是最容易被 LLM 拆成嵌套 dict 的字段
    （类似 ability_contract 的漂移），严格 str 校验能立刻捕获并回喂。
    device_tags 用 Literal 强枚举——ALL_DEVICE_TAGS 是单点定义的合法集合。
    """

    model_config = ConfigDict(extra="ignore")

    beat_id: int = Field(gt=0)
    scene: str = ""
    goal: str = ""
    obstacle: str = ""
    outcome: str = ""
    cost: str = ""
    emotion_arc: str = ""
    pacing: str = ""
    prose_focus: str = ""
    target_words: str = ""
    device_tags: list[_DeviceTagLiteral] = Field(default_factory=list)

    @field_validator("beat_id", mode="before")
    @classmethod
    def _no_bool_beat_id(cls, v):
        if isinstance(v, bool):
            raise ValueError("beat_id 必须是正整数，禁止用布尔值")
        return v


# ── foreshadowing（伏笔台账）── dict 顶层 ─────────────────────────────────────


class ForeshadowEntry(BaseModel):
    """悬置伏笔单条 draft——字段与 prompts/ledger.py 的 prompt 契约对齐。

    planted_batch 是纯数字（禁字符串"第 1 批"）；freedom 强枚举高/中/低；
    id/name/current_appearance/core_purpose/planned_recovery_range 均严格 str。
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    planted_batch: int = Field(gt=0)
    current_appearance: str
    core_purpose: str
    planned_recovery_range: str
    freedom: Literal["高", "中", "低"]

    @field_validator("planted_batch", mode="before")
    @classmethod
    def _no_bool_batch(cls, v):
        if isinstance(v, bool):
            raise ValueError("planted_batch(埋点批次) 必须是正整数，禁止用布尔值")
        return v


class ForeshadowCollectedEntry(ForeshadowEntry):
    """已收伏笔单条 draft——比 pending 多一个 recovered_at_chapter（回收章号，必填）。"""

    recovered_at_chapter: int = Field(gt=0)

    @field_validator("recovered_at_chapter", mode="before")
    @classmethod
    def _no_bool_recover(cls, v):
        if isinstance(v, bool):
            raise ValueError("recovered_at_chapter(回收章号) 必须是正整数，禁止用布尔值")
        return v


class ForeshadowingDraft(BaseModel):
    """伏笔台账 draft——`{"pending": [...], "collected": [...]}`。

    LLM 偶尔漏 pending 或 collected 一半是合法输入（新书没已收、章末刚回收就没悬置），
    两个字段都 default 为空数组——校验单条 entry 字段是否合规就够了。
    """

    model_config = ConfigDict(extra="ignore")

    pending: list[ForeshadowEntry] = Field(default_factory=list)
    collected: list[ForeshadowCollectedEntry] = Field(default_factory=list)
