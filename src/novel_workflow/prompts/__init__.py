"""提示词包：按题材加载的提示词系统。

对外统一入口：
- get_prompt_pack(genre)：按 state.genre 加载 PromptPack（创作类提示词）
- 共享常量/审核提示词/台账函数/伏笔工具：所有题材通用，直接 re-export

import 路径 noval_workflow.prompts 与改造前的单文件一致，旧调用点对共享名继续可用。
"""

from noval_workflow.prompts.base import (
    ARC_CHAPTER_FORMAT,
    EVOLVED_DIRECTIVES_FIELDS,
    SUMMARY_PROMPT,
    GenreFlavor,
    PromptPack,
    evolved_directives_block,
    evolved_field_for,
    get_evolved_directives,
)
from noval_workflow.prompts.ledger import (
    _format_foreshadowing_for_context,
    foreshadowing_prompt,
    initial_status_prompt,
    phase_summary_prompt,
)
from noval_workflow.prompts.evolution import (
    CurrentPrompt,
    DistillResult,
    ReconcileResult,
    RefinedItem,
    distill,
    reconcile,
    refine_to_items,
)
from noval_workflow.prompts.evolution_store import (
    DirectiveItem,
    EvolutionEvent,
    Proposal,
    init_db,
)
from noval_workflow.prompts.overrides import (
    apply_overrides,
    load_overrides,
    save_overrides,
)
from noval_workflow.prompts.registry import available_genres, get_prompt_pack
from noval_workflow.prompts.scene_beats import (
    ALL_DEVICE_TAGS,
    SCENE_BEATS_PROMPT,
    SCENE_BEATS_REVIEW_PROMPT,
    format_beats_for_chapter_prompt,
    scene_beats_prompt,
    validate_beats,
)
from noval_workflow.prompts.entity_cards import (
    CHARACTER_CARDS_REVIEW_PROMPT,
    ENTITY_CARDS_PROMPT,
    ENTITY_CARDS_REVIEW_PROMPT,
    ENTITY_DISCOVER_PROMPT,
    ENTITY_DISCOVER_REVIEW_PROMPT,
    ENTITY_TYPES,
    UPDATABLE_FIELDS,
    entity_cards_prompt,
    entity_discover_prompt,
    format_cards_for_chapter_prompt,
    format_character_profiles_from_cards,
    format_equipment_for_context,
    normalize_entity_name,
    resolve_owner,
)
from noval_workflow.prompts.review_shared import (
    ARC_OUTLINE_REVIEW_PROMPT,
    CHAPTER_PLAN_REVIEW_PROMPT,
    CHAPTER_REVIEW_PROMPT,
    CONSISTENCY_AUDIT_PROMPT,
    CONSISTENCY_AUDIT_SYSTEM_PROMPT,
    CONSISTENCY_REVISE_PROMPT,
    CONSISTENCY_REVISE_SYSTEM_PROMPT,
    CORE_CONFLICTS_REVIEW_PROMPT,
    CORE_THEME_REVIEW_PROMPT,
    FORESHADOW_PRUNE_ANALYSIS_PROMPT,
    FORESHADOWING_REVIEW_PROMPT,
    OVERALL_OUTLINE_REVIEW_PROMPT,
    PHASE_SUMMARY_REVIEW_PROMPT,
    POWER_SYSTEM_REVIEW_PROMPT,
    TITLES_REVIEW_PROMPT,
    VOLUMES_REVIEW_PROMPT,
    WORLD_BUILDING_REVIEW_PROMPT,
)

__all__ = [
    # 提示词包系统
    "get_prompt_pack",
    "available_genres",
    "PromptPack",
    "GenreFlavor",
    "evolved_directives_block",
    "evolved_field_for",
    "get_evolved_directives",
    "EVOLVED_DIRECTIVES_FIELDS",
    # 按小说提示词覆盖
    "load_overrides",
    "apply_overrides",
    "save_overrides",
    # 提示词自进化（提炼 / 精炼入库 / 中央存储）
    "distill",
    "refine_to_items",
    "reconcile",
    "CurrentPrompt",
    "DistillResult",
    "RefinedItem",
    "ReconcileResult",
    "init_db",
    "EvolutionEvent",
    "DirectiveItem",
    "Proposal",
    # 共享常量
    "SUMMARY_PROMPT",
    "ARC_CHAPTER_FORMAT",
    # 审核提示词
    "CORE_THEME_REVIEW_PROMPT",
    "WORLD_BUILDING_REVIEW_PROMPT",
    "POWER_SYSTEM_REVIEW_PROMPT",
    "CORE_CONFLICTS_REVIEW_PROMPT",
    "OVERALL_OUTLINE_REVIEW_PROMPT",
    "VOLUMES_REVIEW_PROMPT",
    "CHARACTER_CARDS_REVIEW_PROMPT",
    "TITLES_REVIEW_PROMPT",
    "CHAPTER_REVIEW_PROMPT",
    "ARC_OUTLINE_REVIEW_PROMPT",
    "CHAPTER_PLAN_REVIEW_PROMPT",
    "FORESHADOWING_REVIEW_PROMPT",
    "PHASE_SUMMARY_REVIEW_PROMPT",
    "FORESHADOW_PRUNE_ANALYSIS_PROMPT",
    "CONSISTENCY_AUDIT_SYSTEM_PROMPT",
    "CONSISTENCY_AUDIT_PROMPT",
    "CONSISTENCY_REVISE_SYSTEM_PROMPT",
    "CONSISTENCY_REVISE_PROMPT",
    # scene beats（章级节拍表）
    "SCENE_BEATS_PROMPT",
    "SCENE_BEATS_REVIEW_PROMPT",
    "ALL_DEVICE_TAGS",
    "scene_beats_prompt",
    "format_beats_for_chapter_prompt",
    "validate_beats",
    # 章前登场实体卡（EntityCard：人物/物品/装备/势力/地点）+ 章末实体发现/更新
    # + Phase-1 结构化卡司审核 + 人物档案/装备/owner 渲染
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
    # 台账类提示词函数
    "foreshadowing_prompt",
    "initial_status_prompt",
    "phase_summary_prompt",
    # 伏笔工具函数
    "_format_foreshadowing_for_context",
]
