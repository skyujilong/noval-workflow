"""Phase 2.5: Mini arc outline + dynamic tracking nodes and routers."""

from __future__ import annotations

from langgraph.types import interrupt

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.prompts import (
    arc_outline_prompt,
    character_relations_prompt,
    character_status_prompt,
    foreshadowing_prompt,
    phase_summary_prompt,
)
from noval_workflow.state import NovelState, reset_review_fields

# The canonical order in which tracking fields are processed.
_TRACKING_ORDER = [
    "character_status",
    "character_relations",
    "foreshadowing",
    "phase_summary",
]

_VALID_TRACKING_FIELDS = set(_TRACKING_ORDER)


# ── arc outline ───────────────────────────────────────────────────────────────

def prepare_arc_outline(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": arc_outline_prompt(state),
        "review_type": "arc_outline",
        **reset_review_fields(),
    }


def save_arc_outline(state: NovelState) -> dict:
    return {
        "current_arc_outline": state.current_draft,
        "arc_outline_history": [state.current_draft],
    }


# ── tracking: ask & route ─────────────────────────────────────────────────────

def ask_update_tracking(state: NovelState) -> dict:
    """Interrupt to ask which tracking fields the user wants to update this batch.

    User may:
    - Enter a comma-separated list of field names, e.g. "character_status, foreshadowing"
    - Enter field numbers from the menu, e.g. "1,3"
    - Enter "skip" / "跳过" / empty string to skip all
    Valid names: character_status, character_relations, foreshadowing, phase_summary
    """
    answer = interrupt(
        {
            "message": (
                "请选择本批需要更新的动态状态字段（多选用逗号分隔，或输入编号）：\n"
                "  1. character_status   — 人物动态状态\n"
                "  2. character_relations — 人物关系/势力格局\n"
                "  3. foreshadowing      — 伏笔台账\n"
                "  4. phase_summary      — 阶段固化数据\n"
                "输入 'skip' 或直接回车跳过全部。"
            ),
        }
    )

    raw = str(answer).strip().lower()

    # Skip signals
    if raw in {"skip", "跳过", "", "s", "no", "n"}:
        return {"tracking_fields_to_update": [], "tracking_cursor": 0}

    # Map numeric shortcuts to field names
    _NUM_MAP = {
        "1": "character_status",
        "2": "character_relations",
        "3": "foreshadowing",
        "4": "phase_summary",
    }

    selected: list[str] = []
    for token in raw.replace("，", ",").split(","):
        token = token.strip()
        if token in _NUM_MAP:
            selected.append(_NUM_MAP[token])
        elif token in _VALID_TRACKING_FIELDS:
            selected.append(token)
        # silently ignore unrecognised tokens

    # Deduplicate while preserving _TRACKING_ORDER
    ordered = [f for f in _TRACKING_ORDER if f in selected]
    return {"tracking_fields_to_update": ordered, "tracking_cursor": 0}


def _next_tracking_node(state: NovelState) -> str:
    """Return the name of the next prepare_* node to visit, or 'prepare_chapter'."""
    remaining = state.tracking_fields_to_update[state.tracking_cursor:]
    for field in _TRACKING_ORDER:
        if field in remaining:
            return f"prepare_{field}"
    return "prepare_chapter"


def route_tracking_entry(state: NovelState) -> str:
    """Conditional edge after ask_update_tracking."""
    return _next_tracking_node(state)


def route_tracking_next(state: NovelState) -> str:
    """Conditional edge after each save_<tracking_field> node."""
    return _next_tracking_node(state)


# ── character_status ──────────────────────────────────────────────────────────

def prepare_character_status(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_status_prompt(state, build_chapter_context(state)),
        "review_type": "character_status",
        **reset_review_fields(),
    }


def save_character_status(state: NovelState) -> dict:
    return {
        "character_status_history": [state.current_draft],
        "tracking_cursor": state.tracking_cursor + 1,
    }


# ── character_relations ───────────────────────────────────────────────────────

def prepare_character_relations(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_relations_prompt(state, build_chapter_context(state)),
        "review_type": "character_relations",
        **reset_review_fields(),
    }


def save_character_relations(state: NovelState) -> dict:
    return {
        "character_relations_history": [state.current_draft],
        "tracking_cursor": state.tracking_cursor + 1,
    }


# ── foreshadowing ─────────────────────────────────────────────────────────────

def prepare_foreshadowing(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": foreshadowing_prompt(state, build_chapter_context(state)),
        "review_type": "foreshadowing",
        **reset_review_fields(),
    }


def save_foreshadowing(state: NovelState) -> dict:
    return {
        "foreshadowing_history": [state.current_draft],
        "tracking_cursor": state.tracking_cursor + 1,
    }


# ── phase_summary ─────────────────────────────────────────────────────────────

def prepare_phase_summary(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": phase_summary_prompt(state, build_chapter_context(state)),
        "review_type": "phase_summary",
        **reset_review_fields(),
    }


def save_phase_summary(state: NovelState) -> dict:
    return {
        "phase_summary_history": [state.current_draft],
        "tracking_cursor": state.tracking_cursor + 1,
    }
