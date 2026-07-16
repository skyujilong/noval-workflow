"""伏笔台账精简子图（post-review 后处理，可插拔进 make_edit_step_subgraph）。

拓扑（入口 ask，出口 END；由工厂用 add_edge("post_review", "step_save") 兜到保存）：
  foreshadow_prune_ask (interrupt: "是否精简？")
    ↓ no / skip → END
    ↓ yes → foreshadow_prune_analyze (LLM 生成建议)
        ↓ 无删除建议 → END
        ↓ 有删除建议 → foreshadow_prune_confirm (interrupt: 展示建议，人工勾选)
            ↓
          foreshadow_prune_apply (应用删除) → END

这是「人工审核通过后、save 之前」的伏笔专属后处理，从通用工厂 edit_step_subgraph
拆出——通用工厂只留 post_review_subgraph 扩展点，不再认识 "foreshadowing"。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.edit_step_subgraph import EditStepSubState, _SKIP_WORDS
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import invoke_json, repair_and_parse
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    FORESHADOW_PRUNE_ANALYSIS_PROMPT,
    format_character_profiles_from_cards,
)

_logger = logging.getLogger(__name__)


@dataclass
class ForeshadowSubState(EditStepSubState):
    """伏笔步骤专用 state：在通用 EditStepSubState 之上补精简流程字段。

    这 3 个字段只服务伏笔精简，从 EditStepSubState 拆出以免污染其他 4 个调用方。
    作为 post_review 嵌套子图时，父子两层图都必须用本类编译，否则 langgraph 按同名
    字段桥接时这些字段不在 schema 里、更新被丢弃（详见 make_edit_step_subgraph 的
    state_cls 说明与其节点闭包的窄化注释）。
    """
    foreshadow_prune_enabled: bool = False
    foreshadow_prune_suggestion: dict = field(default_factory=dict)  # LLM分析结果
    foreshadow_prune_selected: list[str] = field(default_factory=list)  # 用户勾选的待删ID


# ── 节点 ──────────────────────────────────────────────────────────────────────
# ⚠️ 节点闭包不写 state 类型注解：LangGraph 会按第一个参数的注解窄化传入的 state，
# 写基类就丢掉子类字段。不写注解 → 回退到编译时的图 schema（ForeshadowSubState）。

def foreshadow_prune_ask(state) -> dict:
    """询问用户是否需要精简伏笔台账。"""
    answer = interrupt({
        "type": InterruptType.FORESHADOW_PRUNE_ASK.value,
        "message": "是否对伏笔台账进行精简？\n\n提示：精简将由AI分析并建议删除老旧、次要的伏笔，避免上下文膨胀。",
    })
    # 空字符串 / 否 / no / n → 不精简；是 / yes / y → 精简
    answer_str = str(answer or "").strip().lower()
    do_prune = answer_str not in _SKIP_WORDS and answer_str != ""
    _logger.info("伏笔精简·询问：用户答=%r → %s", answer_str, "执行精简" if do_prune else "跳过（不精简）")
    return {"foreshadow_prune_enabled": do_prune}


def foreshadow_prune_analyze(state) -> dict:
    """调用LLM分析伏笔台账，给出精简建议。"""
    try:
        # 解析当前草稿中的伏笔数据（LLM 生成的 JSON 台账，先修复再解析）
        draft = state.current_draft
        foreshadow_data = repair_and_parse(draft, kind=dict) if isinstance(draft, str) else draft
        pending_n = len(foreshadow_data.get("pending", []) or [])
        collected_n = len(foreshadow_data.get("collected", []) or [])
        _logger.info("伏笔精简·分析开始：pending=%d collected=%d 人物卡=%d",
                     pending_n, collected_n, len(state.entity_cards or []))

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
            character_profiles=format_character_profiles_from_cards(state.entity_cards) or "（暂无人物档案）",
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
        to_delete = suggestion.get("to_delete", []) or []
        # 关键日志：区分「LLM 真判定无可删（to_delete=0）」与下方 except 的「报错被吞」——
        # 二者都会让路由跳过确认 UI，靠这行日志判断是哪种。
        _logger.info("伏笔精简·分析完成：S级=%s A级=%s 建议删除=%d 条｜建议语：%s",
                     suggestion.get("s_level_count"), suggestion.get("a_level_count"),
                     len(to_delete), suggestion.get("suggestion", ""))
        return {"foreshadow_prune_suggestion": suggestion}

    except Exception as e:
        # 失败时返回空建议不中断流程——但这会让路由按「无待删」跳过确认 UI（表现为「界面没弹」）。
        # 故此处 error 级 + 完整 traceback 落盘，便于回答「到底是 LLM 返回空还是报错」。
        _logger.error("伏笔精简·分析失败（将跳过精简、不弹确认 UI）: %s", e, exc_info=True)
        return {"foreshadow_prune_suggestion": {"s_level_count": 0, "a_level_count": 0, "to_delete": [], "suggestion": "分析失败，跳过精简"}}


def foreshadow_prune_confirm(state) -> dict:
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


def foreshadow_prune_apply(state) -> dict:
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


# ── routing ───────────────────────────────────────────────────────────────────
# 跳过 / 直达支路一律指向本子图的 END，再由工厂 add_edge("post_review", "step_save")
# 兜到保存——子图内部引用不到外层的 step_save。

def route_after_prune_ask(state) -> str:
    if state.foreshadow_prune_enabled:
        return "foreshadow_prune_analyze"
    return END


def route_after_prune_analyze(state) -> str:
    suggestion = state.foreshadow_prune_suggestion
    to_delete = suggestion.get("to_delete", [])
    # 有建议删除的内容，进入确认环节；否则直接结束（回工厂去 save）——这里正是「弹不弹 UI」的分叉点
    if to_delete:
        _logger.info("伏笔精简·路由：待删 %d 条 → 弹确认 UI", len(to_delete))
        return "foreshadow_prune_confirm"
    _logger.info("伏笔精简·路由：无待删项 → 跳过确认 UI，直接保存")
    return END


# ── graph assembly ────────────────────────────────────────────────────────────

def _build_foreshadow_prune_subgraph():
    builder = StateGraph(ForeshadowSubState)

    builder.add_node("foreshadow_prune_ask", foreshadow_prune_ask)
    builder.add_node("foreshadow_prune_analyze", foreshadow_prune_analyze)
    builder.add_node("foreshadow_prune_confirm", foreshadow_prune_confirm)
    builder.add_node("foreshadow_prune_apply", foreshadow_prune_apply)

    builder.set_entry_point("foreshadow_prune_ask")

    builder.add_conditional_edges(
        "foreshadow_prune_ask",
        route_after_prune_ask,
        {"foreshadow_prune_analyze": "foreshadow_prune_analyze", END: END},
    )
    builder.add_conditional_edges(
        "foreshadow_prune_analyze",
        route_after_prune_analyze,
        {"foreshadow_prune_confirm": "foreshadow_prune_confirm", END: END},
    )
    builder.add_edge("foreshadow_prune_confirm", "foreshadow_prune_apply")
    builder.add_edge("foreshadow_prune_apply", END)

    return builder.compile()


# 预编译，供 _FORESHADOW_STEP 作为 post_review_subgraph 挂载
foreshadow_prune_step = _build_foreshadow_prune_subgraph()
