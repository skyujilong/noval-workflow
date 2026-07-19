"""route_continue_or_end 三分路由单测（滚动生成卷架构）。

END(用户停) / prepare_volumes(触及当前卷末章且无下一卷→先滚动规划下一卷) / prepare_arc_outline(直接下一批)。
"""

from __future__ import annotations

from langgraph.graph import END

from noval_workflow.config import BATCH_SIZE
from noval_workflow.nodes.chapter import route_continue_or_end
from noval_workflow.state import NovelState, Volume


def _vol(index: int, start: int, end: int, status: str = "in_progress",
         actual_end: int | None = None) -> Volume:
    return Volume(index=index, title=f"卷{index}", chapter_start=start, planned_end=end,
                  status=status, actual_end=actual_end)


def test_route_end_when_not_continue():
    """用户停 → END。"""
    state = NovelState(continue_writing=False, volumes=[_vol(1, 1, 30)], total_chapters_written=10)
    assert route_continue_or_end(state) == END


def test_route_arc_when_no_volumes():
    """无 volumes（冷启动兜底，current_volume=None）→ 直接下一批。"""
    state = NovelState(continue_writing=True, volumes=[], total_chapters_written=10)
    assert route_continue_or_end(state) == "prepare_arc_outline"


def test_route_arc_when_far_from_volume_end():
    """离当前卷末章还远（done+BATCH < 卷末）→ 直接下一批。"""
    # done=5, 卷1 末章 30；done+BATCH(5 或 10)=10~15 < 30
    state = NovelState(continue_writing=True, volumes=[_vol(1, 1, 30)], total_chapters_written=5)
    assert route_continue_or_end(state) == "prepare_arc_outline"


def test_route_prepare_volumes_when_near_end_no_next():
    """触及当前卷末章(done+BATCH >= 卷末)且无下一卷 → 先滚动规划下一卷。"""
    done = 30 - BATCH_SIZE  # done + BATCH == 30 == 卷末 → 触发
    state = NovelState(continue_writing=True, volumes=[_vol(1, 1, 30)], total_chapters_written=done)
    assert route_continue_or_end(state) == "prepare_volumes"


def test_route_arc_when_near_end_but_has_next():
    """已有下一卷（has_next 守卫）→ 不重复触发滚动，直接下一批。"""
    done = 30 - BATCH_SIZE
    vols = [_vol(1, 1, 30, status="closed", actual_end=30), _vol(2, 31, 60)]
    state = NovelState(continue_writing=True, volumes=vols, total_chapters_written=done)
    # 下一章仍在卷1 [1,30] 内 → cur=卷1；但卷2 已存在 → has_next → 不滚动
    assert route_continue_or_end(state) == "prepare_arc_outline"


def test_route_prepare_volumes_ignores_draft_lookahead():
    """前瞻草稿卷(planning，planned_end=0)不算 has_next → 触及激活卷末章仍触发滚动。"""
    done = 30 - BATCH_SIZE  # done + BATCH == 30 == 激活卷末章
    vols = [
        _vol(1, 1, 30),                        # 激活卷
        _vol(2, 0, 0, status="planning"),      # 草稿卷（未锁章号，不算已激活下一卷）
        _vol(3, 0, 0, status="planning"),
    ]
    state = NovelState(continue_writing=True, volumes=vols, total_chapters_written=done)
    # cur=卷1；草稿卷 planned_end=0 不满足 has_next 限定 → 无已激活下一卷 → 滚动
    assert route_continue_or_end(state) == "prepare_volumes"
