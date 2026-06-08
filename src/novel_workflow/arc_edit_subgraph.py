"""Arc-specific edit subgraph factory.

Flow:
  arc_entry (interrupt: "是否调整弧线大纲？")
    ↓ skip → END
    ↓ yes
  arc_direction (interrupt: 输入调整方向)
    ↓
  arc_rewrite (LLM)
    ↓
  arc_confirm (interrupt: accept / new direction / manual replace)
    ↓ new direction → arc_rewrite (loop)
    ↓ accept or manual replace
  arc_titles_regen (LLM: 重新生成剩余章节标题)
    ↓
  arc_titles_confirm (interrupt: accept / new direction / manual replace)
    ↓ new direction → arc_titles_regen (loop)
    ↓ accept or manual replace
  END
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.edit_step_subgraph import _SKIP_WORDS
from noval_workflow.llm import get_llm


@dataclass
class ArcEditSubState:
    """State for the arc edit step subgraph."""
    # Parent-graph fields (read-only context)
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""
    core_theme: str = ""
    world_building: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)
    current_arc_outline: str = ""
    arc_outline_history: list[str] = field(default_factory=list)
    character_status_history: list[str] = field(default_factory=list)
    character_relations_history: list[str] = field(default_factory=list)
    foreshadowing_history: list[str] = field(default_factory=list)
    phase_summary_history: list[str] = field(default_factory=list)

    # Review bridge (needed by system_context used in arc_rewrite)
    system_context: str = ""

    # Arc-private intermediate state
    arc_direction: str = ""
    ai_arc: str = ""
    arc_error: str = ""
    final_arc: str = ""
    arc_needs_rewrite: bool = False
    ai_titles: list[str] = field(default_factory=list)
    titles_direction: str = ""
    titles_needs_regen: bool = False

    # Entry gate
    arc_execute_gate: bool = False


# ── helpers (self-contained, not imported from nodes/chapter_edit.py) ──────────

def _clean_title(line: str) -> str:
    line = re.sub(r'^\d+[\.）\)\uff0e\u3001]\s*', '', line)
    return line.lstrip('-– ').strip()


def _rewrite_arc_with_ai(state: ArcEditSubState, direction: str) -> str:
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
    state: ArcEditSubState, arc_outline: str, direction: str, remaining_count: int
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


# ── node functions ─────────────────────────────────────────────────────────────

def _arc_entry(entry_prompt: str):
    def arc_entry(state: ArcEditSubState) -> dict:
        is_last_in_batch = state.current_chapter_index >= len(state.current_batch_titles)
        if is_last_in_batch:
            return {"arc_execute_gate": False}

        already_written = state.current_batch_titles[:state.current_chapter_index]
        remaining = state.current_batch_titles[state.current_chapter_index:]

        arc_section = (
            f"\n\n【当前弧线大纲】\n{state.current_arc_outline}"
            if state.current_arc_outline else ""
        )
        written_section = (
            "\n\n【本批已写章节】\n"
            + "\n".join(
                f"  {state.total_chapters_written - len(already_written) + i + 1}. {t}"
                for i, t in enumerate(already_written)
            )
        ) if already_written else ""
        remaining_section = (
            "\n\n【本批未写章节】\n"
            + "\n".join(
                f"  {state.total_chapters_written + i + 1}. {t}"
                for i, t in enumerate(remaining)
            )
        ) if remaining else ""

        message = (
            entry_prompt
            + arc_section
            + written_section
            + remaining_section
            + "\n\n---\n· 直接回车 / 输入 no 或 否 → 跳过\n· 输入其他内容 → 执行"
        )

        answer = interrupt({"message": message})
        raw = str(answer).strip().lower()
        execute = raw not in _SKIP_WORDS
        return {
            "arc_execute_gate": execute,
            "system_context": build_foundation_context(state),
            "arc_direction": "",
            "ai_arc": "",
            "arc_error": "",
            "final_arc": "",
            "ai_titles": [],
            "arc_needs_rewrite": False,
            "titles_direction": "",
            "titles_needs_regen": False,
        }
    return arc_entry


def arc_direction_node(state: ArcEditSubState) -> dict:
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    direction_raw = interrupt({
        "message": (
            "【弧线大纲调整】\n\n"
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
            + "\n\n---\n"
            + "· 直接回车 → 取消\n"
            + "· 输入调整方向 → AI 重写大纲并更新剩余章节标题"
        ),
        "current_arc_outline": state.current_arc_outline,
        "remaining_titles": remaining_titles,
    })
    return {"arc_direction": str(direction_raw).strip()}


def arc_rewrite_node(state: ArcEditSubState) -> dict:
    import logging
    _logger = logging.getLogger(__name__)
    direction = state.arc_direction
    if not direction:
        return {"ai_arc": "", "arc_error": ""}
    try:
        ai_arc = _rewrite_arc_with_ai(state, direction)
        return {"ai_arc": ai_arc, "arc_error": ""}
    except Exception as e:
        _logger.error("arc_rewrite failed: %s", e)
        return {"ai_arc": "", "arc_error": str(e)}


def arc_confirm_node(state: ArcEditSubState) -> dict:
    if not state.arc_direction:
        return {"final_arc": "", "arc_needs_rewrite": False}

    if not state.ai_arc:
        raw = interrupt({
            "message": (
                f"AI重写失败（{state.arc_error}），请手动输入新的弧线大纲\n\n"
                "---\n"
                "· 直接回车 → 跳过\n"
                "· 输入完整大纲内容 → 手动替换"
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
            + "\n\n---\n"
            "· 直接回车 → 接受\n"
            "· 输入新的调整方向 → AI 重新生成（可多次迭代）\n"
            "· 以「=」开头 → 直接替换为完整内容（跳过 AI）"
        ),
        "ai_generated_arc": state.ai_arc,
    })
    confirm = str(raw).strip()

    if not confirm:
        final = state.ai_arc
        return {
            "final_arc": final,
            "arc_needs_rewrite": False,
            "current_arc_outline": final,
            "arc_outline_history": [final],
        }

    if confirm.startswith("="):
        final = confirm[1:].strip() or state.ai_arc
        result = {"final_arc": final, "arc_needs_rewrite": False}
        if final:
            result["current_arc_outline"] = final
            result["arc_outline_history"] = [final]
        return result

    return {
        "arc_direction": confirm,
        "ai_arc": "",
        "arc_error": "",
        "final_arc": "",
        "arc_needs_rewrite": True,
    }


def arc_titles_regen_node(state: ArcEditSubState) -> dict:
    import logging
    _logger = logging.getLogger(__name__)
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    arc_outline = state.final_arc or state.current_arc_outline
    direction = state.titles_direction or state.arc_direction
    try:
        ai_titles = _generate_titles_with_ai(state, arc_outline, direction, len(remaining_titles))
    except Exception as e:
        _logger.error("arc_titles_regen failed: %s", e)
        ai_titles = []
    return {"ai_titles": ai_titles}


def arc_titles_confirm_node(state: ArcEditSubState) -> dict:
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    ai_titles = state.ai_titles
    shortage = len(remaining_titles) - len(ai_titles)

    shortage_note = (
        f"\nAI 仅生成了 {len(ai_titles)} 个，需要 {len(remaining_titles)} 个，"
        "用「=」覆盖时请补全所有标题。"
        if shortage > 0 else ""
    )

    if not ai_titles:
        titles_display = f"AI 未能生成任何标题（需要 {len(remaining_titles)} 个）。"
    else:
        titles_display = "【AI根据新大纲生成的剩余章节标题】\n" + "\n".join(
            f"  {state.current_chapter_index + i + 1}. {t}"
            for i, t in enumerate(ai_titles)
        )

    titles_confirm_raw = interrupt({
        "message": (
            titles_display
            + shortage_note
            + "\n\n---\n"
            "· 直接回车 → 接受\n"
            "· 输入新的调整方向 → AI 重新生成（可多次迭代）\n"
            "· 以「=」开头，每行一个标题 → 直接替换（跳过 AI）"
        ),
        "ai_generated_titles": ai_titles,
        "shortage": shortage,
    })
    titles_confirm = str(titles_confirm_raw).strip()

    if not titles_confirm:
        final_titles = ai_titles
    elif titles_confirm.startswith("="):
        content = titles_confirm[1:].strip()
        new_lines = [_clean_title(l) for l in content.splitlines() if l.strip()]
        final_titles = [l for l in new_lines if l][:len(remaining_titles)]
    else:
        return {
            "titles_direction": titles_confirm,
            "titles_needs_regen": True,
        }

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


# ── routing ────────────────────────────────────────────────────────────────────

def _route_after_direction(state: ArcEditSubState) -> str:
    if not state.arc_direction:
        return END
    return "arc_rewrite"


def _route_after_entry(state: ArcEditSubState) -> str:
    if not state.arc_execute_gate:
        return END
    return "arc_direction"


def _route_after_arc_confirm(state: ArcEditSubState) -> str:
    if state.arc_needs_rewrite:
        return "arc_rewrite"
    remaining = state.current_batch_titles[state.current_chapter_index:]
    if state.final_arc and remaining:
        return "arc_titles_regen"
    return END


def _route_after_titles_confirm(state: ArcEditSubState) -> str:
    if state.titles_needs_regen:
        return "arc_titles_regen"
    return END


# ── factory ────────────────────────────────────────────────────────────────────

def make_arc_edit_subgraph(*, entry_prompt: str = "是否调整弧线大纲？"):
    """Build and compile the arc edit subgraph."""
    builder = StateGraph(ArcEditSubState)

    builder.add_node("arc_entry", _arc_entry(entry_prompt))
    builder.add_node("arc_direction", arc_direction_node)
    builder.add_node("arc_rewrite", arc_rewrite_node)
    builder.add_node("arc_confirm", arc_confirm_node)
    builder.add_node("arc_titles_regen", arc_titles_regen_node)
    builder.add_node("arc_titles_confirm", arc_titles_confirm_node)

    builder.set_entry_point("arc_entry")

    builder.add_conditional_edges(
        "arc_entry",
        _route_after_entry,
        {END: END, "arc_direction": "arc_direction"},
    )
    builder.add_conditional_edges(
        "arc_direction",
        _route_after_direction,
        {END: END, "arc_rewrite": "arc_rewrite"},
    )
    builder.add_edge("arc_rewrite", "arc_confirm")
    builder.add_conditional_edges(
        "arc_confirm",
        _route_after_arc_confirm,
        {"arc_rewrite": "arc_rewrite", "arc_titles_regen": "arc_titles_regen", END: END},
    )
    builder.add_edge("arc_titles_regen", "arc_titles_confirm")
    builder.add_conditional_edges(
        "arc_titles_confirm",
        _route_after_titles_confirm,
        {"arc_titles_regen": "arc_titles_regen", END: END},
    )

    return builder.compile()
