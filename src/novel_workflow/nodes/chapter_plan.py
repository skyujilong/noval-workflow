"""Phase 2.5: 章节规划(chapter_plan) 节点——以「卷」为规划单元的中景大纲层。

在整书 overall_outline 与批级 arc_outline 之间的中景大纲层:滚动生成卷架构下,chapter_plan
以「卷」为单元一次规划整卷的 4 字段结构化条目(chapter/purpose/key_turn/ending_hook)——
prepare_chapter_plan 只在「卷刚生成好」时触发(开书首卷 / 滚动新卷),规划该卷 [chapter_start,
planned_end];本卷之前(含前卷)的条目永久锁定,不重规划。

- prepare_chapter_plan: 组装 system_context / task_prompt / review_type,交由通用 review_subgraph
- save_chapter_plan: 解析 LLM JSON → 逐条造 ChapterPlanItem → 与历史锁定段合并 → 写回 state
"""

from __future__ import annotations

import logging

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
    plan_end: int | None = None,
) -> list[ChapterPlanItem]:
    """合并新旧章节规划:章号 <= done 的历史条目锁定为真值,LLM 若误输这些章号一律
    丢弃并 warning;章号 > done 采用新条目。返回按 chapter 升序的完整 list。

    plan_end 非 None 时再钳制上界:章号 > plan_end 的新条目一律丢弃——LLM 常无视
    「只规划 N 章」而超发(实测首规划被要求 40 章却一口气吐 119 章),不拦就会静默全收、
    还会把 planned_upto 顶到 119 污染 STRIDE 滚动记账。与下界 done 对称,把新条目锁死
    在 [done+1, plan_end] 窗口内。mid-batch 编辑子图不传此参(默认 None),行为不变。

    唯一的锁定合并实现——主图 save_chapter_plan 与章末 mid-batch 编辑子图共用,
    避免两套语义漂移成新的分叉源。
    """
    historical = _extract_chapter_plan_range(existing_plan, 1, done) if done > 0 else []
    fresh: list[ChapterPlanItem] = []
    overshoot = 0
    for item in new_items:
        if item.chapter <= done:
            _logger.warning(
                "章节规划 LLM 输出了已锁定章号 %d,丢弃(以历史真值为准)", item.chapter
            )
            continue
        if plan_end is not None and item.chapter > plan_end:
            overshoot += 1
            continue
        fresh.append(item)
    if overshoot:
        # 聚合成一条 warning,避免超发几十条时刷屏
        _logger.warning(
            "章节规划 LLM 超发 %d 条(章号 > 窗口末章 %d),已截断丢弃", overshoot, plan_end
        )
    return sorted(historical + fresh, key=lambda x: x.chapter)


def _plan_range(state: NovelState) -> tuple[int, int]:
    """本次 chapter_plan 要规划的章号范围 [start, end]——以「卷」为单元。

    规划对象 = 当前(最大 index)卷:开书首卷,或滚动刚生成的新卷。
      start = max(卷 chapter_start, 已写 + 1)  —— 卷内已写部分锁定,只规划未写段的卷范围
      end   = 卷 planned_end                    —— 规划到卷末(而非旧的固定 WINDOW 窗口)
    无 volumes / planned_end 未定(老快照) → 回退,不返回非法区间(end < start)。
    """
    done = state.total_chapters_written
    if not state.volumes:
        return done + 1, done + 1
    cur = max(state.volumes, key=lambda v: v.index)
    start = max(cur.chapter_start, done + 1)
    end = cur.planned_end
    if end < start:
        # planned_end 未定(老快照)回退 target_max 换算;再不行退化为单章,避免非法区间
        end = cur.chapter_start + cur.target_max - 1 if cur.target_max > 0 else start
        end = max(end, start)
    return start, end


def prepare_chapter_plan(state: NovelState) -> dict:
    """组装章节规划任务:整书大纲 + 已写章速览 + 状态快照 + 已锁定历史条目 → prompt。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    start, end = _plan_range(state)
    # 本卷之前(含前卷未写尾巴)已锁定,取靠近 start 的一段(最多 10 条)作承接上下文,不整段倾倒。
    lock_upto = start - 1
    locked_entries = (
        _extract_chapter_plan_range(state.chapter_plan, max(1, start - 10), lock_upto)
        if lock_upto >= 1 else []
    )
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
    - 合并策略:章号 <= lock_boundary(本卷之前)的条目走历史真值,LLM 若误输出一律丢弃;
      章号 > lock_boundary 的条目采用 LLM 输出。最后按 chapter 升序返回。
    """
    # 本卷规划范围 [start, plan_end];复用 _plan_range 保持单一来源。
    start, plan_end = _plan_range(state)
    # 锁定边界 = 本卷之前的一切(含前卷已规划未写的尾巴),只规划本卷 [start, plan_end]。
    # 卷中续规划(start=done+1)时 lock_boundary=done,等价旧「锁已写、重规划未写」;
    # 滚动新卷(start=前卷末+1)时 lock_boundary=前卷末,保住前卷未写尾巴不被丢。
    lock_boundary = start - 1

    # 解析 + 校验 + 锁定合并全部走公共 helper(与 mid-batch 编辑子图共用同一实现)
    new_items = parse_chapter_plan_items(state.current_draft)
    merged = merge_chapter_plan(state.chapter_plan, new_items, lock_boundary, plan_end)
    planned_upto = merged[-1].chapter if merged else state.chapter_plan_planned_upto

    return {
        "chapter_plan": merged,
        "chapter_plan_planned_upto": planned_upto,
        # 记录本次触发进度,供 route_continue_or_end 的 STRIDE 判定避免重复触发（Step 4 删）。
        "chapter_plan_last_regen_at": state.total_chapters_written,
    }
