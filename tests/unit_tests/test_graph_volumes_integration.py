"""图装配 + prompt 注入集成测试。

验证：
1. Step 06 装配后新增节点 (prepare_volumes/review_volumes/save_volumes/volume_boundary_gate) 在图上
2. save_overall_outline → prepare_volumes → review → save → prepare_character_cards 链路
3. save_config / ask_continue 分支路由到 volume_boundary_gate → prepare_chapter_plan
4. 三处 prompt (chapter_plan / arc_outline / chapter) 在 volumes 非空时含【当前卷位置】，
   volumes 为空时不含（向后兼容）。
"""

from __future__ import annotations

from noval_workflow.graph import graph
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.prompts.base import render_chapter_plan_prompt, ChapterPlanGenreSpec
from noval_workflow.state import NovelState, Volume


# ── 图装配 ──────────────────────────────────────────────────────────────────


def test_graph_has_volume_nodes():
    """新增 4 个节点必须挂进图。"""
    nodes = set(graph.get_graph().nodes)
    assert "prepare_volumes" in nodes
    assert "review_volumes" in nodes
    assert "save_volumes" in nodes
    assert "volume_boundary_gate" in nodes


def test_graph_wires_volumes_chain_after_overall_outline():
    """save_overall_outline 之后的下一站是 prepare_volumes（不是 prepare_character_cards）。"""
    edges = graph.get_graph().edges
    downstream = {(e.source, e.target) for e in edges}
    assert ("save_overall_outline", "prepare_volumes") in downstream
    assert ("prepare_volumes", "review_volumes") in downstream
    assert ("review_volumes", "save_volumes") in downstream
    assert ("save_volumes", "prepare_character_cards") in downstream
    # 原直连边应已断
    assert ("save_overall_outline", "prepare_character_cards") not in downstream


def test_graph_gate_before_chapter_plan():
    """volume_boundary_gate → prepare_chapter_plan（透传边）。"""
    edges = graph.get_graph().edges
    downstream = {(e.source, e.target) for e in edges}
    assert ("volume_boundary_gate", "prepare_chapter_plan") in downstream


# ── prompt 注入 ─────────────────────────────────────────────────────────────


def _sample_volumes() -> list[Volume]:
    return [
        Volume(index=1, title="卷1", chapter_start=1, target_min=22, target_max=28,
               summary="卷1主线", setup_for_next="埋钩", status="in_progress"),
        Volume(index=2, title="卷2", chapter_start=29, target_min=35, target_max=45,
               summary="卷2主线", setup_for_next="", status="planning"),
    ]


def test_arc_outline_prompt_includes_volume_position_when_volumes_set():
    """有 volumes 时 arc_outline_prompt 头部包含【当前卷位置】。"""
    pack = get_prompt_pack("玄幻", "test")
    state = NovelState(volumes=_sample_volumes(), total_chapters_written=5,
                       total_word_count="200万")
    text = pack.arc_outline_prompt(state)
    assert "【当前卷位置】" in text
    assert "卷1" in text


def test_arc_outline_prompt_omits_volume_when_empty():
    """无 volumes → 不注入卷位置卡（向后兼容，老小说不受影响）。"""
    pack = get_prompt_pack("玄幻", "test")
    state = NovelState(volumes=[], total_chapters_written=5, total_word_count="200万")
    text = pack.arc_outline_prompt(state)
    assert "【当前卷位置】" not in text


def test_chapter_plan_prompt_includes_volume_position_when_volumes_set():
    """render_chapter_plan_prompt 有 volumes 时应含【当前卷位置】。"""
    state = NovelState(volumes=_sample_volumes(), total_chapters_written=0,
                       total_word_count="200万")
    spec = ChapterPlanGenreSpec()  # 中性版
    text = render_chapter_plan_prompt(state, 1, 40, [], spec)
    assert "【当前卷位置】" in text


def test_chapter_plan_prompt_omits_volume_when_empty():
    """render_chapter_plan_prompt 无 volumes 时不注入。"""
    state = NovelState(volumes=[], total_chapters_written=0, total_word_count="200万")
    spec = ChapterPlanGenreSpec()
    text = render_chapter_plan_prompt(state, 1, 40, [], spec)
    assert "【当前卷位置】" not in text


def test_chapter_prompt_includes_volume_when_state_and_volumes():
    """chapter_prompt 传入 state 且有 volumes 时应注入卷位置。"""
    pack = get_prompt_pack("玄幻", "test")
    state = NovelState(volumes=_sample_volumes(), total_chapters_written=5)
    text = pack.chapter_prompt(
        title="第六章",
        chapter_num=6,
        all_titles=["第一章", "第二章"],
        state=state,
    )
    assert "【当前卷位置】" in text


def test_chapter_prompt_omits_volume_when_state_none():
    """chapter_prompt 不传 state（旧调用点/单测）→ 不注入，向后兼容。"""
    pack = get_prompt_pack("玄幻", "test")
    text = pack.chapter_prompt(
        title="第六章",
        chapter_num=6,
        all_titles=["第一章", "第二章"],
    )
    assert "【当前卷位置】" not in text


def test_chapter_prompt_omits_volume_when_volumes_empty():
    """chapter_prompt 有 state 但 volumes 空 → 不注入。"""
    pack = get_prompt_pack("玄幻", "test")
    state = NovelState(volumes=[], total_chapters_written=5)
    text = pack.chapter_prompt(
        title="第六章",
        chapter_num=6,
        all_titles=["第一章"],
        state=state,
    )
    assert "【当前卷位置】" not in text
