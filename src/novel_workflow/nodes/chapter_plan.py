"""Phase 2.5: 章节规划(chapter_plan) 节点——滚动窗口的远端锚点层。

在整书 overall_outline 与批级 arc_outline 之间新增的中景大纲层:一次向前规划
CHAPTER_PLAN_WINDOW 章的 4 字段结构化条目(chapter/purpose/key_turn/ending_hook),
每写完 CHAPTER_PLAN_STRIDE 章滚动一次;已写完的章条目永久锁定,只重写未写部分。

- prepare_chapter_plan: 组装 system_context / task_prompt / review_type,交由通用 review_subgraph
- save_chapter_plan: 解析 LLM JSON → 逐条造 ChapterPlanItem → 与历史锁定段合并 → 写回 state
"""

from __future__ import annotations

import logging

from noval_workflow.config import CHAPTER_PLAN_WINDOW
from noval_workflow.context import build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.prompts.base import _extract_chapter_plan_range
from noval_workflow.state import ChapterPlanItem, NovelState, reset_review_fields

_logger = logging.getLogger(__name__)


def parse_chapter_plan_items(draft: str) -> list[ChapterPlanItem]:
    """把 LLM 输出的严格 JSON 数组解析成 ChapterPlanItem 列表并校验章号连续升序。

    解析失败 / 非对象 / 字段缺失 / 跳号倒序时抛 ValueError,让调用方(审核循环或
    mid-batch 编辑的错误兜底)重生成——不静默吞掉。空数组合法,返回空 list。
    """
    try:
        raw_items = repair_and_parse(draft, kind=list)
    except JsonParseError as exc:
        raise ValueError(f"章节规划 JSON 解析失败: {exc}") from exc

    items: list[ChapterPlanItem] = []
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"章节规划第 {idx} 条不是对象(dict),实际类型={type(raw).__name__}")
        try:
            item = ChapterPlanItem(**raw)
        except TypeError as exc:
            raise ValueError(f"章节规划第 {idx} 条字段不符: {exc}; 原始={raw!r}") from exc
        items.append(item)

    # 章号连续升序校验(LLM 常见错误:跳号 / 倒序)
    if items:
        chapters = [it.chapter for it in items]
        expected = list(range(chapters[0], chapters[0] + len(chapters)))
        if chapters != expected:
            raise ValueError(
                f"章节规划章号必须连续升序,实际={chapters}, 期望连续升序如 {expected}"
            )
    return items


def merge_chapter_plan(
    existing_plan: list[ChapterPlanItem],
    new_items: list[ChapterPlanItem],
    done: int,
) -> list[ChapterPlanItem]:
    """合并新旧章节规划:章号 <= done 的历史条目锁定为真值,LLM 若误输这些章号一律
    丢弃并 warning;章号 > done 采用新条目。返回按 chapter 升序的完整 list。

    唯一的锁定合并实现——主图 save_chapter_plan 与章末 mid-batch 编辑子图共用,
    避免两套语义漂移成新的分叉源。
    """
    historical = _extract_chapter_plan_range(existing_plan, 1, done) if done > 0 else []
    fresh: list[ChapterPlanItem] = []
    for item in new_items:
        if item.chapter <= done:
            _logger.warning(
                "章节规划 LLM 输出了已锁定章号 %d,丢弃(以历史真值为准)", item.chapter
            )
            continue
        fresh.append(item)
    return sorted(historical + fresh, key=lambda x: x.chapter)


def _plan_range(state: NovelState) -> tuple[int, int]:
    """按当前进度算本次要规划的章号范围 [start, end]。

    start = total_chapters_written + 1(下一章开始规划);
    end = start + WINDOW - 1(向前窗口末端)。
    调用方保证 CHAPTER_PLAN_ENABLED=True 且需要规划;不做边界剪裁,交由 LLM 自然处理。
    """
    start = state.total_chapters_written + 1
    end = start + CHAPTER_PLAN_WINDOW - 1
    return start, end


def prepare_chapter_plan(state: NovelState) -> dict:
    """组装章节规划任务:整书大纲 + 已写章速览 + 状态快照 + 已锁定历史条目 → prompt。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    start, end = _plan_range(state)
    # 已写完段(chapter <= done)作为「已锁定的历史条目」传入 prompt,LLM 只输出 [start, end] 新条目。
    done = state.total_chapters_written
    locked_entries = _extract_chapter_plan_range(state.chapter_plan, 1, done) if done > 0 else []
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.chapter_plan_prompt(
            state=state,
            start_chapter=start,
            end_chapter=end,
            locked_entries=locked_entries,
        ),
        "review_type": "chapter_plan",
        **reset_review_fields(),
    }


def save_chapter_plan(state: NovelState) -> dict:
    """解析并落库章节规划:严格 JSON → 逐条 ChapterPlanItem → 与历史锁定段合并。

    - JSON 解析失败 / 字段缺失 / 类型错时抛 ValueError,让审核子图的下一轮重生成兜底
      (不静默吞掉——上游把审核循环设计成对这种失败友好)。
    - 合并策略:章号 <= done 的条目走历史真值,LLM 若误输出这些章号一律丢弃;
      章号 > done 的条目采用 LLM 输出。最后按 chapter 升序返回。
    """
    done = state.total_chapters_written

    # 解析 + 校验 + 锁定合并全部走公共 helper(与 mid-batch 编辑子图共用同一实现)
    new_items = parse_chapter_plan_items(state.current_draft)
    merged = merge_chapter_plan(state.chapter_plan, new_items, done)
    planned_upto = merged[-1].chapter if merged else state.chapter_plan_planned_upto

    return {
        "chapter_plan": merged,
        "chapter_plan_planned_upto": planned_upto,
        # 记录本次触发进度,供 route_continue_or_end 的 STRIDE 判定避免重复触发。
        "chapter_plan_last_regen_at": done,
    }
