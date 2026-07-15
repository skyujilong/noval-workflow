"""Phase 1.5: 分卷规划(volumes) 节点——横向大结构中间层。

位于 overall_outline 之下、chapter_plan 之上：把整体大纲里已有的"四卷式"markdown
骨架抽取成结构化 Volume 列表，供下游 volume_position_card / volume_boundary_gate
消费。弹性 range 语义（chapter_start 锁章号，target_min/max 是章数软约束）严格
与 volume_utils.py + state.Volume 一致。

- prepare_volumes: 组装 system_context / task_prompt / review_type=volumes,交由通用 review_subgraph
- save_volumes: 解析 LLM JSON → 逐条造 Volume → 校验拼接/顺序 → 第一卷 status=in_progress → 写回 state

参照 chapter_plan.py 的节点范式（章号连续升序 → 卷章号顺次拼接；JSON 解析失败/字段
错时抛 ValueError，让审核子图重试兜底）。
"""

from __future__ import annotations

from noval_workflow.context import build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.state import NovelState, Volume, reset_review_fields


def prepare_volumes(state: NovelState) -> dict:
    """从 state.overall_outline 抽卷：拼装 task_prompt 交给通用 review_subgraph。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.volumes_prompt(state.overall_outline),
        "review_type": "volumes",
        **reset_review_fields(),
    }


def save_volumes(state: NovelState) -> dict:
    """解析并落库分卷列表：严格 JSON → 逐条 Volume → 拼接校验 → 第一卷 in_progress。

    校验失败一律抛 ValueError（LLM 常错点：字段缺失、chapter_start 不接续、min>max、
    非正数章数），由审核子图下一轮兜底重生成——与 save_chapter_plan 同款策略。
    """
    # 第一步：解析 JSON
    try:
        raw_items = repair_and_parse(state.current_draft, kind=list)
    except JsonParseError as exc:
        raise ValueError(f"分卷规划 JSON 解析失败: {exc}") from exc

    if not raw_items:
        raise ValueError("分卷规划输出为空数组，至少需要 1 卷")

    # 第二步：逐条造 Volume 实例（字段缺失/类型错抛 TypeError）
    volumes: list[Volume] = []
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"分卷规划第 {idx+1} 项不是对象(dict)，实际类型={type(raw).__name__}")
        try:
            vol = Volume(**raw)
        except TypeError as exc:
            raise ValueError(f"分卷规划第 {idx+1} 项字段不符: {exc}; 原始={raw!r}") from exc
        volumes.append(vol)

    # 第三步：校验 index 顺次 1..N + chapter_start 顺次拼接 + range 合法
    next_expected_start = 1
    for i, vol in enumerate(volumes):
        expected_index = i + 1
        if vol.index != expected_index:
            raise ValueError(
                f"分卷 index 必须 1-based 顺次，实际第 {i+1} 项 index={vol.index}，期望 {expected_index}"
            )
        if not isinstance(vol.chapter_start, int) or not isinstance(vol.target_min, int) or not isinstance(vol.target_max, int):
            raise ValueError(
                f"分卷第 {expected_index} 卷 chapter_start/target_min/target_max 必须都是 int"
            )
        if vol.chapter_start != next_expected_start:
            raise ValueError(
                f"分卷第 {expected_index} 卷 chapter_start={vol.chapter_start} 与期望 {next_expected_start} 不符 "
                f"(拼接规则: chapter_start[i+1] = chapter_start[i] + target_max[i])"
            )
        if vol.target_min <= 0 or vol.target_max <= 0:
            raise ValueError(
                f"分卷第 {expected_index} 卷 target_min/target_max 必须 > 0，实际 "
                f"target_min={vol.target_min}, target_max={vol.target_max}"
            )
        if vol.target_min > vol.target_max:
            raise ValueError(
                f"分卷第 {expected_index} 卷 target_min={vol.target_min} > target_max={vol.target_max}"
            )
        next_expected_start = vol.chapter_start + vol.target_max

    # 第四步：第一卷 status=in_progress，其余保持 planning（Volume 默认 status="planning"）
    volumes[0].status = "in_progress"

    return {
        "volumes": volumes,
        **reset_review_fields(),
    }
