"""章前「登场实体卡（EntityCard）」子图：scene_beats 之后、prepare_chapter 之前的可跳步骤。

拓扑（复用 make_edit_step_subgraph 工厂，与 scene_beats_subgraph 同形）：
  step_entry (interrupt: 是否为本章登场实体建卡？) → 跳过 → END
                                                    → 执行
  step_prepare → step_generate → step_llm_review → step_human_review
                                                    → 通过 → step_save → END
                                                    → 打回 → step_generate（循环）

读父图字段：current_chapter_beats / beats_chapter_index（本章节拍表，登场实体主要依据）+
entity_cards（已有卡库，判新旧 + 去重）+ 章循环上下文（由 EditStepSubState 镜像）。
写回父图字段：entity_cards（去重 merge 后卡库）+ current_chapter_cast + cast_chapter_index。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from noval_workflow.edit_step_subgraph import EditStepSubState, make_edit_step_subgraph
from noval_workflow.interrupt_types import InterruptType
from noval_workflow.nodes.entity_cards import _prepare_entity_cards, _save_entity_cards


@dataclass
class EntityCardsSubState(EditStepSubState):
    """继承 EditStepSubState（已含基础设定 + 章循环上下文），额外声明本步骤要读/写的字段。

    LangGraph 按字段名自动在父/子图之间桥接映射：只读字段（beats/卡库）由父图流入，
    写回字段（卡库/登场名单/章号锚）由 save_fn 返回后流回父图 NovelState。
    """
    # 读：本章已定稿 beats（登场实体主要依据）+ 章号锚（严格核对，防跳 gate 残留串章）
    current_chapter_beats: list = field(default_factory=list)
    beats_chapter_index: int = -1
    # 读：分卷 + 本卷花名册——entity_cards_prompt 头部注入【本卷花名册】（volume_cast_card 读
    # volumes/volume_cast/volume_cast_index），让本章建卡依据卷级登场规划、减少临场乱造新重要角色。
    # 只读桥接，不写回 parent。
    volumes: list = field(default_factory=list)
    volume_cast: dict = field(default_factory=dict)
    volume_cast_index: int = -1
    # 读 + 写：全书实体卡库（save 端去重 merge 后写回）
    entity_cards: list = field(default_factory=list)
    # 写：本章登场实体名单 + 章号锚（供 prepare_chapter 触发式注入）
    current_chapter_cast: list = field(default_factory=list)
    cast_chapter_index: int = -1


_ENTRY_HINT = (
    "\n\n---\n"
    "· 直接回车 / 输入 no 或 否 → 跳过（本章不建实体卡，正文按已有档案/台账写）\n"
    "· 输入其他内容 → 识别本章登场实体并为新实体建卡"
)


entity_cards_step = make_edit_step_subgraph(
    entry_prompt="是否为本章登场实体建结构化属性卡（识别新人物/物品/装备，防写飘）？" + _ENTRY_HINT,
    prepare_fn=_prepare_entity_cards,
    save_fn=_save_entity_cards,
    entry_gate_type=InterruptType.ENTITY_CARDS_ENTRY_GATE,
    direction_type=InterruptType.ENTITY_CARDS_DIRECTION_INPUT,
    enable_llm_review=True,
    llm_review_max=3,
    ask_direction=False,  # 首版不做方向输入，与 scene_beats 一致
    state_cls=EntityCardsSubState,  # 必须传：save_fn 写 entity_cards/current_chapter_cast/cast_chapter_index，需在 schema 里
)
