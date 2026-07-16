"""章末实体发现·入库筛选子图（post-review 后处理，挂在 _ENTITY_DISCOVER_STEP）。

拓扑（入口条件判断，出口 END；由工厂 add_edge("post_review", "step_save") 兜到保存）：
  (conditional entry)
    ↓ 草稿无 new_cards / updates（纯过场章）→ END（不打扰用户）
    ↓ 有可选项 → entity_select_confirm (interrupt: 展示清单，人工勾选默认全选)
        ↓
      entity_select_apply (按勾选过滤 current_draft) → END

设计动机：LLM 章末实体发现常把一次性碎屑（遣散费、情绪道具、一幕 NPC）也建卡，
入库后每章注入写作上下文、持续膨胀。这里在落库前让人工勾选真正入库的项，未选中的
从 current_draft 里剔除——_save_entity_discover 原样消费过滤后的草稿，无需改动。

与 foreshadow_prune_subgraph 同构，复用 make_edit_step_subgraph 的 post_review_subgraph
扩展点；差别是本流程无「是否筛选」询问（用户要求每次都弹清单、默认全选）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph

from noval_workflow.edit_step_subgraph import EditStepSubState
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import repair_and_parse
from langgraph.types import interrupt

_logger = logging.getLogger(__name__)

# 勾选 key 前缀：new_cards 与 updates 各自按 name 生成稳定 key，避免同名跨类碰撞
# （update 定位已有卡、new_card 是新实体，名字本不应撞，但显式前缀更稳）。
_NEW_PREFIX = "new:"
_UPDATE_PREFIX = "update:"

# update 里除 name 外的键即「本条改了哪些动态字段」，展示给用户判断该不该入库
_UPDATE_META_KEYS = frozenset({"name"})


@dataclass
class EntityDiscoverSubState(EditStepSubState):
    """章末实体发现步骤专用 state：在通用 EditStepSubState 之上补入库筛选字段。

    作为 post_review 嵌套子图时，父子两层图都必须用本类编译，否则 langgraph 按同名字段
    桥接时 entity_select_selected 不在 schema 里、更新被丢弃（详见 make_edit_step_subgraph
    的 state_cls 说明）。
    """
    # 用户勾选保留（入库）的项 key 列表，如 ["new:圣焰皇家骑士团", "update:陆默"]
    entity_select_selected: list[str] = field(default_factory=list)


def _parse_draft(draft) -> dict:
    """把 current_draft 解析成 {new_cards, updates} dict（草稿是 LLM 输出的 JSON 字符串）。"""
    data = repair_and_parse(draft, kind=dict) if isinstance(draft, str) else draft
    return data if isinstance(data, dict) else {}


# ── 节点 ──────────────────────────────────────────────────────────────────────
# ⚠️ 节点闭包不写 state 类型注解：LangGraph 会按第一个参数的注解窄化传入的 state，
# 写基类就丢掉子类字段。不写注解 → 回退到编译时的图 schema（EntityDiscoverSubState）。

def entity_select_confirm(state) -> dict:
    """展示本章发现的 new_cards / updates 清单，让用户勾选真正入库的项。"""
    data = _parse_draft(state.current_draft)
    new_cards = data.get("new_cards", []) or []
    updates = data.get("updates", []) or []

    # 组装给前端渲染的选项：new_cards 给 name/type/summary，updates 给 name + 改动字段
    new_items = [
        {
            "key": f"{_NEW_PREFIX}{c.get('name', '')}",
            "name": c.get("name", ""),
            "type": c.get("type", ""),
            "summary": c.get("summary", ""),
        }
        for c in new_cards
    ]
    update_items = [
        {
            "key": f"{_UPDATE_PREFIX}{u.get('name', '')}",
            "name": u.get("name", ""),
            # 除 name 外的键即本条改动的动态字段，拼成 "字段: 新值" 供人工判断
            "changes": {k: v for k, v in u.items() if k not in _UPDATE_META_KEYS},
        }
        for u in updates
    ]

    answer = interrupt({
        "type": InterruptType.ENTITY_SELECT_CONFIRM.value,
        "message": "请勾选本章要入库的实体（默认全选，取消一次性碎屑/过场项后提交）。",
        "new_cards": new_items,
        "updates": update_items,
    })

    # answer 是用户提交的 JSON 字符串数组（选中的 key），如 "[\"new:圣焰皇家骑士团\"]"
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

    _logger.info("入库筛选：候选 %d 新卡 + %d 更新，用户选中 %d 项",
                 len(new_items), len(update_items), len(selected))
    return {"entity_select_selected": [str(k) for k in selected]}


def entity_select_apply(state) -> dict:
    """按用户勾选过滤 current_draft，未选中的 new_cards / updates 剔除后写回。"""
    selected = set(state.entity_select_selected)
    data = _parse_draft(state.current_draft)
    new_cards = data.get("new_cards", []) or []
    updates = data.get("updates", []) or []

    kept_new = [c for c in new_cards if f"{_NEW_PREFIX}{c.get('name', '')}" in selected]
    kept_updates = [u for u in updates if f"{_UPDATE_PREFIX}{u.get('name', '')}" in selected]

    dropped = (len(new_cards) - len(kept_new)) + (len(updates) - len(kept_updates))
    _logger.info("入库筛选落地：保留 %d 新卡 + %d 更新，剔除 %d 项",
                 len(kept_new), len(kept_updates), dropped)

    data["new_cards"] = kept_new
    data["updates"] = kept_updates
    # 回写 JSON 字符串——_save_entity_discover 按字符串消费
    return {"current_draft": json.dumps(data, ensure_ascii=False, indent=2)}


# ── routing ───────────────────────────────────────────────────────────────────

def route_should_select(state) -> str:
    """草稿无任何 new_cards / updates（纯过场章）→ 直接 END，不弹空清单打扰用户。"""
    data = _parse_draft(state.current_draft)
    if (data.get("new_cards") or []) or (data.get("updates") or []):
        return "entity_select_confirm"
    return END


# ── graph assembly ────────────────────────────────────────────────────────────

def _build_entity_select_subgraph():
    builder = StateGraph(EntityDiscoverSubState)

    builder.add_node("entity_select_confirm", entity_select_confirm)
    builder.add_node("entity_select_apply", entity_select_apply)

    builder.set_conditional_entry_point(
        route_should_select,
        {"entity_select_confirm": "entity_select_confirm", END: END},
    )
    builder.add_edge("entity_select_confirm", "entity_select_apply")
    builder.add_edge("entity_select_apply", END)

    return builder.compile()


# 预编译，供 _ENTITY_DISCOVER_STEP 作为 post_review_subgraph 挂载
entity_select_step = _build_entity_select_subgraph()
