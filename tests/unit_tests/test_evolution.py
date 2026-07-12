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


# ── evolved_directives 三桶隔离拼装 ─────────────────────────────────────────
# chapter_prompt 读 chapter 桶;arc_outline_prompt 读 arc_outline 桶;scene_beats 读自己那桶。
# 老单桶 evolved_directives 字段仅用于兼容旧 prompt_overrides.json,加载时会自动迁移到 chapter 桶。


def test_chapter_prompt_injects_chapter_bucket_directives():
    pack = get_prompt_pack("玄幻")
    flavor = replace(
        pack.flavor,
        evolved_directives_chapter="战斗控制在300字内，覆盖原字数要求",
    )
    prompt = PromptPack("玄幻", flavor).chapter_prompt("试炼", 1, ["试炼"])
    assert "历史整改要点" in prompt
    assert "以本节为准" in prompt  # 最高优先级冲突声明
    assert "战斗控制在300字内，覆盖原字数要求" in prompt


def test_chapter_prompt_ignores_arc_bucket():
    """三桶隔离硬保:arc_outline 桶的整改不该泄漏到 chapter_prompt。"""
    pack = get_prompt_pack("玄幻")
    flavor = replace(pack.flavor, evolved_directives_arc_outline="弧线要跨批次升级反派")
    prompt = PromptPack("玄幻", flavor).chapter_prompt("试炼", 1, ["试炼"])
    assert "弧线要跨批次升级反派" not in prompt


def test_chapter_prompt_no_section_when_empty():
    pack = get_prompt_pack("玄幻")  # 所有桶默认空
    prompt = pack.chapter_prompt("试炼", 1, ["试炼"])
    assert "历史整改要点" not in prompt


def test_arc_outline_prompt_injects_arc_bucket_directives():
    """弧线大纲阶段读自己独立的 evolved_directives_arc_outline 桶。"""
    from noval_workflow.state import NovelState

    flavor = replace(
        get_prompt_pack("玄幻").flavor,
        evolved_directives_arc_outline="战斗压到300字内",
    )
    prompt = PromptPack("玄幻", flavor).arc_outline_prompt(NovelState(novel_name="x", genre="玄幻"))
    assert "历史整改要点" in prompt
    assert "战斗压到300字内" in prompt


def test_arc_outline_prompt_ignores_chapter_bucket():
    """三桶隔离硬保:chapter 桶的整改不该泄漏到 arc_outline_prompt。"""
    from noval_workflow.state import NovelState

    flavor = replace(
        get_prompt_pack("玄幻").flavor,
        evolved_directives_chapter="正文单场景不超500字",
    )
    prompt = PromptPack("玄幻", flavor).arc_outline_prompt(NovelState(novel_name="x", genre="玄幻"))
    assert "正文单场景不超500字" not in prompt


def test_arc_outline_prompt_no_section_when_empty():
    from noval_workflow.state import NovelState

    prompt = get_prompt_pack("玄幻").arc_outline_prompt(NovelState(novel_name="x", genre="玄幻"))
    assert "历史整改要点" not in prompt


def test_apply_overrides_supports_all_three_buckets():
    pack = get_prompt_pack("玄幻")
    merged = apply_overrides(
        pack.flavor,
        {
            "evolved_directives_chapter": "正文规则",
            "evolved_directives_arc_outline": "弧线规则",
            "evolved_directives_scene_beats": "beats 规则",
        },
    )
    assert merged.evolved_directives_chapter == "正文规则"
    assert merged.evolved_directives_arc_outline == "弧线规则"
    assert merged.evolved_directives_scene_beats == "beats 规则"


def test_overrides_roundtrip_persists_new_buckets(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides(
        "测试书",
        {
            "evolved_directives_chapter": "正文规则",
            "evolved_directives_arc_outline": "弧线规则",
        },
    )
    loaded = load_overrides("测试书")
    assert loaded["evolved_directives_chapter"] == "正文规则"
    assert loaded["evolved_directives_arc_outline"] == "弧线规则"


def test_legacy_evolved_directives_migrated_to_chapter_bucket(monkeypatch, tmp_path):
    """老 prompt_overrides.json 的单桶 evolved_directives 加载时迁移到 chapter 桶(仅内存)。"""
    import json

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    # 手写老格式的 overrides 文件(不走 save_overrides,模拟历史遗留)
    from noval_workflow.context import get_output_dir

    output_dir = get_output_dir("老书")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prompt_overrides.json").write_text(
        json.dumps({"evolved_directives": "老规则:战斗压到300字"}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = load_overrides("老书")
    # 老字段仍在(deprecated 保留),但新桶已由迁移函数填充
    assert loaded["evolved_directives"] == "老规则:战斗压到300字"
    assert loaded["evolved_directives_chapter"] == "老规则:战斗压到300字"


def test_legacy_migration_skipped_when_new_bucket_used(monkeypatch, tmp_path):
    """新桶已启用后,老字段不再自动迁移(避免覆盖用户已修改的新桶)。"""
    import json

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    from noval_workflow.context import get_output_dir

    output_dir = get_output_dir("混合书")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prompt_overrides.json").write_text(
        json.dumps(
            {
                "evolved_directives": "老规则",
                "evolved_directives_chapter": "新规则(已由用户改过)",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = load_overrides("混合书")
    # 新桶保留用户的值,不被老字段覆盖
    assert loaded["evolved_directives_chapter"] == "新规则(已由用户改过)"


# ── distill ──────────────────────────────────────────────────────────────────


def test_distill_parses_proposals_with_conflict(monkeypatch):
    out = (
        "好的：\n```json\n"
        '{"proposals":[{"field":"evolved_directives_chapter","op":"append",'
        '"text":"将战斗篇幅改为不超过300字，覆盖原3000字要求","rationale":"节奏",'
        '"conflicts_with":"原每场战斗约3000字"}],"summary":"收紧战斗篇幅"}\n```'
    )
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    res = e.distill("战斗太长", "chapter", e.CurrentPrompt(chapter_style_rules="每场战斗约3000字"))
    assert res.summary == "收紧战斗篇幅"
    assert len(res.proposals) == 1
    p = res.proposals[0]
    assert p.field == "evolved_directives_chapter"
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
    """LLM 输出的非法 field 被归一到当前 review_type 对应桶(chapter → evolved_directives_chapter)。"""
    out = '{"proposals":[{"field":"weird","text":"x"}],"summary":""}'
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    assert e.distill("f", "chapter", e.CurrentPrompt()).proposals[0].field == "evolved_directives_chapter"


def test_distill_coerces_unknown_field_for_scene_beats(monkeypatch):
    """review_type=scene_beats 时非法 field 归一到 evolved_directives_scene_beats 桶。"""
    out = '{"proposals":[{"field":"weird","text":"x"}],"summary":""}'
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM(out))
    proposals = e.distill("f", "scene_beats", e.CurrentPrompt()).proposals
    assert proposals[0].field == "evolved_directives_scene_beats"


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


def test_distill_raises_on_unparseable_llm_output(monkeypatch):
    # LLM 反复吐无 JSON 的脏文本：json_repair 修不出、回喂重试仍失败 → 抛 EvolutionParseError 到顶层。
    monkeypatch.setattr(e, "get_llm", lambda *a, **k: _FakeLLM("这里没有 JSON，纯说明文字"))
    with pytest.raises(e.EvolutionParseError):
        e.distill("把战斗写短一点", "chapter", e.CurrentPrompt())


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
    """章节打回重跑（review_history 非空）时，从 overrides 读最新整改注入 messages 末尾。

    review_type=chapter → 读 evolved_directives_chapter 桶(三桶隔离)。
    """
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides("重跑书", {"evolved_directives_chapter": "每场战斗压到300字内"})
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


def test_generate_injects_scene_beats_bucket_on_reject_rerun(monkeypatch, tmp_path):
    """scene_beats 打回重跑读 scene_beats 桶,不读 chapter 桶(三桶隔离硬保)。"""
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides(
        "beats重跑书",
        {
            "evolved_directives_chapter": "正文桶规则(不该出现)",
            "evolved_directives_scene_beats": "打脸桥段必须四拍齐全",
        },
    )
    rec = _RecLLM()
    monkeypatch.setattr(sg, "get_llm", lambda *a, **k: rec)

    state = ReviewSubState(
        novel_name="beats重跑书",
        genre="玄幻",
        review_type="scene_beats",
        system_context="设定",
        review_feedback="打脸不齐",
        review_history=[
            {"role": "human", "content": "任务"},
            {"role": "ai", "content": "旧beats"},
        ],
    )
    sg.generate(state)
    joined = "\n".join(m.content for m in rec.messages)
    assert "打脸桥段必须四拍齐全" in joined
    assert "正文桶规则(不该出现)" not in joined


def test_generate_no_evolved_injection_for_non_evolvable_type(monkeypatch, tmp_path):
    """非 chapter/arc_outline/scene_beats（如 world_building）打回重跑不注入任何桶整改。"""
    from noval_workflow import subgraph as sg
    from noval_workflow.state import ReviewSubState

    monkeypatch.setenv("NOVEL_OUTPUT_DIR", str(tmp_path))
    save_overrides("重跑书2", {"evolved_directives_chapter": "每场战斗压到300字内"})
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
