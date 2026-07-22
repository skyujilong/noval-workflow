"""端到端回归：章末长线章节规划调整子图（弧线自动派生跟随，二者不分叉）。

锁定的核心不变量：
  1. mid-batch 调 chapter_plan → 弧线基于「更新后的 chapter_plan 本批切片」重出（不分叉）。
  2. 历史章条目（chapter <= done）永久锁定，逐字不变。
  3. chapter_plan_planned_upto 不被 mid-batch 编辑推进（不破坏 STRIDE 滚动记账）。
  4. 剩余章节标题随新弧线重生成。
  5. 跳过 gate / chapter_plan 为空 → 全不改动。
  6. AI 输出坏 JSON → 走手动兜底，不污染 parent chapter_plan。

用真实子图 + 内存 checkpointer 驱动 interrupt 序列（Command(resume=...)），mock get_llm。
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

import noval_workflow.chapter_plan_edit_subgraph as cpe
from noval_workflow.chapter_plan_edit_subgraph import (
    ChapterPlanEditSubState,
    make_chapter_plan_edit_subgraph,
)
from noval_workflow.state import ChapterPlanItem


def _compiled():
    """把编辑子图嵌进一个带 checkpointer 的父图（复刻生产装配），以支持 interrupt/resume。"""
    sub = make_chapter_plan_edit_subgraph()
    b = StateGraph(ChapterPlanEditSubState)
    b.add_node("cp", sub)
    b.set_entry_point("cp")
    b.add_edge("cp", END)
    return b.compile(checkpointer=MemorySaver())


# written=2、批 1-5、下一章=第3章；chapter_plan 覆盖 1..8（planned_upto=8）
_DONE = 2
_PLANNED_UPTO = 8
_BATCH_TITLES = ["旧标题1", "旧标题2", "旧标题3", "旧标题4", "旧标题5"]
_REWRITE_MARK = "主角提前暴露身份"


def _init_plan() -> list[ChapterPlanItem]:
    return [
        ChapterPlanItem(
            chapter=i,
            purpose=f"旧目标{i}",
            key_turn=f"旧转折{i}",
            ending_hook=f"旧钩子{i}",
            intensity="推进",
        )
        for i in range(1, _PLANNED_UPTO + 1)
    ]


class _FakeLLM:
    """按 label 分派确定输出：
    - rewrite:      输出未写段 [3..8] 的 JSON（purpose 带 _REWRITE_MARK 标记新方向）
    - derive_arc:   回显收到的 HumanMessage（含更新后的锚点块）——便于断言弧线来自新 plan
    - generate_titles: 按剩余章数输出对应行数标题

    可选参数：
    - bad_json=True: rewrite 始终返回畸形 JSON（验证 3 次重试全挂 → CONFIRM_ERROR）
    - empty_before_ok=N: rewrite 前 N 次返回空 content，之后正常（验证 gateway 兜住偶发抽风）
    """

    def __init__(
        self,
        label: str,
        *,
        bad_json: bool = False,
        empty_before_ok: int = 0,
    ) -> None:
        self.label = label
        self.bad_json = bad_json
        self.empty_before_ok = empty_before_ok
        self._invoke_count = 0

    def invoke(self, messages):
        self._invoke_count += 1
        human = messages[-1].content
        if self.label.startswith("chapter_plan_edit:rewrite"):
            if self.bad_json:
                return AIMessage(content="这不是 JSON {[")
            # 前 N 次空 content：模拟 LLM 单次抽风 → gateway 回喂 + 重试
            if self._invoke_count <= self.empty_before_ok:
                return AIMessage(content="")
            arr = [
                {
                    "chapter": i,
                    "purpose": f"{_REWRITE_MARK}-新目标{i}",
                    "key_turn": f"新转折{i}",
                    "ending_hook": f"新钩子{i}",
                    "intensity": "转折",
                }
                for i in range(_DONE + 1, _PLANNED_UPTO + 1)
            ]
            return AIMessage(content=json.dumps(arr, ensure_ascii=False))
        if self.label.startswith("chapter_plan_edit:derive_arc"):
            return AIMessage(content="【新弧线】\n" + human)
        if self.label.startswith("chapter_plan_edit:generate_titles"):
            # 剩余 3 章 → 3 行
            return AIMessage(content="新标题3\n新标题4\n新标题5")
        return AIMessage(content="")


def _install_llm(monkeypatch, *, bad_json: bool = False, empty_before_ok: int = 0):
    monkeypatch.setattr(
        cpe,
        "get_llm",
        lambda *a, **k: _FakeLLM(
            k.get("label", ""),
            bad_json=bad_json,
            empty_before_ok=empty_before_ok,
        ),
    )


def _mk_state(**over) -> ChapterPlanEditSubState:
    base = dict(
        novel_name="测试书",
        genre="玄幻",
        overall_outline="整书大纲……",
        current_batch_titles=list(_BATCH_TITLES),
        current_chapter_index=_DONE,  # 已写 2 章 → 下一章 index=2（第3章）
        total_chapters_written=_DONE,
        all_chapter_titles=["旧标题1", "旧标题2"],
        all_chapter_summaries=["摘要1", "摘要2"],
        current_arc_outline="旧弧线大纲",
        chapter_plan=_init_plan(),
        chapter_plan_planned_upto=_PLANNED_UPTO,
    )
    base.update(over)
    return ChapterPlanEditSubState(**base)


def _pending_type(graph, config) -> str:
    tasks = graph.get_state(config).tasks
    return tasks[0].interrupts[0].value["type"] if tasks and tasks[0].interrupts else ""


def test_edit_chapter_plan_then_arc_follows(monkeypatch):
    """完整走一遍：调 chapter_plan → 弧线派生自更新后的 plan → 标题跟随；历史锁定、planned_upto 不动。"""
    _install_llm(monkeypatch)
    graph = _compiled()
    config = {"configurable": {"thread_id": "t-cpe-1"}}

    graph.invoke(_mk_state(), config)
    assert _pending_type(graph, config) == "chapter_plan_edit_entry_gate"

    graph.invoke(Command(resume="yes"), config)  # 执行 gate
    assert _pending_type(graph, config) == "chapter_plan_edit_direction"

    graph.invoke(Command(resume="让主角提前暴露身份"), config)  # 输入方向 → rewrite
    assert _pending_type(graph, config) == "chapter_plan_edit_confirm"

    graph.invoke(
        Command(resume=""), config
    )  # 接受 → writeback + rederive + titles regen
    assert _pending_type(graph, config) == "arc_titles_confirm"

    final = graph.invoke(Command(resume=""), config)  # 接受标题 → END

    plan = final["chapter_plan"]
    assert [p.chapter for p in plan] == list(range(1, _PLANNED_UPTO + 1))
    # ② 历史锁定：1..2 逐字不变
    assert plan[0].purpose == "旧目标1" and plan[1].purpose == "旧目标2"
    # ① 未写段 3..8 被改写为新方向
    assert all(_REWRITE_MARK in plan[i].purpose for i in range(_DONE, _PLANNED_UPTO))
    # ③ planned_upto 不被 mid-batch 编辑推进
    assert final["chapter_plan_planned_upto"] == _PLANNED_UPTO
    # ① 关键：弧线派生自「更新后的 plan 本批切片(1..5)」——含第3章新方向标记 → 不分叉
    arc = final["current_arc_outline"]
    assert _REWRITE_MARK in arc, "弧线未跟随更新后的 chapter_plan（分叉了）"
    # 弧线切片只覆盖本批（batch 1..5），不应带入第 6 章之后的远端锚点
    assert "第6章" not in arc and "第7章" not in arc
    # ④ 剩余章标题（第3-5章）随新弧线重生成
    assert final["current_batch_titles"] == [
        "旧标题1",
        "旧标题2",
        "新标题3",
        "新标题4",
        "新标题5",
    ]


def test_skip_gate_changes_nothing(monkeypatch):
    """跳过 gate（回车/no）→ chapter_plan 与弧线均不变。"""
    _install_llm(monkeypatch)
    graph = _compiled()
    config = {"configurable": {"thread_id": "t-cpe-skip"}}
    graph.invoke(_mk_state(), config)
    final = graph.invoke(Command(resume="no"), config)
    assert [p.purpose for p in final["chapter_plan"]] == [
        f"旧目标{i}" for i in range(1, _PLANNED_UPTO + 1)
    ]
    assert final["current_arc_outline"] == "旧弧线大纲"


def test_empty_chapter_plan_skips_without_interrupt(monkeypatch):
    """chapter_plan 为空（未启用/未生成）→ 直接跳过，不进 interrupt，弧线不变。"""
    _install_llm(monkeypatch)
    graph = _compiled()
    config = {"configurable": {"thread_id": "t-cpe-empty"}}
    final = graph.invoke(
        _mk_state(chapter_plan=[], chapter_plan_planned_upto=0), config
    )
    # 无 pending interrupt（跑到 END）
    assert not graph.get_state(config).tasks
    assert final["current_arc_outline"] == "旧弧线大纲"


def test_bad_json_falls_back_without_polluting(monkeypatch):
    """AI 输出坏 JSON → 走手动兜底 interrupt；用户跳过 → parent chapter_plan 不被污染。"""
    _install_llm(monkeypatch, bad_json=True)
    graph = _compiled()
    config = {"configurable": {"thread_id": "t-cpe-bad"}}
    graph.invoke(_mk_state(), config)
    graph.invoke(Command(resume="yes"), config)
    graph.invoke(Command(resume="随便一个方向"), config)  # rewrite 出坏 JSON
    assert _pending_type(graph, config) == "chapter_plan_edit_confirm_error"
    final = graph.invoke(Command(resume=""), config)  # 手动兜底也跳过 → 不改动
    assert [p.purpose for p in final["chapter_plan"]] == [
        f"旧目标{i}" for i in range(1, _PLANNED_UPTO + 1)
    ]
    assert final["current_arc_outline"] == "旧弧线大纲"


def test_rewrite_empty_content_recovers_via_gateway_retry(monkeypatch):
    """LLM 前 2 次返回空 content → invoke_pydantic_list 回喂重试 → 第 3 次成功。

    锁定的是关键路径：不走 CONFIRM_ERROR 分支、直达正常 CONFIRM，让用户几乎无感。
    覆盖原始 bug 场景：`AI 重规划失败：修复后顶层不是 list（得到 str）；原文：''`
    """
    _install_llm(monkeypatch, empty_before_ok=2)  # 前 2 次空 → 第 3 次成功
    graph = _compiled()
    config = {"configurable": {"thread_id": "t-cpe-retry"}}

    graph.invoke(_mk_state(), config)
    graph.invoke(Command(resume="yes"), config)
    graph.invoke(Command(resume="让主角提前暴露身份"), config)

    # 关键断言：走正常 CONFIRM，不进 CONFIRM_ERROR
    assert _pending_type(graph, config) == "chapter_plan_edit_confirm"

    # 接受 → 走完整流程；未写段应含 _REWRITE_MARK（第 3 次成功输出的 JSON）
    graph.invoke(Command(resume=""), config)
    final = graph.invoke(Command(resume=""), config)
    plan = final["chapter_plan"]
    assert all(_REWRITE_MARK in plan[i].purpose for i in range(_DONE, _PLANNED_UPTO))
