"""章前「登场实体卡（EntityCard）」步骤的 prepare/save 闭包。

entity_cards 是 scene_beats 之后、prepare_chapter 之前的可跳步骤：读已定稿 beats + 本章弧线
大纲 + 已有实体清单，识别本章登场实体，只为**新**实体建结构化卡，写回父图卡库 + 本章登场名单。

数据落地：LLM 输出 {"cast": [...], "new_cards": [EntityCard...]} → repair_and_parse(kind=dict)
解析 → 逐条 EntityCard(**c) → name+aliases 归一化去重 merge 进 entity_cards。

去重两层保证（防重复建卡）见 _merge_cards：即使 LLM 把已有实体也吐进 new_cards，代码层按
name+aliases 归一化命中已有卡即丢弃（canon 锁定），卡库永不出现同一实体两张卡。
"""

from __future__ import annotations

import logging

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.prompts import (
    UPDATABLE_FIELDS,
    entity_cards_prompt,
    entity_discover_prompt,
    normalize_entity_name,
    resolve_owner,
)
from noval_workflow.prompts.render import SystemRole, build_prepare_fields
from noval_workflow.state import EntityCard, ItemCard, parse_card

_logger = logging.getLogger(__name__)


def _prepare_entity_cards(state) -> dict:
    """组装本章登场实体卡的生成任务。

    context_prompt 用完整基础设定（含世界观/力量体系/人物档案）——判定实体是否已有、能力是否
    落体系都依赖它；task_prompt 用 entity_cards 组装函数（读 beats/大纲/已有卡库）。
    """
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        **build_prepare_fields(
            role=SystemRole.GENRE_AUTHOR,
            genre_identity=pack.flavor.system_identity,
            task_contract="识别本章登场实体并为新实体建结构化卡",
            context=build_foundation_context(state, include_identity=False),
            task=entity_cards_prompt(state),
        ),
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
        raise ValueError(
            f"登场实体卡 new_cards 必须是数组，实际类型={type(raw_new).__name__}"
        )

    new_cards: list[EntityCard] = []
    for idx, raw in enumerate(raw_new):
        try:
            # _coerce_card 判别工厂：先把 LLM 漂移出的 dict/list 字段收敛回字符串（例如
            # ability_contract 拆成三段 JSON 的常见漂移），再走 parse_card 分派变体+校验。
            # 章前/章末/Phase-1/volume_cast 四条建卡路径统一入口，避免脏数据串到 checkpoint。
            new_cards.append(_coerce_card(raw))
        except ValueError as exc:
            raise ValueError(f"new_cards 第 {idx} 条: {exc}") from exc

    existing = [_coerce_card(c) for c in (state.entity_cards or [])]
    merged = _merge_cards(existing, new_cards)
    _resolve_owners(merged)  # 物品 owner 解析绑定到规范实体（引用完整性）

    chapter_num = state.total_chapters_written + 1
    cast_names = [str(n) for n in cast]
    _logger.info(
        "entity_cards 落地：第 %d 章登场 %d 实体，新增 %d 张卡（卡库共 %d）",
        chapter_num,
        len(cast_names),
        len(merged) - len(existing),
        len(merged),
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
        keys = {normalize_entity_name(card.name)} | {
            normalize_entity_name(a) for a in card.aliases
        }
        keys.discard("")  # 空名不参与匹配，避免把两个空名实体误判为同一个
        if keys & seen:
            _logger.info(
                "entity_cards: 实体 %r 已在卡库（名/别名命中），丢弃重复卡", card.name
            )
            continue
        merged.append(card)
        seen |= keys
    return merged


def _coerce_card(obj) -> EntityCard:
    """把卡库里的条目归一成具体 EntityCard 变体——checkpoint 反序列化后条目是 dict。

    dict 一律走 parse_card：按 type 重新分派到正确变体（CharacterCard/ItemCard/SimpleEntityCard），
    跨类脏键自动过滤，字符串 type/role 转回枚举。已是实例（含子类）直接返回。

    字段值类型校验（str 字段被 LLM 漂移成 dict/list 等）已上移到 subgraph.generate 出口的
    pydantic 层——draft 写入 state 前校验+回喂重试，落库路径不再做字段值收敛。
    老 checkpoint 里的脏数据由前端 safeStr helper 兜底渲染，不再在这里静默收敛。
    """
    if isinstance(obj, EntityCard):
        return obj
    if isinstance(obj, dict):
        return parse_card(obj)
    raise ValueError(f"卡库条目类型非法：{type(obj).__name__}")


# ── 章末「实体发现 + 动态更新」闭包（读已写正文，补新卡 + 更新已有卡动态字段）──────


def _prepare_entity_discover(state) -> dict:
    """组装章末实体发现任务：读本章正文（build_chapter_context）+ 已有卡库 → 补卡 + 动态更新。

    本章正文从 chapter_context 读——章末 current_draft 已被前序 discover 步骤覆盖，不可靠。
    """
    pack = get_prompt_pack(state.genre, state.novel_name)
    chapter_ctx = build_chapter_context(state)
    context = build_foundation_context(
        state, include_identity=False, exclude_snapshots=True
    )
    if chapter_ctx:
        context = f"{context}\n\n{chapter_ctx}" if context else chapter_ctx
    return {
        **build_prepare_fields(
            role=SystemRole.GENRE_AUTHOR,
            genre_identity=pack.flavor.system_identity,
            task_contract="章末发现新实体并更新已有卡动态字段",
            context=context,
            task=entity_discover_prompt(state, chapter_ctx),
        ),
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
        try:
            # 走 _coerce_card 统一入口：先字段值收敛(dict/list→str) 再 parse_card 分派变体
            new_cards.append(_coerce_card(raw))
        except ValueError as exc:
            raise ValueError(f"new_cards 第 {idx} 条: {exc}") from exc

    cards = [_coerce_card(c) for c in (state.entity_cards or [])]
    cards = _merge_cards(cards, new_cards)  # 先补新卡
    cards, applied = _apply_updates(cards, updates)  # 再对已有卡应用动态更新
    _resolve_owners(cards)  # owner 解析绑定（新卡/易主后统一校验）

    if not new_cards and applied == 0:
        # 纯过场章：无新实体、无有效更新，卡库不动
        return {}

    _logger.info(
        "entity_discover 落地：第 %d 章新增 %d 卡、更新 %d 卡（卡库共 %d）",
        state.total_chapters_written,
        len(new_cards),
        applied,
        len(cards),
    )
    return {"entity_cards": cards}


def _apply_updates(
    cards: list[EntityCard], updates: list
) -> tuple[list[EntityCard], int]:
    """对已有卡应用动态字段变更——按卡 type 取 UPDATABLE_FIELDS 白名单，canon 不动（代码层兜底）。

    返回 (更新后卡库, 实际生效的更新条数)。update 找不到对应卡时 warn 跳过（不新建，
    新建是 new_cards 的活）；越权改 canon 的键因不在白名单被静默忽略（LLM 已被 prompt 约束，
    这里是代码层兜底）。返回值仍是原 EntityCard 实例的原地修改结果。
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
            _logger.warning(
                "entity_discover update 找不到已有卡 %r，跳过（新增应走 new_cards）",
                upd["name"],
            )
            continue
        allowed = UPDATABLE_FIELDS.get(
            target.type, ()
        )  # 按 type 取白名单（target.type 是 EntityType 枚举）
        changed = False
        for key in allowed:
            if (
                key in upd
                and upd[key] not in (None, "")
                and getattr(target, key) != upd[key]
            ):
                setattr(target, key, upd[key])
                changed = True
        if changed:
            applied += 1
    return cards, applied


def _resolve_owners(cards: list[EntityCard]) -> None:
    """把所有物品/装备卡的 owner 就地解析绑定到规范实体 name（引用完整性 + 别名不漂移断链）。

    命中 → 存规范名；未命中 → fail-loud 告警但保留原值（owner 可能是尚未建卡的次要角色，
    不删数据、只暴露问题，符合 CLAUDE.md 不静默兜底）。空 owner 不处理。就地改 ItemCard 实例。
    """
    for card in cards:
        if not isinstance(card, ItemCard):
            continue
        raw_owner = (card.owner or "").strip()
        if not raw_owner:
            continue
        resolved = resolve_owner(raw_owner, cards)
        if resolved is None:
            _logger.warning(
                "entity owner %r 在卡库无对应实体（%s 的归属挂空，请核对）",
                raw_owner,
                card.name,
            )
        elif resolved != card.owner:
            card.owner = resolved


def merge_cards_from_json(raw_new: list, existing_cards: list) -> list[EntityCard]:
    """把一批 new_cards（原始 dict 列表）parse + 去重 merge + owner 解析进已有卡库并返回。

    Phase-1 建卡司（foundation.save_character_cards）复用本函数，与章前 _save_entity_cards
    走同一套 _coerce_card / 去重 / owner 解析，保证两条建卡路径行为一致（字段值先收敛回
    字符串再判别分派，避免 LLM 漂移出的 dict 字段串到 checkpoint 和前端）。解析失败 fail-loud。
    """
    new_cards: list[EntityCard] = []
    for idx, raw in enumerate(raw_new):
        try:
            new_cards.append(_coerce_card(raw))
        except ValueError as exc:
            raise ValueError(f"new_cards 第 {idx} 条: {exc}") from exc
    merged = _merge_cards([_coerce_card(c) for c in (existing_cards or [])], new_cards)
    _resolve_owners(merged)
    return merged
