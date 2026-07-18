"""volume_utils 纯函数工具的单元测试。"""

from __future__ import annotations

import pytest

from noval_workflow.state import NovelState, Volume
from noval_workflow.volume_utils import (
    current_volume,
    find_boundary_crossings,
    format_chapter_plan_volume_budget,
    volume_of_chapter,
    volume_position_card,
)


# ── 辅助 fixture ─────────────────────────────────────────────────────────────

def _four_volumes() -> list[Volume]:
    """典型 4 卷布局：卷1[1, 22-28] 卷2[29, 35-45] 卷3[74, 40-50] 卷4[124, 42-52]。"""
    return [
        Volume(index=1, title="第一卷 · 少年入宗", chapter_start=1,
               target_min=22, target_max=28, summary="卷1主线", setup_for_next="埋卷2钩",
               actual_end=None, status="in_progress"),
        Volume(index=2, title="第二卷 · 内门风云", chapter_start=29,
               target_min=35, target_max=45, summary="卷2主线", setup_for_next="埋卷3钩",
               actual_end=None, status="planning"),
        Volume(index=3, title="第三卷 · 远征异域", chapter_start=74,
               target_min=40, target_max=50, summary="卷3主线", setup_for_next="埋卷4钩",
               actual_end=None, status="planning"),
        Volume(index=4, title="第四卷 · 剑指九霄", chapter_start=124,
               target_min=42, target_max=52, summary="卷4主线", setup_for_next="",
               actual_end=None, status="planning"),
    ]


# ── volume_of_chapter ────────────────────────────────────────────────────────

def test_volume_of_chapter_hits_in_progress_volume():
    """第一卷进行中：第 5 章、第 20 章、第 28 章都属于卷 1。"""
    vs = _four_volumes()
    assert volume_of_chapter(1, vs).index == 1
    assert volume_of_chapter(5, vs).index == 1
    assert volume_of_chapter(28, vs).index == 1


def test_volume_of_chapter_hits_planning_volume():
    """卷 2 planning 但 chapter_start=29：第 29-73 章属于卷 2。"""
    vs = _four_volumes()
    assert volume_of_chapter(29, vs).index == 2
    assert volume_of_chapter(50, vs).index == 2


def test_volume_of_chapter_closed_volume_hard_boundary():
    """已收卷用 [chapter_start, actual_end] 硬边界匹配。"""
    vs = _four_volumes()
    vs[0].actual_end = 25
    vs[0].status = "closed"
    vs[1].chapter_start = 26  # 收卷后卷 2 起点前移
    vs[1].status = "in_progress"

    assert volume_of_chapter(25, vs).index == 1  # 卷 1 收尾章
    assert volume_of_chapter(26, vs).index == 2  # 已经进入卷 2


def test_volume_of_chapter_empty_or_invalid():
    """空 volumes 或非法章号返回 None。"""
    assert volume_of_chapter(1, []) is None
    assert volume_of_chapter(0, _four_volumes()) is None
    assert volume_of_chapter(-1, _four_volumes()) is None


def test_volume_of_chapter_far_beyond_returns_last_volume():
    """略超最后一卷 target_max（软边界）仍映射到最后一卷（容忍度以内）。"""
    vs = _four_volumes()
    # 最后一卷 chapter_start=124, target_max=52 → 上限 175
    # 175 应该命中卷 4
    assert volume_of_chapter(175, vs).index == 4


# ── current_volume ───────────────────────────────────────────────────────────

def test_current_volume_prefers_in_progress():
    """有 in_progress 卷时直接返回它，无关 total_chapters_written。"""
    vs = _four_volumes()
    assert current_volume(vs, 0).index == 1
    assert current_volume(vs, 5).index == 1


def test_current_volume_falls_back_by_chapter():
    """无 in_progress 时按下一章号推断。"""
    vs = _four_volumes()
    for v in vs:
        v.status = "planning"
    # total_chapters_written=25 → 下一章 26，属于卷 1（1~28）
    assert current_volume(vs, 25).index == 1
    # total_chapters_written=28 → 下一章 29，属于卷 2
    assert current_volume(vs, 28).index == 2


def test_current_volume_empty():
    assert current_volume([], 0) is None


# ── find_boundary_crossings ──────────────────────────────────────────────────

def test_find_boundary_crossings_all_within_first_volume():
    """窗口全在卷 1 target range 内部，穿卷 1 min/max。"""
    vs = _four_volumes()
    crossings = find_boundary_crossings(1, 40, vs)
    # 卷 1: min=22 max=28（都在 [1,40] 内）→ 2 条
    # 卷 2: min=63 max=73（都不在 [1,40] 内）→ 0 条
    # 卷 3+: 起点更远 → 0 条
    kinds = [(c["volume_index"], c["kind"], c["chapter"]) for c in crossings]
    assert (1, "target_min", 22) in kinds
    assert (1, "target_max", 28) in kinds
    assert len(crossings) == 2


def test_find_boundary_crossings_cross_multiple_volumes():
    """大窗口穿多卷。"""
    vs = _four_volumes()
    # 窗口 [1, 100]：
    #   卷1 min=22 max=28（都命中）
    #   卷2 min=63 max=73（都命中）
    #   卷3 min=113 max=123（都不命中，超 100）
    crossings = find_boundary_crossings(1, 100, vs)
    volumes_hit = {c["volume_index"] for c in crossings}
    assert volumes_hit == {1, 2}
    assert len(crossings) == 4


def test_find_boundary_crossings_no_crossing():
    """窗口在两卷 target range 之间的空隙，不穿任何边界。"""
    vs = _four_volumes()
    # 窗口 [30, 60]：
    #   卷1: min=22 max=28（都在窗口前）
    #   卷2: min=63 max=73（都在窗口后）
    #   卷3+: 起点更远
    crossings = find_boundary_crossings(30, 60, vs)
    assert crossings == []


def test_find_boundary_crossings_skip_closed_volumes():
    """已收卷不算穿越。"""
    vs = _four_volumes()
    vs[0].actual_end = 25
    vs[0].status = "closed"
    # 窗口 [20, 30] 若不跳过卷 1，会误报 target_max=28 穿越
    crossings = find_boundary_crossings(20, 30, vs)
    volumes_hit = {c["volume_index"] for c in crossings}
    assert 1 not in volumes_hit  # 卷 1 已收，跳过


def test_find_boundary_crossings_empty_or_invalid():
    """空 volumes / 反向窗口。"""
    assert find_boundary_crossings(1, 40, []) == []
    assert find_boundary_crossings(40, 1, _four_volumes()) == []


def test_find_boundary_crossings_skips_zero_target():
    """target_min/target_max 为 0 视为未定义，跳过。"""
    vs = [Volume(index=1, title="卷1", chapter_start=1, target_min=0, target_max=0)]
    assert find_boundary_crossings(1, 100, vs) == []


# ── volume_position_card ─────────────────────────────────────────────────────

def test_volume_position_card_first_volume():
    """在卷 1 进行中，本卷进度 0 章。"""
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    card = volume_position_card(state)
    assert "【当前卷位置】" in card
    assert "第 1 卷" in card
    assert "第一卷 · 少年入宗" in card
    assert "本卷已完成 0/(22~28) 章" in card
    assert "上一卷" not in card  # 首卷无上一卷
    assert "下一卷预告：第二卷" in card


def test_volume_position_card_middle_volume():
    """卷 2 进行中，本卷已完成 5 章。"""
    vs = _four_volumes()
    vs[0].actual_end = 25
    vs[0].status = "closed"
    vs[1].chapter_start = 26
    vs[1].status = "in_progress"
    # 已写 30 章，本卷进度 30 - 26 + 1 = 5 章
    state = NovelState(volumes=vs, total_chapters_written=30)
    card = volume_position_card(state)
    assert "第 2 卷" in card
    assert "本卷已完成 5/(35~45) 章" in card
    assert "上一卷：第一卷 · 少年入宗" in card
    assert "下一卷预告：第三卷" in card


def test_volume_position_card_last_volume():
    """终卷显示「（本卷为终卷）」。"""
    vs = _four_volumes()
    for v in vs[:3]:
        v.status = "closed"
        v.actual_end = v.chapter_start + v.target_max - 1
    vs[3].status = "in_progress"
    state = NovelState(volumes=vs, total_chapters_written=125)
    card = volume_position_card(state)
    assert "第 4 卷" in card
    assert "下一卷预告：（本卷为终卷）" in card


def test_volume_position_card_empty_volumes_returns_empty():
    """未启用分卷的老小说返回 ""，不注入 prompt。"""
    state = NovelState(volumes=[], total_chapters_written=10)
    assert volume_position_card(state) == ""


def test_volume_position_card_no_in_progress_falls_back():
    """无 in_progress 时按 total_chapters_written 推断当前卷。"""
    vs = _four_volumes()
    for v in vs:
        v.status = "planning"
    state = NovelState(volumes=vs, total_chapters_written=30)
    card = volume_position_card(state)
    assert "第 2 卷" in card  # 下一章 31 属于卷 2


# ── format_chapter_plan_volume_budget ─────────────────────────────────────────

def test_budget_spans_two_volumes():
    """本批 40 章横跨 2 卷:分别输出各卷覆盖区间 + 卷内位置 + 剩余额度。"""
    vs = _four_volumes()
    # 卷1 已收卷到 29；卷2 [29, 29+45-1=73]（target_max=45）
    vs[0].status = "closed"
    vs[0].actual_end = 29
    # 本批 [50, 89]:横跨 卷2 尾部 [50, 73] + 卷3 头部 [74, 89]
    hint = format_chapter_plan_volume_budget(vs, 50, 89)
    assert hint != ""
    assert "本批规划区间:第 50" in hint.replace("：", ":")
    # 卷2 覆盖 50-73（24 章）
    assert "本批覆盖第 50-73 章" in hint
    # 卷3 覆盖 74-89（16 章）
    assert "本批覆盖第 74-89 章" in hint
    # 卷内位置显示（卷2 已到末尾 24 章位置 / 45；卷3 头 16 章）
    assert "第 22-45/45" in hint  # 卷2 span=45(target_max), 50-73 → 卷内 22-45
    assert "第 1-16/50" in hint   # 卷3 span=50, 74-89 → 卷内 1-16


def test_budget_within_single_volume():
    """本批完全在 1 卷内:只输出 1 行,卷内位置准确。"""
    vs = _four_volumes()
    # 卷3 [74, 74+50-1=123]，本批 [80, 100] 完全落在卷3
    hint = format_chapter_plan_volume_budget(vs, 80, 100)
    assert "第 3 卷" in hint
    # 只覆盖 1 卷:2 卷/4 卷标题都不应出现在覆盖行
    assert "第 1 卷《" not in hint
    assert "第 2 卷《" not in hint
    assert "第 4 卷《" not in hint
    assert "本批覆盖第 80-100 章" in hint


def test_budget_empty_volumes_returns_empty():
    """未启用分卷 → 返回 ""(向后兼容,不注入 prompt)。"""
    assert format_chapter_plan_volume_budget([], 1, 40) == ""


def test_budget_no_overlap_returns_empty():
    """本批区间落在所有卷之外(超出终卷 target_max 上限)→ 返回 ""。"""
    vs = _four_volumes()  # 终卷 [124, 124+52-1=175]
    hint = format_chapter_plan_volume_budget(vs, 500, 540)
    assert hint == ""


def test_budget_closed_volume_uses_actual_end():
    """已收卷用 actual_end(而非 target_max)算区间上限;剩余额度 = actual_end 之后 = 0。"""
    vs = _four_volumes()
    vs[0].status = "closed"
    vs[0].actual_end = 25  # 卷1 实收 25 章（虽然 target 22-28）
    # 本批 [10, 30] 覆盖 卷1[10-25] + 卷2[29-30]
    hint = format_chapter_plan_volume_budget(vs, 10, 30)
    assert "本批覆盖第 10-25 章" in hint  # 卷1 到 actual_end=25 截止
    assert "actual_end=25" in hint
    # 卷2 从 29 起,本批到 30
    assert "本批覆盖第 29-30 章" in hint


def test_budget_invalid_range_returns_empty():
    """end < start 视为非法输入 → 空串。"""
    vs = _four_volumes()
    assert format_chapter_plan_volume_budget(vs, 50, 20) == ""
