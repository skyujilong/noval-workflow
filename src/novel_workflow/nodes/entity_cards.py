"""章前「登场实体卡（EntityCard）」步骤的 prepare/save 闭包。

entity_cards 是 scene_beats 之后、prepare_chapter 之前的可跳步骤：读已定稿 beats + 本章弧线
大纲 + 已有实体清单，识别本章登场实体，只为**新**实体建结构化卡，写回父图卡库 + 本章登场名单。

数据落地：LLM 输出 {"cast": [...], "new_cards": [EntityCard...]} → repair_and_parse(kind=dict)
解析 → 逐条 EntityCard(**c) → name+aliases 归一化去重 merge 进 entity_cards。

去重两层保证（防重复建卡）见 _merge_cards：即使 LLM 把已有实体也吐进 new_cards，代码层按
name+aliases 归一化命中已有卡即丢弃（canon 锁定），卡库永不出现同一实体两张卡。
"""

from __future__ import annotations

import dataclasses
import logging

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import (
    ENTITY_TYPES,
    UPDATABLE_FIELDS,
    entity_cards_prompt,
    entity_discover_prompt,
    normalize_entity_name,
)
from noval_workflow.state import EntityCard

_logger = logging.getLogger(__name__)


def _prepare_entity_cards(state) -> dict:
    """组装本章登场实体卡的生成任务。

    system_context 用完整基础设定（含世界观/力量体系/人物档案）——判定实体是否已有、能力是否
    落体系都依赖它；task_prompt 用 entity_cards 组装函数（读 beats/大纲/已有卡库）。
    """
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": entity_cards_prompt(state),
        "review_type": "entity_cards",
    }


def _save_entity_cards(state) -> dict:
    """解析并落库本章登场实体卡：JSON → 逐条 EntityCard → 归一化去重 merge → 写回三字段。

    - JSON 解析失败 / 字段缺失 / 类型错 / type 非法 时抛 ValueError（fail-loud，不静默把
      脏数据塞进卡库）；上游审核循环对这种失败友好。
    - 章号锚定：cast_chapter_index = 本章号（total_chapters_written + 1），供 prepare_chapter
      严格核对，避免跳 gate 时误用上一章残留名单。
    """
    if not state.current_draft:
        _logger.warning("entity_cards current_draft 为空，未写入 entity_cards")
        return {}

    try:
        parsed = repair_and_parse(state.current_draft, kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"登场实体卡 JSON 解析失败: {exc}") from exc

    cast = parsed.get("cast", []) or []
    raw_new = parsed.get("new_cards", []) or []
    if not isinstance(cast, list):
        raise ValueError(f"登场实体卡 cast 必须是数组，实际类型={type(cast).__name__}")
    if not isinstance(raw_new, list):
        raise ValueError(f"登场实体卡 new_cards 必须是数组，实际类型={type(raw_new).__name__}")

    new_cards: list[EntityCard] = []
    for idx, raw in enumerate(raw_new):
        if not isinstance(raw, dict):
            raise ValueError(f"new_cards 第 {idx} 条不是对象(dict)，实际类型={type(raw).__name__}")
        try:
            card = EntityCard(**raw)
        except TypeError as exc:
            raise ValueError(f"new_cards 第 {idx} 条字段不符: {exc}; 原始={raw!r}") from exc
        if card.type not in ENTITY_TYPES:
            raise ValueError(f"new_cards 第 {idx} 条 type={card.type!r} 非法，须为 {ENTITY_TYPES} 之一")
        new_cards.append(card)

    existing = [_coerce_card(c) for c in (state.entity_cards or [])]
    merged = _merge_cards(existing, new_cards)

    chapter_num = state.total_chapters_written + 1
    cast_names = [str(n) for n in cast]
    _logger.info(
        "entity_cards 落地：第 %d 章登场 %d 实体，新增 %d 张卡（卡库共 %d）",
        chapter_num, len(cast_names), len(merged) - len(existing), len(merged),
    )
    return {
        "entity_cards": merged,
        "current_chapter_cast": cast_names,
        "cast_chapter_index": chapter_num,
    }


# ── 去重 merge（防重复建卡的代码层兜底）──────────────────────────────────────

def _merge_cards(existing: list[EntityCard], new: list[EntityCard]) -> list[EntityCard]:
    """把新卡按 name+aliases 归一化去重后并入已有卡库。

    代码层兜底（不依赖 LLM 听话）：新卡的 name/aliases 归一化后，只要命中任一已有卡的
    name/aliases，即视为「同一实体」→ 丢弃这张新卡（canon 锁定，不覆盖不新增）；未命中才 append。
    → 卡库永不出现同一实体两张卡。已有卡的动态字段更新交由章末 entity_discover_step。
    """
    seen: set[str] = set()
    for card in existing:
        seen.add(normalize_entity_name(card.name))
        seen.update(normalize_entity_name(a) for a in card.aliases)

    merged = list(existing)
    for card in new:
        keys = {normalize_entity_name(card.name)} | {normalize_entity_name(a) for a in card.aliases}
        keys.discard("")  # 空名不参与匹配，避免把两个空名实体误判为同一个
        if keys & seen:
            _logger.info("entity_cards: 实体 %r 已在卡库（名/别名命中），丢弃重复卡", card.name)
            continue
        merged.append(card)
        seen |= keys
    return merged


def _coerce_card(obj) -> EntityCard:
    """把卡库里的条目归一成 EntityCard——兼容 checkpoint 反序列化后可能是 dict 的情况。

    dict 里的未知键丢弃（只取 EntityCard 已定义字段），避免老 schema 残留键炸构造。
    """
    if isinstance(obj, EntityCard):
        return obj
    if isinstance(obj, dict):
        valid = {f.name for f in dataclasses.fields(EntityCard)}
        return EntityCard(**{k: v for k, v in obj.items() if k in valid})
    raise ValueError(f"卡库条目类型非法：{type(obj).__name__}")


# ── 章末「实体发现 + 动态更新」闭包（读已写正文，补新卡 + 更新已有卡动态字段）──────

def _prepare_entity_discover(state) -> dict:
    """组装章末实体发现任务：读本章正文（build_chapter_context）+ 已有卡库 → 补卡 + 动态更新。

    本章正文从 chapter_context 读——章末 current_draft 已被前序 discover 步骤覆盖，不可靠。
    """
    return {
        "system_context": build_foundation_context(state, exclude_snapshots=True, include_identity=False),
        "task_prompt": entity_discover_prompt(state, build_chapter_context(state)),
        "review_type": "entity_discover",
    }


def _save_entity_discover(state) -> dict:
    """解析章末发现结果：new_cards 去重 merge + updates 对已有卡应用动态字段变更 → 写回卡库。

    - new_cards：造 EntityCard，走 _merge_cards 去重（命中已有丢弃）。
    - updates：按 name 定位已有卡，只 apply UPDATABLE_FIELDS（status/owner/motivation），
      核心设定 canon 锁定不动（代码层兜底，不依赖 LLM 听话）。
    - 空发现（{new_cards:[], updates:[]}）→ 卡库原样不动，返回空 dict（不触发 last-value 覆盖）。
    """
    if not state.current_draft:
        _logger.warning("entity_discover current_draft 为空，卡库未改动")
        return {}

    try:
        parsed = repair_and_parse(state.current_draft, kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"章末实体发现 JSON 解析失败: {exc}") from exc

    raw_new = parsed.get("new_cards", []) or []
    updates = parsed.get("updates", []) or []
    if not isinstance(raw_new, list) or not isinstance(updates, list):
        raise ValueError("章末实体发现 new_cards / updates 必须都是数组")

    new_cards: list[EntityCard] = []
    for idx, raw in enumerate(raw_new):
        if not isinstance(raw, dict):
            raise ValueError(f"new_cards 第 {idx} 条不是对象(dict)")
        try:
            card = EntityCard(**raw)
        except TypeError as exc:
            raise ValueError(f"new_cards 第 {idx} 条字段不符: {exc}; 原始={raw!r}") from exc
        if card.type not in ENTITY_TYPES:
            raise ValueError(f"new_cards 第 {idx} 条 type={card.type!r} 非法")
        new_cards.append(card)

    cards = [_coerce_card(c) for c in (state.entity_cards or [])]
    cards = _merge_cards(cards, new_cards)          # 先补新卡
    cards, applied = _apply_updates(cards, updates)  # 再对已有卡应用动态更新

    if not new_cards and applied == 0:
        # 纯过场章：无新实体、无有效更新，卡库不动
        return {}

    _logger.info(
        "entity_discover 落地：第 %d 章新增 %d 卡、更新 %d 卡（卡库共 %d）",
        state.total_chapters_written, len(new_cards), applied, len(cards),
    )
    return {"entity_cards": cards}


def _apply_updates(cards: list[EntityCard], updates: list) -> tuple[list[EntityCard], int]:
    """对已有卡应用动态字段变更——只改 UPDATABLE_FIELDS，核心设定不动（代码层兜底）。

    返回 (更新后卡库, 实际生效的更新条数)。update 找不到对应卡时 warn 跳过（不新建，
    新建是 new_cards 的活）。返回值仍是原 EntityCard 实例的原地修改结果。
    """
    # 归一化名 → 卡 索引（name + aliases 都建索引，支持用别名定位）
    index: dict[str, EntityCard] = {}
    for card in cards:
        index.setdefault(normalize_entity_name(card.name), card)
        for alias in card.aliases:
            index.setdefault(normalize_entity_name(alias), card)

    applied = 0
    for upd in updates:
        if not isinstance(upd, dict) or "name" not in upd:
            _logger.warning("entity_discover update 缺 name 或非 dict，跳过：%r", upd)
            continue
        target = index.get(normalize_entity_name(upd["name"]))
        if target is None:
            _logger.warning("entity_discover update 找不到已有卡 %r，跳过（新增应走 new_cards）", upd["name"])
            continue
        changed = False
        for key in UPDATABLE_FIELDS:
            if key in upd and upd[key] not in (None, "") and getattr(target, key) != upd[key]:
                setattr(target, key, upd[key])
                changed = True
        if changed:
            applied += 1
    return cards, applied
