"""make_edit_step_subgraph 的 state schema 回归测试。

锁死一个隐蔽坑：工厂里的节点闭包若把 state 注解成基类 EditStepSubState，LangGraph 会按注解
把传入 state **窄化**成基类实例，丢掉 state_cls 子类才声明的字段。于是 prepare_fn/save_fn 读子类
字段时报 "'EditStepSubState' object has no attribute 'current_chapter_beats'"，run 卡在 entry gate
「执行」后不往下走。闭包不写注解 → LangGraph 回退到编译时的图 schema（完整子类），本测试守住这点。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import Field

from noval_workflow.edit_step_subgraph import EditStepSubState, make_edit_step_subgraph
from noval_workflow.interrupt_types import InterruptType


class _ProbeSubState(EditStepSubState):
    """带一个基类没有的字段，模拟 EntityCardsSubState.current_chapter_beats 那类子类专属字段。

    EditStepSubState 已迁至 pydantic BaseModel——继承时用 pydantic Field 声明子类字段。
    """

    subclass_only_field: list = Field(default_factory=list)


def test_prepare_fn_receives_full_subclass_state(monkeypatch):
    """entry gate「执行」后，prepare_fn 必须收到完整子类 state（能读子类专属字段），而非窄化的基类。"""
    import noval_workflow.subgraph as sg

    class _R:
        content = '{"ok": true}'

    class _FakeLLM:
        def invoke(self, _messages):
            return _R()

    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM())

    seen: dict = {}

    def prepare_fn(state):
        # 关键断言点：真实读子类专属字段。窄化成基类会在此 AttributeError。
        seen["type"] = type(state).__name__
        seen["value"] = state.subclass_only_field
        return {
            "system_prompt": "SYS",
            "context_prompt": "CTX",
            "task_prompt": "TASK",
            "review_type": "entity_cards",
        }

    def save_fn(_state):
        return {}

    sub = make_edit_step_subgraph(
        entry_prompt="?",
        prepare_fn=prepare_fn,
        save_fn=save_fn,
        entry_gate_type=InterruptType.ENTITY_CARDS_ENTRY_GATE,
        direction_type=InterruptType.ENTITY_CARDS_DIRECTION_INPUT,
        enable_llm_review=False,  # 免去自审，直达 human_review interrupt
        ask_direction=False,
        state_cls=_ProbeSubState,
    )
    # 工厂返回的已编译子图不带 checkpointer；interrupt/resume 需要，重新挂一份。
    graph = sub.copy(update={"checkpointer": MemorySaver()})

    cfg = {"configurable": {"thread_id": "probe-1"}}
    graph.invoke(_ProbeSubState(subclass_only_field=["beat-a"]), cfg)  # 停在 entry gate
    graph.invoke(Command(resume="yes"), cfg)  # 点「执行」→ 走到 step_prepare

    assert seen["type"] == "_ProbeSubState", (
        "prepare_fn 应收到完整子类 state，而非被窄化的基类"
    )
    assert seen["value"] == ["beat-a"], (
        "子类专属字段必须原样流入，不能被 schema 窄化丢弃"
    )
