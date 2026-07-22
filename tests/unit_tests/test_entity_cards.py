"""登场实体卡（EntityCard 判别联合）的去重 merge、save_fn 落地、触发式注入渲染的单元测试。"""

from __future__ import annotations

import json

import pytest

from noval_workflow.nodes.entity_cards import (
    _apply_updates,
    _coerce_card,
    _merge_cards,
    _resolve_owners,
    _save_entity_cards,
    _save_entity_discover,
)
from noval_workflow.prompts import (
    format_cards_for_chapter_prompt,
    format_character_profiles_from_cards,
    format_equipment_for_context,
    normalize_entity_name,
)
from noval_workflow.state import (
    CharacterCard,
    CharacterRole,
    ItemCard,
    NovelState,
    SimpleEntityCard,
    coerce_character_role,
    parse_card,
)


def _card(name: str, type_: str = "人物", aliases: list[str] | None = None, **kw):
    """构造具体卡变体——走 parse_card 判别工厂；人物默认补 role（parse_card 必填）。"""
    raw = {"name": name, "type": type_, "aliases": aliases or [], **kw}
    if type_ == "人物":
        raw.setdefault("role", "次要角色")
    return parse_card(raw)


# ── normalize_entity_name ─────────────────────────────────────────────────────

def test_normalize_strips_spaces_and_lowercases():
    assert normalize_entity_name(" 张三 ") == "张三"
    assert normalize_entity_name("Ye　Fan") == "yefan"  # 全角空格 + 大小写
    assert normalize_entity_name("") == ""
    assert normalize_entity_name(None) == ""  # type: ignore[arg-type]


# ── parse_card：判别工厂分派 + fail-loud ──────────────────────────────────────

def test_parse_card_dispatches_variants():
    assert isinstance(_card("张三", role="主角"), CharacterCard)
    assert isinstance(_card("灵剑", type_="装备"), ItemCard)
    assert isinstance(_card("青云宗", type_="势力"), SimpleEntityCard)  # 势力→SimpleEntityCard


def test_parse_card_character_requires_role():
    with pytest.raises(ValueError):
        parse_card({"name": "张三", "type": "人物"})  # 缺 role


def test_parse_card_rejects_illegal_type():
    with pytest.raises(ValueError):
        parse_card({"name": "x", "type": "角色"})


def test_parse_card_filters_cross_type_keys():
    """物品卡里混入人物字段（role）→ 被过滤，不炸构造。"""
    item = parse_card({"name": "灵剑", "type": "装备", "role": "乱填", "owner": "张三"})
    assert isinstance(item, ItemCard) and not hasattr(item, "role")


# ── coerce_character_role：多重定位收敛（复现线上崩溃「主要配角、感情线角色」）────────

def test_coerce_role_exact_and_whitespace():
    assert coerce_character_role("主角") is CharacterRole.PROTAGONIST
    assert coerce_character_role(" 主角 ") is CharacterRole.PROTAGONIST  # 前后空格
    assert coerce_character_role(CharacterRole.MINOR) is CharacterRole.MINOR  # 已是成员直通


def test_coerce_role_multi_collapses_to_primary():
    """LLM 吐「主要配角、感情线角色」（原崩溃输入）→ 收敛为感情线角色（比泛化的主要配角更可注入）。"""
    assert coerce_character_role("主要配角、感情线角色") is CharacterRole.ROMANCE


def test_coerce_role_multi_never_drops_villain_layer():
    """铁律：反派分层不被正面定位挤掉——「感情线角色、功能性反派」必须留住反派信息。"""
    assert coerce_character_role("感情线角色、功能性反派") is CharacterRole.FUNCTIONAL_VILLAIN
    assert coerce_character_role("主要配角/根源反派") is CharacterRole.ROOT_VILLAIN  # 任意分隔符


def test_coerce_role_wholly_invalid_fails_loud():
    """一个合法定位都扫不到（自造词）→ fail-loud，不静默兜底。"""
    with pytest.raises(ValueError):
        coerce_character_role("反派头目")


def test_parse_card_coerces_multi_role_no_crash():
    """端到端：parse_card 吃下多重定位串不再抛，收敛为单枚举写进卡。"""
    card = _card("沈清颜", role="主要配角、感情线角色")
    assert isinstance(card, CharacterCard)
    assert card.role is CharacterRole.ROMANCE


def test_parse_card_rejects_wholly_invalid_role():
    """自造 role（无任何合法定位）仍 fail-loud——pydantic ValidationError 转 ValueError。

    pydantic 报错是字段级（loc=人物.role），不含人物 name；只断言错误信息含 role 值。
    """
    with pytest.raises(ValueError, match="大反派头目"):
        parse_card({"name": "沈清颜", "type": "人物", "role": "大反派头目"})


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

def test_coerce_card_from_dict_dispatches_and_drops_unknown_keys():
    card = _coerce_card({"name": "张三", "type": "人物", "role": "主角", "_legacy": "x"})
    assert isinstance(card, CharacterCard)
    assert card.name == "张三" and not hasattr(card, "_legacy")


def test_coerce_card_passthrough_instance():
    c = _card("张三")
    assert _coerce_card(c) is c


# ── _save_entity_cards：JSON 落地 ─────────────────────────────────────────────

def _state(draft: str, existing: list | None = None, done: int = 4) -> NovelState:
    return NovelState(
        current_draft=draft,
        entity_cards=existing or [],
        total_chapters_written=done,
    )


def test_save_parses_and_merges():
    draft = json.dumps({
        "cast": ["张三", "灵剑"],
        "new_cards": [
            {"name": "张三", "type": "人物", "role": "主角", "aliases": ["三哥"], "appearance": "刀疤脸"},
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
            {"name": "张三", "type": "人物", "role": "主角"},   # 已有 → 丢弃
            {"name": "李四", "type": "人物", "role": "次要角色"},  # 新 → 保留
        ],
    })
    out = _save_entity_cards(_state(draft, existing=[_card("张三")]))
    assert [c.name for c in out["entity_cards"]] == ["张三", "李四"]
    assert out["current_chapter_cast"] == ["张三", "李四"]


def test_save_empty_draft_returns_empty():
    assert _save_entity_cards(_state("")) == {}


def test_save_missing_required_field_raises():
    """缺 name（EntityCard 必填）→ ValueError（fail-loud，触发审核重生成）。"""
    draft = json.dumps({"cast": [], "new_cards": [{"type": "物品"}]})
    with pytest.raises(ValueError):
        _save_entity_cards(_state(draft))


def test_save_character_missing_role_raises():
    """人物卡缺 role → ValueError（人物必填 role）。"""
    draft = json.dumps({"cast": [], "new_cards": [{"name": "张三", "type": "人物"}]})
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
    assert "EntityType" not in rendered and "CharacterRole" not in rendered  # 枚举取 value 不漏名


def test_format_matches_by_alias_and_normalization():
    cards = [_card("叶凡", aliases=["叶老魔"])]
    # cast 用别名 + 带空格，仍应命中
    assert "叶凡" in format_cards_for_chapter_prompt(cards, [" 叶老魔 "])


def test_format_empty_cast_returns_empty():
    assert format_cards_for_chapter_prompt([_card("张三")], []) == ""


# ── format_character_profiles_from_cards：人物档案渲染（操作 vs 深层视图）───────

def test_character_profiles_operational_vs_deep_view():
    cards = [_card(
        "林轩", role="主角", appearance="剑眉", current_state="闭关",
        hidden_persona="魔胎", arc_trajectory="四卷弧光", ability_contract="底牌契约",
    )]
    op = format_character_profiles_from_cards(cards)
    deep = format_character_profiles_from_cards(cards, deep=True)
    assert "林轩〔主角〕" in op and "闭关" in op
    assert "隐藏人设" not in op            # 操作视图不含深层字段
    assert "隐藏人设" in deep and "魔胎" in deep and "四卷弧光" in deep


def test_character_profiles_ignores_non_characters():
    assert format_character_profiles_from_cards([_card("灵剑", type_="装备")]) == ""


# ── format_equipment_for_context：装备/物品按 owner 归组渲染 ───────────────────

def test_equipment_groups_by_owner_and_excludes_retired():
    cards = [
        _card("张三"),  # 人物，不渲染
        _card("灵剑", type_="装备", owner="张三", status="完好", rank="上品", effect="斩妖"),
        _card("破船", type_="物品", status="遗失"),  # 已退场，不渲染
    ]
    out = format_equipment_for_context(cards)
    assert "张三 携带" in out          # 按归属人归组（owner 反向视角）
    assert "灵剑（完好·上品）" in out
    assert "破船" not in out           # 已退场排除


def test_equipment_unowned_bucket():
    out = format_equipment_for_context([_card("地图残卷", type_="物品", status="完好")])
    assert "无归属" in out and "地图残卷" in out


def test_equipment_empty_returns_empty():
    assert format_equipment_for_context([]) == ""
    assert format_equipment_for_context([_card("张三")]) == ""  # 无装备/物品


# ── _apply_updates：章末动态更新按 type 白名单，canon 锁定 ─────────────────────

def test_apply_updates_item_dynamic_only_canon_locked():
    sword = _card("灵剑", type_="装备", owner="张三", status="完好", rank="上品")
    cards, applied = _apply_updates([sword], [
        {"name": "灵剑", "owner": "李四", "status": "损坏", "rank": "篡改品阶"},
    ])
    assert applied == 1
    assert sword.owner == "李四"      # 动态字段已改
    assert sword.status == "损坏"
    assert sword.rank == "上品"        # canon（rank 不在装备白名单）被拦下，未改


def test_apply_updates_character_whitelist():
    """人物 update 只能改 current_state/motivation/relations；role/appearance 是 canon。"""
    hero = _card("林轩", role="主角", appearance="剑眉", motivation="旧", current_state="炼气")
    _, applied = _apply_updates([hero], [
        {"name": "林轩", "current_state": "筑基", "role": "反派", "appearance": "篡改"},
    ])
    assert applied == 1
    assert hero.current_state == "筑基"   # 动态字段已改
    assert hero.role == "主角"            # canon 锁定
    assert hero.appearance == "剑眉"      # canon 锁定


def test_apply_updates_locates_by_alias():
    hero = _card("叶凡", aliases=["叶老魔"], motivation="旧")
    _, applied = _apply_updates([hero], [{"name": "叶老魔", "motivation": "复仇"}])
    assert applied == 1
    assert hero.motivation == "复仇"


def test_apply_updates_skips_unknown_target():
    hero = _card("张三")
    cards, applied = _apply_updates([hero], [{"name": "查无此人", "status": "x"}])
    assert applied == 0  # 找不到已有卡 → 跳过，不新建（新建走 new_cards）


# ── _resolve_owners：owner 解析绑定 ───────────────────────────────────────────

def test_resolve_owners_binds_to_canonical_name():
    hero = _card("叶凡", aliases=["叶老魔"])
    sword = _card("灵剑", type_="装备", owner="叶老魔")  # 用别名填 owner
    _resolve_owners([hero, sword])
    assert sword.owner == "叶凡"  # 解析绑定到规范 name（别名不漂移）


def test_resolve_owners_keeps_unresolved_owner():
    sword = _card("灵剑", type_="装备", owner="查无此人")
    _resolve_owners([sword])
    assert sword.owner == "查无此人"  # 未命中保留原值（fail-loud 只告警不删数据）


# ── _save_entity_discover：章末发现 + 更新落地 ────────────────────────────────

def test_save_discover_adds_new_and_updates_existing():
    draft = json.dumps({
        "new_cards": [{"name": "神秘人", "type": "人物", "role": "功能性反派"}],
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
