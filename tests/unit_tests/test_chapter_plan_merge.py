"""merge_chapter_plan 的窗口钳制单测——重点覆盖新增的 plan_end 上界防线。

背景:LLM 常无视「只规划 N 章」而超发(实测首规划被要求 40 章却一口气吐 119 章),
merge_chapter_plan 现用 plan_end 把新条目锁死在 [done+1, plan_end] 窗口内。这里锁定:
  1. 首规划超发 119 → 只留 1-40,且打 WARNING。
  2. 滚动重规划超发 → 只留窗口段,且已锁定历史(chapter <= done)逐字不变。
  3. plan_end=None(mid-batch 编辑子图路径)→ 不设上界,向后兼容。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

from noval_workflow.nodes.chapter_plan import merge_chapter_plan
from noval_workflow.state import ChapterPlanItem

_PLAN_LOGGER = "noval_workflow.nodes.chapter_plan"


@contextmanager
def _capture_plan_warnings(caplog):
    """抓取 chapter_plan 节点的 WARNING。

    本包 logger 在 logging_setup 里设了 propagate=False,pytest 的 caplog 默认挂 root、
    抓不到;这里把 caplog 的 handler 直接挂到目标 logger 上绕过 propagate 拦截。
    """
    logger = logging.getLogger(_PLAN_LOGGER)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=_PLAN_LOGGER):
            yield
    finally:
        logger.removeHandler(caplog.handler)


def _item(chapter: int, purpose: str = "占位目标") -> ChapterPlanItem:
    """造一条字段齐全的合规 ChapterPlanItem;purpose 可定制以验证逐字保留。"""
    return ChapterPlanItem(
        chapter=chapter,
        purpose=purpose,
        key_turn=f"第{chapter}章关键事件",
        ending_hook=f"第{chapter}章结尾钩子",
        intensity="推进",
    )


def test_first_plan_caps_overshoot_at_window_end(caplog):
    """首规划被要求 40 章、LLM 却吐 119 章 → 只保留 1-40,并 WARNING 暴露超发。"""
    new_items = [_item(c) for c in range(1, 120)]  # 1..119

    with _capture_plan_warnings(caplog):
        merged = merge_chapter_plan([], new_items, done=0, plan_end=40)

    assert [it.chapter for it in merged] == list(range(1, 41))  # 恰好 1..40
    assert len(merged) == 40
    assert any("超发" in rec.message for rec in caplog.records), "超发应打 WARNING 暴露"


def test_rolling_regen_keeps_locked_history_and_caps_tail(caplog):
    """滚动重规划:已写 30 章,窗口 [31,70];LLM 又超发到 119。
    → 历史 1-30 逐字锁定、新段截到 31-70、超出的 71+ 丢弃。
    """
    existing = [_item(c, purpose=f"历史真值-{c}") for c in range(1, 31)]  # 1..30 已锁定
    # LLM 常见错误:既重输已锁定章号(带篡改),又超发到窗口外
    new_items = [_item(c, purpose="LLM改写") for c in range(1, 120)]  # 1..119

    with _capture_plan_warnings(caplog):
        merged = merge_chapter_plan(existing, new_items, done=30, plan_end=70)

    assert [it.chapter for it in merged] == list(range(1, 71))  # 1..70
    # 1..30 走历史真值,LLM 的改写被丢弃
    for it in merged:
        if it.chapter <= 30:
            assert it.purpose == f"历史真值-{it.chapter}"
    assert any("超发" in rec.message for rec in caplog.records)


def test_plan_end_none_is_backward_compatible():
    """plan_end 缺省(mid-batch 编辑子图调用姿势)→ 不设上界,新条目全保留。"""
    new_items = [_item(c) for c in range(1, 51)]  # 1..50

    merged = merge_chapter_plan([], new_items, done=0)  # 不传 plan_end

    assert [it.chapter for it in merged] == list(range(1, 51))
    assert len(merged) == 50


def test_rolling_volume_expand_preserves_prior_volume_tail():
    """滚动展开新卷:卷1 已规划 [1,30](含未写尾巴 21-30),锁定边界=30,新卷规划 [31,40]。
    → 合并保住卷1 全部 1-30(逐字不变) + 追加新卷 31-40,不丢中间未写的 21-30。
    """
    # 卷1 的完整 chapter_plan(1..30),其中 21-30 尚未写但已规划
    existing = [_item(c, purpose=f"卷1真值-{c}") for c in range(1, 31)]
    # 新卷 chapter_plan(31..40)
    new_items = [_item(c, purpose="卷2新规划") for c in range(31, 41)]

    # lock_boundary=30(=新卷 chapter_start-1),plan_end=40(新卷 planned_end)
    merged = merge_chapter_plan(existing, new_items, done=30, plan_end=40)

    assert [it.chapter for it in merged] == list(range(1, 41))  # 1..40 无缺口
    # 卷1 的 21-30(未写尾巴)逐字保住,没被丢
    for it in merged:
        if it.chapter <= 30:
            assert it.purpose == f"卷1真值-{it.chapter}"
        else:
            assert it.purpose == "卷2新规划"
