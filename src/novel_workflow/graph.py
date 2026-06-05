"""Novel Writing Workflow — full graph assembly."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from noval_workflow.nodes.arc import (
    ask_update_tracking,
    prepare_arc_outline,
    prepare_character_relations,
    prepare_character_status,
    prepare_foreshadowing,
    prepare_phase_summary,
    route_tracking_entry,
    route_tracking_next,
    save_arc_outline,
    save_character_relations,
    save_character_status,
    save_foreshadowing,
    save_phase_summary,
)
from noval_workflow.nodes.chapter import (
    ask_chapter_edit,
    ask_continue,
    generate_summary,
    prepare_chapter,
    prepare_titles,
    route_chapter_or_continue,
    route_continue_or_end,
    save_chapter,
    save_titles,
)
from noval_workflow.nodes.foundation import (
    prepare_character_profiles,
    prepare_core_conflicts,
    prepare_core_theme,
    prepare_overall_outline,
    prepare_world_building,
    save_character_profiles,
    save_core_conflicts,
    save_core_theme,
    save_overall_outline,
    save_world_building,
)
from noval_workflow.nodes.inputs import collect_user_inputs
from noval_workflow.state import NovelState
from noval_workflow.subgraph import review_subgraph

builder = StateGraph(NovelState)

# Phase 0
builder.add_node("collect_user_inputs", collect_user_inputs)

# Phase 1 — prepare nodes
builder.add_node("prepare_core_theme", prepare_core_theme)
builder.add_node("prepare_world_building", prepare_world_building)
builder.add_node("prepare_core_conflicts", prepare_core_conflicts)
builder.add_node("prepare_overall_outline", prepare_overall_outline)
builder.add_node("prepare_character_profiles", prepare_character_profiles)

# Phase 1 — review subgraphs (same compiled subgraph, different node names)
builder.add_node("review_core_theme", review_subgraph)
builder.add_node("review_world_building", review_subgraph)
builder.add_node("review_core_conflicts", review_subgraph)
builder.add_node("review_overall_outline", review_subgraph)
builder.add_node("review_character_profiles", review_subgraph)

# Phase 1 — save nodes
builder.add_node("save_core_theme", save_core_theme)
builder.add_node("save_world_building", save_world_building)
builder.add_node("save_core_conflicts", save_core_conflicts)
builder.add_node("save_overall_outline", save_overall_outline)
builder.add_node("save_character_profiles", save_character_profiles)

# Phase 2.5 — arc outline
builder.add_node("prepare_arc_outline", prepare_arc_outline)
builder.add_node("review_arc_outline", review_subgraph)
builder.add_node("save_arc_outline", save_arc_outline)

# Phase 2 — titles
builder.add_node("prepare_titles", prepare_titles)
builder.add_node("review_titles", review_subgraph)
builder.add_node("save_titles", save_titles)

# Phase 2.5 — dynamic tracking
builder.add_node("ask_update_tracking", ask_update_tracking)

builder.add_node("prepare_character_status", prepare_character_status)
builder.add_node("review_character_status", review_subgraph)
builder.add_node("save_character_status", save_character_status)

builder.add_node("prepare_character_relations", prepare_character_relations)
builder.add_node("review_character_relations", review_subgraph)
builder.add_node("save_character_relations", save_character_relations)

builder.add_node("prepare_foreshadowing", prepare_foreshadowing)
builder.add_node("review_foreshadowing", review_subgraph)
builder.add_node("save_foreshadowing", save_foreshadowing)

builder.add_node("prepare_phase_summary", prepare_phase_summary)
builder.add_node("review_phase_summary", review_subgraph)
builder.add_node("save_phase_summary", save_phase_summary)

# Phase 2 — chapter loop
builder.add_node("prepare_chapter", prepare_chapter)
builder.add_node("review_chapter", review_subgraph)
builder.add_node("save_chapter", save_chapter)
builder.add_node("generate_summary", generate_summary)
builder.add_node("ask_chapter_edit", ask_chapter_edit)
builder.add_node("ask_continue", ask_continue)

# ── edges ──────────────────────────────────────────────────────────────────────

builder.set_entry_point("collect_user_inputs")
builder.add_edge("collect_user_inputs", "prepare_core_theme")

# Phase 1 chain
builder.add_edge("prepare_core_theme", "review_core_theme")
builder.add_edge("review_core_theme", "save_core_theme")
builder.add_edge("save_core_theme", "prepare_world_building")

builder.add_edge("prepare_world_building", "review_world_building")
builder.add_edge("review_world_building", "save_world_building")
builder.add_edge("save_world_building", "prepare_core_conflicts")

builder.add_edge("prepare_core_conflicts", "review_core_conflicts")
builder.add_edge("review_core_conflicts", "save_core_conflicts")
builder.add_edge("save_core_conflicts", "prepare_overall_outline")

builder.add_edge("prepare_overall_outline", "review_overall_outline")
builder.add_edge("review_overall_outline", "save_overall_outline")
builder.add_edge("save_overall_outline", "prepare_character_profiles")

builder.add_edge("prepare_character_profiles", "review_character_profiles")
builder.add_edge("review_character_profiles", "save_character_profiles")

# Phase 1 → Phase 2.5: arc outline first
builder.add_edge("save_character_profiles", "prepare_arc_outline")

# Phase 2.5 — arc outline chain
builder.add_edge("prepare_arc_outline", "review_arc_outline")
builder.add_edge("review_arc_outline", "save_arc_outline")
builder.add_edge("save_arc_outline", "prepare_titles")

# Phase 2 — titles chain
builder.add_edge("prepare_titles", "review_titles")
builder.add_edge("review_titles", "save_titles")
builder.add_edge("save_titles", "ask_update_tracking")

# Phase 2.5 — tracking: entry router dispatches to first requested field or chapter
builder.add_conditional_edges(
    "ask_update_tracking",
    route_tracking_entry,
    {
        "prepare_character_status": "prepare_character_status",
        "prepare_character_relations": "prepare_character_relations",
        "prepare_foreshadowing": "prepare_foreshadowing",
        "prepare_phase_summary": "prepare_phase_summary",
        "prepare_chapter": "prepare_chapter",
    },
)

# character_status loop
builder.add_edge("prepare_character_status", "review_character_status")
builder.add_edge("review_character_status", "save_character_status")
builder.add_conditional_edges(
    "save_character_status",
    route_tracking_next,
    {
        "prepare_character_status": "prepare_character_status",
        "prepare_character_relations": "prepare_character_relations",
        "prepare_foreshadowing": "prepare_foreshadowing",
        "prepare_phase_summary": "prepare_phase_summary",
        "prepare_chapter": "prepare_chapter",
    },
)

# character_relations loop
builder.add_edge("prepare_character_relations", "review_character_relations")
builder.add_edge("review_character_relations", "save_character_relations")
builder.add_conditional_edges(
    "save_character_relations",
    route_tracking_next,
    {
        "prepare_character_status": "prepare_character_status",
        "prepare_character_relations": "prepare_character_relations",
        "prepare_foreshadowing": "prepare_foreshadowing",
        "prepare_phase_summary": "prepare_phase_summary",
        "prepare_chapter": "prepare_chapter",
    },
)

# foreshadowing loop
builder.add_edge("prepare_foreshadowing", "review_foreshadowing")
builder.add_edge("review_foreshadowing", "save_foreshadowing")
builder.add_conditional_edges(
    "save_foreshadowing",
    route_tracking_next,
    {
        "prepare_character_status": "prepare_character_status",
        "prepare_character_relations": "prepare_character_relations",
        "prepare_foreshadowing": "prepare_foreshadowing",
        "prepare_phase_summary": "prepare_phase_summary",
        "prepare_chapter": "prepare_chapter",
    },
)

# phase_summary loop
builder.add_edge("prepare_phase_summary", "review_phase_summary")
builder.add_edge("review_phase_summary", "save_phase_summary")
builder.add_conditional_edges(
    "save_phase_summary",
    route_tracking_next,
    {
        "prepare_character_status": "prepare_character_status",
        "prepare_character_relations": "prepare_character_relations",
        "prepare_foreshadowing": "prepare_foreshadowing",
        "prepare_phase_summary": "prepare_phase_summary",
        "prepare_chapter": "prepare_chapter",
    },
)

# Phase 2 — chapter loop
builder.add_edge("prepare_chapter", "review_chapter")
builder.add_edge("review_chapter", "save_chapter")
builder.add_edge("save_chapter", "generate_summary")
builder.add_edge("generate_summary", "ask_chapter_edit")
builder.add_conditional_edges(
    "ask_chapter_edit",
    route_chapter_or_continue,
    {"prepare_chapter": "prepare_chapter", "ask_continue": "ask_continue"},
)
builder.add_conditional_edges(
    "ask_continue",
    route_continue_or_end,
    {"prepare_arc_outline": "prepare_arc_outline", END: END},
)

graph = builder.compile(name="Novel Writing Workflow")
