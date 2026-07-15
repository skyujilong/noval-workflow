"""分卷（Volume）辅助工具集 —— 章卷映射、位置卡渲染、边界穿越判定。

设计约束（关键，参见 state.Volume 注释）：
- Volume.chapter_start 是**绝对章号**（1-based）
- Volume.target_min / target_max 是**本卷章数**（数量，不是绝对章号）
- 卷内绝对章号窗口 = [chapter_start, chapter_start + target_max - 1]
- 已收卷（actual_end != None）占用 [chapter_start, actual_end] 硬边界；
  进行中卷按 target_max 上限占位，直到 VOLUME_BOUNDARY_GATE 用户点收卷。

本模块所有函数为纯函数，无副作用，便于单测。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from noval_workflow.state import NovelState, Volume


class BoundaryCrossing(TypedDict):
    """chapter_plan 窗口穿越某卷 target_min/target_max 时的一条穿越记录。"""
    volume_index: int      # 被穿越的卷 index（1-based）
    kind: str              # 'target_min' | 'target_max'
    chapter: int           # 该边界对应的绝对章号


def volume_of_chapter(chapter_num: int, volumes: list["Volume"]) -> "Volume | None":
    """回答"第 N 章属于第几卷"。

    规则：
    - 已收卷（actual_end != None）：chapter ∈ [chapter_start, actual_end] 时命中
    - 进行中卷（actual_end == None）：chapter >= chapter_start 且是当前第一个未收卷时命中
    - 章号超出所有卷范围 → None（发生在超出最后一卷 target_max 时，语义上"越界"）
    """
    if chapter_num < 1 or not volumes:
        return None

    # 已收卷：硬边界比对
    for v in volumes:
        if v.actual_end is not None and v.chapter_start <= chapter_num <= v.actual_end:
            return v

    # 进行中/未开启卷：找 chapter_start <= chapter_num 的最靠后卷
    # 其 chapter_num 上限 = chapter_start + target_max - 1（软边界）
    candidates = [v for v in volumes if v.actual_end is None and v.chapter_start <= chapter_num]
    if not candidates:
        return None
    latest = max(candidates, key=lambda v: v.chapter_start)
    # 允许略超 target_max（软边界），但超太多（>target_max * 2）视为越界
    upper_bound = latest.chapter_start + latest.target_max - 1
    if chapter_num <= upper_bound + latest.target_max:  # 容忍度：软上限 + 一个 target_max
        return latest
    return None


def current_volume(volumes: list["Volume"], total_chapters_written: int) -> "Volume | None":
    """当前活跃卷 —— 即"下一章将属于哪一卷"。

    优先规则：
    1. 有 status == "in_progress" 的卷 → 直接返回该卷
    2. 否则按 total_chapters_written + 1（下一章号）走 volume_of_chapter
    3. 无卷或全部越界 → None
    """
    if not volumes:
        return None
    in_progress = [v for v in volumes if v.status == "in_progress"]
    if in_progress:
        return in_progress[0]
    return volume_of_chapter(total_chapters_written + 1, volumes)


def find_boundary_crossings(
    window_start: int,
    window_end: int,
    volumes: list["Volume"],
) -> list[BoundaryCrossing]:
    """判定 [window_start, window_end] 这个 chapter_plan 窗口是否穿越任一卷的
    target_min / target_max 章号边界。

    只统计**未收卷**（actual_end == None）的卷——已收卷已经是硬边界，chapter_plan
    的窗口不会再"穿越"它。

    target_min 对应的绝对章号 = chapter_start + target_min - 1
    target_max 对应的绝对章号 = chapter_start + target_max - 1

    返回穿越点列表，用于 VOLUME_BOUNDARY_GATE 提示用户"本次规划将走过这些卷边界"。
    """
    if not volumes or window_end < window_start:
        return []

    crossings: list[BoundaryCrossing] = []
    for v in volumes:
        if v.actual_end is not None:
            continue  # 已收卷跳过
        if v.target_min <= 0 or v.target_max <= 0:
            continue  # 未定 target range 跳过

        min_chapter = v.chapter_start + v.target_min - 1
        max_chapter = v.chapter_start + v.target_max - 1

        if window_start <= min_chapter <= window_end:
            crossings.append(
                BoundaryCrossing(volume_index=v.index, kind="target_min", chapter=min_chapter)
            )
        if window_start <= max_chapter <= window_end:
            crossings.append(
                BoundaryCrossing(volume_index=v.index, kind="target_max", chapter=max_chapter)
            )
    return crossings


def volume_position_card(state: "NovelState") -> str:
    """生成"当前卷位置卡"markdown 片段，供 chapter_plan / arc_outline / chapter
    三处 prompt 头部注入。

    空 volumes 时返回 ""（保持向后兼容，未启用分卷的老小说不注入）。

    返回格式（示例）：
        【当前卷位置】
        - 当前所在：第 2 卷《第二卷 · 内门风云》（第 29 章起，目标 35-42 章）
        - 本卷进度：本卷已完成 3/(35~42) 章
        - 上一卷：第一卷 · 少年入宗 —— …
        - 本卷主线：林渊晋升内门卷入派系与妖族危机…
        - 卷尾 setup：血月教锁定林渊为目标
        - 下一卷预告：第三卷 · 远征异域
    """
    if not state.volumes:
        return ""

    cur = current_volume(state.volumes, state.total_chapters_written)
    if cur is None:
        return ""

    # 本卷已完成章数
    done_in_vol = max(0, state.total_chapters_written - cur.chapter_start + 1)

    lines = ["【当前卷位置】"]
    lines.append(
        f"- 当前所在：第 {cur.index} 卷《{cur.title}》"
        f"（第 {cur.chapter_start} 章起，目标 {cur.target_min}-{cur.target_max} 章）"
    )
    lines.append(
        f"- 本卷进度：本卷已完成 {done_in_vol}/({cur.target_min}~{cur.target_max}) 章"
    )

    # 上一卷
    prev_list = [v for v in state.volumes if v.index < cur.index]
    if prev_list:
        prev = max(prev_list, key=lambda v: v.index)
        prev_summary = prev.summary or "（无摘要）"
        lines.append(f"- 上一卷：{prev.title} —— {prev_summary}")

    lines.append(f"- 本卷主线：{cur.summary or '（无摘要）'}")

    if cur.setup_for_next:
        lines.append(f"- 卷尾 setup：{cur.setup_for_next}")

    # 下一卷
    next_list = [v for v in state.volumes if v.index > cur.index]
    if next_list:
        nxt = min(next_list, key=lambda v: v.index)
        lines.append(f"- 下一卷预告：{nxt.title}")
    else:
        lines.append("- 下一卷预告：（本卷为终卷）")

    return "\n".join(lines)
