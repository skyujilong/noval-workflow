"""图装配 + prompt 注入集成测试（滚动生成卷架构）。

验证：
1. 分卷节点 (prepare_volumes/review_volumes/save_volumes) 在图上；闸门 volume_boundary_gate 已删
2. save_overall_outline → prepare_volumes → review → save 链路 + save_volumes 后二分（首次/滚动）
3. save_config 直连 prepare_chapter_plan（首卷展开）；ask_continue 可路由到 prepare_volumes（滚动新卷）
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
    """分卷 3 个节点必须挂进图；闸门 volume_boundary_gate 已删。"""
    nodes = set(graph.get_graph().nodes)
    assert "prepare_volumes" in nodes
    assert "review_volumes" in nodes
    assert "save_volumes" in nodes
    assert "volume_boundary_gate" not in nodes


def test_graph_wires_volumes_chain_after_overall_outline():
    """save_overall_outline 之后的下一站是 prepare_volumes；save_volumes 后二分（首次/滚动）。"""
    edges = graph.get_graph().edges
    downstream = {(e.source, e.target) for e in edges}
    assert ("save_overall_outline", "prepare_volumes") in downstream
    assert ("prepare_volumes", "review_volumes") in downstream
    assert ("review_volumes", "save_volumes") in downstream
    # save_volumes 现为条件路由：首次→人物卡；滚动→先生成本卷花名册 prepare_volume_cast
    assert ("save_volumes", "prepare_character_cards") in downstream
    assert ("save_volumes", "prepare_volume_cast") in downstream
    # 滚动分支不再直连 chapter_plan（改经花名册三元组）
    assert ("save_volumes", "prepare_chapter_plan") not in downstream
    # 原直连边应已断
    assert ("save_overall_outline", "prepare_character_cards") not in downstream


def test_graph_wires_volume_cast_triple_before_chapter_plan():
    """花名册三元组：save_config / 滚动新卷都先过 prepare_volume_cast → review → save → chapter_plan。"""
    edges = graph.get_graph().edges
    downstream = {(e.source, e.target) for e in edges}
    # 开书路径：设定链末尾 save_config 汇入花名册（不再直连 chapter_plan）
    assert ("save_config", "prepare_volume_cast") in downstream
    assert ("save_config", "prepare_chapter_plan") not in downstream
    # 三元组内部接线 + 收口到 chapter_plan
    assert ("prepare_volume_cast", "review_volume_cast") in downstream
    assert ("review_volume_cast", "save_volume_cast") in downstream
    assert ("save_volume_cast", "prepare_chapter_plan") in downstream
    # 三个节点在图上
    nodes = set(graph.get_graph().nodes)
    assert {"prepare_volume_cast", "review_volume_cast", "save_volume_cast"} <= nodes


def test_graph_ask_continue_routes_to_prepare_volumes():
    """ask_continue 三分路由含 prepare_volumes（滚动新卷）与 prepare_arc_outline（直接下一批）。"""
    edges = graph.get_graph().edges
    downstream = {(e.source, e.target) for e in edges}
    assert ("ask_continue", "prepare_volumes") in downstream
    assert ("ask_continue", "prepare_arc_outline") in downstream
    # 闸门去除后不再有 ask_continue → volume_boundary_gate
    assert ("ask_continue", "volume_boundary_gate") not in downstream


# ── prompt 注入 ─────────────────────────────────────────────────────────────


def _sample_volumes() -> list[Volume]:
    return [
        Volume(index=1, title="卷1", chapter_start=1, planned_end=28,
               summary="卷1主线", setup_for_next="埋钩", status="in_progress"),
        Volume(index=2, title="卷2", chapter_start=29, planned_end=73,
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
