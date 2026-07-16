"""章级 scene beats 子图：save_titles 之后、prepare_chapter 之前的可跳步骤。

拓扑（复用 make_edit_step_subgraph 工厂）：
  step_entry (interrupt: 是否为本章生成 beats？) → 跳过 → END
                                                → 执行
  step_prepare → step_generate → step_llm_review → step_human_review
                                                    → 通过 → step_save → END
                                                    → 打回 → step_generate（循环）

写回父图的字段只有两个：current_chapter_beats（list[dict]） + beats_chapter_index（int）。
其余字段（基础设定/章循环上下文）由父图 NovelState 通过 langgraph 自动映射流入子图 state，
子图只读不写。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from noval_workflow.edit_step_subgraph import EditStepSubState, make_edit_step_subgraph
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.nodes.scene_beats import _prepare_scene_beats, _save_scene_beats


@dataclass
class SceneBeatsSubState(EditStepSubState):
    """继承 EditStepSubState（已含所有 _ContextState Protocol 需要的字段），
    额外加两个写回父图的字段——LangGraph 按字段名自动在父/子图之间桥接映射。

    ⚠️ chapter_edit_subgraph.ChapterEditSubState 目前不含这两个字段——本子图先于
    chapter_edit_subgraph 执行，只写、不消费，所以它们不需要在 ChapterEditSubState
    出现。真正消费点是父图 NovelState.prepare_chapter，它继承 NovelState 已含。
    """
    # scene_beats 步骤写回：本章 beats JSON（list[dict]）
    current_chapter_beats: list = field(default_factory=list)
    # 本 beats 是为哪一章生成的（1-based 全书章号）；供 prepare_chapter 严格核对
    beats_chapter_index: int = -1


_ENTRY_HINT = "\n\n---\n· 直接回车 / 输入 no 或 否 → 跳过（本章直接按章纲写正文，无 beat 结构约束）\n· 输入其他内容 → 生成 scene beats"


scene_beats_step = make_edit_step_subgraph(
    entry_prompt="是否为本章生成 scene beats（章内节拍表）？" + _ENTRY_HINT,
    prepare_fn=_prepare_scene_beats,
    save_fn=_save_scene_beats,
    entry_gate_type=InterruptType.SCENE_BEATS_ENTRY_GATE,
    direction_type=InterruptType.SCENE_BEATS_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=3,
    ask_direction=False,  # 首版不做方向输入，用户反馈需要再加
    state_cls=SceneBeatsSubState,  # 必须传：子图 save_fn 写 current_chapter_beats/beats_chapter_index，需在 schema 里
)
