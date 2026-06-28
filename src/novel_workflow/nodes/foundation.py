"""Phase 1: Foundation setup nodes (10 nodes: 5 prepare + 5 save)."""

from __future__ import annotations

import json

from noval_workflow.context import build_foundation_context, get_output_dir
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.state import NovelState, reset_review_fields


# ── prepare nodes ─────────────────────────────────────────────────────────────

def prepare_core_theme(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.core_theme_prompt,
        "review_type": "core_theme",
        **reset_review_fields(),
    }


def prepare_world_building(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.world_building_prompt,
        "review_type": "world_building",
        **reset_review_fields(),
    }


def prepare_core_conflicts(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.core_conflicts_prompt,
        "review_type": "core_conflicts",
        **reset_review_fields(),
    }


def prepare_overall_outline(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.overall_outline_prompt(state.total_word_count),
        "review_type": "overall_outline",
        **reset_review_fields(),
    }


def prepare_character_profiles(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.character_profiles_prompt,
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


def save_config(state: NovelState) -> dict:
    """Persist foundation-phase state to <output_dir>/config.json before chapter writing."""
    output_dir = get_output_dir(state.novel_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "novel_name": state.novel_name,
        "genre": state.genre,
        "writing_style": state.writing_style,
        "target_audience": state.target_audience,
        "core_tone": state.core_tone,
        "chapter_word_count": state.chapter_word_count,
        "total_word_count": state.total_word_count,
        "core_theme": state.core_theme,
        "world_building": state.world_building,
        "core_conflicts": state.core_conflicts,
        "overall_outline": state.overall_outline,
        "character_profiles": state.character_profiles,
    }

    config_path = output_dir / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {}
