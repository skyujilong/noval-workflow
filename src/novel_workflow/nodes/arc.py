"""Phase 2.5: Mini arc outline nodes."""

from __future__ import annotations

from noval_workflow.context import build_foundation_context
from noval_workflow.prompts import get_prompt_pack
from noval_workflow.prompts.render import SystemRole, build_prepare_fields
from noval_workflow.state import NovelState, reset_review_fields


# ── arc outline ───────────────────────────────────────────────────────────────


def prepare_arc_outline(state: NovelState) -> dict:
    """规划本批 BATCH_SIZE 章的故事弧线大纲。

    L2 用 deep_character_view=True：规划类节点需看到人物卡的隐藏人设/底牌契约/全书成长
    天花板，以正确安排战力跃迁节奏（P2 修复点：原为默认 False，规划依据不足）。
    evolved_directives_arc_outline 桶在 arc_outline_prompt 末尾，由 prompt 方法注入，不动。
    """
    pack = get_prompt_pack(state.genre, state.novel_name)
    return {
        **build_prepare_fields(
            role=SystemRole.GENRE_AUTHOR,
            genre_identity=pack.flavor.system_identity,
            task_contract="为本批接下来的章节规划故事弧线大纲",
            context=build_foundation_context(
                state, include_identity=False, deep_character_view=True
            ),
            task=pack.arc_outline_prompt(state),
        ),
        "review_type": "arc_outline",
        **reset_review_fields(),
    }


def save_arc_outline(state: NovelState) -> dict:
    return {
        "current_arc_outline": state.current_draft,
    }
