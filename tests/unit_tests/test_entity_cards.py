"""登场实体卡（EntityCard）的去重 merge、save_fn 落地、触发式注入渲染的单元测试。"""

from __future__ import annotations

import json

import pytest

from noval_workflow.nodes.entity_cards import (
    _apply_updates,
    _coerce_card,
    _merge_cards,
    _save_entity_cards,
    _save_entity_discover,
)
from noval_workflow.prompts import (
    format_cards_for_chapter_prompt,
    format_equipment_for_context,
    normalize_entity_name,
)
from noval_workflow.state import EntityCard, NovelState


def _card(name: str, type_: str = "人物", aliases: list[str] | None = None, **kw) -> EntityCard:
    return EntityCard(name=name, type=type_, aliases=aliases or [], **kw)


# ── normalize_entity_name ─────────────────────────────────────────────────────

def test_normalize_strips_spaces_and_lowercases():
    assert normalize_entity_name(" 张三 ") == "张三"
    assert normalize_entity_name("Ye　Fan") == "yefan"  # 全角空格 + 大小写
    assert normalize_entity_name("") == ""
    assert normalize_entity_name(None) == ""  # type: ignore[arg-type]


# ── _merge_cards：去重代码层兜底 ──────────────────────────────────────────────

def test_merge_appends_new_card():
    existing = [_card("张三")]
    merged = _merge_cards(existing, [_card("李四")])
    assert [c.name for c in merged] == ["张三", "李四"]


def test_merge_drops_duplicate_by_name():
    """LLM 误把已有实体也吐进 new_cards，代码层按 name 命中丢弃。"""
    existing = [_card("张三")]
    merged = _merge_cards(existing, [_card("张三", summary="重复卡")])
    assert len(merged) == 1
    assert merged[0].summary == ""  # 已有卡保留原样，重复卡被丢弃（canon 锁定）


def test_merge_drops_duplicate_by_alias():
    """新卡的名字命中已有卡的别名 → 视为同一实体丢弃。"""
    existing = [_card("叶凡", aliases=["叶老魔"])]
    merged = _merge_cards(existing, [_card("叶老魔")])
    assert len(merged) == 1
    assert merged[0].name == "叶凡"


def test_merge_drops_when_new_alias_hits_existing_name():
    """反向：新卡别名命中已有卡的名字也算重复。"""
    existing = [_card("叶老魔")]
    merged = _merge_cards(existing, [_card("叶凡", aliases=["叶老魔"])])
    assert len(merged) == 1


def test_merge_normalizes_before_compare():
    existing = [_card("张三")]
    merged = _merge_cards(existing, [_card(" 张三 ")])  # 带空格
    assert len(merged) == 1


def test_merge_empty_name_does_not_collide():
    """两个空名实体不应被误判为同一个（空名不参与匹配）。"""
    merged = _merge_cards([_card("")], [_card("", type_="物品")])
    assert len(merged) == 2


# ── _coerce_card：兼容 checkpoint 反序列化后的 dict ────────────────────────────

def test_coerce_card_from_dict_drops_unknown_keys():
    card = _coerce_card({"name": "张三", "type": "人物", "_legacy": "x"})
    assert isinstance(card, EntityCard)
    assert card.name == "张三"


def test_coerce_card_passthrough_instance():
    c = _card("张三")
    assert _coerce_card(c) is c


# ── _save_entity_cards：JSON 落地 ─────────────────────────────────────────────

def _state(draft: str, existing: list[EntityCard] | None = None, done: int = 4) -> NovelState:
    return NovelState(
        current_draft=draft,
        entity_cards=existing or [],
        total_chapters_written=done,
    )


def test_save_parses_and_merges():
    draft = json.dumps({
        "cast": ["张三", "灵剑"],
        "new_cards": [
            {"name": "张三", "type": "人物", "aliases": ["三哥"], "appearance": "刀疤脸"},
            {"name": "灵剑", "type": "装备", "owner": "张三", "status": "完好"},
        ],
    })
    out = _save_entity_cards(_state(draft, done=4))
    assert [c.name for c in out["entity_cards"]] == ["张三", "灵剑"]
    assert out["current_chapter_cast"] == ["张三", "灵剑"]
    assert out["cast_chapter_index"] == 5  # done + 1 = 本章号


def test_save_drops_new_card_that_already_exists():
    """已有卡库里有张三，new_cards 又建一张 → 丢弃，cast 仍保留。"""
    draft = json.dumps({
        "cast": ["张三", "李四"],
        "new_cards": [
            {"name": "张三", "type": "人物"},   # 已有 → 丢弃
            {"name": "李四", "type": "人物"},   # 新 → 保留
        ],
    })
    out = _save_entity_cards(_state(draft, existing=[_card("张三")]))
    assert [c.name for c in out["entity_cards"]] == ["张三", "李四"]
    assert out["current_chapter_cast"] == ["张三", "李四"]


def test_save_empty_draft_returns_empty():
    assert _save_entity_cards(_state("")) == {}


def test_save_missing_required_field_raises():
    """缺 name（EntityCard 必填）→ ValueError（fail-loud，触发审核重生成）。"""
    draft = json.dumps({"cast": [], "new_cards": [{"type": "人物"}]})
    with pytest.raises(ValueError):
        _save_entity_cards(_state(draft))


def test_save_illegal_type_raises():
    draft = json.dumps({"cast": [], "new_cards": [{"name": "张三", "type": "角色"}]})
    with pytest.raises(ValueError):
        _save_entity_cards(_state(draft))


def test_save_invalid_json_raises():
    with pytest.raises(ValueError):
        _save_entity_cards(_state("这不是 JSON"))


def test_save_new_cards_not_list_raises():
    draft = json.dumps({"cast": [], "new_cards": {"name": "x"}})
    with pytest.raises(ValueError):
        _save_entity_cards(_state(draft))


# ── format_cards_for_chapter_prompt：触发式注入只渲染登场卡 ────────────────────

def test_format_only_renders_cast_matched_cards():
    cards = [_card("张三"), _card("李四"), _card("灵剑", type_="装备", owner="张三", status="完好")]
    rendered = format_cards_for_chapter_prompt(cards, ["张三", "灵剑"])
    assert "张三" in rendered
    assert "灵剑" in rendered
    assert "李四" not in rendered  # 未登场，不注入


def test_format_matches_by_alias_and_normalization():
    cards = [_card("叶凡", aliases=["叶老魔"])]
    # cast 用别名 + 带空格，仍应命中
    assert "叶凡" in format_cards_for_chapter_prompt(cards, [" 叶老魔 "])


def test_format_empty_cast_returns_empty():
    assert format_cards_for_chapter_prompt([_card("张三")], []) == ""


# ── format_equipment_for_context：装备/物品全局真源渲染 ────────────────────────

def test_equipment_renders_only_items_and_excludes_retired():
    cards = [
        _card("张三"),  # 人物，不渲染
        _card("灵剑", type_="装备", owner="张三", status="完好", effect="斩妖"),
        _card("破船", type_="物品", status="遗失"),  # 已退场，不渲染
    ]
    out = format_equipment_for_context(cards)
    assert "灵剑" in out
    assert "张三" not in out.replace("归属:张三", "")  # 人物本身不作为条目
    assert "破船" not in out


def test_equipment_empty_returns_empty():
    assert format_equipment_for_context([]) == ""
    assert format_equipment_for_context([_card("张三")]) == ""  # 无装备/物品


# ── _apply_updates：章末动态更新只改白名单字段 ─────────────────────────────────

def test_apply_updates_changes_dynamic_fields_only():
    sword = _card("灵剑", type_="装备", owner="张三", status="完好", appearance="原设定")
    cards, applied = _apply_updates([sword], [
        {"name": "灵剑", "owner": "李四", "status": "损坏", "appearance": "篡改核心设定"},
    ])
    assert applied == 1
    assert sword.owner == "李四"      # 动态字段已改
    assert sword.status == "损坏"
    assert sword.appearance == "原设定"  # 核心设定被代码层拦下，未改


def test_apply_updates_locates_by_alias():
    hero = _card("叶凡", aliases=["叶老魔"], motivation="旧")
    _, applied = _apply_updates([hero], [{"name": "叶老魔", "motivation": "复仇"}])
    assert applied == 1
    assert hero.motivation == "复仇"


def test_apply_updates_skips_unknown_target():
    hero = _card("张三")
    cards, applied = _apply_updates([hero], [{"name": "查无此人", "status": "x"}])
    assert applied == 0  # 找不到已有卡 → 跳过，不新建（新建走 new_cards）


# ── _save_entity_discover：章末发现 + 更新落地 ────────────────────────────────

def test_save_discover_adds_new_and_updates_existing():
    draft = json.dumps({
        "new_cards": [{"name": "神秘人", "type": "人物"}],
        "updates": [{"name": "灵剑", "status": "损坏"}],
    })
    st = NovelState(
        current_draft=draft,
        entity_cards=[_card("灵剑", type_="装备", status="完好")],
        total_chapters_written=5,
    )
    out = _save_entity_discover(st)
    names = [c.name for c in out["entity_cards"]]
    assert "神秘人" in names
    sword = next(c for c in out["entity_cards"] if c.name == "灵剑")
    assert sword.status == "损坏"


def test_save_discover_empty_findings_returns_empty():
    """纯过场章：无新实体无更新 → 卡库不动，返回空 dict。"""
    draft = json.dumps({"new_cards": [], "updates": []})
    st = NovelState(current_draft=draft, entity_cards=[_card("张三")], total_chapters_written=5)
    assert _save_entity_discover(st) == {}


def test_save_discover_empty_draft_returns_empty():
    st = NovelState(current_draft="", total_chapters_written=5)
    assert _save_entity_discover(st) == {}
