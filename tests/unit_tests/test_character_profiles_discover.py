"""Character profiles discover 契约层单元测试（prompt / prepare / save / 映射 / 审核 prompt）。"""

from __future__ import annotations

from noval_workflow.interrupt_types import InterruptType, review_type_to_interrupt_type
from noval_workflow.nodes.character_profiles_discover import (
    _prepare_character_profiles_discover,
    _save_character_profiles_discover,
)
from noval_workflow.prompts import character_profiles_discover_prompt
from noval_workflow.state import NovelState
from noval_workflow.subgraph import _REVIEW_PROMPTS


def _mk_state() -> NovelState:
    s = NovelState()
    s.total_chapters_written = 3
    s.character_profiles = "主角：李云\n性格：谨慎"
    s.current_draft = "本章正文：李云在客栈遇到神秘人赵七。"
    return s


# ── prepare 契约 ───────────────────────────────────────────────────────────────

def test_prepare_returns_contract():
    """prepare 返回字典须含三键；task_prompt 同时嵌入已有档案 + 本章正文。"""
    s = _mk_state()
    r = _prepare_character_profiles_discover(s)
    assert set(r.keys()) == {"system_context", "task_prompt", "review_type"}
    assert r["review_type"] == "character_profiles_discover"
    assert "主角：李云" in r["task_prompt"]
    assert "本章正文" in r["task_prompt"]


# ── save 契约 ──────────────────────────────────────────────────────────────────

def test_save_non_empty_writes_current_draft():
    s = _mk_state()
    s.current_draft = "更新后的档案 markdown"
    r = _save_character_profiles_discover(s)
    assert r == {"character_profiles": "更新后的档案 markdown"}


def test_save_empty_no_clobber():
    """空 draft 兜底：不清空原字段，返回 {}。"""
    s = _mk_state()
    s.current_draft = ""
    r = _save_character_profiles_discover(s)
    assert r == {}


# ── prompt 组装 ────────────────────────────────────────────────────────────────

def test_prompt_placeholders_resolved():
    """组装后的 prompt 不应残留 {chapter_num}/{existing_profiles}/{chapter_draft} 占位符，
    且已知档案与本章正文的原文值须出现在结果里。"""
    s = _mk_state()
    p = character_profiles_discover_prompt(s)
    assert "{chapter_num}" not in p
    assert "{existing_profiles}" not in p
    assert "{chapter_draft}" not in p
    assert "主角：李云" in p
    assert "本章正文" in p


# ── interrupt 映射 ─────────────────────────────────────────────────────────────

def test_interrupt_mapping():
    assert (
        review_type_to_interrupt_type("character_profiles_discover")
        == InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW
    )


# ── 审核 prompt 隔离 Phase 1 硬清单 ────────────────────────────────────────────

def test_review_prompt_disclaims_phase1_hard_checklist():
    """discover 审核 prompt 必须显式声明「不检查」力量体系归属等 Phase 1 硬项，
    避免未来手滑串接 CHARACTER_PROFILES_REVIEW_PROMPT。"""
    p = _REVIEW_PROMPTS["character_profiles_discover"]
    assert "力量体系" in p
    assert "不检查" in p
