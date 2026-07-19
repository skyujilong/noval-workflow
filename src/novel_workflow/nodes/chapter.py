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
from noval_workflow.prompts import SUMMARY_PROMPT, format_cards_for_chapter_prompt, get_prompt_pack
from noval_workflow.state import NovelState, reset_review_fields

_logger = logging.getLogger(__name__)


# ── titles ────────────────────────────────────────────────────────────────────

def prepare_titles(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.titles_prompt(
            state.all_chapter_titles,
            build_chapter_context(state),
            arc_outline=state.current_arc_outline,
        ),
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
    # 批内定位：current_chapter_index 为本章在当前批次内的 0-based 序号（save_chapter 写完才自增），
    # 故 batch_pos = index + 1；据此把「本批弧线大纲」中对应本章的那一段锚定到提示词。
    batch_pos = state.current_chapter_index + 1
    batch_total = len(state.current_batch_titles)
    # scene beats 消费：严格核对 beats_chapter_index == chapter_num 才注入；不匹配（跳过 gate
    # / 上一章残留 / save_chapter 清零后）时视同无 beats，走原路径不注入。
    scene_beats_for_prompt = None
    if state.current_chapter_beats and state.beats_chapter_index == chapter_num:
        scene_beats_for_prompt = state.current_chapter_beats
    # chapter_plan 远端锚点消费：按 chapter_num 从章节规划里精确取本章那一条（4 字段）；
    # 未开启 chapter_plan / 未覆盖到本章 / 空 plan 时视同 None，不注入,行为向后兼容。
    chapter_plan_entry_for_prompt = None
    for item in state.chapter_plan:
        if item.chapter == chapter_num:
            chapter_plan_entry_for_prompt = item
            break
    # 登场实体卡触发式注入：严格核对 cast_chapter_index == chapter_num 才注入本章登场名单命中的卡
    # （不匹配 = 跳过 gate / 上一章残留 / 从未生成，视同无卡）。渲染成 markdown 追加到 task_prompt
    # 末尾作为「本章人物/物品设定锚点」，防止写正文时人物外貌/口吻、装备状态写飘。
    cards_section = ""
    if state.cast_chapter_index == chapter_num and state.current_chapter_cast:
        rendered = format_cards_for_chapter_prompt(state.entity_cards, state.current_chapter_cast)
        if rendered:
            cards_section = (
                "\n\n---\n【本章登场实体卡（人物/物品/装备设定锚点，务必严格遵守，防写飘）】\n"
                f"{rendered}"
            )
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.chapter_prompt(
            title,
            chapter_num,
            merged_titles,
            chapter_context,
            arc_outline=state.current_arc_outline,
            batch_pos=batch_pos,
            batch_total=batch_total,
            scene_beats=scene_beats_for_prompt,
            chapter_plan_entry=chapter_plan_entry_for_prompt,
            state=state,
        ) + cards_section,
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
        # 清零 scene beats：本章已写完保存，下一章 gate 若跳过则不应误用本章 beats
        # （prepare_chapter 双重保险：还会核对 beats_chapter_index==chapter_num）。
        "current_chapter_beats": [],
        "beats_chapter_index": -1,
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
        # 章节概要是对已定稿正文的压缩提炼（摘要任务），非创作：关闭深度思考加速。
        # 每章生成一次，累积加速明显；摘要质量对思考不敏感，风险低。
        llm = get_llm(temperature=0.3, label="chapter_summary", thinking="disabled")
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

    # 覆盖语义：返回「历史 + 本章」的完整新列表（父图无 reducer，见 NovelState 注释——
    # 追加语义会被子图镜像字段回写放大爆炸）。摘要即使为空也占位，保持与标题索引对齐。
    return {
        "all_chapter_titles": state.all_chapter_titles + [title],
        "all_chapter_summaries": state.all_chapter_summaries + [summary],
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
    # 本批未完 → 回到 scene_beats_step（每章都进 gate，用户可选择跳过或做 beats）
    # 本批完 → ask_continue 询问是否继续下一批
    if state.current_chapter_index < len(state.current_batch_titles):
        return "scene_beats_step"
    return "ask_continue"


def route_continue_or_end(state: NovelState) -> str:
    """批次结束后三分:END(用户停) / prepare_volumes(先滚动规划下一卷) / prepare_arc_outline(直接下一批)。

    滚动生成卷触发:当前卷之后尚无下一卷、且下一批末章(done + BATCH_SIZE)将触及/越过当前卷
    末章(planned_end,已收卷用 actual_end)时,先滚动规划下一卷(prepare_volumes → save_volumes
    →展开新卷 chapter_plan),让卷与卷衔接自然、下一卷 chapter_plan 在写该批前就就位。
      - has_next 守卫:下一卷已生成后,接近当前卷末章的后续批不再重复触发。
      - `>=`(非 `>`):保证越卷前一批就完成滚动,下一卷 chapter_plan 提前就绪。
      - 冷启动兜底:current_volume 为 None(无 volumes / 章号越界)→ 直接下一批。
    """
    from noval_workflow.volume_utils import current_volume

    if not state.continue_writing:
        return END

    done = state.total_chapters_written
    cur = current_volume(state.volumes, done)
    if cur is None:
        return "prepare_arc_outline"

    # 只看「已激活的下一卷」(planned_end>0)——前瞻草稿卷(planning，planned_end=0)index 虽更大，
    # 但未真正排产，不能算 has_next，否则草稿卷会让 has_next 恒真、滚动永不触发。
    has_next = any(v.planned_end > 0 and v.index > cur.index for v in state.volumes)
    vol_end = cur.actual_end if cur.actual_end is not None else cur.planned_end
    if (not has_next) and vol_end > 0 and (done + BATCH_SIZE >= vol_end):
        return "prepare_volumes"
    return "prepare_arc_outline"
