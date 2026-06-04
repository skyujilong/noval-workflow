import operator
from dataclasses import dataclass, field
from typing import Annotated


@dataclass
class ReviewSubState:
    system_context: str = ""    # foundation context as system prompt text
    task_prompt: str = ""       # what to generate (set by parent's prepare node)
    current_draft: str = ""     # live draft being iterated
    review_feedback: str = ""   # LLM or human feedback (empty = no issues / approved)
    approved: bool = False      # True when human approves
    review_type: str = "foundation"  # selects review prompt: "foundation" | "titles" | "chapter"
    review_history: list = field(default_factory=list)
    # list[dict], each entry: {"role": "human"|"ai", "content": str}
    # Managed by generate(); capped at _HISTORY_MAX_ROUNDS rounds (2 msgs/round)


@dataclass
class NovelState:
    # User inputs (Phase 0)
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""

    # Shared bridge fields (name-matched with ReviewSubState)
    system_context: str = ""
    task_prompt: str = ""
    current_draft: str = ""
    review_feedback: str = ""
    approved: bool = False
    review_type: str = "foundation"  # selects review prompt: "foundation" | "titles" | "chapter"

    # Foundation results (Phase 1 - each saved after approval)
    core_theme: str = ""
    world_building: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""

    # Chapter tracking (Phase 2)
    current_batch_titles: list[str] = field(default_factory=list)
    # LangGraph >= 1.2 honours Annotated reducers on dataclasses; operator.add appends batches
    all_chapter_titles: Annotated[list[str], operator.add] = field(default_factory=list)
    all_chapter_summaries: Annotated[list[str], operator.add] = field(default_factory=list)
    current_chapter_index: int = 0   # index into current_batch_titles; resets to 0 each batch
    total_chapters_written: int = 0
    continue_writing: bool = True


def reset_review_fields() -> dict:
    """Return a dict that clears the shared review bridge fields."""
    return {"current_draft": "", "review_feedback": "", "approved": False, "review_history": []}
