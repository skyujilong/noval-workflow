"""Chapter-edit subgraph: 4-step serial chain after chapter generation.

Topology (zero conditional branches at this level):
  arc_step → foreshadow_step → phase_step → entity_discover_step
  → chapter_edit_done → END

人物动态（处境/动机/关系）已并入 CharacterCard，由 entity_discover_step 单腿覆盖更新——
原 status_step / relations_step 两条散文快照腿已删。

Each *_step is a pre-compiled subgraph that internally asks the user
"是否执行？" before doing anything. The user can skip any step by answering
"否" / "no" / pressing Enter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langgraph.graph import END, StateGraph

from noval_workflow.arc_edit_subgraph import make_arc_edit_subgraph
from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.edit_step_subgraph import make_edit_step_subgraph
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.nodes.chapter_edit import chapter_edit_done
from noval_workflow.nodes.entity_cards import _prepare_entity_discover, _save_entity_discover
from noval_workflow.prompts import (
    foreshadowing_prompt,
    phase_summary_prompt,
)

_logger = logging.getLogger(__name__)

# ── ChapterEditSubState ────────────────────────────────────────────────────────

@dataclass
class ChapterEditSubState:
    """Bridge state between the parent NovelState and the 5 edit-step subgraphs.

    Fields are a union of all fields consumed by the subgraphs.
    Removed: do_arc, tracking_fields, edit_tracking_cursor, pending_steps,
             active_tracking_field (all menu/dispatcher artefacts).
    """

    # ── Phase 0 基础输入 ────────────────────────────────────────────────────────
    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""

    # ── Phase 1 成果 ────────────────────────────────────────────────────────────
    core_theme: str = ""
    world_building: str = ""
    # 力量体系为作品级 state，_ContextState Protocol 要求子图必须镜像它——否则
    # _prepare_foreshadowing/phase 里的 build_foundation_context 会 AttributeError。
    has_power_system: bool = False
    power_system: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""

    # ── Phase 2 章节追踪（只读）─────────────────────────────────────────────────
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)

    # ── Phase 2.5 弧线（读入 + 写回）──────────────────────────────────────────
    current_arc_outline: str = ""

    # ── Phase 2.5 动态状态库（读入最新值 + 覆盖写回）─────────────────────────
    # 人物动态（处境/动机/关系）已并入 entity_cards，原 character_status/relations 桥接字段已删。
    foreshadowing: dict = field(default_factory=dict)
    phase_summary: str = ""
    # 统一实体卡库：章末 entity_discover_step 读入 + 写回（补新卡 / 更新动态字段）。
    entity_cards: list = field(default_factory=list)

    # ── review_subgraph 桥接字段 ────────────────────────────────────────────────
    system_context: str = ""
    task_prompt: str = ""
    current_draft: str = ""
    review_feedback: str = ""
    approved: bool = False
    review_type: str = "foundation"  # 初始哨兵值；各 prepare 步骤必覆盖为已登记 review 类型
    review_history: list = field(default_factory=list)
    llm_review_count: int = 0
    llm_review_max: int = 3

    # ── 弧线子图私有中间状态（保留，由 arc_edit_subgraph 读写）─────────────────
    arc_direction: str = ""
    ai_arc: str = ""
    arc_error: str = ""
    final_arc: str = ""
    arc_needs_rewrite: bool = False
    ai_titles: list[str] = field(default_factory=list)
    titles_direction: str = ""
    titles_needs_regen: bool = False


# ── prepare / save closures for the tracking steps ───────────────────────────

def _prepare_foreshadowing(state) -> dict:
    return {
        "system_context": build_foundation_context(state, exclude_snapshots=True, include_identity=False),
        "task_prompt": foreshadowing_prompt(state, build_chapter_context(state)),
        "review_type": "foreshadowing",
    }


def _save_foreshadowing(state) -> dict:
    """保存 LLM 输出的伏笔台账（结构化 JSON）。无 compat——解析失败即 fail-loud 触发重生成。"""
    if not state.current_draft:
        return {}

    # 先修复再解析：LLM 生成的台账常带围栏 / 尾逗号 / 截断等脏输出；仍失败即抛，交审核循环重生成
    try:
        foreshadowing = repair_and_parse(state.current_draft.strip(), kind=dict)
    except JsonParseError as exc:
        raise ValueError(f"伏笔台账 JSON 解析失败: {exc}") from exc
    return {"foreshadowing": foreshadowing}


def _prepare_phase(state) -> dict:
    return {
        "system_context": build_foundation_context(state, exclude_snapshots=True, include_identity=False),
        "task_prompt": phase_summary_prompt(state, build_chapter_context(state)),
        "review_type": "phase_summary",
    }


def _save_phase(state) -> dict:
    return {"phase_summary": state.current_draft} if state.current_draft else {}


# ── Pre-compile the 5 step subgraphs ──────────────────────────────────────────

_ENTRY_HINT = "\n\n---\n· 直接回车 / 输入 no 或 否 → 跳过\n· 输入其他内容 → 执行"

_ARC_STEP = make_arc_edit_subgraph(
    entry_prompt="是否调整弧线大纲？",
)

_FORESHADOW_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新伏笔台账？" + _ENTRY_HINT,
    prepare_fn=_prepare_foreshadowing,
    save_fn=_save_foreshadowing,
    entry_gate_type=InterruptType.FORESHADOWING_ENTRY_GATE,
    direction_type=InterruptType.FORESHADOWING_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=3,
    enable_prune=True,
)

_PHASE_STEP = make_edit_step_subgraph(
    entry_prompt="是否更新阶段固化数据？" + _ENTRY_HINT,
    prepare_fn=_prepare_phase,
    save_fn=_save_phase,
    entry_gate_type=InterruptType.PHASE_SUMMARY_ENTRY_GATE,
    direction_type=InterruptType.PHASE_SUMMARY_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=3,
)

# 章末实体发现 + 动态更新：读本章正文补新卡 + 更新已有卡装备状态/人物动机。
# 默认 state_cls=EditStepSubState（已含 entity_cards 桥接字段，可读入 + 写回）。
_ENTITY_DISCOVER_STEP = make_edit_step_subgraph(
    entry_prompt="是否发现本章新实体 / 更新实体卡库（装备状态、人物动机）？" + _ENTRY_HINT,
    prepare_fn=_prepare_entity_discover,
    save_fn=_save_entity_discover,
    entry_gate_type=InterruptType.ENTITY_DISCOVER_ENTRY_GATE,
    direction_type=InterruptType.ENTITY_DISCOVER_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=3,
)


# ── Top-level chapter_edit_subgraph: 5 nodes, 0 conditional branches ──────────

_builder = StateGraph(ChapterEditSubState)

_builder.add_node("arc_step", _ARC_STEP)
_builder.add_node("foreshadow_step", _FORESHADOW_STEP)
_builder.add_node("phase_step", _PHASE_STEP)
_builder.add_node("entity_discover_step", _ENTITY_DISCOVER_STEP)
_builder.add_node("chapter_edit_done", chapter_edit_done)

_builder.set_entry_point("arc_step")

_builder.add_edge("arc_step", "foreshadow_step")
_builder.add_edge("foreshadow_step", "phase_step")
_builder.add_edge("phase_step", "entity_discover_step")
_builder.add_edge("entity_discover_step", "chapter_edit_done")
_builder.add_edge("chapter_edit_done", END)

chapter_edit_subgraph = _builder.compile()
