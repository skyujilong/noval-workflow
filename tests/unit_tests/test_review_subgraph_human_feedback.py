"""回归测试：人工审核意见必须贯穿到 llm_self_review。

复现并锁定的 bug：human_review 打回后，generate 会把 review_feedback 清空为 ""，
而 llm_self_review 原先靠 review_feedback 触发「最高优先级：人工审核意见」强调块——
于是该块永远拿不到人工意见（死代码），自审阶段丢失人工审核意见。

修复：新增持久字段 human_feedback，由 human_review 写入/重置，generate 不清空，
llm_self_review 改读 human_feedback。本测试用真实节点 + 内存 checkpointer 端到端跑
「首次生成 → 自审通过 → 人工打回 → 重写 → 自审」，断言重写后的自审 prompt 里带上了人工意见。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.types import Command

from noval_workflow import subgraph as sg
from noval_workflow.state import ReviewSubState

HUMAN_FB = "主角性格太单薄，请补充成长动机与一个关键弱点。"


class _FakeLLM:
    """记录每次 invoke 的 (label, messages)，并按调用方返回确定内容。

    - self_review:* 默认返回「无问题」→ _is_pass 命中 → 流程转人工，便于稳定推进；
                    传 self_review_reply 可让自审返回具体意见（触发机器审核循环）。
    - generate:*    返回一段占位正文。
    """

    def __init__(
        self, label: str, recorder: list, self_review_reply: str = "无问题"
    ) -> None:
        self.label = label
        self.recorder = recorder
        self.self_review_reply = self_review_reply

    def invoke(self, messages):
        self.recorder.append((self.label, list(messages)))
        if self.label.startswith("self_review:"):
            return AIMessage(content=self.self_review_reply)
        n = sum(1 for lbl, _ in self.recorder if lbl.startswith("generate:"))
        return AIMessage(content=f"人物档案第{n}版：主角、配角、反派的设定正文。")


def _build_graph():
    """用被测的真实节点重建子图（与 subgraph.py 拓扑一致），挂内存 checkpointer 以支持 interrupt。"""
    b = StateGraph(ReviewSubState)
    b.add_node("generate", sg.generate)
    b.add_node("llm_self_review", sg.llm_self_review)
    b.add_node("human_review", sg.human_review)
    b.set_entry_point("generate")
    b.add_edge("generate", "llm_self_review")
    b.add_conditional_edges("llm_self_review", sg.route_after_llm_review)
    b.add_conditional_edges("human_review", sg.route_after_human)
    return b.compile(checkpointer=MemorySaver())


def _texts(messages: list[BaseMessage]) -> str:
    return "\n".join(str(getattr(m, "content", "")) for m in messages)


def test_human_feedback_reaches_self_review(monkeypatch):
    recorder: list = []
    monkeypatch.setattr(
        sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder)
    )

    graph = _build_graph()
    config = {"configurable": {"thread_id": "t-char"}}
    init = ReviewSubState(
        review_type="core_theme",
        system_prompt="SYSTEM_CONTEXT_角色",
        task_prompt="请生成主要人物档案。",
    )

    # ① 首次生成 → 自审通过 → 停在 human_review
    graph.invoke(init, config)

    # ② 人工打回（带修改意见 + 深度思考）→ 重写 → 自审 → 再次停在 human_review
    graph.invoke(Command(resume={"feedback": HUMAN_FB, "thinking": "enabled"}), config)

    self_reviews = [msgs for lbl, msgs in recorder if lbl.startswith("self_review:")]
    assert len(self_reviews) == 2, "应有两次自审：首次生成后 + 打回重写后"

    # 首次自审（打回前）不应含人工意见——此时还没有人工输入
    assert HUMAN_FB not in _texts(self_reviews[0])

    # 关键断言：打回重写后的自审 prompt 必须带上人工意见及其强调块（bug 修复点）
    after_reject = _texts(self_reviews[1])
    assert HUMAN_FB in after_reject, "人工审核意见在自审阶段丢失了！"
    assert "最高优先级：人工审核意见" in after_reject

    # 直接印证机制：generate 已清空 review_feedback，但 human_feedback 仍然存活
    state_after_reject = graph.get_state(config).values
    assert state_after_reject["review_feedback"] == ""
    assert state_after_reject["human_feedback"] == HUMAN_FB

    # ③ 人工通过 → 结束；human_feedback 应被重置，避免污染下一轮
    final = graph.invoke(Command(resume={"feedback": "", "thinking": ""}), config)
    assert final["approved"] is True
    assert final["human_feedback"] == ""


def test_first_generation_has_no_human_feedback_prefix(monkeypatch):
    """无人工打回时，llm_self_review 不应注入人工意见强调块（避免误报/空块）。"""
    recorder: list = []
    monkeypatch.setattr(
        sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder)
    )
    state = ReviewSubState(
        review_type="core_theme",
        system_prompt="SYS",
        current_draft="一段草稿正文。",
        human_feedback="",
    )
    sg.llm_self_review(state)
    sr = [msgs for lbl, msgs in recorder if lbl.startswith("self_review:")]
    assert sr, "应触发一次自审调用"
    assert "最高优先级：人工审核意见" not in _texts(sr[0])


def test_machine_review_coexists_with_human_feedback(monkeypatch):
    """回归防护：加了 human_feedback 逻辑后，机器（AI）审核意见不能丢。

    自审 prompt 必须同时包含【人工意见强调块（最高优先级）】+【标准机器审核清单】，
    且自审仍照常产出机器意见（写入 review_feedback，带 [AI审稿意见] 前缀）。
    """
    recorder: list = []
    AI_ISSUE = "主角动机仍不够清晰，请再补一处早期铺垫。"
    monkeypatch.setattr(
        sg,
        "get_llm",
        lambda *a, **k: _FakeLLM(
            k.get("label", "llm"), recorder, self_review_reply=AI_ISSUE
        ),
    )
    state = ReviewSubState(
        review_type="character_cards",
        system_prompt="SYS",
        current_draft="一段人物档案草稿。",
        human_feedback="请补充主角的一个关键弱点。",
    )
    out = sg.llm_self_review(state)

    # ① 机器审核意见照常产出，未被 human_feedback 逻辑吞掉
    assert out["review_feedback"].startswith("[AI审稿意见]")
    assert AI_ISSUE in out["review_feedback"]

    # ② 自审 prompt 里人工意见（最高优先级）与机器审核清单并存
    prompt = _texts(recorder[-1][1])
    assert "最高优先级：人工审核意见" in prompt  # 人工意见强调块在
    assert "请补充主角的一个关键弱点。" in prompt  # 人工意见原文在
    assert "卡司配额" in prompt  # 标准机器审核清单也在（CHARACTER_CARDS_REVIEW_PROMPT）


def test_generate_consumes_machine_feedback_and_keeps_human_feedback(monkeypatch):
    """机器审核循环里：generate 依据 review_feedback（机器意见）重写，human_feedback 持续存活。"""
    recorder: list = []
    monkeypatch.setattr(
        sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder)
    )
    ai_fb = "[AI审稿意见]\n主角动机不清晰。"
    state = ReviewSubState(
        review_type="core_theme",
        system_prompt="SYS",
        review_feedback=ai_fb,  # 机器意见：待本轮 generate 消费
        human_feedback="请补充主角弱点。",  # 人工意见：应持久保留
        review_history=[
            {"role": "human", "content": "请补充主角弱点。"},
            {"role": "ai", "content": "上一版草稿。"},
        ],
    )
    out = sg.generate(state)

    # 机器意见被 generate 用于重写（regen 指令里带上了 [AI审稿意见] 原文）→ 未丢失
    assert ai_fb in _texts(recorder[-1][1])
    # review_feedback 本轮已消费 → 清空；human_feedback 不在返回 dict → LangGraph 部分更新下自动存活
    assert out["review_feedback"] == ""
    assert "human_feedback" not in out
