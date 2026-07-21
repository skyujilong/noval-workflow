"""EntityCard 三种 draft schema 的字段校验单测——LLM 出 dict/list 时 pydantic 必须 fail-loud
让 invoke_pydantic 回喂修正，而不是静默收敛脏数据。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from noval_workflow.drafts import (
    CharacterCardsDraft,
    EntityCardsDraft,
    EntityDiscoverDraft,
)
from noval_workflow.state import CharacterRole, EntityType


# ── CharacterCardsDraft：合规通过 ────────────────────────────────────────────

def test_character_cards_draft_valid_passes():
    d = CharacterCardsDraft.model_validate({
        "new_cards": [
            {"name": "张三", "type": "人物", "role": "主角", "ability_contract": "初始锚点：凡阶；成长：仙阶"}
        ]
    })
    assert len(d.new_cards) == 1
    c = d.new_cards[0]
    assert c.name == "张三"
    assert c.type == EntityType.CHARACTER
    assert c.role == CharacterRole.PROTAGONIST
    assert c.ability_contract == "初始锚点：凡阶；成长：仙阶"


# ── CharacterCardsDraft：str 字段被 LLM 出成 dict → ValidationError ─────────

def test_character_cards_draft_dict_field_fails_loud():
    """LLM 把 ability_contract 拆成 {initial_anchor, growth_ceiling, hidden_trump} → 拒绝。"""
    with pytest.raises(ValidationError) as exc_info:
        CharacterCardsDraft.model_validate({
            "new_cards": [{
                "name": "李四", "type": "人物", "role": "主角",
                "ability_contract": {
                    "initial_anchor": "凡阶",
                    "growth_ceiling": "仙阶",
                    "hidden_trump": "血脉觉醒",
                },
            }]
        })
    # 报错消息里应能定位到字段问题——loc 是 ('new_cards',)（外层字段级），
    # msg 或 str(exc) 里含 ability_contract 字段名 + string 类型说明
    exc_str = str(exc_info.value)
    assert "ability_contract" in exc_str
    assert "string" in exc_str.lower() or "字符串" in exc_str


# ── CharacterCardsDraft：str 字段被 LLM 出成空 dict → 也拒绝 ────────────────

def test_character_cards_draft_empty_dict_also_fails():
    """LLM 把"留空"处理成 {} → 应该拒绝，回喂让 LLM 出成空串 ""。"""
    with pytest.raises(ValidationError):
        CharacterCardsDraft.model_validate({
            "new_cards": [{
                "name": "王五", "type": "人物", "role": "主角",
                "hidden_persona": {},
            }]
        })


# ── EntityCardsDraft：cast + new_cards + 判别联合 ─────────────────────────────

def test_entity_cards_draft_dispatches_variants():
    d = EntityCardsDraft.model_validate({
        "cast": ["张三", "灵剑"],
        "new_cards": [
            {"name": "张三", "type": "人物", "role": "主角"},
            {"name": "灵剑", "type": "装备", "effect": "斩妖", "owner": "张三"},
            {"name": "青云宗", "type": "势力", "standing": "北方三大宗之一"},
        ],
    })
    assert d.cast == ["张三", "灵剑"]
    assert len(d.new_cards) == 3
    # 分派到正确子类
    from noval_workflow.drafts.schemas import (
        CharacterCardDraft,
        ItemCardDraft,
        SimpleEntityDraft,
    )
    assert isinstance(d.new_cards[0], CharacterCardDraft)
    assert isinstance(d.new_cards[1], ItemCardDraft)
    assert isinstance(d.new_cards[2], SimpleEntityDraft)
    # 子类字段
    assert d.new_cards[1].effect == "斩妖"
    assert d.new_cards[2].standing == "北方三大宗之一"


def test_entity_cards_draft_cross_type_keys_silently_dropped():
    """物品卡里塞 role（跨类脏键）→ extra="ignore" 静默丢弃，不当作 LLM 错误。"""
    d = EntityCardsDraft.model_validate({
        "cast": [],
        "new_cards": [
            {"name": "灵剑", "type": "装备", "role": "乱填", "effect": "斩妖"}
        ],
    })
    assert not hasattr(d.new_cards[0], "role")
    assert d.new_cards[0].effect == "斩妖"


def test_entity_cards_draft_illegal_type_fails():
    with pytest.raises(ValidationError):
        EntityCardsDraft.model_validate({
            "cast": [],
            "new_cards": [{"name": "x", "type": "角色", "role": "主角"}],  # type 非法
        })


# ── CharacterRole 多重定位收敛 ──────────────────────────────────────────────

def test_character_role_multi_locus_collapses():
    """"主要配角、感情线角色" → 按优先级收敛到 感情线角色（ROMANCE 优先于 MAIN_SUPPORTING）。"""
    d = CharacterCardsDraft.model_validate({
        "new_cards": [{"name": "钱七", "type": "人物", "role": "主要配角、感情线角色"}]
    })
    assert d.new_cards[0].role == CharacterRole.ROMANCE


def test_character_role_missing_fails():
    """人物卡缺 role → 拒绝（保持 parse_card fail-loud 语义）。"""
    with pytest.raises(ValidationError):
        CharacterCardsDraft.model_validate({
            "new_cards": [{"name": "孙八", "type": "人物"}]  # 无 role
        })


# ── EntityDiscoverDraft：new_cards + updates ─────────────────────────────────

def test_entity_discover_draft_valid():
    d = EntityDiscoverDraft.model_validate({
        "new_cards": [{"name": "赵九", "type": "人物", "role": "次要角色"}],
        "updates": [
            {"name": "张三", "current_state": "受伤", "motivation": "复仇"},
            {"name": "灵剑", "owner": "李四", "status": "损坏"},
        ],
    })
    assert len(d.new_cards) == 1
    assert len(d.updates) == 2
    # updates 允许 extra 动态字段
    assert d.updates[0].name == "张三"
    assert d.updates[0].model_extra == {"current_state": "受伤", "motivation": "复仇"}


def test_entity_discover_draft_new_cards_dict_field_fails():
    """entity_discover 的 new_cards 字段值也走同样校验。"""
    with pytest.raises(ValidationError):
        EntityDiscoverDraft.model_validate({
            "new_cards": [{
                "name": "周十", "type": "人物", "role": "主角",
                "arc_trajectory": {"start": "x", "end": "y"},  # LLM 漂移
            }],
            "updates": [],
        })


# ── model_dump_json roundtrip：serialize_as_any 保子类字段 ────────────────────

def test_draft_dumps_with_subclass_fields():
    """dump_json 用 serialize_as_any=True 才能带出 CharacterCardDraft 的 role/ability_contract 等
    子类独有字段，否则只按基类 dump 会丢字段。"""
    d = CharacterCardsDraft.model_validate({
        "new_cards": [{
            "name": "张三", "type": "人物", "role": "主角",
            "ability_contract": "初始锚点：凡阶",
            "appearance": "剑修少年"
        }]
    })
    dumped = d.model_dump_json(serialize_as_any=True)
    assert '"role":"主角"' in dumped
    assert '"ability_contract":"初始锚点：凡阶"' in dumped
    assert '"appearance":"剑修少年"' in dumped
    # type 枚举值 dump 成中文字符串（EntityType 是 str, Enum）
    assert '"type":"人物"' in dumped
