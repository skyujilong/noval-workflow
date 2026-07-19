"""卷级花名册（Volume Cast Roster）节点——卷激活、展开 chapter_plan 之前生成本卷登场阵容。

「全书实体真源 entity_cards」与「章级临场发现」之间的中间层：为本卷新登场的重要人物/关键物品
在卷规划时就生成**完整设定卡**（同开书卡司规格，含物品），复用 merge_cards_from_json 去重预注册
进 entity_cards（canon，已有实体按 name+aliases 命中即丢弃）；返场角色 + 本卷弧线 + 本卷主线走
动态字段 volume_cast。经强制人工审核（可编辑）后，由 volume_cast_card 注入 chapter_plan/arc/
章前实体环节，给长线埋线与卷内承接提供卷级前置依据，取代「正文临场现编重要人物/道具」。

在图里位于两条路径汇入 prepare_chapter_plan 之前（开书：save_config→；滚动：save_volumes 的
written>0 分支→），每次卷激活跑一次；草稿卷不触发。

- prepare_volume_cast: 取当前激活卷 → 组装花名册生成任务（review_type=volume_cast）
- save_volume_cast: 解析 introducing/returning/focus → introducing 去重落 entity_cards + 写 volume_cast
"""

from __future__ import annotations

import logging

from noval_workflow.context import build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.nodes.entity_cards import merge_cards_from_json
from noval_workflow.prompts import volume_cast_prompt
from noval_workflow.state import NovelState, reset_review_fields
from noval_workflow.volume_utils import current_volume

_logger = logging.getLogger(__name__)


def prepare_volume_cast(state: NovelState) -> dict:
    """组装本卷「花名册」生成任务。

    system_context 用完整基础设定（含世界观/力量体系/现有卡司）——判定实体是否已有、能力是否
    落体系都依赖它；task_prompt 用 volume_cast_prompt（读激活卷主线 + 现有卡司 + 后续卷前瞻）。
    题材差异经 system_context 的题材身份前缀影响，故 prompt 本身题材中性（同 entity_cards）。
    """
    active = current_volume(state.volumes, state.total_chapters_written)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": volume_cast_prompt(state, active),
        "review_type": "volume_cast",
        **reset_review_fields(),
    }


def save_volume_cast(state: NovelState) -> dict:
    """解析花名册草稿 → introducing 完整卡去重落 entity_cards（canon）+ 写 volume_cast 动态层。

    - introducing：本卷新登场重要人物/物品的完整卡，走 merge_cards_from_json（与 Phase-1/章前
      同一套 parse/去重/owner 解析；已在卡库的实体按 name+aliases 命中即丢弃，canon 优先，不重复建卡）。
    - returning/focus：返场阵容 + 本卷主线，写进 volume_cast 动态层供注入。
    - 章号锚定 volume_cast_index = 当前激活卷 index，供 volume_cast_card 核对防陈旧串卷。
    - JSON 解析失败 / 字段类型错时 fail-loud（ValueError），交审核子图下一轮重生成兜底。
    """
    if not state.current_draft:
        raise ValueError("volume_cast current_draft 为空，本卷花名册未生成")
    try:
        parsed = repair_and_parse(state.current_draft, kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"本卷花名册 JSON 解析失败: {exc}") from exc

    introducing = parsed.get("introducing", []) or []
    returning = parsed.get("returning", []) or []
    focus = parsed.get("focus", "")
    if not isinstance(introducing, list):
        raise ValueError(f"volume_cast introducing 必须是数组，实际类型={type(introducing).__name__}")
    if not isinstance(returning, list):
        raise ValueError(f"volume_cast returning 必须是数组，实际类型={type(returning).__name__}")

    active = current_volume(state.volumes, state.total_chapters_written)
    active_index = active.index if active else -1

    existing_count = len(state.entity_cards or [])
    # introducing 完整卡去重落库（parse_card 校验字段/type/role，非法即 ValueError）
    merged = merge_cards_from_json(introducing, state.entity_cards)

    # returning 归一为 [{"name","role_in_volume"}]，只留有 name 的条目（防 LLM 塞脏项）
    returning_clean = [
        {"name": str(r["name"]).strip(), "role_in_volume": str(r.get("role_in_volume", "")).strip()}
        for r in returning
        if isinstance(r, dict) and str(r.get("name", "")).strip()
    ]
    # introducing 名单回执（供前端/注入展示「本卷新登场」，完整卡已在 entity_cards）
    introducing_brief = [
        {"name": str(c.get("name", "")).strip(), "type": str(c.get("type", "")).strip()}
        for c in introducing
        if isinstance(c, dict) and str(c.get("name", "")).strip()
    ]

    volume_cast = {
        "volume_index": active_index,
        "focus": focus if isinstance(focus, str) else "",
        "returning": returning_clean,
        "introducing": introducing_brief,
    }
    _logger.info(
        "volume_cast 落地：第 %s 卷 新增卡 %d 张、返场 %d 人（卡库共 %d）",
        active_index, len(merged) - existing_count, len(returning_clean), len(merged),
    )
    return {
        "entity_cards": merged,
        "volume_cast": volume_cast,
        "volume_cast_index": active_index,
        **reset_review_fields(),
    }
