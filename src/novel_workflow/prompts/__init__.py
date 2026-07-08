"""提示词包：按题材加载的提示词系统。

对外统一入口：
- get_prompt_pack(genre)：按 state.genre 加载 PromptPack（创作类提示词）
- 共享常量/审核提示词/台账函数/伏笔工具：所有题材通用，直接 re-export

import 路径 noval_workflow.prompts 与改造前的单文件一致，旧调用点对共享名继续可用。
"""

from noval_workflow.prompts.base import (
    ARC_CHAPTER_FORMAT,
    SUMMARY_PROMPT,
    GenreFlavor,
    PromptPack,
    evolved_directives_block,
)
from noval_workflow.prompts.ledger import (
    _format_foreshadowing_for_context,
    _migrate_legacy_foreshadowing,
    _prune_collected_foreshadowing,
    character_relations_prompt,
    character_status_prompt,
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
from noval_workflow.prompts.review_shared import (
    ARC_OUTLINE_REVIEW_PROMPT,
    CHAPTER_REVIEW_PROMPT,
    CHARACTER_PROFILES_REVIEW_PROMPT,
    CHARACTER_RELATIONS_REVIEW_PROMPT,
    CHARACTER_STATUS_REVIEW_PROMPT,
    CONSISTENCY_AUDIT_PROMPT,
    CONSISTENCY_AUDIT_SYSTEM_PROMPT,
    CORE_CONFLICTS_REVIEW_PROMPT,
    CORE_THEME_REVIEW_PROMPT,
    FORESHADOW_PRUNE_ANALYSIS_PROMPT,
    FORESHADOWING_REVIEW_PROMPT,
    OVERALL_OUTLINE_REVIEW_PROMPT,
    PHASE_SUMMARY_REVIEW_PROMPT,
    TITLES_REVIEW_PROMPT,
    WORLD_BUILDING_REVIEW_PROMPT,
)

__all__ = [
    # 提示词包系统
    "get_prompt_pack",
    "available_genres",
    "PromptPack",
    "GenreFlavor",
    "evolved_directives_block",
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
    "CORE_CONFLICTS_REVIEW_PROMPT",
    "OVERALL_OUTLINE_REVIEW_PROMPT",
    "CHARACTER_PROFILES_REVIEW_PROMPT",
    "TITLES_REVIEW_PROMPT",
    "CHAPTER_REVIEW_PROMPT",
    "ARC_OUTLINE_REVIEW_PROMPT",
    "CHARACTER_STATUS_REVIEW_PROMPT",
    "CHARACTER_RELATIONS_REVIEW_PROMPT",
    "FORESHADOWING_REVIEW_PROMPT",
    "PHASE_SUMMARY_REVIEW_PROMPT",
    "FORESHADOW_PRUNE_ANALYSIS_PROMPT",
    "CONSISTENCY_AUDIT_SYSTEM_PROMPT",
    "CONSISTENCY_AUDIT_PROMPT",
    # 台账类提示词函数
    "character_status_prompt",
    "character_relations_prompt",
    "foreshadowing_prompt",
    "initial_status_prompt",
    "phase_summary_prompt",
    # 伏笔工具函数
    "_format_foreshadowing_for_context",
    "_migrate_legacy_foreshadowing",
    "_prune_collected_foreshadowing",
]
