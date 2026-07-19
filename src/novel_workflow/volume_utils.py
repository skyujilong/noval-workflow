"""分卷（Volume）辅助工具集 —— 章卷映射、当前卷判定、位置卡渲染。

滚动生成卷架构（关键，参见 state.Volume 注释）：
- Volume.chapter_start 是**绝对章号**（1-based，权威锁定）
- Volume.planned_end 是本卷**末章号**（绝对章号，权威边界）
- 卷内绝对章号窗口 = [chapter_start, planned_end]
- 已收卷（actual_end != None）占用 [chapter_start, actual_end]（= planned_end）硬边界；
  进行中卷（actual_end == None）按 planned_end 上限占位，直到滚动到下一卷时收口。

本模块所有函数为纯函数，无副作用，便于单测。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from noval_workflow.state import NovelState, Volume


def volume_of_chapter(chapter_num: int, volumes: list["Volume"]) -> "Volume | None":
    """回答"第 N 章属于第几卷"。

    规则：
    - 已收卷（actual_end != None）：chapter ∈ [chapter_start, actual_end] 时命中
    - 进行中卷（actual_end == None）：chapter ∈ [chapter_start, planned_end] 时命中
    - 章号超出所有卷范围 → None（滚动架构下仅出现在"下一卷尚未滚出"的短暂窗口，路由兜底）
    """
    if chapter_num < 1 or not volumes:
        return None

    # 已收卷：硬边界比对
    for v in volumes:
        if v.actual_end is not None and v.chapter_start <= chapter_num <= v.actual_end:
            return v

    # 进行中卷：找 chapter_start <= chapter_num 的最靠后卷，用 planned_end 作上限。
    # planned_end>0 过滤掉「前瞻草稿卷」(planning，章号未锁 chapter_start=planned_end=0)——
    # 草稿卷不参与章号映射，否则其 chapter_start=0 会恒满足下界、污染判定。
    candidates = [
        v for v in volumes
        if v.actual_end is None and v.planned_end > 0 and v.chapter_start <= chapter_num
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda v: v.chapter_start)
    if chapter_num <= latest.planned_end:
        return latest
    return None


def current_volume(volumes: list["Volume"], total_chapters_written: int) -> "Volume | None":
    """当前活跃卷 —— 即"下一章将属于哪一卷"。

    章号映射优先（滚动生成卷架构，决策 5）：直接按下一章号 total_chapters_written + 1 走
    volume_of_chapter，status 退化为纯展示字段、不参与判定。

    背景：只要下一章仍落在卷 N 的 [chapter_start, planned_end] 内就稳定停在卷 N，
    不会因卷 N+1 已 append 为 in_progress 而"提前翻卷"。
    """
    if not volumes:
        return None
    return volume_of_chapter(total_chapters_written + 1, volumes)


def volume_position_card(state: "NovelState") -> str:
    """生成"当前卷位置卡"markdown 片段，供 chapter_plan / arc_outline / chapter
    三处 prompt 头部注入。

    空 volumes 时返回 ""（保持向后兼容，未启用分卷的老小说不注入）。

    返回格式（示例）：
        【当前卷位置】
        - 当前所在：第 2 卷《第二卷 · 内门风云》（第 29-63 章，共 35 章）
        - 本卷进度：本卷已完成 3/35 章
        - 上一卷：第一卷 · 少年入宗 —— …
        - 本卷主线：林渊晋升内门卷入派系与妖族危机…
        - 卷尾 setup：血月教锁定林渊为目标
        - 后续卷前瞻：
          · 第 3 卷《远征异域》：林渊率队远征妖域，中途遭遇……
    """
    if not state.volumes:
        return ""

    cur = current_volume(state.volumes, state.total_chapters_written)
    if cur is None:
        return ""

    # 本卷已完成章数 + 本卷规划总章数（planned_end 权威）
    done_in_vol = max(0, state.total_chapters_written - cur.chapter_start + 1)
    span = cur.planned_end - cur.chapter_start + 1

    lines = ["【当前卷位置】"]
    lines.append(
        f"- 当前所在：第 {cur.index} 卷《{cur.title}》"
        f"（第 {cur.chapter_start}-{cur.planned_end} 章，共 {span} 章）"
    )
    lines.append(f"- 本卷进度：本卷已完成 {done_in_vol}/{span} 章")

    # 上一卷
    prev_list = [v for v in state.volumes if v.index < cur.index]
    if prev_list:
        prev = max(prev_list, key=lambda v: v.index)
        prev_summary = prev.summary or "（无摘要）"
        lines.append(f"- 上一卷：{prev.title} —— {prev_summary}")

    lines.append(f"- 本卷主线：{cur.summary or '（无摘要）'}")

    if cur.setup_for_next:
        lines.append(f"- 卷尾 setup：{cur.setup_for_next}")

    # 后续卷前瞻（含前瞻草稿卷）：给当前卷规划提供「中期方向地图」——只列方向，不含章级细节。
    next_list = sorted((v for v in state.volumes if v.index > cur.index), key=lambda v: v.index)
    if next_list:
        lines.append("- 后续卷前瞻：")
        for nv in next_list:
            brief = nv.summary.strip() if nv.summary else "（方向待定）"
            lines.append(f"  · 第 {nv.index} 卷《{nv.title}》：{brief}")
    else:
        lines.append("- 后续卷前瞻：（本卷为终卷，无后续）")

    return "\n".join(lines)


def volume_cast_card(state: "NovelState") -> str:
    """生成"本卷花名册"markdown 片段，供 chapter_plan / arc_outline / 章前 entity_cards 三处注入。

    空花名册、或 volume_cast_index 与当前激活卷 index 不一致（陈旧——尚未为本卷生成花名册，或残留
    自上一卷）→ 返回 ""（向后兼容：老小说/未生成时不注入）。

    只渲染动态层（本卷阵容主线 + 返场阵容及各自本卷弧线 + 本卷新登场名单）：新登场实体的完整
    设定卡已并入 entity_cards、随 build_foundation_context 的【人物档案】段注入，故此处不重复卡片
    正文，只给"本卷谁登场、各自本卷干什么"的卷级地图。

    返回格式（示例）：
        【本卷花名册】
        - 本卷阵容主线：林渊挑大梁对阵血月教，夺回焚天印
        - 本卷登场阵容（含各自本卷弧线）：
          · 林渊：本卷从内门弟子成长为核心战力
          · 沈清颜：本卷揭开身世、与林渊结盟
        - 本卷新登场（完整设定见实体卡）：血月教主〔人物〕、焚天印〔物品〕
    """
    vc = state.volume_cast
    if not vc:
        return ""

    cur = current_volume(state.volumes, state.total_chapters_written)
    # 锚定校验：花名册须是「为当前激活卷」生成的，否则视为陈旧不注入（防串卷）。
    if cur is None or state.volume_cast_index != cur.index:
        return ""

    lines = ["【本卷花名册】"]

    focus = (vc.get("focus") or "").strip()
    if focus:
        lines.append(f"- 本卷阵容主线：{focus}")

    returning = vc.get("returning") or []
    returning_lines = []
    for r in returning:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        role = (r.get("role_in_volume") or "").strip() or "（本卷作用待定）"
        returning_lines.append(f"  · {name}：{role}")
    if returning_lines:
        lines.append("- 本卷登场阵容（含各自本卷弧线）：")
        lines.extend(returning_lines)

    introducing = vc.get("introducing") or []
    intro_names = "、".join(
        f"{i.get('name', '')}〔{i.get('type', '')}〕"
        for i in introducing
        if isinstance(i, dict) and (i.get("name") or "").strip()
    )
    if intro_names:
        lines.append(f"- 本卷新登场（完整设定见实体卡）：{intro_names}")

    # 只有标题、无任何实质内容 → 不注入（避免空壳段）
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
