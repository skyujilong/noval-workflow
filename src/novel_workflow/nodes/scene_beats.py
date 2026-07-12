"""章级 scene beats 步骤的 prepare/save 闭包。

Scene beats 是章前节拍表：写正文前先出 3–7 个结构化 beat，把打脸四拍/章尾钩/三段式
爽感闭环等 doctrine 从 chapter_prompt 里的「原则文字」上升为 beat 上的 device_tag 硬约束。

数据落地：LLM 输出严格 JSON 数组 → repair_and_parse(kind=list) 修复解析 → 写入
NovelState.current_chapter_beats + beats_chapter_index。解析失败当场抛 JsonParseError
（新字段无历史包袱，不做 legacy 迁移，fail-fast 便于定位 prompt 契约破裂）。

生成后 validate_beats() 做程序化兜底检查（打脸四拍完整性 / 章尾钩位置 / 枚举合法性），
问题只写 warn 日志、不阻断——阻断是审核层的活；本层负责结构落地。
"""

from __future__ import annotations

import logging

from noval_workflow.context import build_chapter_context, build_foundation_context
from noval_workflow.json_utils import JsonParseError, repair_and_parse
from noval_workflow.prompts import scene_beats_prompt, validate_beats

_logger = logging.getLogger(__name__)


def _prepare_scene_beats(state) -> dict:
    """组装本章 scene beats 的生成任务。

    system_context 用完整基础设定（含世界观/力量体系/大纲/人物档案）——scene beats 是
    创作规划类，正确度依赖对世界观和力量体系的准确把握，不排除快照台账（这里不是
    数据维护类，是节奏创作类）。
    """
    return {
        "system_context": build_foundation_context(state),
        "task_prompt": scene_beats_prompt(state, build_chapter_context(state)),
        "review_type": "scene_beats",
    }


def _save_scene_beats(state) -> dict:
    """把审核通过的 beats JSON 落地为结构化 list[dict]，写回父图 state。

    - 解析：repair_and_parse(kind=list)——LLM 输出常带 markdown 围栏/尾逗号/说明文字，
      json_repair 尽量修复，仍失败即抛 JsonParseError（无迁移兜底：新字段无历史包袱，
      fail-fast 让上游 review 或 prompt 契约破裂问题浮现）。
    - 章号锚定：beats_chapter_index = 本章号（total_chapters_written + 1），供下游
      prepare_chapter 严格核对，避免跳过 gate 时误用上一章残留的 beats。
    - 兜底校验：validate_beats 写 warn 日志——LLM 自审偶尔漏检结构性问题，程序化兜底
      让「非法 beats 已注入下游 chapter_prompt」不至于悄悄发生。
    """
    if not state.current_draft:
        _logger.warning("scene_beats current_draft 为空，未写入 current_chapter_beats")
        return {}

    try:
        beats = repair_and_parse(state.current_draft, kind=list)
    except JsonParseError as e:
        # 落地失败即抛：scene_beats 是首次接入，出问题必须立刻暴露，让 prompt 契约或
        # LLM 输出质量的问题浮出水面，而不是静默把脏字符串塞进下游 chapter_prompt。
        _logger.error("scene_beats JSON 解析失败: %s", e)
        raise

    problems = validate_beats(beats)
    if problems:
        # 只警告不阻断——LLM 审核已过、人工审核已批的 beats，程序化再阻断违反「审核层
        # 决定放行 / 打回」的图哲学。改天需要硬阻断可把这里改成 raise。
        _logger.warning("scene_beats 兜底校验发现问题（未阻断）：%s", problems)

    chapter_num = state.total_chapters_written + 1
    _logger.info("scene_beats 落地：第 %d 章共 %d 个 beat", chapter_num, len(beats))
    return {
        "current_chapter_beats": beats,
        "beats_chapter_index": chapter_num,
    }
