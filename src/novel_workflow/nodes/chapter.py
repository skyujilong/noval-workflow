"""Phase 2: Chapter writing loop nodes and routers."""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import interrupt

from noval_workflow.context import (
    build_chapter_context,
    build_foundation_context,
    chapter_filename,
    get_output_dir,
)
from noval_workflow.llm import get_llm
from noval_workflow.prompts import SUMMARY_PROMPT, chapter_prompt, titles_prompt
from noval_workflow.state import NovelState, reset_review_fields

_logger = logging.getLogger(__name__)


def _clean_title(line: str) -> str:
    """Strip common LLM numbering prefixes (1. / 1) / 1、/ - ) from a title line."""
    line = re.sub(r'^\d+[\.）\)\uff0e\u3001]\s*', '', line)
    return line.lstrip('-– ').strip()


# ── titles ────────────────────────────────────────────────────────────────────

def prepare_titles(state: NovelState) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": titles_prompt(state.all_chapter_titles, build_chapter_context(state)),
        "review_type": "titles",
        **reset_review_fields(),
    }


def save_titles(state: NovelState) -> dict:
    """Parse titles from current_draft (one per line), stripping LLM numbering prefixes."""
    lines = [_clean_title(l) for l in state.current_draft.strip().splitlines() if l.strip()]
    new_titles = [l for l in lines if l][:5]

    if not new_titles:
        raise ValueError(f"LLM returned no valid titles. Raw draft:\n{state.current_draft}")

    return {
        # reducer (operator.add) appends these to all_chapter_titles
        "all_chapter_titles": new_titles,
        "current_batch_titles": new_titles,
        "current_chapter_index": 0,
    }


# ── chapter ───────────────────────────────────────────────────────────────────

def prepare_chapter(state: NovelState) -> dict:
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index]
    chapter_context = build_chapter_context(state)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": chapter_prompt(title, chapter_num, state.all_chapter_titles, chapter_context),
        "review_type": "chapter",
        **reset_review_fields(),
    }


def save_chapter(state: NovelState) -> dict:
    """Write the approved chapter to the chapters/ subdirectory.

    NOTE: current_draft is intentionally NOT cleared here.
    generate_summary (the next node) reads it to produce the chapter summary.
    """
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index]

    chapters_dir = get_output_dir(state.novel_name) / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    filename = chapters_dir / chapter_filename(chapter_num, title)

    try:
        filename.write_text(
            f"第{chapter_num}章：{title}\n\n{state.current_draft}",
            encoding="utf-8",
        )
    except OSError as e:
        _logger.error(
            "Failed to write chapter %d file %s: %s. "
            "Chapter content will not be available for context window.",
            chapter_num, filename, e,
        )

    return {
        "current_chapter_index": state.current_chapter_index + 1,
        "total_chapters_written": chapter_num,
    }


def generate_summary(state: NovelState) -> dict:
    """Call LLM to summarize the just-approved chapter; save to summaries/ dir.

    Reads current_draft which is still populated from the approved chapter
    (save_chapter does not clear it).

    LLM failures are caught and logged; an empty summary is returned so the
    graph can continue. ChatOpenAI's built-in retry (max_retries=2) handles
    transient network errors before this handler is reached.
    """
    chapter_num = state.total_chapters_written   # already incremented by save_chapter
    title = state.all_chapter_titles[chapter_num - 1]

    summary = ""
    try:
        llm = get_llm(temperature=0.3)
        messages = [
            SystemMessage(content=state.system_context),
            HumanMessage(content=SUMMARY_PROMPT.format(title=title, content=state.current_draft)),
        ]
        result = llm.invoke(messages)
        summary = result.content.strip()
    except Exception as e:
        _logger.error(
            "Failed to generate summary for chapter %d after all retries: %s. "
            "An empty summary will be stored; context window for subsequent chapters may be degraded.",
            chapter_num, e,
        )

    if summary:
        summaries_dir = get_output_dir(state.novel_name) / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        filename = summaries_dir / chapter_filename(chapter_num, title)
        try:
            filename.write_text(summary, encoding="utf-8")
        except OSError as e:
            _logger.error("Failed to write summary file %s: %s", filename, e)

    # Always append (even empty string) to keep all_chapter_summaries index
    # aligned with all_chapter_titles (index N-1 == chapter N).
    return {"all_chapter_summaries": [summary]}


# ── continue decision ─────────────────────────────────────────────────────────

def ask_continue(state: NovelState) -> dict:
    """Interrupt to ask if the user wants to write the next batch of 5 chapters."""
    answer = interrupt(
        {
            "message": f"已完成 {state.total_chapters_written} 章。继续写下5章？(yes/no)",
            "total_chapters_written": state.total_chapters_written,
        }
    )
    return {"continue_writing": str(answer).strip().lower() in {"yes", "y", "是", "继续"}}


# ── routers ───────────────────────────────────────────────────────────────────

def route_chapter_or_continue(state: NovelState) -> str:
    if state.current_chapter_index < len(state.current_batch_titles):
        return "prepare_chapter"
    return "ask_continue"


def route_continue_or_end(state: NovelState) -> str:
    if state.continue_writing:
        return "prepare_titles"
    return END
