"""Factory for generic chapter-edit step subgraphs.

Each step follows the pattern:
  step_entry (interrupt: "是否执行？")
    ↓ skip → END
    ↓ yes
  [step_direction (interrupt)] ← optional, when ask_direction=True
    ↓
  step_prepare → step_generate
    ↓
  [step_llm_review] ← optional, when enable_llm_review=True
    ↓ pass / max reached
  step_human_review (interrupt)
    ↓ approved → [post_review_subgraph?] → step_save → END
    ↓ not approved → step_generate (loop)

post_review_subgraph（可选）：人工审核通过后、save 之前插入的一段后处理子图。
入口任意、出口 END，工厂把它接在 step_human_review 与 step_save 之间。伏笔精简
（foreshadow_prune_subgraph）就是一个这样的后处理——通用工厂不再认识任何业务。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.interrupt_types import InterruptType
from noval_workflow.state import ReviewSubState, reset_review_fields
from noval_workflow.subgraph import (
    generate,
    llm_self_review,
    human_review,
    route_after_llm_review,
    route_after_human,
)

# Shared with chapter_plan_edit_subgraph — imported there to avoid divergence.
_SKIP_WORDS = {"skip", "跳过", "", "s", "no", "n", "否", "不", "none", "null"}


@dataclass
class EditStepSubState(ReviewSubState):
    """State for a single edit step subgraph.

    Inherits all ReviewSubState fields. Additional fields carry parent-graph
    context needed by prepare_fn / save_fn.
    """

    novel_name: str = ""
    genre: str = ""
    writing_style: str = ""
    target_audience: str = ""
    core_tone: str = ""
    chapter_word_count: str = ""
    total_word_count: str = ""
    core_theme: str = ""
    world_building: str = ""
    # 力量体系为作品级 state，_ContextState Protocol 要求子图必须镜像它——否则
    # prepare_fn 里的 build_foundation_context 会 AttributeError。
    has_power_system: bool = False
    power_system: str = ""
    core_conflicts: str = ""
    overall_outline: str = ""
    current_batch_titles: list[str] = field(default_factory=list)
    current_chapter_index: int = 0
    total_chapters_written: int = 0
    all_chapter_titles: list[str] = field(default_factory=list)
    all_chapter_summaries: list[str] = field(default_factory=list)
    current_arc_outline: str = ""
    foreshadowing: dict = field(default_factory=dict)
    phase_summary: str = ""
    # 统一实体卡库——桥接父图 NovelState.entity_cards：章末 entity_discover 读入 + 写回，
    # 其余台账步骤只读（build_foundation_context 渲染装备真源用）。
    entity_cards: list = field(default_factory=list)
    review_history: list = field(default_factory=list)

    # Step gate fields (not written back to parent graph)
    step_execute_gate: bool = False
    step_direction_input: str = ""


def make_edit_step_subgraph(
    *,
    entry_prompt: str,
    prepare_fn: Callable,
    save_fn: Callable,
    entry_gate_type: InterruptType,
    direction_type: InterruptType,
    enable_llm_review: bool = True,
    llm_review_max: int = 3,
    ask_direction: bool = False,
    post_review_subgraph=None,  # 审核通过后、save 前插入的可选后处理子图（入口任意、出口 END）
    state_cls: type = EditStepSubState,  # 允许子图携带额外写回字段（如 scene_beats 的 current_chapter_beats）
):
    """Build and compile a single chapter-edit step subgraph.

    Args:
        entry_prompt:      Text shown in the entry interrupt ("是否执行本步骤？")
        prepare_fn:        Receives state; returns dict with system_prompt(L1),
                           context_prompt(L2), task_prompt(L3), review_type (and any other overrides).
        save_fn:           Receives state; writes current_draft back to the
                           appropriate history field; returns a dict.
        entry_gate_type:   step_entry 中断的权威 type（复用节点由调用方传入身份，
                           对应 InterruptType.*_ENTRY_GATE）。
        direction_type:    step_direction 中断的权威 type（对应 *_DIRECTION_INPUT）。
        enable_llm_review: Whether to run LLM self-review after generation.
        llm_review_max:    Max LLM review rounds before forcing human review.
        ask_direction:     If True, interrupt after entry to collect a direction
                           string before calling prepare_fn.
        post_review_subgraph: 可选后处理子图，接在 step_human_review 通过后、step_save 前。
                           它的出口用 END，工厂负责把 END 兜到 step_save。子图与本图按同名
                           字段桥接：若子图读写额外字段（如伏笔精简的 foreshadow_prune_*），
                           **必须配套把 state_cls 设成同时声明这些字段的子类**（如
                           ForeshadowSubState），否则字段不在 schema 里、更新被 langgraph 丢弃。
        state_cls:         Sub-state dataclass used by this compiled subgraph. Defaults
                           to EditStepSubState. Provide a subclass when save_fn or
                           post_review_subgraph writes fields not present in EditStepSubState
                           (e.g. scene_beats writes current_chapter_beats & beats_chapter_index)—
                           those fields must exist in the compiled StateGraph schema, otherwise
                           langgraph drops them on update.
    """

    # ── node closures ──────────────────────────────────────────────────────────
    # ⚠️ 这些闭包**不能**把 state 注解成基类 EditStepSubState：LangGraph 会按节点函数第一个
    # 参数的类型注解**窄化**传入的 state，注解写基类就只会构造出含基类字段的实例，丢掉 state_cls
    # 子类才声明的字段（如 EntityCardsSubState.current_chapter_beats）。于是 prepare_fn/save_fn 读
    # 子类字段时报 AttributeError（"'EditStepSubState' object has no attribute 'current_chapter_beats'"）。
    # 不写注解 → LangGraph 回退到编译时的图 schema（state_cls），传入完整子类实例。

    def step_entry(state) -> dict:
        answer = interrupt({"type": entry_gate_type.value, "message": entry_prompt})
        # 直接处理 None/falsy 值，避免 str(None) = "None" 的问题
        if not answer:
            execute = False
        else:
            execute = str(answer).strip().lower() not in _SKIP_WORDS
        return {"step_execute_gate": execute, "step_direction_input": ""}

    def step_direction(state) -> dict:
        direction = interrupt(
            {
                "type": direction_type.value,
                "message": "请输入调整方向（直接回车使用默认提示词）：",
            }
        )
        # 处理 None，避免 str(None) = "None"
        return {"step_direction_input": str(direction or "").strip()}

    def step_prepare(state) -> dict:
        result = prepare_fn(state)
        return {**reset_review_fields(), **result, "llm_review_max": llm_review_max}

    def step_save(state) -> dict:
        return save_fn(state)

    # ── routing ────────────────────────────────────────────────────────────────

    def route_after_entry(state) -> str:
        if not state.step_execute_gate:
            return END
        return "step_direction" if ask_direction else "step_prepare"

    # ── graph assembly ─────────────────────────────────────────────────────────

    builder = StateGraph(state_cls)

    builder.add_node("step_entry", step_entry)
    if ask_direction:
        builder.add_node("step_direction", step_direction)
    builder.add_node("step_prepare", step_prepare)
    builder.add_node("step_generate", generate)
    if enable_llm_review:
        builder.add_node("step_llm_review", llm_self_review)
    builder.add_node("step_human_review", human_review)
    builder.add_node("step_save", step_save)

    # 审核通过后的后处理子图（可选），出口 END 由下方接线兜到 step_save
    if post_review_subgraph is not None:
        builder.add_node("post_review", post_review_subgraph)

    builder.set_entry_point("step_entry")

    # entry → skip (END) or continue
    if ask_direction:
        builder.add_conditional_edges(
            "step_entry",
            route_after_entry,
            {END: END, "step_direction": "step_direction"},
        )
        builder.add_edge("step_direction", "step_prepare")
    else:
        builder.add_conditional_edges(
            "step_entry", route_after_entry, {END: END, "step_prepare": "step_prepare"}
        )

    builder.add_edge("step_prepare", "step_generate")

    if enable_llm_review:
        builder.add_edge("step_generate", "step_llm_review")
        builder.add_conditional_edges(
            "step_llm_review",
            route_after_llm_review,
            {"generate": "step_generate", "human_review": "step_human_review"},
        )
    else:
        builder.add_edge("step_generate", "step_human_review")

    # human review 之后：通过则进入后处理子图（如果挂了）或直接保存，不通过则回 generate 重生成
    if post_review_subgraph is not None:
        builder.add_conditional_edges(
            "step_human_review",
            route_after_human,
            {END: "post_review", "generate": "step_generate"},  # 通过(END) → 后处理
        )
        builder.add_edge("post_review", "step_save")
    else:
        builder.add_conditional_edges(
            "step_human_review",
            route_after_human,
            {END: "step_save", "generate": "step_generate"},
        )

    builder.add_edge("step_save", END)

    return builder.compile()
