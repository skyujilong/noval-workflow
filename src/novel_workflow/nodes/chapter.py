"""Phase 2: Chapter writing loop nodes and routers."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import interrupt

from noval_workflow.config import BATCH_SIZE
from noval_workflow.context import (
    build_chapter_context,
    build_foundation_context,
    chapter_filename,
    get_output_dir,
)
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.llm import get_llm
from noval_workflow.nodes.chapter_edit import _clean_title
from noval_workflow.prompts import SUMMARY_PROMPT, get_prompt_pack
from noval_workflow.state import NovelState, reset_review_fields

_logger = logging.getLogger(__name__)


# ── titles ────────────────────────────────────────────────────────────────────

def prepare_titles(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.titles_prompt(state.all_chapter_titles, build_chapter_context(state)),
        "review_type": "titles",
        **reset_review_fields(),
    }


def save_titles(state: NovelState) -> dict:
    """Parse titles from current_draft (one per line), stripping LLM numbering prefixes.

    Note: all_chapter_titles is NOT appended here. Titles are appended one-by-one
    in generate_summary after each chapter is written. This allows users to modify
    current_batch_titles mid-batch and have changes reflected in all_chapter_titles.
    """
    from noval_workflow.config import BATCH_SIZE
    lines = [_clean_title(l) for l in state.current_draft.strip().splitlines() if l.strip()]
    new_titles = [l for l in lines if l][:BATCH_SIZE]

    if not new_titles:
        raise ValueError(f"LLM returned no valid titles. Raw draft:\n{state.current_draft}")

    return {
        "current_batch_titles": new_titles,
        "current_chapter_index": 0,
    }


# ── chapter ───────────────────────────────────────────────────────────────────

def prepare_chapter(state: NovelState) -> dict:
    chapter_num = state.total_chapters_written + 1
    title = state.current_batch_titles[state.current_chapter_index]
    chapter_context = build_chapter_context(state)
    # Merge historical titles + unwritten portion of current batch for the LLM TOC.
    # all_chapter_titles accumulates one title per chapter via generate_summary, so it
    # already contains the already-written chapters of the current batch. Appending only
    # current_batch_titles[current_chapter_index:] (the not-yet-written portion) avoids
    # duplicate entries in the numbered list rendered for the LLM.
    merged_titles = state.all_chapter_titles + state.current_batch_titles[state.current_chapter_index:]
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.chapter_prompt(title, chapter_num, merged_titles, chapter_context),
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

    Also appends the chapter title to all_chapter_titles here (one per chapter),
    so that mid-batch edits to current_batch_titles are reflected correctly.
    save_chapter already incremented current_chapter_index, so the title is at
    current_chapter_index - 1.
    """
    chapter_num = state.total_chapters_written   # already incremented by save_chapter
    # Title comes from current_batch_titles (not all_chapter_titles) so user edits
    # made via ask_chapter_edit are picked up correctly.
    title = state.current_batch_titles[state.current_chapter_index - 1]

    summary = ""
    try:
        llm = get_llm(temperature=0.3, label="chapter_summary")
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

    # Append the chapter title to all_chapter_titles (one per chapter, so mid-batch
    # title edits are reflected). Also append the summary (even if empty) to keep
    # all_chapter_summaries index aligned with all_chapter_titles (index N-1 == chapter N).
    return {
        "all_chapter_titles": [title],
        "all_chapter_summaries": [summary],
    }


# ── continue decision ─────────────────────────────────────────────────────────

_CONTINUE_SIGNALS = {"", "yes", "y", "是", "继续"}


def ask_continue(state: NovelState) -> dict:
    """Interrupt to ask if the user wants to write the next batch of chapters."""
    answer = interrupt(
        {
            "type": InterruptType.ASK_CONTINUE.value,
            "message": (
                f"已完成 {state.total_chapters_written} 章。\n\n"
                "---\n"
                f"· 直接回车 / 输入 yes / 是 / 继续 → 继续写下{BATCH_SIZE}章\n"
                "· 输入 no / 否 → 停止"
            ),
            "total_chapters_written": state.total_chapters_written,
        }
    )
    # 处理 None，避免 str(None) = "None" 导致停止
    answer_str = str(answer or "").strip().lower()
    return {"continue_writing": answer_str in _CONTINUE_SIGNALS}


# ── routers ───────────────────────────────────────────────────────────────────

def route_chapter_or_continue(state: NovelState) -> str:
    if state.current_chapter_index < len(state.current_batch_titles):
        return "prepare_chapter"
    return "ask_continue"


def route_continue_or_end(state: NovelState) -> str:
    if state.continue_writing:
        return "prepare_arc_outline"
    return END
