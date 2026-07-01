"""回归测试：快照台账（含阶段固化数据）的生成/自审必须注入完整基础设定（世界观）。

背景：4 个快照类型（character_status/relations/foreshadowing/phase_summary）此前在
generate() 与 llm_self_review() 里刻意丢弃 system_context（唯一承载【世界观设定】），
导致固化数据的等级/装备/资源等硬性数值无法与世界观力量/等级体系对齐。

修复：_prepare_* 以 include_identity=False 产出「纯设定块」system_context，节点再拼上
「数据维护员/审核员」身份 + 完整设定。本测试锁定：
  1) build_foundation_context(include_identity=False) 输出无创作者身份前缀、但含世界观；
  2) 快照 generate 的系统消息含「数据维护员」身份 + 世界观；
  3) 快照 llm_self_review 的系统消息含「数据审核员」身份 + 世界观，且仍前置上次快照基线。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from noval_workflow import subgraph as sg
from noval_workflow.context import build_foundation_context
from noval_workflow.state import NovelState, ReviewSubState

WORLD = "本世界修炼分九境：炼气、筑基、金丹、元婴……灵石为通用货币，一灵石兑百文。"
# build_foundation_context 带身份时的稳定前缀标记（与题材无关）
_IDENTITY_PREAMBLE = "以下是本次作品的核心设定，请严格遵守"


class _FakeLLM:
    """记录每次 invoke 的 (label, messages)，返回占位内容。"""

    def __init__(self, label: str, recorder: list) -> None:
        self.label = label
        self.recorder = recorder

    def invoke(self, messages):
        self.recorder.append((self.label, list(messages)))
        return AIMessage(content="无问题" if self.label.startswith("self_review:") else "占位草稿")


def test_settings_only_context_has_worldview_without_creative_identity():
    state = NovelState(genre="玄幻", world_building=WORLD)

    settings_only = build_foundation_context(state, exclude_snapshots=True, include_identity=False)
    assert "【世界观设定】" in settings_only
    assert WORLD in settings_only
    assert _IDENTITY_PREAMBLE not in settings_only, "include_identity=False 不应含创作者身份前缀"

    with_identity = build_foundation_context(state, exclude_snapshots=True)  # 默认 include_identity=True
    assert _IDENTITY_PREAMBLE in with_identity, "默认应保留创作者身份前缀（非快照流程不受影响）"
    assert WORLD in with_identity


def test_snapshot_generate_injects_worldview(monkeypatch):
    recorder: list = []
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder))

    ctx = "【世界观设定】\n" + WORLD
    state = ReviewSubState(
        review_type="phase_summary",
        system_context=ctx,
        task_prompt="请更新阶段固化数据。",
    )
    sg.generate(state)

    gen = [msgs for lbl, msgs in recorder if lbl.startswith("generate:")]
    assert gen, "应触发一次生成调用"
    sys_text = str(gen[0][0].content)  # messages[0] 为 SystemMessage
    assert "数据维护员" in sys_text, "应保留严谨的数据维护员身份"
    assert WORLD in sys_text, "快照生成的系统提示必须注入世界观"


def test_snapshot_self_review_injects_worldview_and_keeps_baseline(monkeypatch):
    recorder: list = []
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder))

    ctx = "【世界观设定】\n" + WORLD
    state = ReviewSubState(
        review_type="phase_summary",
        system_context=ctx,
        task_prompt="【上次阶段固化数据】\n主角：炼气三层。",
        current_draft="角色：主角\n【当前状态/定位】炼气五层【变化】",
    )
    sg.llm_self_review(state)

    sr = [msgs for lbl, msgs in recorder if lbl.startswith("self_review:")]
    assert sr, "应触发一次自审调用"
    sys_text = str(sr[0][0].content)    # SystemMessage
    human_text = str(sr[0][1].content)  # HumanMessage
    assert "数据审核员" in sys_text, "应保留严谨的数据审核员身份"
    assert WORLD in sys_text, "快照自审的系统提示必须注入世界观"
    assert "上次阶段固化数据" in human_text, "仍须前置上次快照做基线（不得漏条目）"
