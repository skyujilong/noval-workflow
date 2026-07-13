"""Novel Writing Workflow — full graph assembly."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from noval_workflow.nodes.arc import (
    prepare_arc_outline,
    save_arc_outline,
)
from noval_workflow.nodes.chapter import (
    ask_continue,
    generate_summary,
    prepare_chapter,
    prepare_titles,
    route_chapter_or_continue,
    route_continue_or_end,
    save_chapter,
    save_titles,
)
from noval_workflow.nodes.foundation import (
    prepare_character_profiles,
    prepare_core_conflicts,
    prepare_core_theme,
    prepare_initial_status,
    prepare_overall_outline,
    prepare_power_system,
    prepare_world_building,
    route_after_world_building,
    save_character_profiles,
    save_config,
    save_core_conflicts,
    save_core_theme,
    save_initial_status,
    save_overall_outline,
    save_power_system,
    save_world_building,
)
from noval_workflow.nodes.brainstorm import (
    brainstorm_chat,
    brainstorm_extract_review,
    brainstorm_finalize,
    brainstorm_finalize_confirm,
    brainstorm_gate,
    brainstorm_respond,
    route_after_chat,
    route_after_collect,
    route_after_extract_review,
    route_after_finalize_confirm,
    route_after_gate,
)
from noval_workflow.nodes.consistency import (
    audit_consistency,
    consistency_diff_gate,
    consistency_gate,
    revise_consistency,
    route_after_consistency_gate,
    route_after_diff_gate,
    route_after_revise,
)
from noval_workflow.nodes.inputs import collect_user_inputs
from noval_workflow.state import NovelState
from noval_workflow.subgraph import review_subgraph
from noval_workflow.chapter_edit_subgraph import chapter_edit_subgraph
from noval_workflow.scene_beats_subgraph import scene_beats_step
from noval_workflow.character_profiles_discover_subgraph import character_profiles_discover_step

builder = StateGraph(NovelState)

# Phase -1 — 灵感脑爆（可选，入口分叉）
builder.add_node("brainstorm_gate", brainstorm_gate)
builder.add_node("brainstorm_chat", brainstorm_chat)
builder.add_node("brainstorm_respond", brainstorm_respond)
builder.add_node("brainstorm_finalize", brainstorm_finalize)
# v2 保真度改造：finalize 流式生成的完整版 markdown 交给用户在聊天页确认使用 / 返回。
# 该节点用 interrupt 停下，不跑 LLM——只做纯 python 切分或 back_to_chat 剥离。
builder.add_node("brainstorm_finalize_confirm", brainstorm_finalize_confirm)
# 脑爆产物整合 review：一次性 review + 编辑 4 字段，取代原 4 个逐项 confirm。
builder.add_node("brainstorm_extract_review", brainstorm_extract_review)

# Phase 0
builder.add_node("collect_user_inputs", collect_user_inputs)

# Phase 1 — prepare nodes
builder.add_node("prepare_core_theme", prepare_core_theme)
builder.add_node("prepare_world_building", prepare_world_building)
builder.add_node("prepare_power_system", prepare_power_system)
builder.add_node("prepare_core_conflicts", prepare_core_conflicts)
builder.add_node("prepare_overall_outline", prepare_overall_outline)
builder.add_node("prepare_character_profiles", prepare_character_profiles)
builder.add_node("prepare_initial_status", prepare_initial_status)

# Phase 1 — review subgraphs (same compiled subgraph, different node names)
builder.add_node("review_core_theme", review_subgraph)
builder.add_node("review_world_building", review_subgraph)
builder.add_node("review_power_system", review_subgraph)
builder.add_node("review_core_conflicts", review_subgraph)
builder.add_node("review_overall_outline", review_subgraph)
builder.add_node("review_character_profiles", review_subgraph)
builder.add_node("review_initial_status", review_subgraph)

# Phase 1 — save nodes
builder.add_node("save_core_theme", save_core_theme)
builder.add_node("save_world_building", save_world_building)
builder.add_node("save_power_system", save_power_system)
builder.add_node("save_core_conflicts", save_core_conflicts)
builder.add_node("save_overall_outline", save_overall_outline)
builder.add_node("save_character_profiles", save_character_profiles)
builder.add_node("save_initial_status", save_initial_status)
builder.add_node("save_config", save_config)

# Phase 1 → 冻结前的设定一致性总审闸门（脑爆链与常规链在此汇合后统一覆盖）
builder.add_node("audit_consistency", audit_consistency)
builder.add_node("consistency_gate", consistency_gate)
builder.add_node("revise_consistency", revise_consistency)
builder.add_node("consistency_diff_gate", consistency_diff_gate)

# Phase 2.5 — arc outline
builder.add_node("prepare_arc_outline", prepare_arc_outline)
builder.add_node("review_arc_outline", review_subgraph)
builder.add_node("save_arc_outline", save_arc_outline)

# Phase 2 — titles
builder.add_node("prepare_titles", prepare_titles)
builder.add_node("review_titles", review_subgraph)
builder.add_node("save_titles", save_titles)

# Phase 2 — chapter loop
builder.add_node("prepare_chapter", prepare_chapter)
builder.add_node("review_chapter", review_subgraph)
builder.add_node("save_chapter", save_chapter)
builder.add_node("generate_summary", generate_summary)
builder.add_node("ask_continue", ask_continue)

# Phase 2.7 — scene beats（章前节拍表，可跳步骤：save_titles 之后、prepare_chapter 之前）
builder.add_node("scene_beats_step", scene_beats_step)

# Phase 2.8 — 角色档案发现（每章正文完成后自动，可跳步骤：generate_summary 之后、chapter_edit_subgraph 之前）
builder.add_node("character_profiles_discover_step", character_profiles_discover_step)

# Phase 2 — chapter edit subgraph
builder.add_node("chapter_edit_subgraph", chapter_edit_subgraph)

# ── edges ──────────────────────────────────────────────────────────────────────

# Phase -1 — 脑爆入口分叉
builder.set_entry_point("brainstorm_gate")
builder.add_conditional_edges(
    "brainstorm_gate",
    route_after_gate,
    {"brainstorm_chat": "brainstorm_chat", "collect_user_inputs": "collect_user_inputs"},
)
# 聊天循环：chat 等输入 → respond 流式回复 → 自循环回 chat；结束信号 → extract
builder.add_conditional_edges(
    "brainstorm_chat",
    route_after_chat,
    {"brainstorm_respond": "brainstorm_respond", "brainstorm_finalize": "brainstorm_finalize"},
)
builder.add_edge("brainstorm_respond", "brainstorm_chat")
# 结束轮 finalize 节点（可视流式生成完整版 markdown，不再抽 JSON）→ 用户确认闸门 →
# 分支到 extract_review（use，纯 python 切分好的字段已覆写到 state）或回 chat（back_to_chat，
# 完整版历史已被剥掉）
builder.add_edge("brainstorm_finalize", "brainstorm_finalize_confirm")
builder.add_conditional_edges(
    "brainstorm_finalize_confirm",
    route_after_finalize_confirm,
    {"brainstorm_extract_review": "brainstorm_extract_review", "brainstorm_chat": "brainstorm_chat"},
)
builder.add_conditional_edges(
    "brainstorm_extract_review",
    route_after_extract_review,
    {"collect_user_inputs": "collect_user_inputs", "brainstorm_chat": "brainstorm_chat"},
)

# collect 之后条件路由：脑爆来源已在 review 抽屉里确认过 4 字段，直连 prepare_overall_outline
# （整段跳过 Phase 1 主题/世界观/力量体系/核心冲突生成 + 原 4 个 confirm）；否则走原流程。
builder.add_conditional_edges(
    "collect_user_inputs",
    route_after_collect,
    {
        "prepare_overall_outline": "prepare_overall_outline",
        "prepare_core_theme": "prepare_core_theme",
    },
)

# Phase 1 chain
builder.add_edge("prepare_core_theme", "review_core_theme")
builder.add_edge("review_core_theme", "save_core_theme")
builder.add_edge("save_core_theme", "prepare_world_building")

builder.add_edge("prepare_world_building", "review_world_building")
builder.add_edge("review_world_building", "save_world_building")
# 力量体系：依赖世界观、喂给核心冲突/大纲/人物，故插在世界观之后、核心冲突之前。
# 按作品级 state.has_power_system 条件插入：无力量体系时在世界观定稿后直连核心冲突，整步跳过。
# state.has_power_system 由 collect_user_inputs（直接填表路径按题材默认）/
# brainstorm_extract_review（脑爆路径由用户在抽屉里确认）填充。
builder.add_conditional_edges(
    "save_world_building",
    route_after_world_building,
    {
        "prepare_power_system": "prepare_power_system",
        "prepare_core_conflicts": "prepare_core_conflicts",
    },
)
builder.add_edge("prepare_power_system", "review_power_system")
builder.add_edge("review_power_system", "save_power_system")
builder.add_edge("save_power_system", "prepare_core_conflicts")

builder.add_edge("prepare_core_conflicts", "review_core_conflicts")
builder.add_edge("review_core_conflicts", "save_core_conflicts")
builder.add_edge("save_core_conflicts", "prepare_overall_outline")

builder.add_edge("prepare_overall_outline", "review_overall_outline")
builder.add_edge("review_overall_outline", "save_overall_outline")
builder.add_edge("save_overall_outline", "prepare_character_profiles")

builder.add_edge("prepare_character_profiles", "review_character_profiles")
builder.add_edge("review_character_profiles", "save_character_profiles")

# 人物初始基线（第0章）：从已定稿人物档案 + 世界观固化基线，写入 phase_summary
builder.add_edge("save_character_profiles", "prepare_initial_status")
builder.add_edge("prepare_initial_status", "review_initial_status")
builder.add_edge("review_initial_status", "save_initial_status")

# Phase 1 → 设定一致性总审 → save config → Phase 2.5: arc outline first
# 脑爆链在 prepare_overall_outline 汇回常规链，两路都流经 save_initial_status，
# 故闸门插在其后、save_config 前 → 双路径统一覆盖。
builder.add_edge("save_initial_status", "audit_consistency")
builder.add_edge("audit_consistency", "consistency_gate")
builder.add_conditional_edges(
    "consistency_gate",
    route_after_consistency_gate,
    {
        "audit_consistency": "audit_consistency",
        "revise_consistency": "revise_consistency",
        "save_config": "save_config",
    },
)
# 让 AI 修订：revise 产提案 → 有则进 diff 审核闸门，无则折返回闸门；diff 应用 → 复审一轮，放弃 → 折返。
builder.add_conditional_edges(
    "revise_consistency",
    route_after_revise,
    {"consistency_diff_gate": "consistency_diff_gate", "consistency_gate": "consistency_gate"},
)
builder.add_conditional_edges(
    "consistency_diff_gate",
    route_after_diff_gate,
    {"audit_consistency": "audit_consistency", "consistency_gate": "consistency_gate"},
)
builder.add_edge("save_config", "prepare_arc_outline")

# Phase 2.5 — arc outline chain
builder.add_edge("prepare_arc_outline", "review_arc_outline")
builder.add_edge("review_arc_outline", "save_arc_outline")
builder.add_edge("save_arc_outline", "prepare_titles")

# Phase 2 — titles chain
builder.add_edge("prepare_titles", "review_titles")
builder.add_edge("review_titles", "save_titles")
# save_titles → scene_beats_step（可跳步骤：用户可跳过直接进 prepare_chapter）→ prepare_chapter
# 章循环回跳（route_chapter_or_continue）也会回到 scene_beats_step，让每章都进 gate。
builder.add_edge("save_titles", "scene_beats_step")
builder.add_edge("scene_beats_step", "prepare_chapter")

# Phase 2 — chapter loop
builder.add_edge("prepare_chapter", "review_chapter")
builder.add_edge("review_chapter", "save_chapter")
builder.add_edge("save_chapter", "generate_summary")
builder.add_edge("generate_summary", "character_profiles_discover_step")
builder.add_edge("character_profiles_discover_step", "chapter_edit_subgraph")

# chapter_edit_subgraph → chapter or batch end
builder.add_conditional_edges(
    "chapter_edit_subgraph",
    route_chapter_or_continue,
    {"scene_beats_step": "scene_beats_step", "ask_continue": "ask_continue"},
)

builder.add_conditional_edges(
    "ask_continue",
    route_continue_or_end,
    {"prepare_arc_outline": "prepare_arc_outline", END: END},
)

graph = builder.compile(name="Novel Writing Workflow")
