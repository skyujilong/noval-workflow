"""Phase 1.5 / 滚动：分卷规划(volumes) 节点——横向大结构中间层（滚动生成卷架构）。

位于 overall_outline 之下、chapter_plan 之上。滚动生成卷：开书只规划卷 1；写作推进到接近
当前卷末章时，由 route_continue_or_end 触发再规划下一卷。卷长由 LLM 内容驱动（松护栏
[VOLUME_MIN,VOLUME_MAX]，「LLM 夹、人可破」），index/chapter_start/planned_end/status 一律
由 save_volumes 权威赋值——不信 LLM 的绝对章号，只取它给的「本卷章数(chapters)」建议。

单卷契约（current_draft 是一个 JSON 对象，不是数组）：
  LLM 输出 4 个内容字段 title/summary/setup_for_next/chapters；其余字段后端算。
  review 表单「通过」时会带上算好的 planned_end 作为「人工终裁」标记（LLM 原样无此字段）。

- prepare_volumes: 双模（首次仅规划卷 1 / 滚动规划下一卷）
- save_volumes: 单卷解析 + 权威赋值（首次→卷1 in_progress；滚动→上一卷收口 append 新卷）
- route_after_save_volumes: 首次(written==0)→继续设定链(人物卡)；滚动→展开新卷 chapter_plan
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
    这里防御性归一，过滤未知键（过渡期老快照的 target_min/target_max 仍是合法字段，予以保留）。
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
    """双模抽卷：首次仅规划卷 1；滚动规划下一卷。拼装 task_prompt 交给通用 review_subgraph。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    if not state.volumes:
        # 首次：整书大纲 → 卷 1
        task_prompt = pack.volumes_prompt(state.overall_outline)
    else:
        # 滚动：整书大纲 + 已有卷节选 + 当前进度 + 上一卷卷尾钩 → 下一卷
        existing = [_coerce_volume(v) for v in state.volumes]
        prev = max(existing, key=lambda v: v.index)
        task_prompt = pack.volumes_prompt_rolling(
            overall_outline=state.overall_outline,
            prior_volumes_brief=_prior_volumes_brief(existing),
            total_chapters_written=state.total_chapters_written,
            next_index=prev.index + 1,
            next_chapter_start=prev.planned_end + 1,
            prev_setup_for_next=prev.setup_for_next,
        )
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": task_prompt,
        "review_type": "volumes",
        **reset_review_fields(),
    }


def _parse_single_volume_draft(draft: str) -> tuple[str, str, str, int, bool]:
    """解析单卷草稿对象 → (title, summary, setup_for_next, chapters, human_authored)。

    human_authored：草稿是否带 `human_confirmed: true`。review 表单「通过」时会带上此标记（人工终裁），
    LLM 原样不带。用于决定章数是否夹护栏（见 _clamp_chapters）——LLM 夹、人可破。
    解析/字段错抛 ValueError，由 review 子图下一轮兜底重生成。
    """
    try:
        raw = repair_and_parse(draft, kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"分卷规划 JSON 解析失败: {exc}") from exc

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"分卷缺 title(卷名)，原始={raw!r}")
    summary = raw.get("summary", "")
    setup_for_next = raw.get("setup_for_next", "")
    if not isinstance(summary, str) or not isinstance(setup_for_next, str):
        raise ValueError(f"分卷 summary/setup_for_next 必须是字符串，原始={raw!r}")
    chapters = raw.get("chapters")
    # bool 是 int 子类，需显式排除（True/False 混进章数是 LLM 常见错）
    if not isinstance(chapters, int) or isinstance(chapters, bool) or chapters <= 0:
        raise ValueError(f"分卷 chapters(本卷章数)必须是正整数，实际={chapters!r}")

    human_authored = raw.get("human_confirmed") is True
    return title.strip(), summary, setup_for_next, chapters, human_authored


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
    """单卷解析 + 权威赋值 + 滚动 merge。

    首次（state.volumes 空）：生成卷 1（chapter_start=1, in_progress）。
    滚动（已有卷）：上一卷收口（actual_end=planned_end, status=closed）、append 新卷
    （chapter_start=上一卷 planned_end+1, in_progress）。不做拆卷/合卷。

    章数走松护栏（_clamp_chapters）；index/chapter_start/planned_end/status 一律权威赋值。
    覆盖语义：返回全量 volumes 列表（含收口的旧卷 + 新卷）。
    """
    title, summary, setup_for_next, chapters, human_authored = _parse_single_volume_draft(
        state.current_draft
    )
    chapters = _clamp_chapters(chapters, human_authored)

    existing = [_coerce_volume(v) for v in state.volumes]
    if not existing:
        # 首次：仅卷 1，起始章号锁 1
        new_vol = Volume(
            index=1,
            title=title,
            summary=summary,
            setup_for_next=setup_for_next,
            chapter_start=1,
            planned_end=chapters,  # chapter_start(1) + chapters - 1
            status="in_progress",
        )
        volumes = [new_vol]
    else:
        # 滚动：上一卷收口 + append 新卷
        prev = max(existing, key=lambda v: v.index)
        if prev.planned_end <= 0:
            raise ValueError(f"滚动生成卷失败：上一卷（第 {prev.index} 卷）planned_end 未赋值")
        closed_prev = replace(prev, actual_end=prev.planned_end, status="closed")
        chapter_start = prev.planned_end + 1
        new_vol = Volume(
            index=prev.index + 1,
            title=title,
            summary=summary,
            setup_for_next=setup_for_next,
            chapter_start=chapter_start,
            planned_end=chapter_start + chapters - 1,
            status="in_progress",
        )
        volumes = [closed_prev if v.index == prev.index else v for v in existing] + [new_vol]

    return {
        "volumes": volumes,
        **reset_review_fields(),
    }


def route_after_save_volumes(state: NovelState) -> str:
    """首次分卷（尚未开写，written==0）→继续设定链(人物卡)；滚动分卷（写作中）→展开新卷 chapter_plan。"""
    return "prepare_character_cards" if state.total_chapters_written == 0 else "prepare_chapter_plan"
