"""设定一致性总审闸门（save_config 冻结前的最后一道跨设定关卡）。

放在脑爆链与常规链的汇合点之后（save_initial_status → 本闸门 → save_config），
对已定稿的全部底层设定（核心主题 / 世界观 / 核心冲突 / 整体大纲 / 人物档案 / 第0章基线）
做一次整体系统交叉体检——揪出跨设定矛盾、因果断链、逻辑降智，在冻结前切断对全线大纲的污染。

轻量多节点 mini-loop（不复用 review_subgraph——它三节点都绑 current_draft「审单份草稿」，
而这里要「审一组已定稿字段」，语义拧巴且会重生成内容）。严格套用本仓「只调 LLM 的节点」与
「只 interrupt 的节点」拆分范式（见 brainstorm.py / subgraph.py），保证 interrupt resume
重放不会重复调 LLM：

- audit_consistency：只调 LLM 产报告，无 interrupt → 作为 gate 的上游，resume 时不被重放。
- consistency_gate：只 interrupt 等人工决定「通过冻结 / 让 AI 修订 / 重新审查」，无 LLM。
- revise_consistency：只调 LLM，依据审计报告改写涉事设定项，产出修订提案，无 interrupt。
- consistency_diff_gate：只 interrupt，展示改前/改后 diff，等人工「应用（可编辑）/ 放弃」，无 LLM。

「让 AI 修订」闭环：gate →(revise)→ revise_consistency → diff_gate →(应用)→ audit_consistency
复审一轮 → gate，让人工看到修订是否真的消除了问题，再决定冻结。

所有节点保持同步 def（与全仓一致：LangGraph 在线程池跑同步节点，阻塞式 .invoke() 不阻塞事件循环）。
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from noval_workflow.config import MAX_AUDIT_ROUNDS as _MAX_AUDIT_ROUNDS
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import invoke_json
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    CONSISTENCY_AUDIT_PROMPT,
    CONSISTENCY_REVISE_PROMPT,
)
from noval_workflow.state import NovelState

_logger = logging.getLogger(__name__)

# 底层设定字段表（顺序对齐 context.build_foundation_context）：(state 属性名, 中文标签)。
# 审计材料、AI 修订材料、以及应用修订时的白名单都由此单一来源派生。
_FOUNDATION_FIELDS: list[tuple[str, str]] = [
    ("core_theme", "核心主题与立意"),
    ("world_building", "世界观设定"),
    ("power_system", "力量体系"),
    ("core_conflicts", "核心冲突"),
    ("overall_outline", "整体大纲与结局"),
    ("phase_summary", "阶段固化数据（第0章基线）"),
]
# 人物档案真源已迁至 entity_cards（CharacterCard），是 list 不是可修订 str 字段——故不进
# 上面的字段表/_REVISABLE_FIELDS 白名单，只在 _collect_foundation 里从卡库渲染进只读审计材料。
# 允许被 AI 修订应用回写的字段白名单（key → 标签）：拦掉任何越界写入。
_REVISABLE_FIELDS: dict[str, str] = dict(_FOUNDATION_FIELDS)

# 前端语义化按钮：通过冻结(freeze) / 让 AI 修订(revise) / 重新审查(reaudit)。
# 兼容旧值：空串「跳过」= 冻结；"yes"「执行」= 重新审查（历史 entry_gate 复用遗留）。
_REDO_SIGNALS = frozenset({"yes", "y", "执行", "重新审查", "重审", "redo", "reaudit"})
_REVISE_SIGNALS = frozenset(
    {"revise", "修订", "ai修订", "让ai修订", "ai 修订", "让 ai 修订"}
)


def _collect_foundation(state: NovelState) -> str:
    """把已定稿的底层设定拼成只读审计材料（字段顺序对齐 context.build_foundation_context）。

    仅纳入非空字段。phase_summary 是 save_initial_status 刚写入的第0章能力基线，一并纳入
    交叉核对（人物能力是否越出世界观体系）；其余动态快照此刻为空、不产生噪音。

    装备/物品真源已迁至实体卡库：此处从卡库渲染装备段一并纳入审计（Phase 1 冻结时卡库通常
    为空，此段为空不产生噪音；未来若冻结前已有卡则能被交叉核对）。卡库是 list、不是可修订
    的 str 字段，故只进只读审计材料，不进 _REVISABLE_FIELDS 白名单。
    """
    from noval_workflow.prompts import (
        format_character_profiles_from_cards,
        format_equipment_for_context,
    )

    parts = []
    for key, name in _FOUNDATION_FIELDS:
        val = (getattr(state, key, "") or "").strip()
        if val:
            parts.append(f"## 【{name}】\n{val}")
    cards = getattr(state, "entity_cards", []) or []
    # 人物档案：从卡库渲染深层视图（含全书弧光/底牌契约），供交叉核对人物能力是否越出体系
    profiles = format_character_profiles_from_cards(cards, deep=True)
    if profiles:
        parts.append(f"## 【人物档案（卡库真源）】\n{profiles}")
    equipment = format_equipment_for_context(cards)
    if equipment:
        parts.append(f"## 【实体卡·装备/物品（真源）】\n{equipment}")
    return "\n\n".join(parts)


def _collect_foundation_tagged(state: NovelState) -> str:
    """给 AI 修订用：每段用 [字段key] 标注所属设定项，让模型能按 key 定位并回写。"""
    parts = []
    for key, name in _FOUNDATION_FIELDS:
        val = (getattr(state, key, "") or "").strip()
        if val:
            parts.append(f"## [{key}] {name}\n{val}")
    return "\n\n".join(parts)


def _is_clean(report: str) -> bool:
    """宽松的「无硬伤」判定：空 / 精确「无问题」/ 极短且含「无问题」→ 通过。

    只影响 gate 展示的措辞与前端提示，不作为出闸依据（出闸由人工决定，见 consistency_gate）。
    """
    r = report.strip()
    if not r or r == "无问题":
        return True
    return "无问题" in r and len(r) <= 20


def audit_consistency(state: NovelState) -> dict:
    """只调 LLM：把全部底层设定当成一个系统交叉体检，产报告写 state.consistency_report。

    无 interrupt → 作为 gate 上游，在 gate 处 resume 时本节点不被重放，LLM 不会被重复调用
    （与 brainstorm_respond / subgraph.generate 同一条重放边界）。
    审计失败一律兜底判过、绝不阻断冻结（仿 brainstorm_extract）。
    """
    count = state.consistency_audit_count + 1
    settings = _collect_foundation(state)
    if not settings.strip():
        # 无任何设定可审（异常兜底）→ 直接判过，不阻断。
        return {
            "consistency_report": "（未检测到可审的底层设定，已跳过一致性总审。）",
            "consistency_pass": True,
            "consistency_audit_count": count,
        }
    try:
        # 审计是一次性批判性体检，temperature 对齐 llm_self_review 的 0.3，求稳。
        # system 走 build_system：CONSISTENCY_AUDIT_SYSTEM_PROMPT（终审架构师身份+职责）作 identity，
        # 叠加硬契约 + 优先级约定，让一致性审计也守 L1 底线（架构统一）。
        # system 走 build_system(SystemRole.CONSISTENCY_AUDITOR)——身份文本(终审架构师职责)
        # 单点定义在 render._ROLE_TEXT,与其他 role 一致管理。
        from noval_workflow.prompts.render import SystemRole, build_system

        llm = get_llm(temperature=0.3, label="consistency_audit")
        audit_system = build_system(
            SystemRole.CONSISTENCY_AUDITOR, "对全部底层设定做一致性总审"
        )
        report = llm.invoke(
            [
                SystemMessage(content=audit_system),
                HumanMessage(content=CONSISTENCY_AUDIT_PROMPT.format(draft=settings)),
            ]
        ).content.strip()
    except Exception as e:  # noqa: BLE001 — 审计失败绝不阻断冻结（仿 brainstorm_extract）
        _logger.error("设定一致性审计失败：%s", e)
        return {
            "consistency_report": (
                f"⚠️ 一致性审计未能完成（{e}）。系统未自动发现问题，请人工确认各项设定后放行。"
            ),
            "consistency_pass": True,
            "consistency_audit_count": count,
        }
    return {
        "consistency_report": report,
        "consistency_pass": _is_clean(report),
        "consistency_audit_count": count,
    }


def consistency_gate(state: NovelState) -> dict:
    """只 interrupt：展示审计报告，等人工「通过冻结 / 让 AI 修订 / 重新审查」。无 LLM → resume 重放安全。

    人工决定写回 consistency_action（freeze | revise | reaudit），供 route_after_consistency_gate 路由。
    只有本轮发现问题（consistency_pass=False）才提供「让 AI 修订」。达 _MAX_AUDIT_ROUNDS 时提示强制放行。
    """
    count = state.consistency_audit_count
    report = (state.consistency_report or "（无报告）").strip()
    verdict = (
        "本轮未发现跨设定硬伤"
        if state.consistency_pass
        else "本轮发现需关注的问题（见下）"
    )
    # 达上限后任何按钮都强制冻结，此时不再提供「让 AI 修订」（点了也只会冻结，避免误导）。
    can_revise = not state.consistency_pass and count < _MAX_AUDIT_ROUNDS
    if count >= _MAX_AUDIT_ROUNDS:
        tail = (
            "· 已达最高审计轮数，点击任意按钮将直接进入正式创作；"
            "如仍有疑虑，请在左侧「编辑当前状态」手动修订设定后再放行。"
        )
    else:
        lines = ["· 通过冻结 → 采纳当前设定，进入正式创作"]
        if can_revise:
            lines.append(
                "· 让 AI 修订 → 由 AI 依据上述问题改写涉事设定，改动以 diff 呈现，可逐项编辑后应用"
            )
        lines.append(
            "· 重新审查 → 请先在左侧「编辑当前状态」就地修改设定，再点此重新体检"
        )
        tail = "\n".join(lines)
    # AI 修订未产出可用改动时，上一步 revise_consistency 会留一行提示，前置到报告上方。
    note = (state.consistency_revise_note or "").strip()
    note_block = f"{note}\n\n" if note else ""
    message = (
        f"【设定一致性总审 · 第 {count} 轮】{verdict}\n\n"
        f"{note_block}{report}\n\n"
        "────────\n"
        f"{tail}"
    )
    decision = interrupt(
        {
            "type": InterruptType.CONSISTENCY_GATE.value,
            "message": message,
            "can_revise": can_revise,
        }
    )
    d = str(decision or "").strip().lower()
    if d in _REVISE_SIGNALS:
        action = "revise"
    elif d in _REDO_SIGNALS:
        action = "reaudit"
    else:
        action = "freeze"
    # 读完 note 即清，避免下一轮闸门残留旧提示。
    return {"consistency_action": action, "consistency_revise_note": ""}


def route_after_consistency_gate(state: NovelState) -> str:
    """按人工决定路由：通过冻结→save_config；让 AI 修订→revise_consistency；重新审查→audit_consistency。

    达 _MAX_AUDIT_ROUNDS 一律强制 save_config（安全阀，防反复重审卡死冻结）。
    """
    if state.consistency_audit_count >= _MAX_AUDIT_ROUNDS:
        return "save_config"
    if state.consistency_action == "reaudit":
        return "audit_consistency"
    if state.consistency_action == "revise":
        return "revise_consistency"
    return "save_config"


def revise_consistency(state: NovelState) -> dict:
    """只调 LLM：依据审计报告改写涉事设定项，产出修订提案 consistency_revisions。

    无 interrupt → 作为 diff_gate 上游，resume 时不重放、不重复调 LLM。
    产不出可用修订（无问题 / LLM 异常 / 空结果 / 改动与原文无异）一律兜底空提案 + 一行提示，
    由 route_after_revise 折返回闸门（绝不阻断，仿 audit_consistency）。
    """
    report = (state.consistency_report or "").strip()
    settings = _collect_foundation_tagged(state)
    if _is_clean(report) or not settings.strip():
        return {"consistency_revisions": []}

    _EMPTY_NOTE = "（AI 未提出可用修订，可手动修订设定或直接通过冻结。）"
    try:
        from noval_workflow.prompts.render import SystemRole, build_system

        llm = get_llm(temperature=0.3, label="consistency_revise")
        revise_system = build_system(
            SystemRole.SETTINGS_ENGINEER, "针对问题清单做最小必要修订"
        )
        data = invoke_json(
            llm,
            [
                SystemMessage(content=revise_system),
                HumanMessage(
                    content=CONSISTENCY_REVISE_PROMPT.format(
                        report=report, settings=settings
                    )
                ),
            ],
            kind=dict,
            label="consistency_revise",
        )
    except Exception as e:  # noqa: BLE001 — 修订失败绝不阻断，折返闸门
        _logger.error("设定一致性修订失败：%s", e)
        return {"consistency_revisions": [], "consistency_revise_note": _EMPTY_NOTE}

    raw = data.get("revisions") or []
    revisions = []
    dropped: list[str] = []  # 丢弃原因，供 INFO 日志定位「为何没出 diff」
    for item in raw:
        if not isinstance(item, dict):
            dropped.append("非对象项")
            continue
        key = item.get("field")
        label = _REVISABLE_FIELDS.get(key)
        if label is None:  # 越界 / 非法 field key（模型常误填中文标签）→ 丢弃
            dropped.append(f"越界字段 field={key!r}")
            continue
        after = str(item.get("revised") or "").strip()
        before = (getattr(state, key, "") or "").strip()
        if not after:
            dropped.append(f"{key}: revised 为空")
            continue
        if after == before:  # 与原文一字不差 → 无实际改动，丢弃
            dropped.append(f"{key}: 与原文无异")
            continue
        revisions.append(
            {
                "field": key,
                "label": label,
                "before": before,
                "after": after,
                "reason": str(item.get("reason") or "").strip(),
            }
        )

    # 观测点：diff 闸门只在 revisions 非空时触发；折回闸门时靠这行定位是「模型没给」还是「被过滤光」。
    _logger.info(
        "一致性修订：LLM 返回 %d 条，采纳 %d 条，丢弃 %d 条%s",
        len(raw),
        len(revisions),
        len(dropped),
        "（" + "；".join(dropped) + "）" if dropped else "",
    )

    if not revisions:
        return {"consistency_revisions": [], "consistency_revise_note": _EMPTY_NOTE}
    return {"consistency_revisions": revisions}


def route_after_revise(state: NovelState) -> str:
    """有可用修订 → 进 diff 审核闸门；否则折返回一致性闸门（带一行「AI 未修订」提示）。"""
    return (
        "consistency_diff_gate" if state.consistency_revisions else "consistency_gate"
    )


def consistency_diff_gate(state: NovelState) -> dict:
    """只 interrupt：展示 AI 修订的改前/改后 diff，等人工「应用（可编辑）/ 放弃」。无 LLM → resume 安全。

    resume 值为结构化 dict：
      - {"action":"apply","revisions":[{"field","after"},...]} → 把（可能人工编辑过的）终稿回写对应字段，复审一轮。
      - {"action":"discard"} 或其他 → 放弃修订，折返回闸门（设定不变）。
    """
    revisions = state.consistency_revisions or []
    message = (
        f"AI 依据一致性总审报告提出 {len(revisions)} 处修订。请审核每处改动（可直接编辑修订后文本），"
        "「应用修订」将写回设定并自动复审一轮，「放弃」则不改动任何设定。"
    )
    decision = interrupt(
        {
            "type": InterruptType.CONSISTENCY_DIFF.value,
            "message": message,
            "revisions": revisions,
        }
    )

    action = (
        decision.get("action")
        if isinstance(decision, dict)
        else str(decision or "").strip().lower()
    )
    if action == "apply":
        items = decision.get("revisions") or [] if isinstance(decision, dict) else []
        edits = {
            item["field"]: str(item.get("after") or "")
            for item in items
            if isinstance(item, dict)
            and item.get("field") in _REVISABLE_FIELDS
            and str(item.get("after") or "").strip()
        }
        return {**edits, "consistency_action": "apply", "consistency_revisions": []}
    return {"consistency_action": "discard", "consistency_revisions": []}


def route_after_diff_gate(state: NovelState) -> str:
    """应用修订 → 回 audit_consistency 复审一轮（验证问题是否消除）；放弃 → 折返回闸门。"""
    return (
        "audit_consistency"
        if state.consistency_action == "apply"
        else "consistency_gate"
    )
