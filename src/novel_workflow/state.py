"""State for the simple review workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkflowState:
    """Global state passed between nodes."""

    user_input: str = ""       # what the user wants to generate
    llm_output: str = ""       # what the LLM produced
    human_feedback: str = ""   # reviewer's feedback (empty = approved)
