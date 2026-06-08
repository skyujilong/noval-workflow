"""Chapter-edit subgraph: 5-step serial chain after chapter generation.

Topology (zero conditional branches at this level):
  arc_step → status_step → relations_step → foreshadow_step → phase_step
  → chapter_edit_done → END

Each *_step is a pre-compiled subgraph that internally asks the user
"是否执行？" before doing anything. The user can skip any step by answering
"否" / "no" / pressing Enter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph

from noval_workflow.arc_edit_subgraph import make_arc_edit_subgraph
from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.edit_step_subgraph import make_edit_step_subgraph
from noval_workflow.nodes.chapter_edit import chapter_edit_done
from noval_workflow.prompts import (
    character_relations_prompt,
    character_status_prompt,
    foreshadowing_prompt,
    phase_summary_prompt,
)

# ── ChapterEditSubState ────────────────────────────────────────────────────────

@dataclass
class ChapterEditSubState:
    """Bridge state between the parent NovelState and the 5 edit-step subgraphs.

    Fields are a union of all fields consumed by the subgraphs.
    Removed: do_arc, tracking_fields, edit_tracking_cursor, pending_steps,
             active_tracking_field (all menu/dispatcher artefacts).
    """

    # ── Phase 0 基础输入 ────────────────────────────────────────────────────────
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""

    # ── Phase 1 成果 ────────────────────────────────────────────────────────────
    core_theme: str = ""
    world_building: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""

    # ── Phase 2 章节追踪（只读）─────────────────────────────────────────────────
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)

    # ── Phase 2.5 弧线（读入 + 写回）──────────────────────────────────────────
    current_arc_outline: str = ""
    arc_outline_history: list[str] = field(default_factory=list)

    # ── Phase 2.5 动态状态库（读入最新快照 + 写回追加）────────────────────────
    character_status_history: list[str] = field(default_factory=list)
    character_relations_history: list[str] = field(default_factory=list)
    foreshadowing_history: list[str] = field(default_factory=list)
    phase_summary_history: list[str] = field(default_factory=list)

    # ── review_subgraph 桥接字段 ────────────────────────────────────────────────
    system_context: str = ""
    task_prompt: str = ""
    current_draft: str = ""
    review_feedback: str = ""
    approved: bool = False
    review_type: str = "foundation"
    review_history: list = field(default_factory=list)
    llm_review_count: int = 0
    llm_review_max: int = 3

    # ── 弧线子图私有中间状态（保留，由 arc_edit_subgraph 读写）─────────────────
    arc_direction: str = ""
    ai_arc: str = ""
    arc_error: str = ""
    final_arc: str = ""
    arc_needs_rewrite: bool = False
    ai_titles: list[str] = field(default_factory=list)
    titles_direction: str = ""
    titles_needs_regen: bool = False


# ── prepare / save closures for the 4 tracking steps ─────────────────────────

def _prepare_status(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_status_prompt(state, build_chapter_context(state)),
        "review_type": "character_status",
    }


def _save_status(state) -> dict:
    return {"character_status_history": [state.current_draft]} if state.current_draft else {}


def _prepare_relations(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_relations_prompt(state, build_chapter_context(state)),
        "review_type": "character_relations",
    }


def _save_relations(state) -> dict:
    return {"character_relations_history": [state.current_draft]} if state.current_draft else {}


def _prepare_foreshadowing(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": foreshadowing_prompt(state, build_chapter_context(state)),
        "review_type": "foreshadowing",
    }


def _save_foreshadowing(state) -> dict:
    return {"foreshadowing_history": [state.current_draft]} if state.current_draft else {}


def _prepare_phase(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": phase_summary_prompt(state, build_chapter_context(state)),
        "review_type": "phase_summary",
    }


def _save_phase(state) -> dict:
    return {"phase_summary_history": [state.current_draft]} if state.current_draft else {}


# ── Pre-compile the 5 step subgraphs ──────────────────────────────────────────

_ARC_STEP = make_arc_edit_subgraph(entry_prompt="是否调整弧线大纲？")

_STATUS_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新人物动态状态？",
    prepare_fn=_prepare_status,
    save_fn=_save_status,
    enable_llm_review=True,
    llm_review_max=3,
)

_RELATIONS_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新人物关系/势力格局？",
    prepare_fn=_prepare_relations,
    save_fn=_save_relations,
    enable_llm_review=True,
    llm_review_max=3,
)

_FORESHADOW_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新伏笔台账？",
    prepare_fn=_prepare_foreshadowing,
    save_fn=_save_foreshadowing,
    enable_llm_review=True,
    llm_review_max=3,
)

_PHASE_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新阶段固化数据？",
    prepare_fn=_prepare_phase,
    save_fn=_save_phase,
    enable_llm_review=True,
    llm_review_max=3,
)


# ── Top-level chapter_edit_subgraph: 7 nodes, 0 conditional branches ──────────

_builder = StateGraph(ChapterEditSubState)

_builder.add_node("arc_step", _ARC_STEP)
_builder.add_node("status_step", _STATUS_STEP)
_builder.add_node("relations_step", _RELATIONS_STEP)
_builder.add_node("foreshadow_step", _FORESHADOW_STEP)
_builder.add_node("phase_step", _PHASE_STEP)
_builder.add_node("chapter_edit_done", chapter_edit_done)

_builder.set_entry_point("arc_step")

_builder.add_edge("arc_step", "status_step")
_builder.add_edge("status_step", "relations_step")
_builder.add_edge("relations_step", "foreshadow_step")
_builder.add_edge("foreshadow_step", "phase_step")
_builder.add_edge("phase_step", "chapter_edit_done")
_builder.add_edge("chapter_edit_done", END)

chapter_edit_subgraph = _builder.compile()
