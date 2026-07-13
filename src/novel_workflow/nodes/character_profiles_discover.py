"""章末「角色档案发现」步骤的 prepare/save 闭包。

Character profiles discover 是每章正文完成后自动插入的一个后置节点：
LLM 读本章正文 + 已有 character_profiles → 输出**合流后的完整档案 markdown** →
自审 → 人工审核 → 覆盖写回 state.character_profiles，让本章新登场角色与
新暴露信息在下一章的 build_foundation_context 里可见。

字段落地：LLM 全量输出档案 markdown（不是章节正文，也不是 delta），save 端直接
用 state.current_draft 覆盖 state.character_profiles——不做 delta 合流算法（str
字段无结构 anchor，代码合流更脆）；用户审到什么就是落地什么，避免"审核 draft ≠
写回内容"。

不做章号锚定字段：discover 每章独立、覆盖写即幂等，与 scene_beats 的
beats_chapter_index 场景不同（scene_beats 需要防跳 gate 时残留串到下一章）。
"""

from __future__ import annotations

import logging

from noval_workflow.context import build_foundation_context
from noval_workflow.prompts import character_profiles_discover_prompt

_logger = logging.getLogger(__name__)


def _prepare_character_profiles_discover(state) -> dict:
    """组装本章角色档案发现的生成任务。

    system_context 用完整基础设定（含世界观/力量体系/大纲/已有人物档案）——
    LLM 需据世界观 / 力量体系判断新角色定位是否合理；task_prompt 用 discover
    组装函数（读 current_draft 本章正文 + character_profiles 已有档案 +
    total_chapters_written 本章号，均在 save_chapter 之后未被清空）。
    """
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": character_profiles_discover_prompt(state),
        "review_type": "character_profiles_discover",
    }


def _save_character_profiles_discover(state) -> dict:
    """把 LLM 全量输出的合流后档案 markdown 直接覆盖写回父图 character_profiles。

    - 无 delta 合并：LLM 每次都吐完整档案，用户审到什么落地什么，避免"审核 draft
      与实际写回不一致"的心智负担。
    - 空 draft 兜底：若 current_draft 为空（异常路径或用户跳出），warn 并**不写回**——
      character_profiles 保持原样，避免用空串清空 Phase 1 初版档案。
    """
    if not state.current_draft:
        _logger.warning("character_profiles_discover current_draft 为空，未写入 character_profiles")
        return {}

    _logger.info(
        "character_profiles_discover 落地：第 %d 章，档案长度 %d 字符",
        state.total_chapters_written,
        len(state.current_draft),
    )
    return {"character_profiles": state.current_draft}
