"""Factory for generic chapter-edit step subgraphs.

Each step follows the pattern:
  step_entry (interrupt: "是否执行？")
    ↓ skip → END
    ↓ yes
  [step_direction (interrupt)] ← optional, when ask_direction=True
    ↓
  step_prepare → step_generate
    ↓
  [step_llm_review] ← optional, when enable_llm_review=True
    ↓ pass / max reached
  step_human_review (interrupt)
    ↓ approved → step_save → END
    ↓ not approved → step_generate (loop)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.state import ReviewSubState, reset_review_fields
from noval_workflow.subgraph import (
    generate,
    llm_self_review,
    human_review,
    route_after_llm_review,
    route_after_human,
)

# Shared with arc_edit_subgraph — imported there to avoid divergence.
_SKIP_WORDS = {"skip", "跳过", "", "s", "no", "n", "否", "不"}


@dataclass
class EditStepSubState(ReviewSubState):
    """State for a single edit step subgraph.

    Inherits all ReviewSubState fields. Additional fields carry parent-graph
    context needed by prepare_fn / save_fn.
    """
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""
    core_theme: str = ""
    world_building: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)
    current_arc_outline: str = ""
    arc_outline_history: list[str] = field(default_factory=list)
    character_status_history: list[str] = field(default_factory=list)
    character_relations_history: list[str] = field(default_factory=list)
    foreshadowing_history: list[str] = field(default_factory=list)
    phase_summary_history: list[str] = field(default_factory=list)
    review_history: list = field(default_factory=list)

    # Step gate fields (not written back to parent graph)
    step_execute_gate: bool = False
    step_direction_input: str = ""


def make_edit_step_subgraph(
    *,
    entry_prompt: str,
    prepare_fn: Callable,
    save_fn: Callable,
    enable_llm_review: bool = True,
    llm_review_max: int = 3,
    ask_direction: bool = False,
):
    """Build and compile a single chapter-edit step subgraph.

    Args:
        entry_prompt:      Text shown in the entry interrupt ("是否执行本步骤？")
        prepare_fn:        Receives state; returns dict with system_context,
                           task_prompt, review_type (and any other overrides).
        save_fn:           Receives state; writes current_draft back to the
                           appropriate history field; returns a dict.
        enable_llm_review: Whether to run LLM self-review after generation.
        llm_review_max:    Max LLM review rounds before forcing human review.
        ask_direction:     If True, interrupt after entry to collect a direction
                           string before calling prepare_fn.
    """

    # ── node closures ──────────────────────────────────────────────────────────

    def step_entry(state: EditStepSubState) -> dict:
        answer = interrupt({"message": entry_prompt})
        execute = str(answer).strip().lower() not in _SKIP_WORDS
        return {"step_execute_gate": execute, "step_direction_input": ""}

    def step_direction(state: EditStepSubState) -> dict:
        direction = interrupt({"message": "请输入调整方向（直接回车使用默认提示词）："})
        return {"step_direction_input": str(direction).strip()}

    def step_prepare(state: EditStepSubState) -> dict:
        result = prepare_fn(state)
        return {**reset_review_fields(), **result, "llm_review_max": llm_review_max}

    def step_save(state: EditStepSubState) -> dict:
        return save_fn(state)

    # ── routing ────────────────────────────────────────────────────────────────

    def route_after_entry(state: EditStepSubState) -> str:
        if not state.step_execute_gate:
            return END
        return "step_direction" if ask_direction else "step_prepare"

    # ── graph assembly ─────────────────────────────────────────────────────────

    builder = StateGraph(EditStepSubState)

    builder.add_node("step_entry", step_entry)
    if ask_direction:
        builder.add_node("step_direction", step_direction)
    builder.add_node("step_prepare", step_prepare)
    builder.add_node("step_generate", generate)
    if enable_llm_review:
        builder.add_node("step_llm_review", llm_self_review)
    builder.add_node("step_human_review", human_review)
    builder.add_node("step_save", step_save)

    builder.set_entry_point("step_entry")

    # entry → skip (END) or continue
    if ask_direction:
        builder.add_conditional_edges(
            "step_entry", route_after_entry, {END: END, "step_direction": "step_direction"}
        )
        builder.add_edge("step_direction", "step_prepare")
    else:
        builder.add_conditional_edges(
            "step_entry", route_after_entry, {END: END, "step_prepare": "step_prepare"}
        )

    builder.add_edge("step_prepare", "step_generate")

    if enable_llm_review:
        builder.add_edge("step_generate", "step_llm_review")
        builder.add_conditional_edges(
            "step_llm_review",
            route_after_llm_review,
            {"generate": "step_generate", "human_review": "step_human_review"},
        )
    else:
        builder.add_edge("step_generate", "step_human_review")

    # approved → step_save; feedback → step_generate (loop)
    builder.add_conditional_edges(
        "step_human_review",
        route_after_human,
        {END: "step_save", "generate": "step_generate"},
    )

    builder.add_edge("step_save", END)

    return builder.compile()
