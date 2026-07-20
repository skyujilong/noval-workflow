"""overall_outline Synopsis 化重构的结构断言。

全书级大纲已从「起承转合四段作文」改为 Synopsis 五小节
（故事内核/主线动力/暗线悬念承诺/人物弧光/结局锚点），
起承转合只保留在卷级（volumes）——这里锁住该口径，防止回退。
"""

from noval_workflow.prompts import available_genres, get_prompt_pack
from noval_workflow.prompts.review_shared import (
    OVERALL_OUTLINE_REVIEW_PROMPT,
    VOLUMES_REVIEW_PROMPT,
)

_SECTIONS = ["【故事内核】", "【主线动力】", "【暗线与悬念承诺】", "【人物弧光大势】", "【结局锚点】"]


def test_overall_outline_prompt_is_synopsis_style_for_all_genres():
    """所有题材的生成提示词都要求五小节结构，且不再要求起承转合四段。"""
    for genre in available_genres():
        pack = get_prompt_pack(genre, "测试书")
        prompt = pack.overall_outline_prompt("50万字")
        for section in _SECTIONS:
            assert section in prompt, f"{genre} 缺少小节 {section}"
        assert "起承转合" not in prompt, f"{genre} 仍要求全书级起承转合"
        assert "50万字" in prompt
        assert "800-1200" in prompt


def test_overall_outline_review_matches_synopsis_sections():
    """审核口径与生成口径同步：审五小节，不再审起承转合。"""
    for section in _SECTIONS:
        assert section in OVERALL_OUTLINE_REVIEW_PROMPT
    assert "起承转合" not in OVERALL_OUTLINE_REVIEW_PROMPT
    assert "800-1200" in OVERALL_OUTLINE_REVIEW_PROMPT


def test_volume_level_story_beats_are_preserved():
    """卷级起承转合是刻意保留的叙事节拍层，不随全书级改动而丢失。"""
    pack = get_prompt_pack("玄幻", "测试书")
    assert "起（引入" in pack.volumes_prompt("全书战略概要……")
    assert "起（引入）→承（展开）→转（高潮/关键转折）→合" in VOLUMES_REVIEW_PROMPT
