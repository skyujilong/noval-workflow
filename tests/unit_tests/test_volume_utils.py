"""volume_utils 纯函数工具的单元测试（滚动生成卷架构）。

覆盖 volume_of_chapter（planned_end 边界）、current_volume（章号映射优先，不看 in_progress
status）、volume_position_card（planned_end 绝对区间 + 共 N 章）。
边界穿越 find_boundary_crossings / 容量锚点 format_chapter_plan_volume_budget 已随分卷闸门删除。
"""

from __future__ import annotations

from noval_workflow.state import NovelState, Volume
from noval_workflow.volume_utils import (
    current_volume,
    volume_of_chapter,
    volume_position_card,
)


# ── 辅助 fixture ─────────────────────────────────────────────────────────────

def _four_volumes() -> list[Volume]:
    """典型 4 卷布局（planned_end 绝对章号）：卷1[1,28] 卷2[29,73] 卷3[74,123] 卷4[124,175]。"""
    return [
        Volume(index=1, title="第一卷 · 少年入宗", chapter_start=1, planned_end=28,
               summary="卷1主线", setup_for_next="埋卷2钩", actual_end=None, status="in_progress"),
        Volume(index=2, title="第二卷 · 内门风云", chapter_start=29, planned_end=73,
               summary="卷2主线", setup_for_next="埋卷3钩", actual_end=None, status="planning"),
        Volume(index=3, title="第三卷 · 远征异域", chapter_start=74, planned_end=123,
               summary="卷3主线", setup_for_next="埋卷4钩", actual_end=None, status="planning"),
        Volume(index=4, title="第四卷 · 剑指九霄", chapter_start=124, planned_end=175,
               summary="卷4主线", setup_for_next="", actual_end=None, status="planning"),
    ]


# ── volume_of_chapter ────────────────────────────────────────────────────────

def test_volume_of_chapter_hits_in_progress_volume():
    """卷 1 [1,28]：第 1/5/28 章都属于卷 1。"""
    vs = _four_volumes()
    assert volume_of_chapter(1, vs).index == 1
    assert volume_of_chapter(5, vs).index == 1
    assert volume_of_chapter(28, vs).index == 1


def test_volume_of_chapter_hits_planning_volume():
    """卷 2 [29,73]：第 29-73 章属于卷 2。"""
    vs = _four_volumes()
    assert volume_of_chapter(29, vs).index == 2
    assert volume_of_chapter(50, vs).index == 2
    assert volume_of_chapter(73, vs).index == 2


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


def test_volume_of_chapter_beyond_last_planned_end_returns_none():
    """超出末卷 planned_end（不再有 target_max 容忍度）→ None（等下一卷滚出）。"""
    vs = _four_volumes()  # 末卷 planned_end=175
    assert volume_of_chapter(175, vs).index == 4
    assert volume_of_chapter(176, vs) is None


def test_volume_of_chapter_uses_planned_end_boundary():
    """planned_end 即卷内上限：越过即进下一卷；末卷之外为 None。"""
    vs = [
        Volume(index=1, title="卷1", chapter_start=1, planned_end=20,
               actual_end=None, status="in_progress"),
        Volume(index=2, title="卷2", chapter_start=21, planned_end=40,
               actual_end=None, status="planning"),
    ]
    assert volume_of_chapter(20, vs).index == 1   # 卷1 末章
    assert volume_of_chapter(21, vs).index == 2   # 越过 planned_end=20 → 进卷2
    assert volume_of_chapter(41, vs) is None


# ── current_volume ───────────────────────────────────────────────────────────

def test_current_volume_maps_by_chapter_not_in_progress_status():
    """决策 5：按下一章号映射，status=in_progress 不再抢优先——修"提前翻卷"bug。"""
    vs = [
        Volume(index=1, title="卷1", chapter_start=1, planned_end=30,
               actual_end=30, status="closed"),
        Volume(index=2, title="卷2", chapter_start=31, planned_end=60,
               actual_end=None, status="in_progress"),
    ]
    assert current_volume(vs, 20).index == 1   # 下一章 21 ∈ [1,30] → 卷1（不被 in_progress 卷2 抢走）
    assert current_volume(vs, 30).index == 2   # 下一章 31 ∈ [31,60] → 卷2


def test_current_volume_falls_back_by_chapter():
    """按下一章号推断当前卷。"""
    vs = _four_volumes()
    # total_chapters_written=25 → 下一章 26，属于卷 1（[1,28]）
    assert current_volume(vs, 25).index == 1
    # total_chapters_written=28 → 下一章 29，属于卷 2
    assert current_volume(vs, 28).index == 2


def test_current_volume_empty():
    assert current_volume([], 0) is None


# ── volume_position_card ─────────────────────────────────────────────────────

def test_volume_position_card_first_volume():
    """在卷 1 进行中，本卷进度 0 章。"""
    state = NovelState(volumes=_four_volumes(), total_chapters_written=0)
    card = volume_position_card(state)
    assert "【当前卷位置】" in card
    assert "第 1 卷" in card
    assert "第一卷 · 少年入宗" in card
    assert "第 1-28 章，共 28 章" in card
    assert "本卷已完成 0/28 章" in card
    assert "上一卷" not in card  # 首卷无上一卷
    assert "下一卷预告：第二卷" in card


def test_volume_position_card_middle_volume():
    """卷 2 进行中，本卷已完成 5 章。"""
    vs = _four_volumes()
    vs[0].actual_end = 25
    vs[0].status = "closed"
    vs[1].chapter_start = 26
    vs[1].status = "in_progress"
    # 卷2 [26, 73]，已写 30 章 → 本卷进度 30 - 26 + 1 = 5 章；span = 73 - 26 + 1 = 48
    state = NovelState(volumes=vs, total_chapters_written=30)
    card = volume_position_card(state)
    assert "第 2 卷" in card
    assert "本卷已完成 5/48 章" in card
    assert "上一卷：第一卷 · 少年入宗" in card
    assert "下一卷预告：第三卷" in card


def test_volume_position_card_last_volume():
    """终卷显示「（本卷为终卷）」。"""
    vs = _four_volumes()
    for v in vs[:3]:
        v.status = "closed"
        v.actual_end = v.planned_end
    vs[3].status = "in_progress"
    state = NovelState(volumes=vs, total_chapters_written=125)
    card = volume_position_card(state)
    assert "第 4 卷" in card
    assert "下一卷预告：（本卷为终卷）" in card


def test_volume_position_card_uses_planned_end_span():
    """位置卡按 [chapter_start, planned_end] 绝对区间 + 共 N 章展示。"""
    vs = [
        Volume(index=1, title="第一卷 · 少年入宗", chapter_start=1, planned_end=30,
               summary="卷1主线", setup_for_next="埋卷2钩", actual_end=None, status="in_progress"),
        Volume(index=2, title="第二卷 · 内门风云", chapter_start=31, planned_end=65,
               summary="卷2主线", actual_end=None, status="planning"),
    ]
    state = NovelState(volumes=vs, total_chapters_written=9)
    card = volume_position_card(state)
    assert "第 1 卷" in card
    assert "第 1-30 章，共 30 章" in card
    assert "本卷已完成 9/30 章" in card
    assert "目标" not in card
    assert "下一卷预告：第二卷 · 内门风云" in card


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
