"""正文「手感规则」注入的单元测试。

验证目标（确定性可测部分）：从 chinese-webnovel-skills 提炼的 5 条去 AI 味手感规则，
确实被注入到实际喂给 LLM 的两处 prompt 里，且对**所有题材**生效、拼装不报错：
  1. 正文创作 prompt（base.py::PromptPack.chapter_prompt 的通用「去机械化」段）
  2. 章节自审 prompt（review_shared.py::CHAPTER_REVIEW_PROMPT 第 11 条「文字手感」）

注意边界：本测试只保证「规则进入了 prompt」，不保证「LLM 照做写出更好的文字」——
后者是概率性输出，需真实生成 + 人工/LLM 评审，不在单元测试范畴内。
"""

from __future__ import annotations

import pytest

from noval_workflow.prompts import CHAPTER_REVIEW_PROMPT
from noval_workflow.prompts.registry import available_genres, get_prompt_pack

# 正文 prompt 必须包含的 5 条手感规则锚点（各取规则里唯一、稳定的标识短语）。
# 缺任一条即说明该规则在通用创作 prompt 里丢失。
_PROSE_CRAFT_ANCHORS: tuple[str, ...] = (
    "修辞为剧情服务",      # 无缘无故的修辞
    "忌同义反复与极端词",  # 同义反复 + 极端程度词
    "不写说明书",          # 说明书式机制/动机解释
    "标点克制守规范",      # 破折号/省略号/顿号/弯引号
    "开篇不倾泻背景",      # 开篇背景后置
)

# 自审 prompt 第 11 条「文字手感」必须包含的 5 个检查点锚点，与创作端一一对应。
_REVIEW_CRAFT_ANCHORS: tuple[str, ...] = (
    "文字手感",            # 第 11 条标题
    "为修辞而修辞",
    "同义反复",
    "说明书式解释",
    "集中倾泻背景设定",
)


def _chapter_prompt_for(genre: str) -> str:
    """用固定的最小参数拼出某题材的正文创作 prompt。"""
    pack = get_prompt_pack(genre)
    return pack.chapter_prompt(
        title="试炼之章",
        chapter_num=3,
        all_titles=["第一章", "第二章", "第三章"],
    )


def _review_prompt_for(genre: str) -> str:
    """拼出某题材的章节自审 prompt（注入该题材的文风审核清单）。"""
    pack = get_prompt_pack(genre)
    return CHAPTER_REVIEW_PROMPT.format(
        draft="占位正文",
        style_checklist=pack.flavor.chapter_review_checklist,
    )


# ── 正文 prompt：手感规则对所有题材生效 ─────────────────────────────────────────

@pytest.mark.parametrize("genre", available_genres())
def test_chapter_prompt_injects_all_craft_rules(genre: str) -> None:
    """每个题材拼出的正文 prompt，都应含全部 5 条手感规则（通用层，全题材受益）。"""
    prompt = _chapter_prompt_for(genre)
    for anchor in _PROSE_CRAFT_ANCHORS:
        assert anchor in prompt, f"题材「{genre}」的正文 prompt 缺少手感规则锚点：{anchor}"


# ── 自审 prompt：手感检查项注入且格式化健壮 ─────────────────────────────────────

@pytest.mark.parametrize("genre", available_genres())
def test_review_prompt_injects_craft_checklist(genre: str) -> None:
    """自审 prompt 第 11 条「文字手感」的 5 个检查点应齐全，且 format 注入不报错。"""
    prompt = _review_prompt_for(genre)
    for anchor in _REVIEW_CRAFT_ANCHORS:
        assert anchor in prompt, f"题材「{genre}」的自审 prompt 缺少手感检查项锚点：{anchor}"


def test_review_prompt_has_no_unfilled_placeholders() -> None:
    """format 后不应残留 {draft}/{style_checklist} 占位符——防止新增文本误引花括号。"""
    prompt = _review_prompt_for("玄幻")
    assert "{draft}" not in prompt
    assert "{style_checklist}" not in prompt
