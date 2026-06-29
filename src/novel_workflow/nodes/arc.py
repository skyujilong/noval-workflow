"""Phase 2.5: Mini arc outline nodes."""

from __future__ import annotations

from noval_workflow.context import build_foundation_context
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.state import NovelState, reset_review_fields


# ── arc outline ───────────────────────────────────────────────────────────────

def prepare_arc_outline(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.arc_outline_prompt(state),
        "review_type": "arc_outline",
        **reset_review_fields(),
    }


def save_arc_outline(state: NovelState) -> dict:
    return {
        "current_arc_outline": state.current_draft,
    }
