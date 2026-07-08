"""设定一致性总审闸门（save_config 冻结前的最后一道跨设定关卡）。

放在脑爆链与常规链的汇合点之后（save_initial_status → 本闸门 → save_config），
对已定稿的全部底层设定（核心主题 / 世界观 / 核心冲突 / 整体大纲 / 人物档案 / 第0章基线）
做一次整体系统交叉体检——揪出跨设定矛盾、因果断链、逻辑降智，在冻结前切断对全线大纲的污染。
复活了 review_shared.FOUNDATION_REVIEW_PROMPT 的初衷（那条 prompt 在真实流程中从未触发）。

轻量双节点 mini-loop（不复用 review_subgraph——它三节点都绑 current_draft「审单份草稿」，
而这里要「审一组已定稿字段」，语义拧巴且会重生成内容）。严格套用本仓「只调 LLM 的节点」与
「只 interrupt 的节点」拆分范式（见 brainstorm.py / subgraph.py），保证 interrupt resume
重放不会重复调 LLM：

- audit_consistency：只调 LLM 产报告，无 interrupt → 作为 gate 的上游，resume 时不被重放。
- consistency_gate：只 interrupt 等人工决定，无 LLM → resume 重放幂等且廉价。

所有节点保持同步 def（与全仓一致：LangGraph 在线程池跑同步节点，阻塞式 .invoke() 不阻塞事件循环）。
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from noval_workflow.interrupt_types import InterruptType
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    CONSISTENCY_AUDIT_PROMPT,
    CONSISTENCY_AUDIT_SYSTEM_PROMPT,
)
from noval_workflow.state import NovelState

_logger = logging.getLogger(__name__)

# 重审轮数上限：达此轮数强制放行，杜绝「反复重审卡死冻结」。仅作安全阀，正常由人工「通过冻结」出闸。
_MAX_AUDIT_ROUNDS = 5

# 前端 entry_gate 复用：跳过(SKIP_VALUE="")=通过冻结；执行(EXECUTE_VALUE="yes")=重新审查。
# 这里识别「重新审查」信号，其余（含空串「跳过」）一律视为「通过冻结」。
_REDO_SIGNALS = frozenset({"yes", "y", "执行", "重新审查", "重审", "redo"})


def _collect_foundation(state: NovelState) -> str:
    """把已定稿的底层设定拼成只读审计材料（字段顺序对齐 context.build_foundation_context）。

    仅纳入非空字段。phase_summary 是 save_initial_status 刚写入的第0章能力基线，一并纳入
    交叉核对（人物能力是否越出世界观体系）；其余动态快照此刻为空、不产生噪音。
    """
    sections = [
        ("核心主题与立意", state.core_theme),
        ("世界观设定", state.world_building),
        ("核心冲突", state.core_conflicts),
        ("整体大纲与结局", state.overall_outline),
        ("人物档案", state.character_profiles),
        ("阶段固化数据（第0章基线）", state.phase_summary),
    ]
    parts = [f"## 【{name}】\n{val.strip()}" for name, val in sections if val and val.strip()]
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
        llm = get_llm(temperature=0.3, label="consistency_audit")
        report = llm.invoke([
            SystemMessage(content=CONSISTENCY_AUDIT_SYSTEM_PROMPT),
            HumanMessage(content=CONSISTENCY_AUDIT_PROMPT.format(draft=settings)),
        ]).content.strip()
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
    """只 interrupt：展示审计报告，等人工「通过冻结 / 重新审查」。无 LLM → resume 重放安全。

    人工决定写回 consistency_pass（覆盖 audit 写入的机器判定）：通过冻结=True、重新审查=False，
    供 route_after_consistency_gate 路由。达 _MAX_AUDIT_ROUNDS 时提示将强制放行（由 router 兜底）。
    """
    count = state.consistency_audit_count
    report = (state.consistency_report or "（无报告）").strip()
    verdict = "本轮未发现跨设定硬伤" if state.consistency_pass else "本轮发现需关注的问题（见下）"
    if count >= _MAX_AUDIT_ROUNDS:
        tail = (
            "· 已达最高审计轮数，点击任意按钮将直接进入正式创作；"
            "如仍有疑虑，请在左侧「编辑当前状态」手动修订设定后再放行。"
        )
    else:
        tail = (
            "· 通过冻结 → 采纳当前设定，进入正式创作\n"
            "· 重新审查 → 请先在左侧「编辑当前状态」就地修改设定，再点此重新体检"
        )
    message = (
        f"【设定一致性总审 · 第 {count} 轮】{verdict}\n\n"
        f"{report}\n\n"
        "────────\n"
        f"{tail}"
    )
    decision = interrupt({
        "type": InterruptType.CONSISTENCY_GATE.value,
        "message": message,
    })
    redo = str(decision or "").strip().lower() in _REDO_SIGNALS
    return {"consistency_pass": not redo}


def route_after_consistency_gate(state: NovelState) -> str:
    """人工选「重新审查」且未达轮数上限 → 回 audit_consistency 复审；否则 → save_config 冻结。"""
    if not state.consistency_pass and state.consistency_audit_count < _MAX_AUDIT_ROUNDS:
        return "audit_consistency"
    return "save_config"
