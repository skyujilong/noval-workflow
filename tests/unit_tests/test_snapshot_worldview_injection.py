"""回归测试：快照台账（含阶段固化数据）的生成必须注入完整基础设定（世界观）。

背景：快照类型（foreshadowing/phase_summary）此前在 generate() 与 llm_self_review() 里
刻意丢弃 system_context（唯一承载【世界观设定】），导致固化数据的等级/资源等硬性数值
无法与世界观力量/等级体系对齐。（人物动态 status/relations 两条腿已并入 CharacterCard。）

修复：_prepare_* 以 include_identity=False 产出「纯设定块」system_context，节点再拼上
「数据维护员/审核员」身份 + 完整设定。本测试锁定：
  1) build_foundation_context(include_identity=False) 输出无创作者身份前缀、但含世界观；
  2) 快照 generate 的系统消息含「数据维护员」身份 + 世界观；
  3) 快照 llm_self_review 现已关闭（结构化数据无需创作级自审，见 _SELF_REVIEW_DISABLED_TYPES）：
     phase_summary/foreshadowing 直接跳过自审、不调 LLM。故快照自审的 worldview 注入路径已休眠。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from noval_workflow import subgraph as sg
from noval_workflow.context import build_foundation_context
from noval_workflow.nodes.foundation import prepare_initial_status, save_initial_status
from noval_workflow.prompts import phase_summary_prompt
from noval_workflow.state import NovelState, ReviewSubState, parse_card

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


def test_snapshot_self_review_is_disabled_no_llm_call(monkeypatch):
    """快照类型（phase_summary/foreshadowing）自审已关闭：不调 LLM，直接判过。

    结构化数据维护无需创作级自审（省调用 + 省连锁重写）。返回空 feedback → 下游走 human_review。
    """
    recorder: list = []
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm"), recorder))

    ctx = "【世界观设定】\n" + WORLD
    state = ReviewSubState(
        review_type="phase_summary",
        system_context=ctx,
        task_prompt="【上次阶段固化数据】\n主角：炼气三层。",
        current_draft="角色：主角\n【当前状态/定位】炼气五层【变化】",
        llm_review_count=0,
    )
    out = sg.llm_self_review(state)

    sr = [msgs for lbl, msgs in recorder if lbl.startswith("self_review:")]
    assert not sr, "快照自审已关闭，不应触发任何自审 LLM 调用"
    assert out["review_feedback"] == "", "跳过自审须判过（空 feedback）"
    assert out["llm_review_count"] == 1, "轮数仍 +1，保持与旧路由一致"


# ── 人物初始基线节点（Phase 1 收尾，复用 phase_summary 字段 / review_type）────────────


def test_prepare_initial_status_reuses_phase_summary_snapshot_wiring():
    """初始基线 prepare 必须走 snapshot 装配：review_type=phase_summary、纯设定块无创作者身份。"""
    state = NovelState(
        genre="玄幻",
        world_building=WORLD,
        # 人物档案真源已迁至 entity_cards：种子一张主角卡，prepare_initial_status 从卡库渲染
        entity_cards=[parse_card({
            "name": "叶凡", "type": "人物", "role": "主角",
            "abilities": "炼气一层", "summary": "携带一枚上古铜棺碎片",
        })],
    )
    out = prepare_initial_status(state)

    assert out["review_type"] == "phase_summary", "复用 phase_summary 以继承数据维护员身份/审核/中断"
    assert "人物初始基线" in out["task_prompt"], "task_prompt 应来自 initial_status_prompt"
    sc = out["system_context"]
    assert WORLD in sc and "【人物档案】" in sc, "system_context 须含世界观与人物档案（初始化数据来源）"
    assert "叶凡" in sc, "人物档案从卡库渲染（deep 视图）"
    assert _IDENTITY_PREAMBLE not in sc, "include_identity=False 不应含创作者身份前缀"
    # 顶层 foundation 节点须清掉上一步（character_cards）的审核桥接字段
    assert out["current_draft"] == "" and out["approved"] is False


def test_save_initial_status_writes_phase_summary_field():
    state = NovelState(current_draft="角色：叶凡\n【核心能力】炼气一层")
    assert save_initial_status(state) == {"phase_summary": "角色：叶凡\n【核心能力】炼气一层"}


def test_seeded_baseline_is_inherited_as_prev_on_first_batch():
    """核心保证：Phase 1 seed 的 phase_summary，在首批动态更新中作为 prev 被 carry-over 继承。"""
    baseline = "角色：叶凡\n【核心能力】炼气一层"
    # total_chapters_written=0 模拟首批；phase_summary 已被初始基线节点预填
    state = NovelState(total_chapters_written=0, phase_summary=baseline)
    prompt = phase_summary_prompt(state)

    assert "【上次阶段固化数据】" in prompt, "seed 非空 → 必须作为 prev 注入"
    assert baseline in prompt
    assert "完整保留上次快照" in prompt, "prev 非空须触发 carry-over（继承而非重造基线）"
