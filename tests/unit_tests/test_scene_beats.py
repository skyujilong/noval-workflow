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


# ── 打回重跑输出格式提醒(防 review_history 窗口截断后 LLM 忘掉 JSON 契约)────────

def test_regen_instruction_reminds_scene_beats_json_format(monkeypatch):
    """scene_beats 打回重跑时,human 消息必须显式声明「严格输出 JSON 数组、无 markdown 围栏」。

    背景:首轮 task_prompt 有 JSON 规范,但被打回一到两轮后:
      1. `regen_instruction` 会作为新的 human 消息追加,若沿用创作类的「直接输出完整正文」
         话术,LLM 会被误导成散文输出,repair_and_parse 抛错;
      2. review_history 有 _HISTORY_MAX_ROUNDS 窗口(scene_beats=3 轮),超窗口后首轮
         task_prompt 会被裁掉,规范提醒随之消失。
    因此每轮重跑都必须在 human message 里显式重申 JSON 契约。
    """
    from langchain_core.messages import AIMessage
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    recorder: list = []

    class _FakeLLM:
        def __init__(self, label: str) -> None:
            self.label = label

        def invoke(self, messages):
            recorder.append((self.label, list(messages)))
            return AIMessage(content='[{"id":1,"device_tags":["setup"]}]')

    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm")))

    state = ReviewSubState(
        review_type="scene_beats",
        system_context="SYS",
        task_prompt="首轮任务(会被窗口裁掉)",
        review_feedback="[AI审稿意见]\npacing 全 fast,请改",
        review_history=[
            {"role": "human", "content": "首轮任务(会被窗口裁掉)"},
            {"role": "ai", "content": "上一版脏 JSON"},
        ],
    )
    sg.generate(state)

    prompt = "\n".join(str(getattr(m, "content", "")) for m in recorder[-1][1])
    # 关键:重跑指令里必须出现 JSON 硬约束,且不含创作类的「完整正文/从第一句话开始」话术
    assert "JSON 数组" in prompt or "严格输出 JSON" in prompt
    assert "device_tags" in prompt, "重跑规范应重申字段列表,防止 LLM 漏字段"
    assert "从正文第一句话开始输出" not in prompt, "scene_beats 不应沿用创作类散文话术"

    # 正例:必须给出可照抄的合规 JSON 样本(含真实字段名与合法枚举值),让 LLM 有明确目标
    assert "合规示例" in prompt
    assert '"id": 1' in prompt
    assert '"pacing":' in prompt and '"slow"' in prompt
    assert '"device_tags":' in prompt and '"setup"' in prompt

    # 反例:必须显式禁止最常见的三种破坏形态(围栏 / 前置解释 / 输出散文)
    assert "严禁的错误形态" in prompt or "❌" in prompt
    assert "```json" in prompt, "反例应显示禁止 markdown 围栏"
    assert "好的" in prompt or "已按意见调整" in prompt, "反例应包含 LLM 常见的说明性前后缀"
    assert "第一个字符必须是 `[`" in prompt, "结尾应再次强调 JSON 边界"


def test_regen_instruction_keeps_prose_hint_for_chapter(monkeypatch):
    """chapter 等创作类走默认散文话术,不应被 scene_beats 的 JSON 提醒污染(回归防护)。"""
    from langchain_core.messages import AIMessage
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    recorder: list = []

    class _FakeLLM:
        def __init__(self, label: str) -> None:
            self.label = label

        def invoke(self, messages):
            recorder.append((self.label, list(messages)))
            return AIMessage(content="重写后的章节正文。")

    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: _FakeLLM(k.get("label", "llm")))

    state = ReviewSubState(
        review_type="chapter",
        system_context="SYS",
        task_prompt="首轮章节任务",
        review_feedback="[AI审稿意见]\n对白偏干",
        review_history=[
            {"role": "human", "content": "首轮章节任务"},
            {"role": "ai", "content": "上一版章节正文"},
        ],
    )
    sg.generate(state)

    prompt = "\n".join(str(getattr(m, "content", "")) for m in recorder[-1][1])
    assert "从正文第一句话开始输出" in prompt
    assert "JSON 数组" not in prompt, "创作类不应被 scene_beats 的 JSON 提醒污染"
