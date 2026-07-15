"""Phase 1.5: 分卷边界闸门 (volume_boundary_gate) —— chapter_plan 前的 interrupt 闸门。

在 prepare_chapter_plan 之前插入：判断本次前瞻窗口 [total_chapters_written + 1,
total_chapters_written + CHAPTER_PLAN_WINDOW] 是否穿越任一卷的 target_min/target_max，
穿越则暂停执行、让用户三选一：
  1. continue_current   — 继续本卷，不改边界
  2. close_at           — 在指定章号收卷（写 actual_end + status=closed；下一卷 in_progress）
  3. extend_target_max  — 延长本卷 target_max（顺移后续卷 chapter_start）

设计原则：
- 无穿越 / 无 volumes → 返回 {}，让主链继续走
- 用户输入通过 LangGraph interrupt() → resume payload 一并回传
- 更新 volumes 时保守：只改必要字段，未开启卷 chapter_start 顺移，已收卷不动

decision payload 契约（前端 VolumeBoundaryGateForm 必须回传的字段）：
  {"action": "continue_current"} —— 无附加字段
  {"action": "close_at", "chapter": 25}
  {"action": "extend_target_max", "target_max": 32}
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import replace

from langgraph.types import interrupt

from noval_workflow.config import CHAPTER_PLAN_WINDOW
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.state import NovelState, Volume
from noval_workflow.volume_utils import current_volume, find_boundary_crossings

_logger = logging.getLogger(__name__)


def _volume_to_dict(v: Volume) -> dict:
    """dataclass → dict 供 interrupt payload 序列化（LangGraph checkpoint 也认 dict）。"""
    return {
        "index": v.index,
        "title": v.title,
        "summary": v.summary,
        "setup_for_next": v.setup_for_next,
        "chapter_start": v.chapter_start,
        "target_min": v.target_min,
        "target_max": v.target_max,
        "actual_end": v.actual_end,
        "status": v.status,
    }


def _apply_close_at(volumes: list[Volume], target_index: int, close_chapter: int) -> list[Volume]:
    """应用「在第 X 章收卷」决策：目标卷 actual_end=X + status=closed；
    下一未开启卷 chapter_start=X+1 + status=in_progress；后续卷 chapter_start 按新链顺移。

    以拷贝返回新 list，不改传入 list（保护 state 的原始 volumes）。
    """
    new_volumes = deepcopy(volumes)
    # 找目标卷
    target_pos = next((i for i, v in enumerate(new_volumes) if v.index == target_index), None)
    if target_pos is None:
        raise ValueError(f"close_at: 找不到 volume_index={target_index} 的卷")

    target = new_volumes[target_pos]
    if close_chapter < target.chapter_start:
        raise ValueError(
            f"close_at: chapter={close_chapter} 早于卷 {target_index} 起始章 {target.chapter_start}"
        )

    # 目标卷收卷
    new_volumes[target_pos] = replace(target, actual_end=close_chapter, status="closed")

    # 后续卷（index > target_index）按新链顺移；未开启的第一卷 status→in_progress
    prev_end = close_chapter
    activated = False
    for i in range(target_pos + 1, len(new_volumes)):
        v = new_volumes[i]
        if v.actual_end is not None:
            # 已收卷不动（罕见，但兼容手动收多卷后回改的情况）
            prev_end = v.actual_end
            continue
        new_start = prev_end + 1
        new_status = v.status
        if not activated and v.status != "in_progress":
            new_status = "in_progress"
            activated = True
        new_volumes[i] = replace(v, chapter_start=new_start, status=new_status)
        prev_end = new_start + v.target_max - 1
    return new_volumes


def _apply_extend_target_max(volumes: list[Volume], target_index: int, new_target_max: int) -> list[Volume]:
    """应用「延长本卷 target_max」决策：目标卷 target_max=N；后续未收卷 chapter_start 顺移。"""
    new_volumes = deepcopy(volumes)
    target_pos = next((i for i, v in enumerate(new_volumes) if v.index == target_index), None)
    if target_pos is None:
        raise ValueError(f"extend_target_max: 找不到 volume_index={target_index} 的卷")

    target = new_volumes[target_pos]
    if new_target_max < target.target_min:
        raise ValueError(
            f"extend_target_max: new_target_max={new_target_max} < 本卷 target_min={target.target_min}"
        )
    new_volumes[target_pos] = replace(target, target_max=new_target_max)

    # 顺移后续未收卷 chapter_start
    prev_end = new_volumes[target_pos].chapter_start + new_target_max - 1
    for i in range(target_pos + 1, len(new_volumes)):
        v = new_volumes[i]
        if v.actual_end is not None:
            prev_end = v.actual_end
            continue
        new_start = prev_end + 1
        new_volumes[i] = replace(v, chapter_start=new_start)
        prev_end = new_start + v.target_max - 1
    return new_volumes


def volume_boundary_gate(state: NovelState) -> dict:
    """chapter_plan 前的分卷边界闸门。

    无 volumes / 未穿越 → 无操作直接 return {}；穿越 → interrupt 等用户决策，
    根据 decision 更新 state.volumes 返回。
    """
    if not state.volumes:
        return {}

    window_start = state.total_chapters_written + 1
    window_end = window_start + CHAPTER_PLAN_WINDOW - 1
    crossings = find_boundary_crossings(window_start, window_end, state.volumes)
    if not crossings:
        return {}

    cur = current_volume(state.volumes, state.total_chapters_written)
    if cur is None:
        # 卷已经越界，无法判定——保守不弹 gate
        _logger.warning(
            "volume_boundary_gate: 有穿越但 current_volume=None，跳过闸门（章号可能已越出末卷）"
        )
        return {}

    # AI 建议：close_at 用 target_min/target_max 中位；extend 默认 +5
    suggested_close_chapter = cur.chapter_start + (cur.target_min + cur.target_max) // 2 - 1
    suggested_new_target_max = cur.target_max + 5

    # 后续未收卷快照（帮用户看穿越影响面）
    next_volumes = [_volume_to_dict(v) for v in state.volumes if v.index > cur.index]

    payload = {
        "type": InterruptType.VOLUME_BOUNDARY_GATE.value,
        "window": [window_start, window_end],
        "crossings": [dict(c) for c in crossings],
        "current_volume": _volume_to_dict(cur),
        "next_volumes": next_volumes,
        "message": f"本次长期规划窗口 [{window_start}, {window_end}] 将穿越卷边界，请确认下一步：",
        "options": [
            {"action": "continue_current", "label": "继续本卷（不改边界）"},
            {
                "action": "close_at",
                "label": f"在第 {suggested_close_chapter} 章收卷（AI 建议，可改）",
                "suggested_chapter": suggested_close_chapter,
            },
            {
                "action": "extend_target_max",
                "label": f"延长本卷 target_max 到 {suggested_new_target_max}（默认 +5）",
                "suggested_target_max": suggested_new_target_max,
            },
        ],
    }
    decision = interrupt(payload)

    # 解析 decision：容忍 dict / 字符串两种形态
    if isinstance(decision, str):
        action = decision.strip()
        params: dict = {}
    elif isinstance(decision, dict):
        action = str(decision.get("action", "")).strip()
        params = decision
    else:
        _logger.warning("volume_boundary_gate: 未识别的 decision 类型 %r，默认继续本卷", type(decision))
        return {}

    if action == "continue_current":
        return {}

    if action == "close_at":
        close_chapter = params.get("chapter") or params.get("suggested_chapter") or suggested_close_chapter
        try:
            close_chapter = int(close_chapter)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"close_at: chapter 无法转 int: {params!r}") from exc
        updated = _apply_close_at(state.volumes, cur.index, close_chapter)
        return {"volumes": updated}

    if action == "extend_target_max":
        new_target_max = params.get("target_max") or params.get("suggested_target_max") or suggested_new_target_max
        try:
            new_target_max = int(new_target_max)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"extend_target_max: target_max 无法转 int: {params!r}") from exc
        updated = _apply_extend_target_max(state.volumes, cur.index, new_target_max)
        return {"volumes": updated}

    _logger.warning("volume_boundary_gate: 未知 action=%r，默认继续本卷", action)
    return {}
