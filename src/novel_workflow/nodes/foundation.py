"""Phase 1: Foundation setup nodes (prepare/save pairs per设定项 + save_config)."""

from __future__ import annotations

import dataclasses
import json

from noval_workflow.context import build_foundation_context, get_output_dir
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.nodes.entity_cards import merge_cards_from_json
from noval_workflow.prompts import get_prompt_pack, initial_status_prompt
from noval_workflow.state import NovelState, reset_review_fields


# ── prepare nodes ─────────────────────────────────────────────────────────────

def prepare_core_theme(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.core_theme_prompt,
        "review_type": "core_theme",
        **reset_review_fields(),
    }


def prepare_world_building(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.world_building_prompt,
        "review_type": "world_building",
        **reset_review_fields(),
    }


def prepare_power_system(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.power_system_prompt,
        "review_type": "power_system",
        **reset_review_fields(),
    }


def prepare_core_conflicts(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.core_conflicts_prompt,
        "review_type": "core_conflicts",
        **reset_review_fields(),
    }


def prepare_overall_outline(state: NovelState) -> dict:
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.overall_outline_prompt(state.total_word_count),
        "review_type": "overall_outline",
        **reset_review_fields(),
    }


def prepare_character_cards(state: NovelState) -> dict:
    """Phase-1 一次直出全套核心人物结构化卡（取代原 bible 散文，省一跑 LLM）。"""
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": pack.character_cards_prompt,
        "review_type": "character_cards",
        **reset_review_fields(),
    }


def prepare_initial_status(state: NovelState) -> dict:
    """从已定稿的人物卡（深层视图）+ 世界观固化「人物初始基线（第0章）」，写入 state.phase_summary。

    复用 review_type="phase_summary" —— 本质是数据维护员式的结构化萃取，需继承 snapshot
    的身份/关思考/审核 prompt/中断表单。故上下文参数对标 chapter_edit_subgraph._prepare_phase
    （exclude_snapshots=True 保持干净、include_identity=False 让 generate 拼数据维护员身份）；
    deep_character_view=True 注入人物卡的底牌契约/全书成长天花板，供固化战力基线校验。
    但作为顶层 foundation 节点，须 reset_review_fields() 清掉上一步（character_cards）的
    审核桥接字段。产出经审核后写入同一个 phase_summary 字段，Phase 2.5 首批据此 carry-over。
    """
    return {
        "system_context": build_foundation_context(
            state, exclude_snapshots=True, include_identity=False, deep_character_view=True
        ),
        "task_prompt": initial_status_prompt(),
        "review_type": "phase_summary",
        **reset_review_fields(),
    }


# ── save nodes ────────────────────────────────────────────────────────────────

def save_core_theme(state: NovelState) -> dict:
    return {"core_theme": state.current_draft}


def save_world_building(state: NovelState) -> dict:
    return {"world_building": state.current_draft}


def save_power_system(state: NovelState) -> dict:
    return {"power_system": state.current_draft}


def route_after_world_building(state: NovelState) -> str:
    """世界观定稿后：作品含力量体系（state.has_power_system=True）走 prepare_power_system，
    否则整步跳过、直连核心冲突。

    state.has_power_system 由 collect_user_inputs（直接填表路径按题材默认写入）或
    brainstorm_extract_review（脑爆路径由用户在抽屉里确认）负责填充。这里不查 flavor——
    作品级决策统一从 state 读，避免"题材开关 vs 作品级用户选择"的双源冲突。
    """
    return "prepare_power_system" if state.has_power_system else "prepare_core_conflicts"


def save_core_conflicts(state: NovelState) -> dict:
    return {"core_conflicts": state.current_draft}


def save_overall_outline(state: NovelState) -> dict:
    return {"overall_outline": state.current_draft}


def save_character_cards(state: NovelState) -> dict:
    """Phase-1 结构化卡司 JSON → 解析落 entity_cards（与章前建卡同一套 parse/去重/owner 解析）。

    LLM 输出 {"new_cards": [...]}；解析失败 fail-loud 触发审核循环重生成（一次出 6-10 张富卡
    的 JSON 比散文更易截断，故走 repair_and_parse 容围栏/尾逗号/截断，仍失败即报错）。
    """
    if not state.current_draft:
        raise ValueError("character_cards current_draft 为空，Phase-1 卡司未生成")
    try:
        parsed = repair_and_parse(state.current_draft, kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"Phase-1 卡司 JSON 解析失败: {exc}") from exc
    raw_new = parsed.get("new_cards", []) or []
    if not isinstance(raw_new, list):
        raise ValueError(f"Phase-1 卡司 new_cards 必须是数组，实际类型={type(raw_new).__name__}")
    merged = merge_cards_from_json(raw_new, state.entity_cards)
    return {"entity_cards": merged}


def save_initial_status(state: NovelState) -> dict:
    """把审核通过的人物初始基线写回 phase_summary（与动态台账同一字段，覆盖语义）。"""
    return {"phase_summary": state.current_draft}


def save_config(state: NovelState) -> dict:
    """Persist foundation-phase state to <output_dir>/config.json before chapter writing."""
    output_dir = get_output_dir(state.novel_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "novel_name": state.novel_name,
        "genre": state.genre,
        "writing_style": state.writing_style,
        "target_audience": state.target_audience,
        "core_tone": state.core_tone,
        "chapter_word_count": state.chapter_word_count,
        "total_word_count": state.total_word_count,
        "core_theme": state.core_theme,
        "world_building": state.world_building,
        "power_system": state.power_system,
        "core_conflicts": state.core_conflicts,
        "overall_outline": state.overall_outline,
        # 人物档案真源已并入 entity_cards（CharacterCard），持久化结构化卡库（枚举经 str 序列化）
        "entity_cards": [
            dataclasses.asdict(c) if dataclasses.is_dataclass(c) else c
            for c in (state.entity_cards or [])
        ],
        "phase_summary": state.phase_summary,
    }

    config_path = output_dir / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {}
