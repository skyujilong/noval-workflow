"""卷级花名册注入测试：volume_cast_card 渲染 + 注入 chapter_plan / arc_outline / 章前 entity_cards。

锚定校验：花名册须为「当前激活卷」生成（volume_cast_index == 当前卷 index），否则视为陈旧不注入。
向后兼容：volume_cast 空 / 未启用分卷时三处 prompt 均不含【本卷花名册】。
"""

from __future__ import annotations

from noval_workflow.prompts import entity_cards_prompt, get_prompt_pack
from noval_workflow.prompts.base import ChapterPlanGenreSpec, render_chapter_plan_prompt
from noval_workflow.state import NovelState, Volume
from noval_workflow.volume_utils import volume_cast_card

_MARK = "【本卷花名册】"


def _volumes() -> list[Volume]:
    return [
        Volume(index=1, title="卷1", chapter_start=1, planned_end=28,
               summary="卷1主线", setup_for_next="埋钩", status="in_progress"),
        Volume(index=2, title="卷2", chapter_start=0, planned_end=0,
               summary="卷2方向", setup_for_next="", status="planning"),
    ]


def _roster() -> dict:
    return {
        "volume_index": 1,
        "focus": "林尘挑大梁对阵血月教",
        "returning": [{"name": "林尘", "role_in_volume": "本卷成长为核心战力"}],
        "introducing": [{"name": "血月教主", "type": "人物"}, {"name": "焚天印", "type": "物品"}],
    }


def _state_with_roster(**extra) -> NovelState:
    base = dict(
        volumes=_volumes(),
        total_chapters_written=0,
        volume_cast=_roster(),
        volume_cast_index=1,
        total_word_count="200万",
    )
    base.update(extra)
    return NovelState(**base)


# ── volume_cast_card 渲染 ─────────────────────────────────────────────────────


def test_volume_cast_card_renders_dynamic_layer():
    card = volume_cast_card(_state_with_roster())
    assert _MARK in card
    assert "林尘挑大梁对阵血月教" in card          # focus
    assert "林尘：本卷成长为核心战力" in card       # returning + 本卷弧线
    assert "血月教主〔人物〕" in card                # 新登场名单
    assert "焚天印〔物品〕" in card


def test_volume_cast_card_empty_when_no_roster():
    assert volume_cast_card(_state_with_roster(volume_cast={})) == ""


def test_volume_cast_card_empty_when_stale_index():
    """volume_cast_index 与当前激活卷 index 不一致（陈旧，如残留自上一卷）→ 不注入。"""
    assert volume_cast_card(_state_with_roster(volume_cast_index=99)) == ""


def test_volume_cast_card_empty_when_no_volumes():
    assert volume_cast_card(NovelState(volumes=[], volume_cast=_roster(), volume_cast_index=1)) == ""


# ── 注入 chapter_plan ─────────────────────────────────────────────────────────


def test_chapter_plan_prompt_injects_roster():
    text = render_chapter_plan_prompt(_state_with_roster(), 1, 28, [], ChapterPlanGenreSpec())
    assert _MARK in text
    assert "林尘：本卷成长为核心战力" in text


def test_chapter_plan_prompt_no_roster_when_empty():
    state = NovelState(volumes=_volumes(), total_chapters_written=0, total_word_count="200万")
    text = render_chapter_plan_prompt(state, 1, 28, [], ChapterPlanGenreSpec())
    assert _MARK not in text


# ── 注入 arc_outline ──────────────────────────────────────────────────────────


def test_arc_outline_prompt_injects_roster():
    pack = get_prompt_pack("玄幻", "test")
    text = pack.arc_outline_prompt(_state_with_roster())
    assert _MARK in text
    assert "林尘挑大梁对阵血月教" in text


def test_arc_outline_prompt_no_roster_when_empty():
    pack = get_prompt_pack("玄幻", "test")
    state = NovelState(volumes=_volumes(), total_chapters_written=0, total_word_count="200万")
    assert _MARK not in pack.arc_outline_prompt(state)


# ── 注入 章前 entity_cards ────────────────────────────────────────────────────


def test_entity_cards_prompt_injects_roster():
    state = _state_with_roster(current_batch_titles=["第一章"], current_chapter_index=0)
    text = entity_cards_prompt(state)
    assert _MARK in text
    assert "血月教主〔人物〕" in text


def test_entity_cards_prompt_no_roster_when_empty():
    state = NovelState(
        volumes=_volumes(), total_chapters_written=0,
        current_batch_titles=["第一章"], current_chapter_index=0,
    )
    assert _MARK not in entity_cards_prompt(state)
