"""Phase 2 五种 draft schema 的字段/枚举/结构校验单测。

对应 review_type：volume_cast / volumes / chapter_plan / scene_beats / foreshadowing。
关键场景：合规通过、str 字段被出成 dict、枚举越界、结构漂移（草稿卷带 chapters 等）。
与 test_draft_schemas.py 的 Phase 1 用例风格保持一致。
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from noval_workflow.drafts import (
    BeatDraft,
    ChapterPlanItemDraft,
    ForeshadowCollectedEntry,
    ForeshadowEntry,
    ForeshadowingDraft,
    ReturningEntry,
    VolumeActiveDraft,
    VolumeCastDraft,
    VolumePlanningDraft,
    VolumesDraft,
)
from noval_workflow.drafts.schemas import CharacterCardDraft


# ══════════════════════════════════════════════════════════════════════════════
# VolumeCastDraft（卷级花名册） ── dict 顶层
# ══════════════════════════════════════════════════════════════════════════════


def test_volume_cast_valid_passes():
    """合规输入：introducing 分派到 CharacterCardDraft、returning 拿到 ReturningEntry。"""
    d = VolumeCastDraft.model_validate({
        "introducing": [
            {"name": "张三", "type": "人物", "role": "主角", "ability_contract": "凡阶→仙阶"},
        ],
        "returning": [{"name": "李四", "role_in_volume": "本卷向导"}],
        "focus": "本卷主角踏入宗门",
    })
    assert len(d.introducing) == 1
    assert isinstance(d.introducing[0], CharacterCardDraft)
    assert d.introducing[0].ability_contract == "凡阶→仙阶"
    assert d.returning[0].name == "李四"
    assert d.focus == "本卷主角踏入宗门"


def test_volume_cast_introducing_dict_field_fails():
    """完整卡里的 str 字段（ability_contract）被出成 dict → 拒绝，与 Phase 1 一致。"""
    with pytest.raises(ValidationError) as exc_info:
        VolumeCastDraft.model_validate({
            "introducing": [{
                "name": "张三", "type": "人物", "role": "主角",
                "ability_contract": {"initial_anchor": "凡", "growth_ceiling": "仙"},
            }],
        })
    assert "ability_contract" in str(exc_info.value)


def test_volume_cast_empty_fields_ok():
    """全空 introducing/returning 合法（本卷没新登场、无返场）。"""
    d = VolumeCastDraft.model_validate({"focus": "过场卷"})
    assert d.introducing == []
    assert d.returning == []


def test_volume_cast_returning_extra_dropped():
    """returning 里塞多余字段（LLM 常见）→ extra="ignore" 静默丢，不当错误。"""
    r = ReturningEntry.model_validate({"name": "王五", "role_in_volume": "反派",
                                        "aliases": ["王老爷"], "summary": "多余"})
    assert r.name == "王五"
    assert not hasattr(r, "aliases")


# ══════════════════════════════════════════════════════════════════════════════
# VolumesDraft（分卷规划） ── dict 顶层
# ══════════════════════════════════════════════════════════════════════════════


def test_volumes_valid_passes():
    """激活卷 + 2 个草稿卷 + human_confirmed 全通过。"""
    d = VolumesDraft.model_validate({
        "volumes": [
            {"title": "第一卷", "summary": "开端", "setup_for_next": "钩", "chapters": 30},
            {"title": "第二卷", "summary": "中盘", "setup_for_next": "钩2"},
            {"title": "第三卷", "summary": "高潮", "setup_for_next": ""},
        ],
        "human_confirmed": True,
    })
    assert len(d.volumes) == 3
    assert isinstance(d.volumes[0], VolumeActiveDraft)
    assert d.volumes[0].chapters == 30
    assert isinstance(d.volumes[1], VolumePlanningDraft)
    assert d.human_confirmed is True


def test_volumes_active_missing_chapters_fails():
    """激活卷（第 1 项）缺 chapters → 拒绝。"""
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        VolumesDraft.model_validate({
            "volumes": [{"title": "第一卷", "summary": "x"}],
        })
    assert "chapters" in str(exc_info.value)


def test_volumes_planning_with_chapters_fails():
    """草稿卷（第 2+ 项）带 chapters → 拒绝（草稿卷不锁章数是硬契约）。"""
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        VolumesDraft.model_validate({
            "volumes": [
                {"title": "第一卷", "chapters": 30},
                {"title": "第二卷", "chapters": 25},  # 草稿卷不能有
            ],
        })
    exc_str = str(exc_info.value).lower()
    assert "chapters" in exc_str or "extra" in exc_str


def test_volumes_empty_array_fails():
    """volumes: [] → 拒绝（至少需要 1 个激活卷）。"""
    with pytest.raises((ValidationError, ValueError)):
        VolumesDraft.model_validate({"volumes": []})


def test_volumes_title_empty_fails():
    """title 空/纯空白 → 拒绝（与老 _parse_active_volume 对齐）。"""
    with pytest.raises((ValidationError, ValueError)):
        VolumesDraft.model_validate({
            "volumes": [{"title": "  ", "chapters": 20}],
        })


def test_volumes_chapters_bool_fails():
    """chapters=True 是 int 子类，但显式拒绝（LLM 常见错）。"""
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        VolumesDraft.model_validate({
            "volumes": [{"title": "第一卷", "chapters": True}],
        })
    assert "chapters" in str(exc_info.value)


def test_volumes_chapters_zero_fails():
    """chapters <= 0 → 拒绝（Field(gt=0)）。"""
    with pytest.raises((ValidationError, ValueError)):
        VolumesDraft.model_validate({
            "volumes": [{"title": "第一卷", "chapters": 0}],
        })


def test_volumes_summary_dict_fails():
    """summary 被出成 dict → 拒绝（str 字段严格）。"""
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        VolumesDraft.model_validate({
            "volumes": [{
                "title": "第一卷", "chapters": 20,
                "summary": {"scene1": "x", "scene2": "y"},
            }],
        })
    assert "summary" in str(exc_info.value)


# ══════════════════════════════════════════════════════════════════════════════
# ChapterPlanItemDraft（章节规划） ── list 顶层
# ══════════════════════════════════════════════════════════════════════════════


def test_chapter_plan_item_valid_passes():
    """合规单条通过——4 必填字段 + intensity 可空。"""
    it = ChapterPlanItemDraft.model_validate({
        "chapter": 1, "purpose": "开场", "key_turn": "撞见反派",
        "ending_hook": "反派留下信物", "intensity": "小转折",
    })
    assert it.chapter == 1 and it.purpose == "开场"


def test_chapter_plan_batch_list_via_type_adapter():
    """裸 JSON 数组走 TypeAdapter[list[ChapterPlanItemDraft]] 逐条校验。"""
    items = TypeAdapter(list[ChapterPlanItemDraft]).validate_python([
        {"chapter": 1, "purpose": "a", "key_turn": "b", "ending_hook": "c"},
        {"chapter": 2, "purpose": "a2", "key_turn": "b2", "ending_hook": "c2"},
    ])
    assert len(items) == 2 and items[1].chapter == 2


def test_chapter_plan_purpose_dict_fails():
    """purpose 被出成 dict → 拒绝（str 字段严格）。"""
    with pytest.raises(ValidationError) as exc_info:
        ChapterPlanItemDraft.model_validate({
            "chapter": 1,
            "purpose": {"target": "开场", "context": "宗门"},
            "key_turn": "x", "ending_hook": "y",
        })
    assert "purpose" in str(exc_info.value)


def test_chapter_plan_chapter_zero_fails():
    """chapter <= 0 → 拒绝。"""
    with pytest.raises(ValidationError):
        ChapterPlanItemDraft.model_validate({
            "chapter": 0, "purpose": "x", "key_turn": "y", "ending_hook": "z",
        })


def test_chapter_plan_chapter_bool_fails():
    """chapter=True → 拒绝（bool 是 int 子类需显式排除）。"""
    with pytest.raises(ValidationError) as exc_info:
        ChapterPlanItemDraft.model_validate({
            "chapter": True, "purpose": "x", "key_turn": "y", "ending_hook": "z",
        })
    assert "chapter" in str(exc_info.value)


def test_chapter_plan_missing_required_field_fails():
    """缺 key_turn → 拒绝。"""
    with pytest.raises(ValidationError):
        ChapterPlanItemDraft.model_validate({
            "chapter": 1, "purpose": "x", "ending_hook": "y",
        })


# ══════════════════════════════════════════════════════════════════════════════
# BeatDraft（scene_beats 章内节拍表） ── list 顶层
# ══════════════════════════════════════════════════════════════════════════════


def test_beat_draft_valid_passes():
    """合规单条 beat 通过——device_tags 走 Literal 严格枚举。"""
    b = BeatDraft.model_validate({
        "beat_id": 1, "scene": "开场厅堂",
        "goal": "主角亮相", "obstacle": "被围观", "outcome": "拂袖离开",
        "device_tags": ["setup", "hook_opening"],
    })
    assert b.beat_id == 1
    assert b.device_tags == ["setup", "hook_opening"]


def test_beat_draft_device_tag_out_of_enum_fails():
    """device_tags 里塞非法 tag → 拒绝（Literal 严格枚举，LLM 出 'slap_taunt2' 走不通）。"""
    with pytest.raises(ValidationError) as exc_info:
        BeatDraft.model_validate({
            "beat_id": 1, "device_tags": ["slap_taunt2"],
        })
    assert "device_tags" in str(exc_info.value)


def test_beat_draft_device_tag_chinese_fails():
    """LLM 常见错：吐中文 tag → 拒绝。"""
    with pytest.raises(ValidationError):
        BeatDraft.model_validate({
            "beat_id": 1, "device_tags": ["高潮爆点"],
        })


def test_beat_draft_all_device_tags_accepted():
    """所有 12 个合法 tag 都能通过 Literal 校验——防 Phase 2 与 scene_beats.py 漂移。"""
    from noval_workflow.prompts.scene_beats import ALL_DEVICE_TAGS
    all_tags = sorted(ALL_DEVICE_TAGS)
    assert len(all_tags) == 12  # 4 slap + 3 catharsis + 2 hook + 2 foreshadow + 1 buffer
    b = BeatDraft.model_validate({"beat_id": 1, "device_tags": all_tags})
    assert set(b.device_tags) == set(all_tags)


def test_beat_draft_goal_dict_fails():
    """goal 被出成嵌套 dict → 拒绝（这是最容易漂移的字段之一）。"""
    with pytest.raises(ValidationError) as exc_info:
        BeatDraft.model_validate({
            "beat_id": 1,
            "goal": {"subject": "主角", "target": "亮相"},
            "device_tags": ["setup"],
        })
    assert "goal" in str(exc_info.value)


def test_beat_draft_beat_id_bool_fails():
    with pytest.raises(ValidationError):
        BeatDraft.model_validate({"beat_id": True, "device_tags": ["setup"]})


def test_beat_draft_optional_fields_default_empty():
    """最小合规输入——只填 beat_id，其他 str 字段默认空串、device_tags 默认空数组。"""
    b = BeatDraft.model_validate({"beat_id": 1})
    assert b.goal == "" and b.device_tags == []


# ══════════════════════════════════════════════════════════════════════════════
# ForeshadowingDraft（伏笔台账） ── dict 顶层
# ══════════════════════════════════════════════════════════════════════════════


def test_foreshadowing_valid_passes():
    """合规输入：pending + collected 都通过。"""
    d = ForeshadowingDraft.model_validate({
        "pending": [{
            "id": "F01", "name": "半张地图", "planted_batch": 1,
            "current_appearance": "母亲遗物", "core_purpose": "通向禁地",
            "planned_recovery_range": "第二卷", "freedom": "高",
        }],
        "collected": [{
            "id": "F00", "name": "宗门信物", "planted_batch": 1,
            "current_appearance": "首章掉落", "core_purpose": "身份铺垫",
            "planned_recovery_range": "第一卷末", "freedom": "低",
            "recovered_at_chapter": 5,
        }],
    })
    assert len(d.pending) == 1 and d.pending[0].freedom == "高"
    assert d.collected[0].recovered_at_chapter == 5


def test_foreshadowing_freedom_out_of_enum_fails():
    """freedom 非「高/中/低」→ 拒绝（Literal 严格）。"""
    with pytest.raises(ValidationError) as exc_info:
        ForeshadowEntry.model_validate({
            "id": "F01", "name": "x", "planted_batch": 1,
            "current_appearance": "a", "core_purpose": "b",
            "planned_recovery_range": "c", "freedom": "非常高",
        })
    assert "freedom" in str(exc_info.value)


def test_foreshadowing_planted_batch_string_fails():
    """planted_batch="第 1 批" → 拒绝（必须是纯数字，与 prompt 硬约束对齐）。"""
    with pytest.raises(ValidationError) as exc_info:
        ForeshadowEntry.model_validate({
            "id": "F01", "name": "x", "planted_batch": "第 1 批",
            "current_appearance": "a", "core_purpose": "b",
            "planned_recovery_range": "c", "freedom": "高",
        })
    assert "planted_batch" in str(exc_info.value)


def test_foreshadowing_planted_batch_bool_fails():
    with pytest.raises(ValidationError):
        ForeshadowEntry.model_validate({
            "id": "F01", "name": "x", "planted_batch": True,
            "current_appearance": "a", "core_purpose": "b",
            "planned_recovery_range": "c", "freedom": "高",
        })


def test_foreshadowing_current_appearance_dict_fails():
    """current_appearance 被出成嵌套 dict → 拒绝（这是 LLM 最爱拆的字段之一）。"""
    with pytest.raises(ValidationError) as exc_info:
        ForeshadowEntry.model_validate({
            "id": "F01", "name": "x", "planted_batch": 1,
            "current_appearance": {"scene1": "a", "scene2": "b"},
            "core_purpose": "b", "planned_recovery_range": "c", "freedom": "高",
        })
    assert "current_appearance" in str(exc_info.value)


def test_foreshadowing_collected_requires_recovered_at():
    """collected 条目必须有 recovered_at_chapter（比 pending 多一个必填字段）。"""
    with pytest.raises(ValidationError) as exc_info:
        ForeshadowCollectedEntry.model_validate({
            "id": "F01", "name": "x", "planted_batch": 1,
            "current_appearance": "a", "core_purpose": "b",
            "planned_recovery_range": "c", "freedom": "高",
        })
    assert "recovered_at_chapter" in str(exc_info.value)


def test_foreshadowing_empty_lists_ok():
    """新书没伏笔 / 章末刚回收就没悬置——两侧都可空。"""
    d = ForeshadowingDraft.model_validate({"pending": [], "collected": []})
    assert d.pending == [] and d.collected == []


def test_foreshadowing_missing_both_lists_ok():
    """两个字段都缺 → default_factory=list 兜底，不当错误。"""
    d = ForeshadowingDraft.model_validate({})
    assert d.pending == [] and d.collected == []


# ══════════════════════════════════════════════════════════════════════════════
# model_dump 序列化 roundtrip：subgraph.generate 出口把 draft 写回 str
# ══════════════════════════════════════════════════════════════════════════════


def test_beat_draft_model_dump_json_shape():
    """dump 后 device_tags 应该是数组、beat_id 是数字（不被序列化成字符串）。"""
    b = BeatDraft.model_validate({"beat_id": 1, "goal": "开场", "device_tags": ["setup"]})
    dumped = b.model_dump_json()
    assert '"beat_id":1' in dumped
    assert '"device_tags":["setup"]' in dumped
    assert '"goal":"开场"' in dumped


def test_volume_cast_model_dump_preserves_card_subclass_fields():
    """VolumeCastDraft dump 时 introducing 里的子类字段（role/ability_contract）需保留。"""
    d = VolumeCastDraft.model_validate({
        "introducing": [{
            "name": "张三", "type": "人物", "role": "主角",
            "ability_contract": "凡阶→仙阶",
        }],
    })
    dumped = d.model_dump_json(serialize_as_any=True)
    assert '"role":"主角"' in dumped
    assert '"ability_contract":"凡阶→仙阶"' in dumped
