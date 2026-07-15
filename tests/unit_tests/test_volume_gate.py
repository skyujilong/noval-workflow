"""volume_boundary_gate 节点单元测试：三种 decision 分支 + 无穿越路径 + interrupt payload。

interrupt() 用 monkeypatch 替换成"直接返回预设 decision"，测试路径分支。
"""

from __future__ import annotations

import pytest

from noval_workflow.nodes import volume_gate as vg_mod
from noval_workflow.nodes.volume_gate import (
    _apply_close_at,
    _apply_extend_target_max,
    volume_boundary_gate,
)
from noval_workflow.state import NovelState, Volume


# ── fixtures ────────────────────────────────────────────────────────────────


def _four_volumes() -> list[Volume]:
    """典型 4 卷布局：卷1 in_progress [1, target 22-28] 其余 planning。"""
    return [
        Volume(index=1, title="卷1", chapter_start=1, target_min=22, target_max=28,
               summary="卷1主线", setup_for_next="埋卷2钩", status="in_progress"),
        Volume(index=2, title="卷2", chapter_start=29, target_min=35, target_max=42,
               summary="卷2主线", setup_for_next="埋卷3钩", status="planning"),
        Volume(index=3, title="卷3", chapter_start=71, target_min=40, target_max=50,
               summary="卷3主线", setup_for_next="埋卷4钩", status="planning"),
        Volume(index=4, title="卷4", chapter_start=121, target_min=42, target_max=52,
               summary="卷4主线", setup_for_next="", status="planning"),
    ]


@pytest.fixture
def patch_interrupt(monkeypatch):
    """把 langgraph.types.interrupt 换成"返回预设 decision"，供分支路径测试。"""
    captured: dict = {"payload": None, "decision": None}

    def _factory(decision):
        captured["decision"] = decision

        def fake_interrupt(payload):
            captured["payload"] = payload
            return decision

        monkeypatch.setattr(vg_mod, "interrupt", fake_interrupt)
        return captured

    return _factory


# ── 无穿越路径（no-op）─────────────────────────────────────────────────────


def test_gate_returns_empty_when_no_volumes(patch_interrupt):
    """无 volumes 时直接返回 {}，不 interrupt。"""
    patch_interrupt("continue_current")  # 装 fake，验证不被调用
    state = NovelState(volumes=[], total_chapters_written=0)
    assert volume_boundary_gate(state) == {}


def test_gate_returns_empty_when_no_crossing(patch_interrupt):
    """total_chapters_written=100（已入卷3），窗口 [101, 140]——
    卷 3 target_min=40→绝对章 110、target_max=50→绝对章 120 都在窗口内会穿越。
    改用 total_chapters_written 让窗口位于卷内内部不穿边界。
    典型 CHAPTER_PLAN_WINDOW=40 → 窗口 40 章。
    卷 3 起 71，target_max=50 → 卷 3 覆盖 71-120。
    total=75 → 窗口 [76, 115]。target_min 绝对章 110 在窗口内 → 会穿越。
    所以取 total=125（已入卷 4）→ 窗口 [126, 165]，卷 4 起 121, target_min=42→绝对 162,
    target_max=52→绝对 172。target_min 162 在窗口内 → 会穿越。
    只能用一个真正不穿越的场景：窗口末端小于任何未收卷的 target_min。
    最容易验证的：单卷 target_min>>window 时。
    """
    # 单卷 target 巨大：卷起 1，target_min=100，target_max=110 → 绝对章 100/110 都远出窗口 40
    vols = [Volume(index=1, title="唯一卷", chapter_start=1, target_min=100, target_max=110,
                   status="in_progress")]
    state = NovelState(volumes=vols, total_chapters_written=0)
    # 窗口 [1, 40]，卷 1 边界在 100 和 110 章——都不在窗口内 → 无穿越
    assert volume_boundary_gate(state) == {}


# ── 三种 decision 分支 ─────────────────────────────────────────────────────


def test_gate_continue_current_returns_empty(patch_interrupt):
    """decision=continue_current → 返回 {} 不改 volumes。"""
    captured = patch_interrupt({"action": "continue_current"})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    # 窗口 [1, 40]，卷 1 target_min=22 → 绝对章 22, target_max=28 → 绝对章 28，都在窗口
    result = volume_boundary_gate(state)
    assert result == {}
    # 验证 payload 里有 3 个选项 + 穿越点
    payload = captured["payload"]
    assert payload["type"] == "volume_boundary_gate"
    assert len(payload["options"]) == 3
    assert len(payload["crossings"]) == 2  # target_min + target_max 都在窗口
    assert payload["current_volume"]["index"] == 1


def test_gate_close_at_updates_volumes(patch_interrupt):
    """decision=close_at chapter=25 → 卷 1 actual_end=25 + closed；卷 2 chapter_start=26 + in_progress；卷 3 chapter_start 顺移。"""
    patch_interrupt({"action": "close_at", "chapter": 25})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    result = volume_boundary_gate(state)

    updated = result["volumes"]
    assert updated[0].actual_end == 25
    assert updated[0].status == "closed"
    # 卷 2 起点 = 26，激活
    assert updated[1].chapter_start == 26
    assert updated[1].status == "in_progress"
    # 卷 3 起点 = 26 + 卷2.target_max 42 = 68
    assert updated[2].chapter_start == 68
    assert updated[2].status == "planning"
    # 卷 4 起点 = 68 + 卷3.target_max 50 = 118
    assert updated[3].chapter_start == 118
    assert updated[3].status == "planning"


def test_gate_close_at_uses_suggested_when_no_chapter(patch_interrupt):
    """decision 只有 action=close_at，无 chapter → 用 payload 里的 suggested_chapter（AI 建议）。"""
    patch_interrupt({"action": "close_at"})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    result = volume_boundary_gate(state)
    # 建议章 = chapter_start(1) + (target_min(22) + target_max(28))//2 - 1 = 1 + 25 - 1 = 25
    assert result["volumes"][0].actual_end == 25
    assert result["volumes"][0].status == "closed"


def test_gate_extend_target_max_updates_volumes(patch_interrupt):
    """decision=extend_target_max target_max=35 → 卷 1 target_max=35；后续卷 chapter_start 顺移。"""
    patch_interrupt({"action": "extend_target_max", "target_max": 35})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    result = volume_boundary_gate(state)

    updated = result["volumes"]
    assert updated[0].target_max == 35
    assert updated[0].status == "in_progress"  # 卷 1 仍然进行中
    assert updated[0].actual_end is None
    # 卷 2 起点 = 1 + 35 = 36
    assert updated[1].chapter_start == 36
    # 卷 3 起点 = 36 + 42 = 78
    assert updated[2].chapter_start == 78
    # 卷 4 起点 = 78 + 50 = 128
    assert updated[3].chapter_start == 128


def test_gate_extend_target_max_uses_suggested_when_no_value(patch_interrupt):
    """decision 只有 action=extend_target_max → 用默认 +5。"""
    patch_interrupt({"action": "extend_target_max"})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    result = volume_boundary_gate(state)
    # 建议 target_max = 28 + 5 = 33
    assert result["volumes"][0].target_max == 33
    # 卷 2 起点 = 1 + 33 = 34
    assert result["volumes"][1].chapter_start == 34


def test_gate_string_decision_treated_as_action(patch_interrupt):
    """兼容前端返回纯字符串 decision（老式）。"""
    patch_interrupt("continue_current")
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    assert volume_boundary_gate(state) == {}


def test_gate_unknown_action_defaults_to_noop(patch_interrupt):
    """未知 action → 保守当 continue_current 处理。"""
    patch_interrupt({"action": "some_unknown_action"})
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    assert volume_boundary_gate(state) == {}


# ── 内部辅助函数（可直接测的纯函数）────────────────────────────────────────


def test_apply_close_at_preserves_input():
    """_apply_close_at 不修改原 list（返回深拷贝）。"""
    vs = _four_volumes()
    original_snapshot = [(v.index, v.chapter_start, v.status) for v in vs]
    _apply_close_at(vs, target_index=1, close_chapter=25)
    assert [(v.index, v.chapter_start, v.status) for v in vs] == original_snapshot


def test_apply_close_at_rejects_early_chapter():
    """close_chapter < chapter_start → ValueError。"""
    vs = _four_volumes()
    with pytest.raises(ValueError, match="早于卷"):
        _apply_close_at(vs, target_index=2, close_chapter=10)  # 卷 2 起 29


def test_apply_close_at_rejects_unknown_index():
    """找不到目标卷 → ValueError。"""
    vs = _four_volumes()
    with pytest.raises(ValueError, match="找不到"):
        _apply_close_at(vs, target_index=99, close_chapter=10)


def test_apply_extend_target_max_rejects_below_min():
    """new_target_max < target_min → ValueError。"""
    vs = _four_volumes()
    with pytest.raises(ValueError, match="target_min"):
        _apply_extend_target_max(vs, target_index=1, new_target_max=10)  # 卷 1 min=22


def test_apply_close_at_activates_only_first_unopened():
    """close 后只激活下一未开启卷，再后面的仍是 planning。"""
    vs = _four_volumes()
    result = _apply_close_at(vs, target_index=1, close_chapter=25)
    assert result[1].status == "in_progress"
    assert result[2].status == "planning"
    assert result[3].status == "planning"
