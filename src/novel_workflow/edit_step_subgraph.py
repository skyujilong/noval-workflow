"""Factory for generic chapter-edit step subgraphs.

Each step follows the pattern:
  step_entry (interrupt: "是否执行？")
    ↓ skip → END
    ↓ yes
  [step_direction (interrupt)] ← optional, when ask_direction=True
    ↓
  step_prepare → step_generate
    ↓
  [step_llm_review] ← optional, when enable_llm_review=True
    ↓ pass / max reached
  step_human_review (interrupt)
    ↓ approved → [enable_prune? foreshadow_prune flow] → step_save → END
    ↓ not approved → step_generate (loop)

Foreshadow prune flow (optional):
  foreshadow_prune_ask (interrupt: "是否精简？")
    ↓ no / skip → step_save
    ↓ yes → foreshadow_prune_analyze (LLM 生成建议)
        ↓
      foreshadow_prune_confirm (interrupt: 展示建议，人工勾选)
        ↓
      foreshadow_prune_apply (应用删除) → step_save
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import invoke_json, repair_and_parse
from noval_workflow.llm import get_llm
from noval_workflow.prompts import FORESHADOW_PRUNE_ANALYSIS_PROMPT
from noval_workflow.state import ReviewSubState, reset_review_fields
from noval_workflow.subgraph import (
    generate,
    llm_self_review,
    human_review,
    route_after_llm_review,
    route_after_human,
)

_logger = logging.getLogger(__name__)

# Shared with arc_edit_subgraph — imported there to avoid divergence.
_SKIP_WORDS = {"skip", "跳过", "", "s", "no", "n", "否", "不", "none", "null"}


@dataclass
class EditStepSubState(ReviewSubState):
    """State for a single edit step subgraph.

    Inherits all ReviewSubState fields. Additional fields carry parent-graph
    context needed by prepare_fn / save_fn.
    """
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""
    core_theme: str = ""
    world_building: str = ""
    # 力量体系为作品级 state，_ContextState Protocol 要求子图必须镜像它——否则
    # prepare_fn 里的 build_foundation_context 会 AttributeError。
    has_power_system: bool = False
    power_system: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    character_profiles: str = ""
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)
    current_arc_outline: str = ""
    character_status: str = ""
    character_relations: str = ""
    foreshadowing: dict = field(default_factory=dict)
    phase_summary: str = ""
    review_history: list = field(default_factory=list)

    # Step gate fields (not written back to parent graph)
    step_execute_gate: bool = False
    step_direction_input: str = ""

    # 伏笔精简流程专用字段
    foreshadow_prune_enabled: bool = False
    foreshadow_prune_suggestion: dict = field(default_factory=dict)  # LLM分析结果
    foreshadow_prune_selected: list[str] = field(default_factory=list)  # 用户勾选的待删ID


def make_edit_step_subgraph(
    *,
    entry_prompt: str,
    prepare_fn: Callable,
    save_fn: Callable,
    entry_gate_type: InterruptType,
    direction_type: InterruptType,
    enable_llm_review: bool = True,
    llm_review_max: int = 3,
    ask_direction: bool = False,
    enable_prune: bool = False,  # 是否启用伏笔精简流程
):
    """Build and compile a single chapter-edit step subgraph.

    Args:
        entry_prompt:      Text shown in the entry interrupt ("是否执行本步骤？")
        prepare_fn:        Receives state; returns dict with system_context,
                           task_prompt, review_type (and any other overrides).
        save_fn:           Receives state; writes current_draft back to the
                           appropriate history field; returns a dict.
        entry_gate_type:   step_entry 中断的权威 type（复用节点由调用方传入身份，
                           对应 InterruptType.*_ENTRY_GATE）。
        direction_type:    step_direction 中断的权威 type（对应 *_DIRECTION_INPUT）。
        enable_llm_review: Whether to run LLM self-review after generation.
        llm_review_max:    Max LLM review rounds before forcing human review.
        ask_direction:     If True, interrupt after entry to collect a direction
                           string before calling prepare_fn.
        enable_prune:      If True, enable foreshadowing prune flow after human review.
    """

    # ── node closures ──────────────────────────────────────────────────────────

    def step_entry(state: EditStepSubState) -> dict:
        answer = interrupt({"type": entry_gate_type.value, "message": entry_prompt})
        # 直接处理 None/falsy 值，避免 str(None) = "None" 的问题
        if not answer:
            execute = False
        else:
            execute = str(answer).strip().lower() not in _SKIP_WORDS
        return {"step_execute_gate": execute, "step_direction_input": ""}

    def step_direction(state: EditStepSubState) -> dict:
        direction = interrupt({
            "type": direction_type.value,
            "message": "请输入调整方向（直接回车使用默认提示词）：",
        })
        # 处理 None，避免 str(None) = "None"
        return {"step_direction_input": str(direction or "").strip()}

    def step_prepare(state: EditStepSubState) -> dict:
        result = prepare_fn(state)
        return {**reset_review_fields(), **result, "llm_review_max": llm_review_max}

    def step_save(state: EditStepSubState) -> dict:
        return save_fn(state)

    # ── 伏笔精简流程专用节点 ──────────────────────────────────────────────────

    def foreshadow_prune_ask(state: EditStepSubState) -> dict:
        """询问用户是否需要精简伏笔台账。"""
        answer = interrupt({
            "type": InterruptType.FORESHADOW_PRUNE_ASK.value,
            "message": "是否对伏笔台账进行精简？\n\n提示：精简将由AI分析并建议删除老旧、次要的伏笔，避免上下文膨胀。",
        })
        # 空字符串 / 否 / no / n → 不精简；是 / yes / y → 精简
        answer_str = str(answer or "").strip().lower()
        do_prune = answer_str not in _SKIP_WORDS and answer_str != ""
        return {"foreshadow_prune_enabled": do_prune}

    def foreshadow_prune_analyze(state: EditStepSubState) -> dict:
        """调用LLM分析伏笔台账，给出精简建议。"""
        try:
            # 解析当前草稿中的伏笔数据（LLM 生成的 JSON 台账，先修复再解析）
            draft = state.current_draft
            foreshadow_data = repair_and_parse(draft, kind=dict) if isinstance(draft, str) else draft

            # 准备上下文
            recent_summaries = "\n".join(
                state.all_chapter_summaries[-3:] if len(state.all_chapter_summaries) >= 3 else state.all_chapter_summaries
            )
            all_titles_str = "\n".join(
                f"第{i+1}章：{title}" for i, title in enumerate(state.all_chapter_titles)
            )

            prompt = FORESHADOW_PRUNE_ANALYSIS_PROMPT.format(
                recent_summaries=recent_summaries or "（暂无章节概要）",
                all_titles_count=len(state.all_chapter_titles),
                all_titles=all_titles_str or "（暂无章节标题）",
                world_building=state.world_building or "（暂无世界观设定）",
                character_profiles=state.character_profiles or "（暂无人物档案）",
                foreshadowing_json=json.dumps(foreshadow_data, ensure_ascii=False, indent=2),
            )

            # 伏笔精简是结构化分类（输出 JSON 删除建议），且结果还要经 foreshadow_prune_confirm
            # 让用户勾选确认兜底：关闭深度思考加速，即便建议略糙也有人工把关。
            llm = get_llm(temperature=0.3, label="foreshadow_prune", thinking="disabled")
            messages = [
                SystemMessage(content="你是专业的小说伏笔管理专家，擅长识别核心伏笔与次要伏笔，帮助作者精简上下文。"),
                HumanMessage(content=prompt),
            ]
            # invoke_json：先修复脏 JSON，失败则回喂报错重试一次；仍失败抛错 → 下方 except 兜底空建议。
            suggestion = invoke_json(llm, messages, kind=dict, label="foreshadow_prune")
            _logger.info(f"伏笔精简分析完成，建议删除 {len(suggestion.get('to_delete', []))} 个")
            return {"foreshadow_prune_suggestion": suggestion}

        except Exception as e:
            _logger.error(f"伏笔精简分析失败: {e}")
            # 失败时返回空建议，不中断流程
            return {"foreshadow_prune_suggestion": {"s_level_count": 0, "a_level_count": 0, "to_delete": [], "suggestion": "分析失败，跳过精简"}}

    def foreshadow_prune_confirm(state: EditStepSubState) -> dict:
        """展示精简建议，让用户勾选确认。"""
        suggestion = state.foreshadow_prune_suggestion
        foreshadow_data = repair_and_parse(state.current_draft, kind=dict) if isinstance(state.current_draft, str) else state.current_draft

        answer = interrupt({
            "type": InterruptType.FORESHADOW_PRUNE_CONFIRM.value,
            "message": "请确认需要删除的伏笔。",
            "s_level_count": suggestion.get("s_level_count", 0),
            "a_level_count": suggestion.get("a_level_count", 0),
            "to_delete": suggestion.get("to_delete", []),
            "suggestion": suggestion.get("suggestion", ""),
            "pending_count": len(foreshadow_data.get("pending", [])),
            "collected_count": len(foreshadow_data.get("collected", [])),
        })

        # answer 是用户提交的 JSON 字符串数组，如 "[\"F01\", \"F02\"]"
        try:
            if isinstance(answer, str) and answer.strip():
                selected_ids = json.loads(answer)
            elif isinstance(answer, list):
                selected_ids = answer
            else:
                selected_ids = []
        except (json.JSONDecodeError, TypeError):
            selected_ids = []

        _logger.info(f"用户确认删除 {len(selected_ids)} 个伏笔")
        return {"foreshadow_prune_selected": selected_ids}

    def foreshadow_prune_apply(state: EditStepSubState) -> dict:
        """执行实际的删除操作，更新 current_draft。"""
        selected_ids = state.foreshadow_prune_selected
        if not selected_ids:
            return {}  # 没有要删除的，直接返回

        try:
            foreshadow_data = repair_and_parse(state.current_draft, kind=dict) if isinstance(state.current_draft, str) else state.current_draft

            # 从 pending 中删除
            before_pending = len(foreshadow_data.get("pending", []))
            foreshadow_data["pending"] = [
                entry for entry in foreshadow_data.get("pending", [])
                if entry.get("id") not in selected_ids
            ]

            # 从 collected 中删除
            before_collected = len(foreshadow_data.get("collected", []))
            foreshadow_data["collected"] = [
                entry for entry in foreshadow_data.get("collected", [])
                if entry.get("id") not in selected_ids
            ]

            deleted_count = (before_pending - len(foreshadow_data["pending"])) + (before_collected - len(foreshadow_data["collected"]))
            _logger.info(f"伏笔精简完成，共删除 {deleted_count} 个伏笔")

            # 更新 current_draft 为新的 JSON 字符串
            return {"current_draft": json.dumps(foreshadow_data, ensure_ascii=False, indent=2)}

        except Exception as e:
            _logger.error(f"伏笔精简应用失败: {e}")
            return {}  # 失败时不修改

    # ── routing ────────────────────────────────────────────────────────────────

    def route_after_entry(state: EditStepSubState) -> str:
        if not state.step_execute_gate:
            return END
        return "step_direction" if ask_direction else "step_prepare"

    def route_after_human_with_prune(state: EditStepSubState) -> str:
        """人工审核后的路由：如果启用精简且是伏笔类型，则进入精简流程。"""
        # 先复用原逻辑判断是否通过
        base_result = route_after_human(state)
        # 如果不是 END（需要修改重生成），直接返回
        if base_result != END:
            return base_result
        # 如果是 END 且启用精简且是伏笔类型，进入精简询问
        if enable_prune and state.review_type == "foreshadowing":
            return "foreshadow_prune_ask"
        # 否则直接去 save
        return "step_save"

    def route_after_prune_ask(state: EditStepSubState) -> str:
        if state.foreshadow_prune_enabled:
            return "foreshadow_prune_analyze"
        return "step_save"

    def route_after_prune_analyze(state: EditStepSubState) -> str:
        suggestion = state.foreshadow_prune_suggestion
        to_delete = suggestion.get("to_delete", [])
        # 有建议删除的内容，进入确认环节；否则直接保存
        if to_delete:
            return "foreshadow_prune_confirm"
        return "step_save"

    # ── graph assembly ─────────────────────────────────────────────────────────

    builder = StateGraph(EditStepSubState)

    builder.add_node("step_entry", step_entry)
    if ask_direction:
        builder.add_node("step_direction", step_direction)
    builder.add_node("step_prepare", step_prepare)
    builder.add_node("step_generate", generate)
    if enable_llm_review:
        builder.add_node("step_llm_review", llm_self_review)
    builder.add_node("step_human_review", human_review)
    builder.add_node("step_save", step_save)

    # 精简流程节点
    if enable_prune:
        builder.add_node("foreshadow_prune_ask", foreshadow_prune_ask)
        builder.add_node("foreshadow_prune_analyze", foreshadow_prune_analyze)
        builder.add_node("foreshadow_prune_confirm", foreshadow_prune_confirm)
        builder.add_node("foreshadow_prune_apply", foreshadow_prune_apply)

    builder.set_entry_point("step_entry")

    # entry → skip (END) or continue
    if ask_direction:
        builder.add_conditional_edges(
            "step_entry", route_after_entry, {END: END, "step_direction": "step_direction"}
        )
        builder.add_edge("step_direction", "step_prepare")
    else:
        builder.add_conditional_edges(
            "step_entry", route_after_entry, {END: END, "step_prepare": "step_prepare"}
        )

    builder.add_edge("step_prepare", "step_generate")

    if enable_llm_review:
        builder.add_edge("step_generate", "step_llm_review")
        builder.add_conditional_edges(
            "step_llm_review",
            route_after_llm_review,
            {"generate": "step_generate", "human_review": "step_human_review"},
        )
    else:
        builder.add_edge("step_generate", "step_human_review")

    # human review 之后：进入精简流程（如果启用）或直接保存
    if enable_prune:
        builder.add_conditional_edges(
            "step_human_review",
            route_after_human_with_prune,
            {
                END: "step_save",  # 原逻辑不通过 → END 实际是指通过去 save
                "generate": "step_generate",
                "foreshadow_prune_ask": "foreshadow_prune_ask",
            },
        )
        # 精简流程分支
        builder.add_conditional_edges(
            "foreshadow_prune_ask",
            route_after_prune_ask,
            {"step_save": "step_save", "foreshadow_prune_analyze": "foreshadow_prune_analyze"},
        )
        builder.add_conditional_edges(
            "foreshadow_prune_analyze",
            route_after_prune_analyze,
            {"step_save": "step_save", "foreshadow_prune_confirm": "foreshadow_prune_confirm"},
        )
        builder.add_edge("foreshadow_prune_confirm", "foreshadow_prune_apply")
        builder.add_edge("foreshadow_prune_apply", "step_save")
    else:
        # 无精简流程，直接保存
        builder.add_conditional_edges(
            "step_human_review",
            route_after_human,
            {END: "step_save", "generate": "step_generate"},
        )

    builder.add_edge("step_save", END)

    return builder.compile()
