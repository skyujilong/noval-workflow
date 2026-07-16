"""Chapter-plan edit subgraph factory（章末长线章节规划调整子图）。

设计原则：**调整从上游 chapter_plan（远端锚点）发起，弧线大纲永远是其纯派生**——
不再允许直接手改弧线，从源头保证「弧线 = f(chapter_plan)」，二者永不分叉。

Flow:
  cp_entry (interrupt: "是否调整后续章节规划？弧线将自动跟随")
    ↓ 跳过 / chapter_plan 为空 / 本批已写完 → END
  cp_direction (interrupt: 输入调整方向)
    ↓ 空 → END
  cp_rewrite (LLM: 重规划 chapter_plan 未写窗口段 [done+1, planned_upto] + direction)
    ↓
  cp_confirm (interrupt: 接受 / 新方向迭代 / 「=」手动替换; AI 失败走手动兜底)
    ↓ 新方向 → cp_rewrite (loop)
    ↓ 接受
  cp_writeback (锁定合并 chapter<=done + 覆写未写段, 写回 parent chapter_plan;
                不动 planned_upto / last_regen_at)
    ↓
  arc_rederive (从新 chapter_plan「本批切片」派生 current_arc_outline)
    ↓
  arc_titles_regen (LLM: 按新弧线重生成剩余章节标题)
    ↓
  arc_titles_confirm (interrupt: 接受 / 新方向 / 「=」手动替换)
    ↓ 新方向 → arc_titles_regen (loop)
    ↓ END
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.context import (
    build_chapter_context,
    build_foundation_context,
)
from noval_workflow.edit_step_subgraph import _SKIP_WORDS
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.llm import get_llm
from noval_workflow.nodes.chapter_plan import merge_chapter_plan, parse_chapter_plan_items
from noval_workflow.prompts import ARC_CHAPTER_FORMAT, get_prompt_pack
from noval_workflow.prompts.base import (
    _extract_chapter_plan_range,
    _format_chapter_plan_block,
)

_logger = logging.getLogger(__name__)


@dataclass
class ChapterPlanEditSubState:
    """State for the chapter-plan edit step subgraph.

    镜像父图 NovelState / ChapterEditSubState 中本子图要读的所有字段——缺字段会被
    langgraph 静默丢弃 / build_foundation_context 与 chapter_plan_prompt 里 AttributeError。
    """
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
    has_power_system: bool = False
    power_system: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)
    current_arc_outline: str = ""
    foreshadowing: dict = field(default_factory=dict)
    phase_summary: str = ""
    entity_cards: list = field(default_factory=list)
    # chapter_plan_prompt 头部要注入分卷位置卡，volume_position_card 读 volumes——
    # 旧弧线子图自建 prompt 不需要它，改走 chapter_plan_prompt 后必须镜像。
    volumes: list = field(default_factory=list)
    # chapter_plan 镜像（读入 + 合并后写回 parent）
    chapter_plan: list = field(default_factory=list)
    chapter_plan_planned_upto: int = 0

    # Review bridge（system_context 用于 LLM system message）
    system_context: str = ""

    # chapter_plan 编辑私有中间态
    chapter_plan_direction: str = ""
    ai_chapter_plan: str = ""          # LLM 输出的原始 JSON 草稿（供 confirm 解析/展示）
    chapter_plan_error: str = ""
    chapter_plan_needs_rewrite: bool = False
    final_chapter_plan: list = field(default_factory=list)  # 确认后的新未写段条目

    # 弧线联动标题（沿用旧逻辑）
    ai_titles: list[str] = field(default_factory=list)
    titles_direction: str = ""
    titles_needs_regen: bool = False

    # Entry gate
    cp_execute_gate: bool = False


# ── helpers ────────────────────────────────────────────────────────────────────

def _clean_title(line: str) -> str:
    line = re.sub(r'^\d+[\.）\)．、]\s*', '', line)
    return line.lstrip('-– ').strip()


def _plan_edit_range(state: ChapterPlanEditSubState) -> tuple[int, int]:
    """本次要重规划的 chapter_plan 章号范围 [done+1, planned_upto]（整个未写窗口）。

    例：已写 4 章、窗口前瞻到 40 → 调整 5~40。planned_upto 缺失时回退到 chapter_plan
    末条章号；仍算不出（空 plan）则退化为 [done+1, done+1]，由 cp_entry 判空拦截。
    """
    done = state.total_chapters_written
    start = done + 1
    end = state.chapter_plan_planned_upto
    if end < start and state.chapter_plan:
        end = state.chapter_plan[-1].chapter
    if end < start:
        end = start
    return start, end


def _batch_window(state: ChapterPlanEditSubState) -> tuple[int, int]:
    """反推本批的原始章号窗口 [batch_start, batch_end]（mid-batch 时 total_chapters_written
    已推进到批中段，不能直接用 total_chapters_written+1 当批首，会与固定的 current_batch_titles
    错配）。batch_start = 已写数 - 批内游标 + 1；batch_end = batch_start + 本批标题数 - 1。
    """
    batch_start = state.total_chapters_written - state.current_chapter_index + 1
    batch_end = batch_start + len(state.current_batch_titles) - 1
    return batch_start, batch_end


def _rewrite_chapter_plan_with_ai(state: ChapterPlanEditSubState, direction: str) -> str:
    """按调整方向重规划 chapter_plan 未写窗口段，复用主图 chapter_plan_prompt 骨架。

    locked_entries = 章 <= done 的历史条目（LLM 禁止改动/重复输出）；prompt 末尾追加
    「人工调整方向」段作为最高优先级约束。返回 LLM 原始 JSON 字符串（不在此解析）。
    """
    done = state.total_chapters_written
    start, end = _plan_edit_range(state)
    pack = get_prompt_pack(state.genre, state.novel_name)
    locked = _extract_chapter_plan_range(state.chapter_plan, 1, done) if done > 0 else []
    base_task = pack.chapter_plan_prompt(
        state=state,
        start_chapter=start,
        end_chapter=end,
        locked_entries=locked,
    )
    direction_section = (
        f"\n\n【本次人工调整方向（最高优先级，必须落实到第 {start}-{end} 章的规划中）】\n"
        f"{direction}\n"
        "要求：严格贯彻上述方向；与已写完章节不矛盾；仅重新输出未写段的 JSON 数组。"
    )
    llm = get_llm(temperature=0.7, label="chapter_plan_edit:rewrite")
    result = llm.invoke([
        SystemMessage(content=state.system_context),
        HumanMessage(content=base_task + direction_section),
    ])
    return result.content.strip()


def _derive_arc_from_plan(state: ChapterPlanEditSubState, plan_slice: list) -> str:
    """从「本批 chapter_plan 切片」派生弧线大纲——弧线是 chapter_plan 的纯下游函数，
    不接受自由方向单独驱动。已写章须承接、未写章严格落在锚点上。
    """
    already_written = state.current_batch_titles[:state.current_chapter_index]
    remaining = state.current_batch_titles[state.current_chapter_index:]

    chapter_ctx = build_chapter_context(state)
    chapter_section = f"\n\n【最近章节内容（请据此保持连贯）】\n{chapter_ctx}" if chapter_ctx else ""

    anchor_block = _format_chapter_plan_block(plan_slice)
    anchor_section = (
        f"\n\n【本批远端锚点（来自更新后的 chapter_plan，弧线须严格落在其目标/转折/钩子上）】\n{anchor_block}"
        if anchor_block else ""
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
        f"请根据更新后的远端锚点，重新规划当前批次的故事弧线大纲。"
        f"{anchor_section}{chapter_section}{written_section}{remaining_section}\n\n"
        f"要求：\n"
        f"- 必须覆盖所有未写章节的故事走向，并严格贴合上方远端锚点\n"
        f"- 与已写章节自然衔接，不得矛盾\n"
        f"- 单章内容不超过500字\n\n"
        f"{ARC_CHAPTER_FORMAT}\n\n"
        f"请直接输出更新后的弧线大纲，不需要额外标题。"
    )
    llm = get_llm(temperature=0.7, label="chapter_plan_edit:derive_arc")
    result = llm.invoke([
        SystemMessage(content=state.system_context),
        HumanMessage(content=prompt),
    ])
    return result.content.strip()


def _generate_titles_with_ai(
    state: ChapterPlanEditSubState, arc_outline: str, direction: str, remaining_count: int
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
    llm = get_llm(temperature=0.7, label="chapter_plan_edit:generate_titles")
    result = llm.invoke([
        SystemMessage(content=state.system_context),
        HumanMessage(content=prompt),
    ])
    lines = [_clean_title(l) for l in result.content.strip().splitlines() if l.strip()]
    return [l for l in lines if l][:remaining_count]


def _plan_cards_payload(items: list) -> list[dict]:
    """把 ChapterPlanItem 列表转成前端 ChapterPlanCards 消费的 dict 数组。"""
    return [asdict(it) for it in items]


# ── node functions ─────────────────────────────────────────────────────────────

def _cp_entry(entry_prompt: str):
    def cp_entry(state: ChapterPlanEditSubState) -> dict:
        # 本批已写完（无剩余章可派生弧线）→ 跳过
        is_last_in_batch = state.current_chapter_index >= len(state.current_batch_titles)
        # chapter_plan 为空（未启用 / 未生成）→ 跳过；维持「弧线永不手改」不变量，
        # 不退回旧的自由改弧线路径。
        if is_last_in_batch or not state.chapter_plan:
            return {"cp_execute_gate": False}

        start, end = _plan_edit_range(state)
        window_slice = _extract_chapter_plan_range(state.chapter_plan, start, end)
        window_block = _format_chapter_plan_block(window_slice)
        window_section = (
            f"\n\n【当前未写章节规划（第 {start}-{end} 章，本次可调整）】\n{window_block}"
            if window_block else ""
        )

        message = (
            entry_prompt
            + window_section
            + "\n\n---\n· 直接回车 / 输入 no 或 否 → 跳过\n· 输入其他内容 → 执行"
        )
        answer = interrupt({"type": InterruptType.CHAPTER_PLAN_EDIT_ENTRY_GATE.value, "message": message})
        if not answer:
            execute = False
        else:
            raw = str(answer).strip().lower()
            execute = raw not in _SKIP_WORDS
        return {
            "cp_execute_gate": execute,
            "system_context": build_foundation_context(state),
            "chapter_plan_direction": "",
            "ai_chapter_plan": "",
            "chapter_plan_error": "",
            "final_chapter_plan": [],
            "chapter_plan_needs_rewrite": False,
            "ai_titles": [],
            "titles_direction": "",
            "titles_needs_regen": False,
        }
    return cp_entry


def cp_direction_node(state: ChapterPlanEditSubState) -> dict:
    start, end = _plan_edit_range(state)
    window_slice = _extract_chapter_plan_range(state.chapter_plan, start, end)
    window_block = _format_chapter_plan_block(window_slice)
    direction_raw = interrupt({
        "type": InterruptType.CHAPTER_PLAN_EDIT_DIRECTION.value,
        "message": (
            "【后续章节规划调整】\n\n"
            + (f"【当前未写章节规划（第 {start}-{end} 章）】\n{window_block}\n\n" if window_block else "")
            + "---\n"
            + "· 直接回车 → 取消\n"
            + "· 输入调整方向 → AI 重规划后续章节，弧线大纲与剩余标题自动跟随"
        ),
        "chapter_plan_window": _plan_cards_payload(window_slice),
        "range": [start, end],
    })
    return {"chapter_plan_direction": str(direction_raw or "").strip()}


def cp_rewrite_node(state: ChapterPlanEditSubState) -> dict:
    """按方向重规划未写窗口段；顺带解析校验，失败即记 error 交由 confirm 走手动兜底。"""
    direction = state.chapter_plan_direction
    if not direction:
        return {"ai_chapter_plan": "", "chapter_plan_error": ""}
    try:
        raw = _rewrite_chapter_plan_with_ai(state, direction)
        parse_chapter_plan_items(raw)  # 早校验：坏 JSON 立即暴露，走 CONFIRM_ERROR
        return {"ai_chapter_plan": raw, "chapter_plan_error": ""}
    except Exception as e:
        _logger.error("chapter_plan rewrite failed: %s", e)
        return {"ai_chapter_plan": "", "chapter_plan_error": str(e)}


def cp_confirm_node(state: ChapterPlanEditSubState) -> dict:
    if not state.chapter_plan_direction:
        return {"final_chapter_plan": [], "chapter_plan_needs_rewrite": False}

    # AI 重写失败 → 手动输入完整 JSON 兜底；仍非法则跳过（绝不污染 parent chapter_plan）
    if not state.ai_chapter_plan:
        raw = interrupt({
            "type": InterruptType.CHAPTER_PLAN_EDIT_CONFIRM_ERROR.value,
            "message": (
                f"AI 重规划失败（{state.chapter_plan_error}），请手动输入完整的未写段章节规划 JSON 数组\n\n"
                "---\n"
                "· 直接回车 → 跳过（不改动）\n"
                "· 粘贴 JSON 数组 → 手动替换"
            ),
            "error": state.chapter_plan_error,
        })
        text = str(raw or "").strip()
        if not text:
            return {"final_chapter_plan": [], "chapter_plan_needs_rewrite": False}
        if text.startswith("="):  # 容忍前端统一的「=」手动替换前缀
            text = text[1:].strip()
        try:
            items = parse_chapter_plan_items(text)
        except ValueError as e:
            _logger.error("手动输入的章节规划 JSON 仍非法，跳过本次调整: %s", e)
            return {"final_chapter_plan": [], "chapter_plan_needs_rewrite": False}
        return {"final_chapter_plan": items, "chapter_plan_needs_rewrite": False}

    raw = interrupt({
        "type": InterruptType.CHAPTER_PLAN_EDIT_CONFIRM.value,
        "message": (
            "【AI 重规划的后续章节规划】\n"
            "（弧线大纲与剩余标题将据此自动重生成）\n\n---\n"
            "· 直接回车 → 接受\n"
            "· 输入新的调整方向 → AI 重新生成（可多次迭代）\n"
            "· 以「=」开头粘贴 JSON 数组 → 直接替换（跳过 AI）"
        ),
        "ai_chapter_plan": _plan_cards_payload(parse_chapter_plan_items(state.ai_chapter_plan)),
    })
    confirm = str(raw or "").strip()

    if not confirm:
        return {
            "final_chapter_plan": parse_chapter_plan_items(state.ai_chapter_plan),
            "chapter_plan_needs_rewrite": False,
        }

    if confirm.startswith("="):
        content = confirm[1:].strip()
        try:
            items = parse_chapter_plan_items(content) if content else parse_chapter_plan_items(state.ai_chapter_plan)
        except ValueError as e:
            _logger.error("手动替换的章节规划 JSON 非法，回退到 AI 结果: %s", e)
            items = parse_chapter_plan_items(state.ai_chapter_plan)
        return {"final_chapter_plan": items, "chapter_plan_needs_rewrite": False}

    # 其他输入 = 新方向，回 cp_rewrite 迭代
    return {
        "chapter_plan_direction": confirm,
        "ai_chapter_plan": "",
        "chapter_plan_error": "",
        "final_chapter_plan": [],
        "chapter_plan_needs_rewrite": True,
    }


def cp_writeback_node(state: ChapterPlanEditSubState) -> dict:
    """锁定合并后写回 parent chapter_plan（全量覆盖语义）。

    只覆写未写段、保留 chapter<=done 历史真值；**不动** chapter_plan_planned_upto /
    chapter_plan_last_regen_at——mid-batch 编辑不是向前延展窗口、也不改 STRIDE 记账节奏。
    """
    if not state.final_chapter_plan:
        return {}
    done = state.total_chapters_written
    merged = merge_chapter_plan(state.chapter_plan, state.final_chapter_plan, done)
    return {"chapter_plan": merged}


def arc_rederive_node(state: ChapterPlanEditSubState) -> dict:
    """从更新后的 chapter_plan 本批切片派生弧线大纲。无未写章 / 无切片时不动弧线。"""
    if not state.final_chapter_plan:
        return {}
    remaining = state.current_batch_titles[state.current_chapter_index:]
    if not remaining:
        return {}
    batch_start, batch_end = _batch_window(state)
    plan_slice = _extract_chapter_plan_range(state.chapter_plan, batch_start, batch_end)
    try:
        new_arc = _derive_arc_from_plan(state, plan_slice)
    except Exception as e:
        _logger.error("arc rederive failed: %s", e)
        return {}
    return {"current_arc_outline": new_arc} if new_arc else {}


def arc_titles_regen_node(state: ChapterPlanEditSubState) -> dict:
    remaining_titles = state.current_batch_titles[state.current_chapter_index:]
    arc_outline = state.current_arc_outline
    direction = state.titles_direction or state.chapter_plan_direction
    try:
        ai_titles = _generate_titles_with_ai(state, arc_outline, direction, len(remaining_titles))
    except Exception as e:
        _logger.error("arc_titles_regen failed: %s", e)
        ai_titles = []
    return {"ai_titles": ai_titles}


def arc_titles_confirm_node(state: ChapterPlanEditSubState) -> dict:
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
        "type": InterruptType.ARC_TITLES_CONFIRM.value,
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
    titles_confirm = str(titles_confirm_raw or "").strip()

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

def _route_after_entry(state: ChapterPlanEditSubState) -> str:
    if not state.cp_execute_gate:
        return END
    return "cp_direction"


def _route_after_direction(state: ChapterPlanEditSubState) -> str:
    if not state.chapter_plan_direction:
        return END
    return "cp_rewrite"


def _route_after_cp_confirm(state: ChapterPlanEditSubState) -> str:
    if state.chapter_plan_needs_rewrite:
        return "cp_rewrite"
    if not state.final_chapter_plan:
        return END
    return "cp_writeback"


def _route_after_arc_rederive(state: ChapterPlanEditSubState) -> str:
    # 无未写章 / 弧线未变时无需重生成标题
    remaining = state.current_batch_titles[state.current_chapter_index:]
    if state.final_chapter_plan and remaining:
        return "arc_titles_regen"
    return END


def _route_after_titles_confirm(state: ChapterPlanEditSubState) -> str:
    if state.titles_needs_regen:
        return "arc_titles_regen"
    return END


# ── factory ────────────────────────────────────────────────────────────────────

def make_chapter_plan_edit_subgraph(
    *, entry_prompt: str = "是否调整后续章节规划？弧线大纲将自动跟随"
):
    """Build and compile the chapter-plan edit subgraph（取代原 arc 手改子图）。"""
    builder = StateGraph(ChapterPlanEditSubState)

    builder.add_node("cp_entry", _cp_entry(entry_prompt))
    builder.add_node("cp_direction", cp_direction_node)
    builder.add_node("cp_rewrite", cp_rewrite_node)
    builder.add_node("cp_confirm", cp_confirm_node)
    builder.add_node("cp_writeback", cp_writeback_node)
    builder.add_node("arc_rederive", arc_rederive_node)
    builder.add_node("arc_titles_regen", arc_titles_regen_node)
    builder.add_node("arc_titles_confirm", arc_titles_confirm_node)

    builder.set_entry_point("cp_entry")

    builder.add_conditional_edges(
        "cp_entry",
        _route_after_entry,
        {END: END, "cp_direction": "cp_direction"},
    )
    builder.add_conditional_edges(
        "cp_direction",
        _route_after_direction,
        {END: END, "cp_rewrite": "cp_rewrite"},
    )
    builder.add_edge("cp_rewrite", "cp_confirm")
    builder.add_conditional_edges(
        "cp_confirm",
        _route_after_cp_confirm,
        {"cp_rewrite": "cp_rewrite", "cp_writeback": "cp_writeback", END: END},
    )
    builder.add_edge("cp_writeback", "arc_rederive")
    builder.add_conditional_edges(
        "arc_rederive",
        _route_after_arc_rederive,
        {"arc_titles_regen": "arc_titles_regen", END: END},
    )
    builder.add_edge("arc_titles_regen", "arc_titles_confirm")
    builder.add_conditional_edges(
        "arc_titles_confirm",
        _route_after_titles_confirm,
        {"arc_titles_regen": "arc_titles_regen", END: END},
    )

    return builder.compile()
