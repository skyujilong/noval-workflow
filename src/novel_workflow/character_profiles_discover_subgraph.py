"""章末「角色档案发现」子图：generate_summary 之后、chapter_edit_subgraph 之前的可跳步骤。

拓扑（复用 make_edit_step_subgraph 工厂，与 scene_beats_subgraph 完全同形）：
  step_entry (interrupt: 是否根据本章正文发现新角色 / 补充档案？) → 跳过 → END
                                                                   → 执行
  step_prepare → step_generate → step_llm_review → step_human_review
                                                    → 通过 → step_save → END
                                                    → 打回 → step_generate（循环）

写回父图的字段只有一个：character_profiles（str，全量覆盖后的合流档案 markdown）。
基础设定 / 本章正文（current_draft 在 save_chapter 后未清空）等只读字段由父图
NovelState 通过 LangGraph 按字段名自动桥接流入子图 state，子图只读不写。

跳过规则：`edit_step_subgraph.step_entry` 已内建 _SKIP_WORDS（空回车 / no / 否 /
skip），本子图无额外 skip 逻辑——首章档案通常在 Phase 1 初版已完备，交给用户在
gate 处自行判断（一空回车即整章跳过，成本可忽略）。
"""

from __future__ import annotations

from dataclasses import dataclass

from noval_workflow.edit_step_subgraph import EditStepSubState, make_edit_step_subgraph
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.nodes.character_profiles_discover import (
    _prepare_character_profiles_discover,
    _save_character_profiles_discover,
)


@dataclass
class CharacterProfilesDiscoverSubState(EditStepSubState):
    """空子类——character_profiles: str 已在 EditStepSubState 父类镜像；此处显式空子类
    仅为与 SceneBeatsSubState 保持对称形态，便于未来扩展（例如加"发现历史"字段）。
    LangGraph 会按字段名自动在父/子图之间桥接映射。
    """
    pass


_ENTRY_HINT = (
    "\n\n---\n"
    "· 直接回车 / 输入 no 或 否 → 跳过（本章无需更新角色档案）\n"
    "· 输入其他内容（例如 yes） → 进入发现流程\n\n"
    "提示：若本章无新角色出场且已知角色未暴露新信息，建议直接跳过；本步骤走一次约需 30 秒生成 + 用户审核。"
)


character_profiles_discover_step = make_edit_step_subgraph(
    entry_prompt="是否根据本章正文发现新角色 / 补充已知角色档案？" + _ENTRY_HINT,
    prepare_fn=_prepare_character_profiles_discover,
    save_fn=_save_character_profiles_discover,
    entry_gate_type=InterruptType.CHARACTER_PROFILES_DISCOVER_ENTRY_GATE,
    direction_type=InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=2,  # 宽松审核 + 每章一次，2 轮控 token
    ask_direction=False,
    enable_prune=False,
    state_cls=CharacterProfilesDiscoverSubState,
)
