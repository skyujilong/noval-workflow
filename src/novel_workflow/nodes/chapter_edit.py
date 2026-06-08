"""Chapter-level user intervention: graph nodes + routers (chapter_edit subgraph)."""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    character_relations_prompt,
    character_status_prompt,
    foreshadowing_prompt,
    phase_summary_prompt,
)
from noval_workflow.state import reset_review_fields

_logger = logging.getLogger(__name__)

_SKIP_WORDS = {"skip", "跳过", "", "s", "no", "n", "continue", "继续"}
_CHOICE_MAP = {
    "1": "character_status",
    "2": "character_relations",
    "3": "foreshadowing",
    "4": "phase_summary",
}
_TRACKING_ORDER = [
    "character_status",
    "character_relations",
    "foreshadowing",
    "phase_summary",
]


def _clean_title(line: str) -> str:
    line = re.sub(r'^\d+[\.）\)\uff0e\u3001]\s*', '', line)
    return line.lstrip('-– ').strip()


def _rewrite_arc_with_ai(state, direction: str) -> str:
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
    state, arc_outline: str, direction: str, remaining_count: int
) -> list[str]:
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


# ── chapter_edit_menu ─────────────────────────────────────────────────────────

def chapter_edit_menu(state) -> dict:
    """Interrupt: 展示菜单，收集用户选择（弧线 + 追踪字段）。"""
    is_last_in_batch = state.current_chapter_index >= len(state.current_batch_titles)
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]

    arc_line = "" if is_last_in_batch else "  a  — 调整弧线大纲（AI将同步更新剩余章节标题）\n"

    choice = interrupt({
        "message": (
            f"第 {state.total_chapters_written} 章已完成。\n"
            f"当前批次进度：{state.current_chapter_index}/{len(state.current_batch_titles)}\n"
            "可调整项（输入对应编号/字母，多选用逗号分隔，直接回车跳过）：\n"
            + arc_line +
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
    do_arc = False
    selected_tracking: list[str] = []

    if raw not in _SKIP_WORDS:
        for token in raw.replace("，", ",").split(","):
            token = token.strip()
            if token == "a" and not is_last_in_batch:
                do_arc = True
            elif token in _CHOICE_MAP:
                selected_tracking.append(_CHOICE_MAP[token])

    # Deduplicate tracking fields preserving canonical order
    ordered_tracking = [f for f in _TRACKING_ORDER if f in selected_tracking]

    return {
        "system_context": build_foundation_context(state),
        "do_arc": do_arc,
        "arc_direction": "",
        "ai_arc": "",
        "arc_error": "",
        "final_arc": "",
        "ai_titles": [],
        "tracking_fields": ordered_tracking,
        "edit_tracking_cursor": 0,
    }


# ── chapter_edit_arc_direction ────────────────────────────────────────────────

def chapter_edit_arc_direction(state) -> dict:
    """Interrupt: 收集弧线调整方向。"""
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]

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

    return {"arc_direction": str(direction_raw).strip()}


# ── chapter_edit_arc_rewrite ──────────────────────────────────────────────────

def chapter_edit_arc_rewrite(state) -> dict:
    """LLM: 根据方向重写弧线大纲；失败时写 arc_error。"""
    direction = state.arc_direction
    if not direction:
        # 用户取消，不调用 LLM
        return {"ai_arc": "", "arc_error": ""}

    try:
        ai_arc = _rewrite_arc_with_ai(state, direction)
        return {"ai_arc": ai_arc, "arc_error": ""}
    except Exception as e:
        _logger.error("chapter_edit_arc_rewrite failed: %s", e)
        return {"ai_arc": "", "arc_error": str(e)}


# ── chapter_edit_arc_confirm ──────────────────────────────────────────────────

def chapter_edit_arc_confirm(state) -> dict:
    """Interrupt OR 直通：确认/再次调整/直接替换弧线大纲。

    - 方向为空       → 无 interrupt，直接返回 final_arc=""
    - LLM 失败       → fallback interrupt（手动输入完整内容）
    - LLM 成功       → interrupt，三种响应：
        空            → 接受 AI 大纲
        以「=」开头   → 「=」后的内容直接替换为最终大纲（跳过 LLM）
        其他文本      → 作为新调整方向，重新调用 LLM（loop back）
    """
    if not state.arc_direction:
        return {"final_arc": "", "arc_needs_rewrite": False}

    if not state.ai_arc:
        # LLM 失败 → fallback interrupt（只接受完整手动输入）
        raw = interrupt({
            "message": (
                f"⚠️ AI重写失败（{state.arc_error}），请手动输入新的弧线大纲\n"
                "（直接回车跳过本次弧线调整）："
            ),
            "error": state.arc_error,
        })
        final = str(raw).strip()
        result: dict = {"final_arc": final, "arc_needs_rewrite": False}
        if final:
            result["current_arc_outline"] = final
            result["arc_outline_history"] = [final]
        return result

    raw = interrupt({
        "message": (
            "【AI生成的新弧线大纲】\n"
            + state.ai_arc
            + "\n\n"
            "· 直接回车 → 接受\n"
            "· 输入新的调整方向 → AI 重新生成（可多次迭代）\n"
            "· 以「=」开头 → 直接替换为完整内容（跳过 AI）："
        ),
        "ai_generated_arc": state.ai_arc,
    })
    confirm = str(raw).strip()

    if not confirm:
        # 接受 AI 大纲
        final = state.ai_arc
        result = {"final_arc": final, "arc_needs_rewrite": False,
                  "current_arc_outline": final, "arc_outline_history": [final]}
        return result

    if confirm.startswith("="):
        # 直接替换完整内容
        final = confirm[1:].strip() or state.ai_arc
        result = {"final_arc": final, "arc_needs_rewrite": False}
        if final:
            result["current_arc_outline"] = final
            result["arc_outline_history"] = [final]
        return result

    # 新调整方向 → loop back 重新调用 LLM
    return {
        "arc_direction": confirm,
        "ai_arc": "",
        "arc_error": "",
        "final_arc": "",
        "arc_needs_rewrite": True,
    }


# ── chapter_edit_titles_regen ─────────────────────────────────────────────────

def chapter_edit_titles_regen(state) -> dict:
    """LLM: 根据弧线大纲和调整方向重新生成剩余章节标题。"""
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    arc_outline = state.final_arc or state.current_arc_outline
    direction = state.titles_direction or state.arc_direction

    try:
        ai_titles = _generate_titles_with_ai(state, arc_outline, direction, len(remaining_titles))
    except Exception as e:
        _logger.error("chapter_edit_titles_regen failed: %s", e)
        ai_titles = []

    return {"ai_titles": ai_titles}


# ── chapter_edit_titles_confirm ───────────────────────────────────────────────

def chapter_edit_titles_confirm(state) -> dict:
    """Interrupt: 确认/再次调整/直接替换重新生成的章节标题。

    三种响应：
        空            → 接受 AI 标题
        以「=」开头   → 「=」后的内容按行解析为最终标题列表（跳过 LLM）
        其他文本      → 作为新调整方向，重新调用 LLM（loop back）
    """
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    ai_titles = state.ai_titles
    shortage = len(remaining_titles) - len(ai_titles)

    shortage_note = (
        f"\n⚠️ AI 仅生成了 {len(ai_titles)} 个，需要 {len(remaining_titles)} 个，"
        "用「=」覆盖时请补全所有标题。"
        if shortage > 0 else ""
    )

    if not ai_titles:
        titles_display = f"⚠️ AI 未能生成任何标题（需要 {len(remaining_titles)} 个）。"
    else:
        titles_display = "【AI根据新大纲生成的剩余章节标题】\n" + "\n".join(
            f"  {state.current_chapter_index + i + 1}. {t}"
            for i, t in enumerate(ai_titles)
        )

    titles_confirm_raw = interrupt({
        "message": (
            titles_display
            + shortage_note
            + "\n\n"
            "· 直接回车 → 接受\n"
            "· 输入新的调整方向 → AI 重新生成（可多次迭代）\n"
            "· 以「=」开头，每行一个标题 → 直接替换（跳过 AI）："
        ),
        "ai_generated_titles": ai_titles,
        "shortage": shortage,
    })
    titles_confirm = str(titles_confirm_raw).strip()

    if not titles_confirm:
        # 接受 AI 标题
        final_titles = ai_titles
    elif titles_confirm.startswith("="):
        # 直接替换完整标题列表
        content = titles_confirm[1:].strip()
        new_lines = [_clean_title(l) for l in content.splitlines() if l.strip()]
        final_titles = [l for l in new_lines if l][:len(remaining_titles)]
    else:
        # 新调整方向 → loop back 重新调用 LLM
        return {
            "titles_direction": titles_confirm,
            "titles_needs_regen": True,
        }

    # 数量不足时用原始标题补位
    if len(final_titles) < len(remaining_titles):
        final_titles = final_titles + remaining_titles[len(final_titles):]

    if final_titles:
        kept = state.current_batch_titles[:state.current_chapter_index]
        return {
            "current_batch_titles": kept + final_titles,
            "titles_direction": "",
            "titles_needs_regen": False,
        }
    return {"titles_direction": "", "titles_needs_regen": False}


# ── chapter_edit_done ─────────────────────────────────────────────────────────

def chapter_edit_done(state) -> dict:
    """Pass-through sentinel node. 显式返回空列表让父图 operator.add 不追加任何值。"""
    return {"all_chapter_titles": [], "all_chapter_summaries": []}


# ── tracking field nodes ──────────────────────────────────────────────────────

def prepare_chapter_edit_character_status(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_status_prompt(state, build_chapter_context(state)),
        "review_type": "character_status",
        **reset_review_fields(),
    }


def save_chapter_edit_character_status(state) -> dict:
    return {
        "character_status_history": [state.current_draft],
        "edit_tracking_cursor": state.edit_tracking_cursor + 1,
    }


def prepare_chapter_edit_character_relations(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_relations_prompt(state, build_chapter_context(state)),
        "review_type": "character_relations",
        **reset_review_fields(),
    }


def save_chapter_edit_character_relations(state) -> dict:
    return {
        "character_relations_history": [state.current_draft],
        "edit_tracking_cursor": state.edit_tracking_cursor + 1,
    }


def prepare_chapter_edit_foreshadowing(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": foreshadowing_prompt(state, build_chapter_context(state)),
        "review_type": "foreshadowing",
        **reset_review_fields(),
    }


def save_chapter_edit_foreshadowing(state) -> dict:
    return {
        "foreshadowing_history": [state.current_draft],
        "edit_tracking_cursor": state.edit_tracking_cursor + 1,
    }


def prepare_chapter_edit_phase_summary(state) -> dict:
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": phase_summary_prompt(state, build_chapter_context(state)),
        "review_type": "phase_summary",
        **reset_review_fields(),
    }


def save_chapter_edit_phase_summary(state) -> dict:
    return {
        "phase_summary_history": [state.current_draft],
        "edit_tracking_cursor": state.edit_tracking_cursor + 1,
    }


# ── routers ───────────────────────────────────────────────────────────────────

def route_chapter_edit_entry(state) -> str:
    """After chapter_edit_menu: decide first destination."""
    if state.do_arc:
        return "chapter_edit_arc_direction"
    # No arc, go to first requested tracking field or done
    pending = state.tracking_fields[state.edit_tracking_cursor:]
    for field in _TRACKING_ORDER:
        if field in pending:
            return f"prepare_chapter_edit_{field}"
    return "chapter_edit_done"


def route_after_arc_confirm(state) -> str:
    """After chapter_edit_arc_confirm: re-run LLM, titles regen, tracking, or done."""
    if state.arc_needs_rewrite:
        return "chapter_edit_arc_rewrite"
    remaining = state.current_batch_titles[state.current_chapter_index:]
    if state.final_arc and remaining:
        return "chapter_edit_titles_regen"
    return _route_tracking_or_done(state)


def route_after_titles_confirm(state) -> str:
    """After chapter_edit_titles_confirm: re-run LLM, tracking fields, or done."""
    if state.titles_needs_regen:
        return "chapter_edit_titles_regen"
    return _route_tracking_or_done(state)


def route_chapter_edit_tracking_or_done(state) -> str:
    """After chapter_edit_titles_confirm: tracking fields or done."""
    return _route_tracking_or_done(state)


def route_chapter_edit_tracking_next(state) -> str:
    """After each save_chapter_edit_<field>: next tracking field or done."""
    return _route_tracking_or_done(state)


def _route_tracking_or_done(state) -> str:
    pending = state.tracking_fields[state.edit_tracking_cursor:]
    for field in _TRACKING_ORDER:
        if field in pending:
            return f"prepare_chapter_edit_{field}"
    return "chapter_edit_done"
