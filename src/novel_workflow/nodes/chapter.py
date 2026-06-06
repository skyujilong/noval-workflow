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
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": chapter_prompt(title, chapter_num, merged_titles, chapter_context),
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

    # Append the chapter title to all_chapter_titles (one per chapter, so mid-batch
    # title edits are reflected). Also append the summary (even if empty) to keep
    # all_chapter_summaries index aligned with all_chapter_titles (index N-1 == chapter N).
    return {
        "all_chapter_titles": [title],
        "all_chapter_summaries": [summary],
    }


# ── per-chapter user intervention ─────────────────────────────────────────────

_SKIP_WORDS = {"skip", "跳过", "", "s", "no", "n", "continue", "继续"}
_CHOICE_MAP = {
    "1": "character_status",
    "2": "character_relations",
    "3": "foreshadowing",
    "4": "phase_summary",
}
_TRACKING_HISTORY_MAP = {
    "character_status": "character_status_history",
    "character_relations": "character_relations_history",
    "foreshadowing": "foreshadowing_history",
    "phase_summary": "phase_summary_history",
}
_TRACKING_LABELS = {
    "character_status": "人物动态状态",
    "character_relations": "人物关系/势力格局",
    "foreshadowing": "伏笔台账",
    "phase_summary": "阶段固化数据",
}


def _rewrite_arc_with_ai(state: NovelState, direction: str) -> str:
    """用LLM根据用户方向重写当前批次弧线大纲。"""
    already_written = state.current_batch_titles[:state.current_chapter_index]
    remaining = state.current_batch_titles[state.current_chapter_index:]

    chapter_ctx = build_chapter_context(state)
    chapter_section = f"\n\n【最近章节内容（请据此保持连贯）】\n{chapter_ctx}" if chapter_ctx else ""

    prev_section = (
        f"\n\n【当前弧线大纲（供参考）】\n{state.current_arc_outline}"
        if state.current_arc_outline else ""
    )
    written_section = (
        "\n\n【本批已写章节（不得矛盾）】\n"
        + "\n".join(
            f"{state.total_chapters_written - len(already_written) + i + 1}. {t}"
            for i, t in enumerate(already_written)
        )
    ) if already_written else ""
    remaining_section = (
        "\n\n【本批未写章节（必须覆盖）】\n"
        + "\n".join(
            f"{state.total_chapters_written + i + 1}. {t}"
            for i, t in enumerate(remaining)
        )
    ) if remaining else ""

    prompt = (
        f"请根据以下调整方向，重新规划当前批次的故事弧线大纲。\n\n"
        f"调整方向：{direction}{chapter_section}{prev_section}{written_section}{remaining_section}\n\n"
        f"要求：\n"
        f"- 用200-400字规划剩余章节的核心故事弧线节点\n"
        f"- 必须覆盖所有未写章节的故事走向\n"
        f"- 与已写章节自然衔接，不得矛盾\n"
        f"- 严格体现调整方向的要求\n\n"
        f"请直接输出更新后的弧线大纲，不需要标题。"
    )
    llm = get_llm(temperature=0.7)
    result = llm.invoke([
        SystemMessage(content=state.system_context),
        HumanMessage(content=prompt),
    ])
    return result.content.strip()


def _generate_titles_with_ai(
    state: NovelState, arc_outline: str, direction: str, remaining_count: int
) -> list[str]:
    """用LLM根据新弧线大纲重新生成剩余章节标题。"""
    existing_titles = state.all_chapter_titles + state.current_batch_titles[:state.current_chapter_index]
    existing_section = (
        "\n".join(f"{i+1}. {t}" for i, t in enumerate(existing_titles))
        if existing_titles else "（暂无）"
    )
    chapter_ctx = build_chapter_context(state)
    chapter_section = f"\n\n【最近章节内容（请据此保持情节连贯）】\n{chapter_ctx}" if chapter_ctx else ""

    prompt = (
        f"请根据以下弧线大纲，生成接下来{remaining_count}个章节的标题。\n\n"
        f"【新的弧线大纲】\n{arc_outline}\n\n"
        f"调整方向（供参考）：{direction}{chapter_section}\n\n"
        f"已有章节标题（请勿重复）：\n{existing_section}\n\n"
        f"要求：\n"
        f"- 生成恰好{remaining_count}个标题，每行一个\n"
        f"- 标题简洁有力（4-12字），紧密贴合新弧线大纲\n"
        f"- 不要添加序号、标点或任何前缀\n\n"
        f"请直接输出{remaining_count}个标题，每行一个。"
    )
    llm = get_llm(temperature=0.7)
    result = llm.invoke([
        SystemMessage(content=state.system_context),
        HumanMessage(content=prompt),
    ])
    lines = [_clean_title(l) for l in result.content.strip().splitlines() if l.strip()]
    return [l for l in lines if l][:remaining_count]


def ask_chapter_edit(state: NovelState) -> dict:
    """每章写完后，让用户决策是否调整当前批次的大纲/动态状态。

    Supports multiple interrupt rounds within a single node:
    1. First interrupt: show menu, user selects what to adjust (comma-separated).
    2. For each selected item, a follow-up interrupt collects the new value.
       For 'a': AI rewrites arc outline → user confirms → AI regenerates remaining titles → user confirms.
    Returns a state update dict with only the fields the user actually changed.
    """
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]

    # First interrupt: show menu and current status
    choice = interrupt({
        "message": (
            f"第 {state.total_chapters_written} 章已完成。\n"
            f"当前批次进度：{state.current_chapter_index}/{len(state.current_batch_titles)}\n"
            "可调整项（输入对应编号/字母，多选用逗号分隔，直接回车跳过）：\n"
            "  a  — 调整弧线大纲（AI将同步更新剩余章节标题）\n"
            "  1  — 人物动态状态\n"
            "  2  — 人物关系/势力格局\n"
            "  3  — 伏笔台账\n"
            "  4  — 阶段固化数据\n"
        ),
        "remaining_titles": remaining_titles,
        "arc_outline": state.current_arc_outline,
        "character_status": state.character_status_history[-1] if state.character_status_history else None,
        "character_relations": state.character_relations_history[-1] if state.character_relations_history else None,
        "foreshadowing": state.foreshadowing_history[-1] if state.foreshadowing_history else None,
        "phase_summary": state.phase_summary_history[-1] if state.phase_summary_history else None,
    })

    raw = str(choice).strip().lower()

    if raw in _SKIP_WORDS:
        return {}

    # Parse selections
    selected_tracking: list[str] = []
    do_arc = False

    for token in raw.replace("，", ",").split(","):
        token = token.strip()
        if token == "a":
            do_arc = True
        elif token in _CHOICE_MAP:
            selected_tracking.append(_CHOICE_MAP[token])

    updates: dict = {}

    # Handle arc outline adjustment (AI-assisted, with title regeneration)
    if do_arc:
        # Step 1: collect adjustment direction
        direction_raw = interrupt({
            "message": (
                "请输入弧线大纲调整方向（AI将据此重写大纲并更新剩余章节标题）\n"
                "（直接回车取消本次调整）：\n\n"
                + (
                    f"【当前弧线大纲】\n{state.current_arc_outline}\n\n"
                    if state.current_arc_outline else ""
                )
                + (
                    "【当前剩余章节标题】\n"
                    + "\n".join(
                        f"  {state.current_chapter_index + i + 1}. {t}"
                        for i, t in enumerate(remaining_titles)
                    )
                    if remaining_titles else ""
                )
            ),
            "current_arc_outline": state.current_arc_outline,
            "remaining_titles": remaining_titles,
        })
        direction = str(direction_raw).strip()
        if direction:
            # Step 2: AI rewrites arc outline（含降级）
            try:
                ai_arc = _rewrite_arc_with_ai(state, direction)
            except Exception as e:
                _logger.error("_rewrite_arc_with_ai failed: %s", e)
                fallback_raw = interrupt({
                    "message": (
                        f"⚠️ AI 重写大纲失败（{e}），请手动输入新的弧线大纲\n"
                        "（直接回车跳过本次弧线调整）："
                    ),
                    "error": str(e),
                })
                fallback = str(fallback_raw).strip()
                ai_arc = fallback if fallback else None

            if ai_arc is not None:
                # Step 3: user confirms or overrides arc outline
                arc_confirm_raw = interrupt({
                    "message": (
                        "【AI生成的新弧线大纲】\n"
                        + ai_arc
                        + "\n\n直接回车接受，或输入修改后的完整内容覆盖："
                    ),
                    "ai_generated_arc": ai_arc,
                })
                arc_confirm = str(arc_confirm_raw).strip()
                final_arc = arc_confirm if arc_confirm else ai_arc

                updates["current_arc_outline"] = final_arc
                updates["arc_outline_history"] = [final_arc]

                # Step 4: if there are remaining titles, AI regenerates them based on new arc
                if remaining_titles:
                    # AI regenerates titles（含降级）
                    try:
                        ai_titles = _generate_titles_with_ai(
                            state, final_arc, direction, len(remaining_titles)
                        )
                    except Exception as e:
                        _logger.error("_generate_titles_with_ai failed: %s", e)
                        ai_titles = []  # 空列表，触发 shortage_note 提示手动输入

                    shortage = len(remaining_titles) - len(ai_titles)

                    if not ai_titles:
                        # LLM 完全失败（0 个标题）：消息明确说明将保留原标题
                        titles_message = (
                            f"⚠️ AI 未能生成任何标题（需要 {len(remaining_titles)} 个）。\n\n"
                            "直接回车保留原标题，或输入新标题列表（每行一个）覆盖："
                        )
                    elif shortage > 0:
                        # 部分生成：列出已有标题并提示数量不足
                        titles_message = (
                            "【AI根据新大纲生成的剩余章节标题】\n"
                            + "\n".join(
                                f"  {state.current_chapter_index + i + 1}. {t}"
                                for i, t in enumerate(ai_titles)
                            )
                            + f"\n\n⚠️ AI 仅生成了 {len(ai_titles)} 个，需要 {len(remaining_titles)} 个，"
                            "请在覆盖输入时补全所有标题。"
                            + "\n\n直接回车接受已有部分（不足处保留原标题），或输入完整列表覆盖："
                        )
                    else:
                        # 数量充足：正常确认流程
                        titles_message = (
                            "【AI根据新大纲生成的剩余章节标题】\n"
                            + "\n".join(
                                f"  {state.current_chapter_index + i + 1}. {t}"
                                for i, t in enumerate(ai_titles)
                            )
                            + "\n\n直接回车接受，或输入新标题列表（每行一个）覆盖："
                        )

                    titles_confirm_raw = interrupt({
                        "message": titles_message,
                        "ai_generated_titles": ai_titles,
                        "shortage": shortage,
                    })
                    titles_confirm = str(titles_confirm_raw).strip()
                    if titles_confirm:
                        new_lines = [_clean_title(l) for l in titles_confirm.splitlines() if l.strip()]
                        final_titles = [l for l in new_lines if l][:len(remaining_titles)]
                    else:
                        final_titles = ai_titles

                    # 数量不足时用原始标题补位（无论 AI 还是用户手动输入）
                    if len(final_titles) < len(remaining_titles):
                        final_titles = final_titles + remaining_titles[len(final_titles):]

                    if final_titles:
                        kept = state.current_batch_titles[:state.current_chapter_index]
                        updates["current_batch_titles"] = kept + final_titles

    # Handle tracking field adjustments
    for field_name in selected_tracking:
        hist_key = _TRACKING_HISTORY_MAP[field_name]
        hist_list: list[str] = getattr(state, hist_key)
        current_val = hist_list[-1] if hist_list else "（尚无记录）"
        new_val_raw = interrupt({
            "message": f"【{_TRACKING_LABELS[field_name]}】当前内容如下，请输入修改后的完整内容：",
            "current": current_val,
        })
        new_val = str(new_val_raw).strip()
        if new_val:
            updates[hist_key] = [new_val]  # operator.add appends new snapshot

    return updates


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
        return "prepare_arc_outline"
    return END
