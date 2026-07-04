"""进化：evolved_directives 拼装、distill 提炼（含冲突侦测）、refine 拆条。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from noval_workflow.prompts import evolution as e
from noval_workflow.prompts.base import PromptPack
from noval_workflow.prompts.evolution_store import ProposalOp
from noval_workflow.prompts.overrides import apply_overrides, load_overrides, save_overrides
from noval_workflow.prompts.registry import get_prompt_pack


class _FakeLLM:
    def __init__(self, out: str) -> None:
        self.out = out

    def invoke(self, _messages):
        class _R:
            pass

        r = _R()
        r.content = self.out
        return r


# ── evolved_directives 拼装 ──────────────────────────────────────────────────


def test_chapter_prompt_injects_evolved_directives_with_priority():
    pack = get_prompt_pack("玄幻")
    flavor = replace(pack.flavor, evolved_directives="战斗控制在300字内，覆盖原字数要求")
    prompt = PromptPack("玄幻", flavor).chapter_prompt("试炼", 1, ["试炼"])
    assert "历史整改要点" in prompt
    assert "以本节为准" in prompt  # 最高优先级冲突声明
    assert "战斗控制在300字内，覆盖原字数要求" in prompt


def test_chapter_prompt_no_section_when_empty():
    pack = get_prompt_pack("玄幻")  # evolved_directives 默认空
    prompt = pack.chapter_prompt("试炼", 1, ["试炼"])
    assert "历史整改要点" not in prompt


def test_arc_outline_prompt_injects_evolved_directives():
    """弧线大纲阶段也纳入自进化闭环（章节 + 弧线大纲共用 evolved_directives）。"""
    from noval_workflow.state import NovelState

    flavor = replace(get_prompt_pack("玄幻").flavor, evolved_directives="战斗压到300字内")
    prompt = PromptPack("玄幻", flavor).arc_outline_prompt(NovelState(novel_name="x", genre="玄幻"))
    assert "历史整改要点" in prompt
    assert "战斗压到300字内" in prompt


def test_arc_outline_prompt_no_section_when_empty():
    from noval_workflow.state import NovelState

    prompt = get_prompt_pack("玄幻").arc_outline_prompt(NovelState(novel_name="x", genre="玄幻"))
    assert "历史整改要点" not in prompt


def test_apply_overrides_supports_evolved_directives():
    pack = get_prompt_pack("玄幻")
    merged = apply_overrides(pack.flavor, {"evolved_directives": "X规则"})
    assert merged.evolved_directives == "X规则"


def test_overrides_roundtrip_persists_evolved_directives(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides("测试书", {"evolved_directives": "战斗控制在300字内"})
    assert load_overrides("测试书")["evolved_directives"] == "战斗控制在300字内"


# ── distill ──────────────────────────────────────────────────────────────────


def test_distill_parses_proposals_with_conflict(monkeypatch):
    out = (
        "好的：\n```json\n"
        '{"proposals":[{"field":"evolved_directives","op":"append",'
        '"text":"将战斗篇幅改为不超过300字，覆盖原3000字要求","rationale":"节奏",'
        '"conflicts_with":"原每场战斗约3000字"}],"summary":"收紧战斗篇幅"}\n```'
    )
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    res = e.distill("战斗太长", "chapter", e.CurrentPrompt(chapter_style_rules="每场战斗约3000字"))
    assert res.summary == "收紧战斗篇幅"
    assert len(res.proposals) == 1
    p = res.proposals[0]
    assert p.field == "evolved_directives"
    assert p.op is ProposalOp.APPEND
    assert p.conflicts_with == "原每场战斗约3000字"
    assert "覆盖原" in p.text


def test_distill_empty_feedback_short_circuits(monkeypatch):
    # 不应调用 LLM
    monkeypatch.setattr(
        e, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用"))
    )
    assert e.distill("   ", "chapter", e.CurrentPrompt()).proposals == ()


def test_distill_coerces_unknown_field(monkeypatch):
    out = '{"proposals":[{"field":"weird","text":"x"}],"summary":""}'
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    assert e.distill("f", "chapter", e.CurrentPrompt()).proposals[0].field == "evolved_directives"


# ── refine_to_items ──────────────────────────────────────────────────────────


def test_refine_parses_items_and_drops_empty(monkeypatch):
    out = (
        '[{"title":"战斗节奏","text":"战斗控制在300字内","tags":["节奏","战斗"]},'
        '{"title":"空","text":""}]'
    )
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    items = e.refine_to_items("战斗控制在300字内；战斗控制在300字内", "玄幻")
    assert len(items) == 1
    assert items[0].title == "战斗节奏" and items[0].tags == ("节奏", "战斗")


def test_refine_empty_input_short_circuits(monkeypatch):
    monkeypatch.setattr(
        e, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用"))
    )
    assert e.refine_to_items("   ", "玄幻") == []


def test_extract_json_raises_on_garbage():
    with pytest.raises(e.EvolutionParseError):
        e._extract_json("这里没有 JSON", dict)


# ── reconcile ────────────────────────────────────────────────────────────────


def test_reconcile_parses_result(monkeypatch):
    out = (
        "整理如下：\n```json\n"
        '{"reconciled":"战斗压到300字内\\n对话推进剧情","summary":"合并2条、消解1处矛盾",'
        '"resolved":["原3000字与300字矛盾，取最新300字"]}\n```'
    )
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    res = e.reconcile("战斗3000字\n战斗压到300字内\n对话推进剧情", "玄幻")
    assert res.reconciled == "战斗压到300字内\n对话推进剧情"
    assert res.summary == "合并2条、消解1处矛盾"
    assert res.resolved == ("原3000字与300字矛盾，取最新300字",)


def test_reconcile_empty_input_short_circuits(monkeypatch):
    monkeypatch.setattr(
        e, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用"))
    )
    res = e.reconcile("   ", "玄幻")
    assert res.reconciled == "" and res.resolved == ()


# ── generate 打回重跑注入最新整改（当前章立即生效） ────────────────────────────


class _RecLLM:
    """记录收到的 messages，返回固定正文。"""

    def __init__(self) -> None:
        self.messages: list = []

    def invoke(self, messages):
        self.messages = messages

        class _R:
            content = "新正文"

        return _R()


def test_generate_injects_latest_evolved_on_reject_rerun(monkeypatch, tmp_path):
    """章节打回重跑（review_history 非空）时，从 overrides 读最新整改注入 messages 末尾。"""
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides("重跑书", {"evolved_directives": "每场战斗压到300字内"})
    rec = _RecLLM()
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: rec)

    state = ReviewSubState(
        novel_name="重跑书",
        genre="玄幻",
        review_type="chapter",
        system_context="设定",
        review_feedback="战斗太长",
        review_history=[
            {"role": "human", "content": "任务"},
            {"role": "ai", "content": "旧正文"},
        ],
    )
    sg.generate(state)
    joined = "\n".join(m.content for m in rec.messages)
    assert "历史整改要点" in joined and "每场战斗压到300字内" in joined


def test_generate_no_evolved_injection_for_non_evolvable_type(monkeypatch, tmp_path):
    """非 chapter/arc_outline（如 world_building）打回重跑不注入章节整改。"""
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides("重跑书2", {"evolved_directives": "每场战斗压到300字内"})
    rec = _RecLLM()
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: rec)

    state = ReviewSubState(
        novel_name="重跑书2",
        genre="玄幻",
        review_type="world_building",
        system_context="设定",
        review_feedback="改一下",
        review_history=[
            {"role": "human", "content": "任务"},
            {"role": "ai", "content": "旧设定"},
        ],
    )
    sg.generate(state)
    joined = "\n".join(m.content for m in rec.messages)
    assert "历史整改要点" not in joined
