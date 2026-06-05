"""Phase 1: Foundation setup nodes (10 nodes: 5 prepare + 5 save)."""

from __future__ import annotations

from noval_workflow.context import build_foundation_context
from noval_workflow.prompts import (
    CHARACTER_PROFILES_PROMPT,
    CORE_CONFLICTS_PROMPT,
    CORE_THEME_PROMPT,
    OVERALL_OUTLINE_PROMPT,
    WORLD_BUILDING_PROMPT,
)
from noval_workflow.state import NovelState, reset_review_fields


# ── prepare nodes ─────────────────────────────────────────────────────────────

def prepare_core_theme(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": CORE_THEME_PROMPT,
        "review_type": "core_theme",
        **reset_review_fields(),
    }


def prepare_world_building(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": WORLD_BUILDING_PROMPT,
        "review_type": "world_building",
        **reset_review_fields(),
    }


def prepare_core_conflicts(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": CORE_CONFLICTS_PROMPT,
        "review_type": "core_conflicts",
        **reset_review_fields(),
    }


def prepare_overall_outline(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": OVERALL_OUTLINE_PROMPT,
        "review_type": "overall_outline",
        **reset_review_fields(),
    }


def prepare_character_profiles(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": CHARACTER_PROFILES_PROMPT,
        "review_type": "character_profiles",
        **reset_review_fields(),
    }


# ── save nodes ────────────────────────────────────────────────────────────────

def save_core_theme(state: NovelState) -> dict:
    return {"core_theme": state.current_draft}


def save_world_building(state: NovelState) -> dict:
    return {"world_building": state.current_draft}


def save_core_conflicts(state: NovelState) -> dict:
    return {"core_conflicts": state.current_draft}


def save_overall_outline(state: NovelState) -> dict:
    return {"overall_outline": state.current_draft}


def save_character_profiles(state: NovelState) -> dict:
    return {"character_profiles": state.current_draft}
