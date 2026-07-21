"""章末实体卡库精简子图（独立节点，挂在 chapter_edit_subgraph 链的最后一站）。

拓扑（入口 ask，出口 END）：
  entity_cards_prune_ask (interrupt: "是否精简卡库？")
    ↓ no / skip → END
    ↓ yes → entity_cards_prune_analyze (LLM 分析整库，给出建议删除清单)
        ↓ 卡库为空 → END
        ↓ 有卡 → entity_cards_prune_confirm (interrupt: 展示全库，预选 AI 建议删的，人工增减)
            ↓
          entity_cards_prune_apply (按勾选整卡从卡库移除) → END

与 foreshadow_prune_subgraph 同构（ask→analyze→confirm→apply），差别有二：
1. 操作对象是**跨章累积的整个卡库** state.entity_cards（人物档案膨胀的真源），
   不是某一章的 current_draft 草稿——故读写 entity_cards 而非 current_draft。
2. confirm 展示**全部卡**（不只 AI 建议删的），AI 建议删的默认预选，人工可自行增删
   （用户诉求：LLM 推断只是默认，人可再删别的）。

放在 chapter_edit_subgraph 链的 entity_discover_step 之后：本章新卡/更新全部入库后，
再对最终卡库做一次精简，confirm 看到的就是最终形态。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.config import PRUNE_STRIDE, should_prune_at_chapter
from noval_workflow.edit_step_subgraph import _SKIP_WORDS
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import invoke_json
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    ENTITY_CARDS_PRUNE_ANALYSIS_PROMPT,
    format_cards_digest_for_prune,
)

_logger = logging.getLogger(__name__)


@dataclass
class EntityCardsPruneSubState:
    """卡库精简子图专用 state。

    本子图挂在 chapter_edit_subgraph 顶层链（非 post_review 嵌套），故不继承
    EditStepSubState；只声明「从 ChapterEditSubState 桥接读入的字段」+「本流程私有字段」。
    字段名必须与 ChapterEditSubState 同名，langgraph 才按同名桥接读入 / 写回：
    - entity_cards 读入 + 写回（删卡后覆盖，无 reducer，见 NovelState.entity_cards 注释）
    - all_chapter_summaries / all_chapter_titles / world_building 只读，供分析上下文
    prune_* 三个私有字段父层没有，桥接后被丢弃——它们只服务本子图内部流转，无需回传。
    """

    # ── 从父层桥接读入 ──────────────────────────────────────────────────────────
    entity_cards: list = field(default_factory=list)
    all_chapter_summaries: list = field(default_factory=list)
    all_chapter_titles: list = field(default_factory=list)
    world_building: str = ""
    # 刚写完的章号，供 ask 节点做精简节流（每 PRUNE_STRIDE 章执行一次）；只读桥接。
    total_chapters_written: int = 0

    # ── 本子图私有流转 ──────────────────────────────────────────────────────────
    entity_cards_prune_enabled: bool = False
    entity_cards_prune_suggestion: dict = field(default_factory=dict)  # LLM 分析结果
    entity_cards_prune_selected: list[str] = field(
        default_factory=list
    )  # 用户勾选待删的实体名


# ── 卡取值工具（卡可能是 EntityCard 实例或 checkpoint roundtrip 后的 dict）──────


def _card_get(card, key, default=""):
    return (
        card.get(key, default)
        if isinstance(card, dict)
        else getattr(card, key, default)
    )


def _card_text(card, key) -> str:
    """取值字符串形态，str 枚举成员归一到 value（type/role roundtrip 前后形态不一）。"""
    v = _card_get(card, key, "")
    return v.value if hasattr(v, "value") else ("" if v is None else v)


# ── 节点 ──────────────────────────────────────────────────────────────────────
# ⚠️ 节点闭包不写 state 类型注解：LangGraph 会按第一个参数的注解窄化传入的 state，
# 写基类就丢掉子类字段。不写注解 → 回退到编译时的图 schema（EntityCardsPruneSubState）。


def entity_cards_prune_ask(state) -> dict:
    """询问用户是否需要精简实体卡库（先过节流：非精简章直接跳过，不弹中断、不调 LLM）。"""
    # 章末精简节流：仅每 PRUNE_STRIDE 章执行一次。非节流章判「不精简」→ route_after_prune_ask
    # 走 END。与伏笔精简共用同一步长（后端全局生效，不感知前端自动模式）。
    chapter_no = state.total_chapters_written
    if not should_prune_at_chapter(chapter_no):
        _logger.info(
            "卡库精简·节流跳过：第%d章 未到步长 %d 的整数倍", chapter_no, PRUNE_STRIDE
        )
        return {"entity_cards_prune_enabled": False}

    answer = interrupt(
        {
            "type": InterruptType.ENTITY_CARDS_PRUNE_ASK.value,
            "message": "是否对实体卡库进行精简？\n\n提示：精简将由AI分析并建议删除一次性碎屑、彻底离场且无复现价值的卡，抑制人物档案/装备清单持续膨胀。",
        }
    )
    # 空字符串 / 否 / no / n → 不精简；其他 → 精简
    answer_str = str(answer or "").strip().lower()
    do_prune = answer_str not in _SKIP_WORDS and answer_str != ""
    _logger.info(
        "卡库精简·询问：用户答=%r → %s",
        answer_str,
        "执行精简" if do_prune else "跳过（不精简）",
    )
    return {"entity_cards_prune_enabled": do_prune}


def entity_cards_prune_analyze(state) -> dict:
    """调用 LLM 分析整个卡库，给出建议删除清单（人工只是默认预选，可再增删）。"""
    cards = state.entity_cards or []
    if not cards:
        return {
            "entity_cards_prune_suggestion": {
                "card_count": 0,
                "to_delete": [],
                "suggestion": "卡库为空，无需精简",
            }
        }

    try:
        recent_summaries = "\n".join(
            state.all_chapter_summaries[-3:]
            if len(state.all_chapter_summaries) >= 3
            else state.all_chapter_summaries
        )
        all_titles_str = "\n".join(
            f"第{i + 1}章：{title}" for i, title in enumerate(state.all_chapter_titles)
        )

        prompt = ENTITY_CARDS_PRUNE_ANALYSIS_PROMPT.format(
            recent_summaries=recent_summaries or "（暂无章节概要）",
            all_titles_count=len(state.all_chapter_titles),
            all_titles=all_titles_str or "（暂无章节标题）",
            world_building=state.world_building or "（暂无世界观设定）",
            card_count=len(cards),
            cards_json=format_cards_digest_for_prune(cards),
        )

        # 结构化分类（输出 JSON 删除建议），结果还经 confirm 让用户勾选兜底：关闭深度思考加速。
        # system 走 build_system(SystemRole.ENTITY_LIBRARIAN)：身份文本单点定义在 render._ROLE_TEXT。
        from noval_workflow.prompts.render import SystemRole, build_system

        llm = get_llm(temperature=0.3, label="entity_cards_prune", thinking="disabled")
        prune_system = build_system(
            SystemRole.ENTITY_LIBRARIAN,
            "分析卡库并给出删除建议",
        )
        messages = [
            SystemMessage(content=prune_system),
            HumanMessage(content=prompt),
        ]
        suggestion = invoke_json(llm, messages, kind=dict, label="entity_cards_prune")
        _logger.info(
            "卡库精简分析完成，建议删除 %d 张",
            len(suggestion.get("to_delete", []) or []),
        )
        return {"entity_cards_prune_suggestion": suggestion}

    except Exception as e:
        # 分析失败不中断流程：给空建议，confirm 仍会展示全库让用户手动勾选（不同于伏笔——这里照样弹 UI）。
        # 仍以 error 级 + traceback 落盘，便于定位 LLM/解析问题。
        _logger.error(
            "卡库精简·分析失败（confirm 仍展示全库供手动勾选）: %s", e, exc_info=True
        )
        return {
            "entity_cards_prune_suggestion": {
                "card_count": len(cards),
                "to_delete": [],
                "suggestion": "分析失败，可手动勾选",
            }
        }


def entity_cards_prune_confirm(state) -> dict:
    """展示**全部**卡，预选 AI 建议删除的，让用户增减后确认整卡删除。"""
    suggestion = state.entity_cards_prune_suggestion or {}
    to_delete = suggestion.get("to_delete", []) or []
    # AI 建议删除的实体名 → 原因，供前端预选 + 展示理由
    suggested: dict[str, str] = {}
    for d in to_delete:
        if isinstance(d, dict) and d.get("name"):
            suggested[str(d["name"])] = str(d.get("reason", ""))

    # 组装全库清单（每卡带判定所需字段 + 是否 AI 建议删 + 建议理由）
    items = []
    for card in state.entity_cards or []:
        name = _card_text(card, "name")
        if not name:
            continue
        items.append(
            {
                "name": name,
                "type": _card_text(card, "type"),
                "role": _card_text(card, "role"),
                "summary": _card_text(card, "summary"),
                "current_state": _card_text(card, "current_state"),
                "first_appear_chapter": _card_get(card, "first_appear_chapter", None),
                "suggested": name in suggested,
                "reason": suggested.get(name, ""),
            }
        )

    answer = interrupt(
        {
            "type": InterruptType.ENTITY_CARDS_PRUNE_CONFIRM.value,
            "message": "请勾选要从卡库删除的实体（已预选 AI 建议删除的，可增减后提交）。",
            "cards": items,
            "suggestion": suggestion.get("suggestion", ""),
            "suggested_count": len(suggested),
            "total_count": len(items),
        }
    )

    # answer 是用户提交的 JSON 字符串数组（选中的实体名），如 "[\"张三\", \"遣散费\"]"
    try:
        if isinstance(answer, str) and answer.strip():
            selected = json.loads(answer)
        elif isinstance(answer, list):
            selected = answer
        else:
            selected = []
    except (json.JSONDecodeError, TypeError):
        selected = []
    if not isinstance(selected, list):
        selected = []

    _logger.info(
        "卡库精简：全库 %d 张，AI 建议删 %d，用户确认删 %d",
        len(items),
        len(suggested),
        len(selected),
    )
    return {"entity_cards_prune_selected": [str(k) for k in selected]}


def entity_cards_prune_apply(state) -> dict:
    """按用户勾选的实体名整卡从卡库移除，覆盖写回 entity_cards。"""
    selected = set(state.entity_cards_prune_selected)
    if not selected:
        return {}  # 没勾选任何卡，不改动

    cards = state.entity_cards or []
    kept = [c for c in cards if _card_text(c, "name") not in selected]
    dropped = len(cards) - len(kept)
    _logger.info("卡库精简落地：保留 %d 张，删除 %d 张", len(kept), dropped)
    # entity_cards 无 reducer（覆盖语义），返回过滤后整表即完成删除
    return {"entity_cards": kept}


# ── routing ───────────────────────────────────────────────────────────────────


def route_after_prune_ask(state) -> str:
    if state.entity_cards_prune_enabled:
        return "entity_cards_prune_analyze"
    return END


def route_after_prune_analyze(state) -> str:
    # 卡库非空就进 confirm（即便 AI 没给建议，也让用户手动勾选）；空库直接结束。
    if state.entity_cards:
        _logger.info("卡库精简·路由：卡库 %d 张 → 弹确认 UI", len(state.entity_cards))
        return "entity_cards_prune_confirm"
    _logger.info("卡库精简·路由：卡库为空 → 跳过确认 UI")
    return END


# ── graph assembly ────────────────────────────────────────────────────────────


def _build_entity_cards_prune_subgraph():
    builder = StateGraph(EntityCardsPruneSubState)

    builder.add_node("entity_cards_prune_ask", entity_cards_prune_ask)
    builder.add_node("entity_cards_prune_analyze", entity_cards_prune_analyze)
    builder.add_node("entity_cards_prune_confirm", entity_cards_prune_confirm)
    builder.add_node("entity_cards_prune_apply", entity_cards_prune_apply)

    builder.set_entry_point("entity_cards_prune_ask")

    builder.add_conditional_edges(
        "entity_cards_prune_ask",
        route_after_prune_ask,
        {"entity_cards_prune_analyze": "entity_cards_prune_analyze", END: END},
    )
    builder.add_conditional_edges(
        "entity_cards_prune_analyze",
        route_after_prune_analyze,
        {"entity_cards_prune_confirm": "entity_cards_prune_confirm", END: END},
    )
    builder.add_edge("entity_cards_prune_confirm", "entity_cards_prune_apply")
    builder.add_edge("entity_cards_prune_apply", END)

    return builder.compile()


# 预编译，作为独立节点挂在 chapter_edit_subgraph 链的 entity_discover_step 之后
entity_cards_prune_step = _build_entity_cards_prune_subgraph()
