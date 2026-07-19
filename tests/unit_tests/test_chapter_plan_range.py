"""_plan_range 单测（滚动生成卷架构：chapter_plan 以「卷」为规划单元）。

覆盖三种触发场景 + 兜底：
  1. 首卷展开（done=0）→ 整卷 [chapter_start, planned_end]
  2. 卷中续规划（Step3 STRIDE，done 落在卷内）→ [done+1, planned_end]（锁已写）
  3. 滚动新卷（Step4，done 落在上一卷内）→ 新卷 [chapter_start, planned_end]
  4. 无 volumes / planned_end 未定（老快照）→ 回退，不返回非法区间
"""

from __future__ import annotations

from noval_workflow.nodes.chapter_plan import _plan_range
from noval_workflow.state import NovelState, Volume


def test_plan_range_first_volume_full_range():
    """首卷展开（done=0）：规划整卷 [chapter_start, planned_end]。"""
    state = NovelState(
        total_chapters_written=0,
        volumes=[Volume(index=1, title="卷1", chapter_start=1, planned_end=30, status="in_progress")],
    )
    assert _plan_range(state) == (1, 30)


def test_plan_range_mid_volume_locks_written_prefix():
    """卷中续规划（done=10 落在卷 1 [1,30] 内）：start=done+1，锁已写、只规划未写段的卷范围。"""
    state = NovelState(
        total_chapters_written=10,
        volumes=[Volume(index=1, title="卷1", chapter_start=1, planned_end=30, status="in_progress")],
    )
    assert _plan_range(state) == (11, 30)


def test_plan_range_rolling_new_volume():
    """滚动新卷：卷1 收口 [1,30]、卷2 [31,60]，done=20 仍在卷1 → 规划最大 index 的卷2 整卷。"""
    state = NovelState(
        total_chapters_written=20,
        volumes=[
            Volume(index=1, title="卷1", chapter_start=1, planned_end=30, actual_end=30, status="closed"),
            Volume(index=2, title="卷2", chapter_start=31, planned_end=60, status="in_progress"),
        ],
    )
    # cur=卷2；start=max(31, 21)=31；end=60
    assert _plan_range(state) == (31, 60)


def test_plan_range_empty_volumes_fallback():
    """无 volumes → 回退 [done+1, done+1]，不炸。"""
    state = NovelState(total_chapters_written=5, volumes=[])
    assert _plan_range(state) == (6, 6)


def test_plan_range_planned_end_unset_falls_back_to_target_max():
    """老快照 planned_end=0 → 回退 target_max 换算，避免 end<start 非法区间。"""
    state = NovelState(
        total_chapters_written=0,
        volumes=[Volume(index=1, title="卷1", chapter_start=1, planned_end=0,
                        target_max=28, status="in_progress")],
    )
    assert _plan_range(state) == (1, 28)
