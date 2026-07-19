"""Phase 1.5 / 滚动：分卷规划(volumes) 节点——横向大结构中间层（滚动生成卷 + 前瞻队列）。

位于 overall_outline 之下、chapter_plan 之上。前瞻队列：每次规划「1 个激活卷（要立即展开）
+ N 个前瞻草稿卷」（N = config.VOLUME_LOOKAHEAD）。草稿卷只出方向骨架、不锁章号
（chapter_start=planned_end=0, status=planning），给当前卷规划提供中期地图，轮到时才转正。
写作推进到接近当前激活卷末章时，由 route_continue_or_end 触发滚动：重新生成「未开始的卷」
（含即将转正的队首），已开始的卷（in_progress/closed）冻结不改。卷长由 LLM 内容驱动
（松护栏 [VOLUME_MIN,VOLUME_MAX]，「LLM 夹、人可破」），index/chapter_start/planned_end/status
一律由 save_volumes 权威赋值——不信 LLM 的绝对章号，只取它给的「本卷章数(chapters)」建议。

契约（current_draft 是对象 {"volumes":[激活卷, 草稿1, ...], "human_confirmed"?: bool}）：
  激活卷 4 字段 title/summary/setup_for_next/chapters；草稿卷 3 字段（无 chapters）。
  review 表单「通过」时带 human_confirmed=true 作「人工终裁」标记（LLM 原样无此字段），控激活卷章数是否夹护栏。

- prepare_volumes: 双模（首次规划前 1+N 卷 / 滚动重规划未开始的 1+N 卷）
- save_volumes: 多卷解析 + 权威赋值（激活卷 in_progress + 草稿卷 planning；滚动收口上一卷 + 丢旧草稿）
- route_after_save_volumes: 首次(written==0)→继续设定链(人物卡)；滚动→展开新激活卷 chapter_plan
"""

from __future__ import annotations

import logging
from dataclasses import fields, replace

from noval_workflow.context import build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.state import NovelState, Volume, reset_review_fields

_logger = logging.getLogger(__name__)


def _coerce_volume(v) -> Volume:
    """把 state.volumes 里的元素归一为 Volume 实例。

    LangGraph checkpoint 重水合可能把 Volume 落成 dict（参照 entity_cards 的 _coerce_card）；
    这里防御性归一，过滤未知键（老快照残留的 target_min/target_max 等已删字段被自动丢弃）。
    """
    if isinstance(v, Volume):
        return v
    if isinstance(v, dict):
        valid = {f.name for f in fields(Volume)}
        return Volume(**{k: val for k, val in v.items() if k in valid})
    raise ValueError(f"分卷条目类型非法: {type(v).__name__}")


def _prior_volumes_brief(volumes: list[Volume]) -> str:
    """把已有卷压成节选（卷号/卷名/章号区间/主线/卷尾钩），喂给滚动卷规划做承接依据。"""
    lines = []
    for v in sorted(volumes, key=lambda x: x.index):
        end = v.planned_end if v.planned_end > 0 else "?"
        line = f"- 第 {v.index} 卷《{v.title}》(第 {v.chapter_start}-{end} 章)：{v.summary or '（无主线摘要）'}"
        if v.setup_for_next:
            line += f" | 卷尾钩：{v.setup_for_next}"
        lines.append(line)
    return "\n".join(lines)


def prepare_volumes(state: NovelState) -> dict:
    """双模抽卷：首次规划开篇前 1+N 卷；滚动重规划从下一卷起的 1+N 卷（N=VOLUME_LOOKAHEAD）。

    第 1 卷是要立即展开的激活卷，其后是前瞻草稿卷（只出方向、不锁章号，可动态修订）。
    """
    from noval_workflow.config import VOLUME_LOOKAHEAD

    pack = get_prompt_pack(state.genre, state.novel_name)
    if not state.volumes:
        # 首次：整书大纲 → 卷 1 激活 + 前瞻草稿
        task_prompt = pack.volumes_prompt(state.overall_outline, lookahead=VOLUME_LOOKAHEAD)
    else:
        # 滚动：只承接「已激活卷」(planned_end>0)——旧草稿卷本轮要重生成，不参与承接。
        existing = [_coerce_volume(v) for v in state.volumes]
        activated = [v for v in existing if v.planned_end > 0]
        prev = max(activated, key=lambda v: v.index)
        task_prompt = pack.volumes_prompt_rolling(
            overall_outline=state.overall_outline,
            prior_volumes_brief=_prior_volumes_brief(activated),
            total_chapters_written=state.total_chapters_written,
            next_index=prev.index + 1,
            next_chapter_start=prev.planned_end + 1,
            prev_setup_for_next=prev.setup_for_next,
            lookahead=VOLUME_LOOKAHEAD,
        )
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": task_prompt,
        "review_type": "volumes",
        **reset_review_fields(),
    }


def _parse_active_volume(raw) -> tuple[str, str, str, int]:
    """解析激活卷（数组第 1 项）→ (title, summary, setup_for_next, chapters)。字段错抛 ValueError。"""
    if not isinstance(raw, dict):
        raise ValueError(f"激活卷必须是 JSON 对象，实际类型={type(raw).__name__}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"激活卷缺 title(卷名)，原始={raw!r}")
    summary = raw.get("summary", "")
    setup_for_next = raw.get("setup_for_next", "")
    if not isinstance(summary, str) or not isinstance(setup_for_next, str):
        raise ValueError(f"激活卷 summary/setup_for_next 必须是字符串，原始={raw!r}")
    chapters = raw.get("chapters")
    # bool 是 int 子类，需显式排除（True/False 混进章数是 LLM 常见错）
    if not isinstance(chapters, int) or isinstance(chapters, bool) or chapters <= 0:
        raise ValueError(f"激活卷 chapters(本卷章数)必须是正整数，实际={chapters!r}")
    return title.strip(), summary, setup_for_next, chapters


def _parse_draft_volume(raw, position: int) -> tuple[str, str, str]:
    """解析前瞻草稿卷（数组第 2 项起）→ (title, summary, setup_for_next)。草稿卷不含 chapters。"""
    if not isinstance(raw, dict):
        raise ValueError(f"草稿卷(第 {position} 项)必须是 JSON 对象，实际类型={type(raw).__name__}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"草稿卷(第 {position} 项)缺 title(卷名)，原始={raw!r}")
    summary = raw.get("summary", "")
    setup_for_next = raw.get("setup_for_next", "")
    if not isinstance(summary, str) or not isinstance(setup_for_next, str):
        raise ValueError(f"草稿卷(第 {position} 项) summary/setup_for_next 必须是字符串，原始={raw!r}")
    return title.strip(), summary, setup_for_next


def _parse_volume_drafts(
    draft: str,
) -> tuple[tuple[str, str, str, int], list[tuple[str, str, str]], bool]:
    """解析多卷草稿 → (激活卷, 草稿卷列表, human_authored)。

    契约：current_draft 是对象 `{"volumes": [激活卷, 草稿1, ...], "human_confirmed"?: bool}`。
      - 激活卷（数组第 1 项）：title/summary/setup_for_next/chapters（要立即展开，含章数）
      - 草稿卷（其余项）：title/summary/setup_for_next（前瞻方向，不含章数）
    human_authored：顶层 `human_confirmed is True`（review 表单「通过」时带），控激活卷章数是否夹护栏
    （见 _clamp_chapters）——LLM 夹、人可破。宽松兼容：LLM 偶尔直接吐裸数组（未包 volumes 键）也接受。
    解析/字段错抛 ValueError，由 review 子图下一轮兜底重生成。
    """
    try:
        raw = repair_and_parse(draft, kind=dict)
    except JsonParseError:
        # 兼容 LLM 偶尔直接吐裸数组（未包 volumes 键）
        try:
            raw = {"volumes": repair_and_parse(draft, kind=list)}
        except JsonParseError as exc:
            raise ValueError(f"分卷规划 JSON 解析失败: {exc}") from exc

    vol_list = raw.get("volumes")
    if not isinstance(vol_list, list) or not vol_list:
        raise ValueError(f"分卷规划必须含非空 volumes 数组，原始={raw!r}")
    human_authored = raw.get("human_confirmed") is True

    active = _parse_active_volume(vol_list[0])
    drafts = [_parse_draft_volume(v, pos) for pos, v in enumerate(vol_list[1:], start=2)]
    return active, drafts, human_authored


def _clamp_chapters(chapters: int, human_authored: bool) -> int:
    """章数松护栏：LLM 自主输出夹到 [MIN,MAX]+warning；人工在 review 抽屉显式突破则尊重(仅 info)。"""
    from noval_workflow.config import VOLUME_MAX_CHAPTERS, VOLUME_MIN_CHAPTERS

    if not human_authored:
        clamped = max(VOLUME_MIN_CHAPTERS, min(VOLUME_MAX_CHAPTERS, chapters))
        if clamped != chapters:
            _logger.warning(
                "分卷章数 %d 超出松护栏 [%d,%d]，夹到 %d（LLM 自主输出；人工可在 review 抽屉突破）",
                chapters, VOLUME_MIN_CHAPTERS, VOLUME_MAX_CHAPTERS, clamped,
            )
        return clamped
    if chapters < VOLUME_MIN_CHAPTERS or chapters > VOLUME_MAX_CHAPTERS:
        _logger.info(
            "分卷章数 %d 超出松护栏 [%d,%d]，人工在 review 抽屉显式突破，予以尊重",
            chapters, VOLUME_MIN_CHAPTERS, VOLUME_MAX_CHAPTERS,
        )
    return chapters


def save_volumes(state: NovelState) -> dict:
    """多卷解析 + 权威赋值 + 前瞻队列 merge。

    首次（无已激活卷）：激活卷=卷 1 [1, chapters] in_progress + 草稿卷 planning（章号 0）。
    滚动（已有激活卷）：上一激活卷收口（actual_end=planned_end, status=closed）、丢弃所有旧 planning
    草稿、append 新激活卷（chapter_start=上一卷 planned_end+1）+ 新草稿卷。已 closed 卷冻结不动。

    激活卷章数走松护栏（_clamp_chapters）；index/chapter_start/planned_end/status 一律权威赋值。
    覆盖语义：返回全量 volumes（已激活卷[含刚收口的] + 新激活卷 + 新草稿卷）。
    """
    active, drafts, human_authored = _parse_volume_drafts(state.current_draft)
    a_title, a_summary, a_setup, a_chapters = active
    a_chapters = _clamp_chapters(a_chapters, human_authored)

    existing = [_coerce_volume(v) for v in state.volumes]
    # 已激活卷 = 有权威章号（planned_end>0）的卷；旧 planning 草稿（planned_end=0）本轮丢弃重生成。
    activated = [v for v in existing if v.planned_end > 0]

    if not activated:
        # 首次：激活卷 = 卷 1，起始章号锁 1；无历史卷需保留
        base_index = 0
        chapter_start = 1
        kept: list[Volume] = []
    else:
        # 滚动：上一激活卷（最大 index）收口 closed，保留全部已激活卷（含它），丢弃旧草稿
        prev = max(activated, key=lambda v: v.index)
        closed_prev = replace(prev, actual_end=prev.planned_end, status="closed")
        kept = [closed_prev if v.index == prev.index else v for v in activated]
        base_index = prev.index
        chapter_start = prev.planned_end + 1

    active_vol = Volume(
        index=base_index + 1,
        title=a_title,
        summary=a_summary,
        setup_for_next=a_setup,
        chapter_start=chapter_start,
        planned_end=chapter_start + a_chapters - 1,
        status="in_progress",
    )
    # 草稿卷：不锁章号（chapter_start=planned_end=0），index 顺延，planning 态。
    draft_vols = [
        Volume(
            index=base_index + 1 + offset,
            title=d_title,
            summary=d_summary,
            setup_for_next=d_setup,
            chapter_start=0,
            planned_end=0,
            status="planning",
        )
        for offset, (d_title, d_summary, d_setup) in enumerate(drafts, start=1)
    ]

    return {
        "volumes": kept + [active_vol] + draft_vols,
        **reset_review_fields(),
    }


def route_after_save_volumes(state: NovelState) -> str:
    """首次分卷（尚未开写，written==0）→继续设定链(人物卡)；滚动分卷（写作中）→展开新卷 chapter_plan。"""
    return "prepare_character_cards" if state.total_chapters_written == 0 else "prepare_chapter_plan"
