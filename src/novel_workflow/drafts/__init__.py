"""LLM 出 JSON 的 review draft 契约层——pydantic BaseModel 定义每种 review_type 的 schema。

与 state.py 的关系：
- state.py 定义**落库后**的运行时数据模型（dataclass，NovelState/EntityCard/Volume 等）
- 本模块定义**审核期**的 LLM 输出契约（pydantic，用于字段级校验 + 校验失败回喂重试）

设计原则：
1. **fail-fast**：str 字段不做 dict→拼句静默收敛，pydantic 直接 ValidationError → invoke_pydantic
   回喂 LLM 修正。这样 LLM 输出漂移会被立刻发现、不会脏进 checkpoint。
2. **1:1 抄 prompt 契约**：字段名/类型严格对齐 `_REVIEW_PROMPTS` 里写死的 JSON 示例，
   避免"prompt 说一套、schema 校验另一套"引起 LLM 永远校验不过的死循环。
3. **不改 state**：draft 通过校验后 model_dump_json 回写 str current_draft，state schema 不动。
"""

from noval_workflow.drafts.schemas import (
    BeatDraft,
    CharacterCardDraft,
    CharacterCardsDraft,
    ChapterPlanItemDraft,
    EntityCardDraft,
    EntityCardsDraft,
    EntityDiscoverDraft,
    ForeshadowCollectedEntry,
    ForeshadowEntry,
    ForeshadowingDraft,
    ItemCardDraft,
    ReturningEntry,
    SimpleEntityDraft,
    VolumeActiveDraft,
    VolumeCastDraft,
    VolumePlanningDraft,
    VolumesDraft,
)

__all__ = [
    "BeatDraft",
    "CharacterCardDraft",
    "CharacterCardsDraft",
    "ChapterPlanItemDraft",
    "EntityCardDraft",
    "EntityCardsDraft",
    "EntityDiscoverDraft",
    "ForeshadowCollectedEntry",
    "ForeshadowEntry",
    "ForeshadowingDraft",
    "ItemCardDraft",
    "ReturningEntry",
    "SimpleEntityDraft",
    "VolumeActiveDraft",
    "VolumeCastDraft",
    "VolumePlanningDraft",
    "VolumesDraft",
]
