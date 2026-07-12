"""Scene beats 提示词、校验函数、save_fn 落地的端到端单元测试。"""

from __future__ import annotations

import json

import pytest

from noval_workflow.json_utils import JsonParseError
from noval_workflow.nodes.scene_beats import _prepare_scene_beats, _save_scene_beats
from noval_workflow.prompts import (
    ALL_DEVICE_TAGS,
    SCENE_BEATS_PROMPT,
    SCENE_BEATS_REVIEW_PROMPT,
    format_beats_for_chapter_prompt,
    scene_beats_prompt,
    validate_beats,
)
from noval_workflow.state import NovelState


# ── device_tag 枚举完整性 ─────────────────────────────────────────────────────

def test_all_device_tags_frozen_and_complete():
    """ALL_DEVICE_TAGS 应覆盖打脸四拍、三段式、钩子、伏笔、缓冲全部枚举值。"""
    expected = {
        "setup", "buildup", "release",
        "slap_taunt", "slap_silence", "slap_crush", "slap_witness",
        "hook_opening", "hook_chapter_end",
        "foreshadow_plant", "foreshadow_recover",
        "buffer",
    }
    assert ALL_DEVICE_TAGS == frozenset(expected)


# ── validate_beats：程序化兜底校验 ─────────────────────────────────────────────

def _mk_beat(bid: int, tags: list[str], **overrides) -> dict:
    base = {
        "id": bid,
        "scene": "客栈门口",
        "goal": "拿到信",
        "obstacle": "李三索钱",
        "outcome": "花 5 两拿到",
        "cost": "暴露身家",
        "emotion_arc": "戒备→释然",
        "device_tags": tags,
        "target_words": 500,
    }
    base.update(overrides)
    return base


def test_validate_accepts_well_formed_beats():
    """典型合规样本：setup / 打脸四拍完整 / 章尾钩挂末位。"""
    beats = [
        _mk_beat(1, ["setup"]),
        _mk_beat(2, ["slap_taunt"]),
        _mk_beat(3, ["slap_silence"]),
        _mk_beat(4, ["slap_crush"]),
        _mk_beat(5, ["slap_witness", "hook_chapter_end"]),
    ]
    assert validate_beats(beats) == []


def test_validate_flags_illegal_device_tag():
    beats = [_mk_beat(1, ["nonsense_tag"])]
    problems = validate_beats(beats)
    assert any("nonsense_tag" in p and "不在枚举内" in p for p in problems)


def test_validate_flags_incomplete_slap_four_beats():
    """硬约束：只要出现任一 slap_*，四拍必须齐全，缺一即报错。"""
    beats = [
        _mk_beat(1, ["slap_taunt"]),
        _mk_beat(2, ["slap_silence"]),
        _mk_beat(3, ["slap_crush"]),
        # 缺 slap_witness
    ]
    problems = validate_beats(beats)
    assert any("打脸四拍不齐全" in p and "slap_witness" in p for p in problems)


def test_validate_flags_hook_chapter_end_not_at_last():
    beats = [
        _mk_beat(1, ["hook_chapter_end"]),  # 不是末 beat
        _mk_beat(2, ["buffer"]),
    ]
    problems = validate_beats(beats)
    assert any("hook_chapter_end" in p and "未挂在末 beat" in p for p in problems)


def test_validate_flags_hook_opening_not_at_first():
    beats = [
        _mk_beat(1, ["setup"]),
        _mk_beat(2, ["hook_opening"]),  # 不是首 beat
    ]
    problems = validate_beats(beats)
    assert any("hook_opening" in p and "未挂在首 beat" in p for p in problems)


def test_validate_flags_empty_device_tags():
    beats = [_mk_beat(1, [])]
    problems = validate_beats(beats)
    assert any("device_tags 为空" in p for p in problems)


def test_validate_flags_non_list_beats():
    assert validate_beats([]) == ["beats 不是非空 list"]
    assert validate_beats(None) == ["beats 不是非空 list"]  # type: ignore[arg-type]


# ── format_beats_for_chapter_prompt：注入 chapter_prompt 的 markdown 渲染 ──────

def test_format_beats_renders_all_fields():
    beats = [_mk_beat(1, ["setup", "foreshadow_plant"])]
    md = format_beats_for_chapter_prompt(beats)
    # 关键字段和 device_tags 都能读到
    assert "Beat 1" in md
    assert "客栈门口" in md
    assert "拿到信" in md
    assert "李三索钱" in md
    assert "setup" in md and "foreshadow_plant" in md


def test_format_empty_beats_returns_empty_string():
    assert format_beats_for_chapter_prompt([]) == ""


# ── scene_beats_prompt：状态组装 ──────────────────────────────────────────────

def test_scene_beats_prompt_injects_batch_and_arc():
    state = NovelState(
        novel_name="测试书",
        genre="玄幻",
        chapter_word_count="2500",
        total_chapters_written=4,  # 即将写第 5 章
        current_batch_titles=["A", "B", "C", "D", "E"],
        current_chapter_index=0,  # 本批第 1 章
        current_arc_outline="【章节1】\n1. 本章核心事件：主角进城\n【章节2】\n1. 本章核心事件：主角遇险",
    )
    prompt = scene_beats_prompt(state, chapter_context="上一章：主角出发")
    # 章号、批内位置、目标字数都注入
    assert "第 5 章" in prompt and "《A》" in prompt
    assert "第 1/5 章" in prompt
    assert "2500" in prompt
    # arc 锚点抽出了【章节1】那一段
    assert "主角进城" in prompt
    # 前文参考注入
    assert "主角出发" in prompt
    # device_tag 枚举清单出现在生成提示词里
    assert "slap_taunt" in prompt and "hook_chapter_end" in prompt


def test_scene_beats_prompt_falls_back_when_arc_block_unfindable():
    """arc_outline 存在但没有【章节X】结构时，锚点段应给出降级提示。"""
    state = NovelState(
        genre="都市",
        chapter_word_count="",
        total_chapters_written=0,
        current_batch_titles=["首章"],
        current_chapter_index=0,
        current_arc_outline="仅有一段散落文字，无【章节X】标记",
    )
    prompt = scene_beats_prompt(state)
    assert "本章弧线大纲锚点" in prompt or "本章定位" in prompt


# ── _save_scene_beats：JSON 落地行为 ──────────────────────────────────────────

class _FakeState:
    """最小 state 桩，只提供 _save_scene_beats 需要的两个字段。"""
    def __init__(self, draft: str, total_written: int = 0):
        self.current_draft = draft
        self.total_chapters_written = total_written


def test_save_scene_beats_parses_clean_json_and_writes_index():
    beats = [_mk_beat(1, ["setup"]), _mk_beat(2, ["release", "hook_chapter_end"])]
    draft = json.dumps(beats, ensure_ascii=False)
    state = _FakeState(draft, total_written=2)  # 即将写第 3 章
    result = _save_scene_beats(state)
    assert result["beats_chapter_index"] == 3
    assert len(result["current_chapter_beats"]) == 2
    assert result["current_chapter_beats"][0]["id"] == 1


def test_save_scene_beats_repairs_dirty_json():
    """LLM 常吐带 markdown 围栏的 JSON——repair_and_parse 应自动修好。"""
    dirty = "```json\n[" + json.dumps(_mk_beat(1, ["setup"]), ensure_ascii=False) + "]\n```"
    state = _FakeState(dirty, total_written=0)
    result = _save_scene_beats(state)
    assert result["beats_chapter_index"] == 1
    assert result["current_chapter_beats"][0]["device_tags"] == ["setup"]


def test_save_scene_beats_raises_on_unparseable_draft():
    """完全无法修复的脏输出应 fail-fast 抛 JsonParseError，不静默塞下游。"""
    state = _FakeState("这不是 JSON，只是一段散文；scene beats 需要严格 JSON 数组。")
    with pytest.raises(JsonParseError):
        _save_scene_beats(state)


def test_save_scene_beats_empty_draft_returns_empty_dict():
    """草稿为空（如用户人工审核清空后通过）时不写字段——nop。"""
    state = _FakeState("")
    assert _save_scene_beats(state) == {}


# ── _prepare_scene_beats：契约字段落地到 review_type ──────────────────────────

def test_prepare_scene_beats_sets_review_type():
    state = NovelState(
        novel_name="X",
        genre="通用",
        chapter_word_count="2000",
        current_batch_titles=["A"],
        current_chapter_index=0,
        total_chapters_written=0,
    )
    result = _prepare_scene_beats(state)
    assert result["review_type"] == "scene_beats"
    assert result["task_prompt"]  # 非空
    assert result["system_context"]


# ── review prompt 注册完整性 ──────────────────────────────────────────────────

def test_scene_beats_review_prompt_has_draft_placeholder():
    """SCENE_BEATS_REVIEW_PROMPT 应含 {draft} 占位，供 subgraph.llm_self_review 填充。"""
    assert "{draft}" in SCENE_BEATS_REVIEW_PROMPT


def test_subgraph_review_prompts_registers_scene_beats():
    """subgraph._REVIEW_PROMPTS 应含 scene_beats 条目——否则自审会 fail-fast 报未登记。"""
    from noval_workflow.subgraph import _REVIEW_PROMPTS
    assert "scene_beats" in _REVIEW_PROMPTS
    assert _REVIEW_PROMPTS["scene_beats"] == SCENE_BEATS_REVIEW_PROMPT
