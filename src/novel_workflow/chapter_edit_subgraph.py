"""Chapter-edit subgraph: encapsulates all chapter-level user intervention nodes."""

from __future__ import annotations

from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph

from noval_workflow.nodes.chapter_edit import (
    chapter_edit_arc_confirm,
    chapter_edit_arc_direction,
    chapter_edit_arc_rewrite,
    chapter_edit_done,
    chapter_edit_menu,
    chapter_edit_titles_confirm,
    chapter_edit_titles_regen,
    prepare_chapter_edit_character_relations,
    prepare_chapter_edit_character_status,
    prepare_chapter_edit_foreshadowing,
    prepare_chapter_edit_phase_summary,
    route_after_arc_confirm,
    route_after_titles_confirm,
    route_chapter_edit_entry,
    route_chapter_edit_tracking_next,
    route_chapter_edit_tracking_or_done,
    save_chapter_edit_character_relations,
    save_chapter_edit_character_status,
    save_chapter_edit_foreshadowing,
    save_chapter_edit_phase_summary,
)
from noval_workflow.subgraph import review_subgraph


@dataclass
class ChapterEditSubState:
    # ── 从父图读入（字段名与 NovelState 重叠，自动映射）────────────────

    # Phase 0 基础输入（build_foundation_context 需要）
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""

    # Phase 1 成果（build_foundation_context 需要）
    core_theme: str = ""
    world_building: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""

    # Phase 2 章节追踪（只读）
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)

    # Phase 2.5 弧线（读入 + 写回）
    current_arc_outline: str = ""
    arc_outline_history: list[str] = field(default_factory=list)

    # Phase 2.5 动态状态库（读入最新快照 + 写回追加）
    character_status_history: list[str] = field(default_factory=list)
    character_relations_history: list[str] = field(default_factory=list)
    foreshadowing_history: list[str] = field(default_factory=list)
    phase_summary_history: list[str] = field(default_factory=list)

    # review_subgraph 桥接字段（字段名与 ReviewSubState 完全一致）
    system_context: str = ""
    task_prompt: str = ""
    current_draft: str = ""
    review_feedback: str = ""
    approved: bool = False
    review_type: str = "foundation"
    review_history: list = field(default_factory=list)

    # ── 子图私有中间状态（不写回父图）──────────────────────────────────
    do_arc: bool = False
    arc_direction: str = ""
    ai_arc: str = ""
    arc_error: str = ""
    final_arc: str = ""
    arc_needs_rewrite: bool = False
    ai_titles: list[str] = field(default_factory=list)
    titles_direction: str = ""
    titles_needs_regen: bool = False
    tracking_fields: list[str] = field(default_factory=list)
    edit_tracking_cursor: int = 0


# ── 子图组装 ──────────────────────────────────────────────────────────────────

_builder = StateGraph(ChapterEditSubState)

_builder.add_node("chapter_edit_menu", chapter_edit_menu)
_builder.add_node("chapter_edit_arc_direction", chapter_edit_arc_direction)
_builder.add_node("chapter_edit_arc_rewrite", chapter_edit_arc_rewrite)
_builder.add_node("chapter_edit_arc_confirm", chapter_edit_arc_confirm)
_builder.add_node("chapter_edit_titles_regen", chapter_edit_titles_regen)
_builder.add_node("chapter_edit_titles_confirm", chapter_edit_titles_confirm)
_builder.add_node("chapter_edit_done", chapter_edit_done)

_builder.add_node("prepare_chapter_edit_character_status", prepare_chapter_edit_character_status)
_builder.add_node("review_chapter_edit_character_status", review_subgraph)
_builder.add_node("save_chapter_edit_character_status", save_chapter_edit_character_status)

_builder.add_node("prepare_chapter_edit_character_relations", prepare_chapter_edit_character_relations)
_builder.add_node("review_chapter_edit_character_relations", review_subgraph)
_builder.add_node("save_chapter_edit_character_relations", save_chapter_edit_character_relations)

_builder.add_node("prepare_chapter_edit_foreshadowing", prepare_chapter_edit_foreshadowing)
_builder.add_node("review_chapter_edit_foreshadowing", review_subgraph)
_builder.add_node("save_chapter_edit_foreshadowing", save_chapter_edit_foreshadowing)

_builder.add_node("prepare_chapter_edit_phase_summary", prepare_chapter_edit_phase_summary)
_builder.add_node("review_chapter_edit_phase_summary", review_subgraph)
_builder.add_node("save_chapter_edit_phase_summary", save_chapter_edit_phase_summary)

# ── 边 ────────────────────────────────────────────────────────────────────────

_builder.set_entry_point("chapter_edit_menu")

_CHAPTER_EDIT_TRACKING_TARGETS = {
    "chapter_edit_arc_direction": "chapter_edit_arc_direction",
    "prepare_chapter_edit_character_status": "prepare_chapter_edit_character_status",
    "prepare_chapter_edit_character_relations": "prepare_chapter_edit_character_relations",
    "prepare_chapter_edit_foreshadowing": "prepare_chapter_edit_foreshadowing",
    "prepare_chapter_edit_phase_summary": "prepare_chapter_edit_phase_summary",
    "chapter_edit_done": "chapter_edit_done",
}
_builder.add_conditional_edges("chapter_edit_menu", route_chapter_edit_entry, _CHAPTER_EDIT_TRACKING_TARGETS)

# arc flow
_builder.add_edge("chapter_edit_arc_direction", "chapter_edit_arc_rewrite")
_builder.add_edge("chapter_edit_arc_rewrite", "chapter_edit_arc_confirm")

_AFTER_ARC_CONFIRM_TARGETS = {
    "chapter_edit_arc_rewrite": "chapter_edit_arc_rewrite",
    "chapter_edit_titles_regen": "chapter_edit_titles_regen",
    "prepare_chapter_edit_character_status": "prepare_chapter_edit_character_status",
    "prepare_chapter_edit_character_relations": "prepare_chapter_edit_character_relations",
    "prepare_chapter_edit_foreshadowing": "prepare_chapter_edit_foreshadowing",
    "prepare_chapter_edit_phase_summary": "prepare_chapter_edit_phase_summary",
    "chapter_edit_done": "chapter_edit_done",
}
_builder.add_conditional_edges("chapter_edit_arc_confirm", route_after_arc_confirm, _AFTER_ARC_CONFIRM_TARGETS)

_builder.add_edge("chapter_edit_titles_regen", "chapter_edit_titles_confirm")

_TRACKING_OR_DONE_TARGETS = {
    "prepare_chapter_edit_character_status": "prepare_chapter_edit_character_status",
    "prepare_chapter_edit_character_relations": "prepare_chapter_edit_character_relations",
    "prepare_chapter_edit_foreshadowing": "prepare_chapter_edit_foreshadowing",
    "prepare_chapter_edit_phase_summary": "prepare_chapter_edit_phase_summary",
    "chapter_edit_done": "chapter_edit_done",
}
_AFTER_TITLES_CONFIRM_TARGETS = {
    "chapter_edit_titles_regen": "chapter_edit_titles_regen",
    **_TRACKING_OR_DONE_TARGETS,
}
_builder.add_conditional_edges(
    "chapter_edit_titles_confirm", route_after_titles_confirm, _AFTER_TITLES_CONFIRM_TARGETS
)

# tracking field loops
_builder.add_edge("prepare_chapter_edit_character_status", "review_chapter_edit_character_status")
_builder.add_edge("review_chapter_edit_character_status", "save_chapter_edit_character_status")
_builder.add_conditional_edges(
    "save_chapter_edit_character_status", route_chapter_edit_tracking_next, _TRACKING_OR_DONE_TARGETS
)

_builder.add_edge("prepare_chapter_edit_character_relations", "review_chapter_edit_character_relations")
_builder.add_edge("review_chapter_edit_character_relations", "save_chapter_edit_character_relations")
_builder.add_conditional_edges(
    "save_chapter_edit_character_relations", route_chapter_edit_tracking_next, _TRACKING_OR_DONE_TARGETS
)

_builder.add_edge("prepare_chapter_edit_foreshadowing", "review_chapter_edit_foreshadowing")
_builder.add_edge("review_chapter_edit_foreshadowing", "save_chapter_edit_foreshadowing")
_builder.add_conditional_edges(
    "save_chapter_edit_foreshadowing", route_chapter_edit_tracking_next, _TRACKING_OR_DONE_TARGETS
)

_builder.add_edge("prepare_chapter_edit_phase_summary", "review_chapter_edit_phase_summary")
_builder.add_edge("review_chapter_edit_phase_summary", "save_chapter_edit_phase_summary")
_builder.add_conditional_edges(
    "save_chapter_edit_phase_summary", route_chapter_edit_tracking_next, _TRACKING_OR_DONE_TARGETS
)

# chapter_edit_done → END（子图出口）
_builder.add_edge("chapter_edit_done", END)

chapter_edit_subgraph = _builder.compile()
