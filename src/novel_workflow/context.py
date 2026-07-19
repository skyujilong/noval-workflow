"""Build context strings from accumulated NovelState fields."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Protocol

from noval_workflow.config import FULL_COUNT, SUMMARY_COUNT
from noval_workflow.prompts import (
    _format_foreshadowing_for_context,
    format_character_profiles_from_cards,
    format_equipment_for_context,
    get_prompt_pack,
)


class _ContextState(Protocol):
    """Structural type for states accepted by build_*_context functions.

    Both NovelState and ChapterEditSubState satisfy this protocol —
    no explicit import of either class is needed.
    """
    # Phase 0 — user inputs
    novel_name: str
    genre: str
    writing_style: str
    target_audience: str
    core_tone: str
    chapter_word_count: str
    total_word_count: str
    # Phase 1 — foundation results
    core_theme: str
    world_building: str
    power_system: str
    core_conflicts: str
    overall_outline: str
    # Phase 2.5 — dynamic tracking
    # 人物动态（处境/动机/关系）已并入 entity_cards 的 CharacterCard，原 character_profiles/
    # character_status/character_relations 三字段已删。
    current_arc_outline: str
    foreshadowing: dict  # 结构化台账 {"pending": [...], "collected": [...]}
    phase_summary: str
    entity_cards: list  # 统一实体卡库：人物档案 + 装备/物品真源（势力/地点）
    # Phase 2 — chapter progress
    total_chapters_written: int
    all_chapter_titles: list[str]
    all_chapter_summaries: list[str]

_logger = logging.getLogger(__name__)


# ── shared file-path utilities ─────────────────────────────────────────────────

def get_output_dir(novel_name: str = "") -> Path:
    """Return the output directory for the current novel.

    Structure: <NOVEL_OUTPUT_DIR>/<safe_novel_name>/
    Falls back to <NOVEL_OUTPUT_DIR>/ when novel_name is empty.
    """
    base = Path(os.environ.get("NOVEL_OUTPUT_DIR", "./output"))
    if novel_name:
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', novel_name).strip('_')
        return base / safe_name
    return base


def chapter_filename(chapter_num: int, title: str) -> str:
    """Return the canonical filename stem for a chapter or summary file.

    Example: chapter_filename(3, "烽火连天") -> "chapter_003_烽火连天.txt"
    Both chapters/ and summaries/ use identical filenames under their respective dirs.
    """
    safe_title = re.sub(r'[^\w\u4e00-\u9fff]', '_', title)
    return f"chapter_{chapter_num:03d}_{safe_title}.txt"


# ── foundation context ─────────────────────────────────────────────────────────

def build_foundation_context(
    state: _ContextState,
    *,
    exclude_snapshots: bool = False,
    include_identity: bool = True,
    deep_character_view: bool = False,
) -> str:
    """Serialize approved foundation fields into a structured system prompt string.

    Only includes non-empty fields, so the context grows as Phase 1 progresses.

    Args:
        exclude_snapshots: When True, omit the dynamic snapshot fields
            (foreshadowing/phase_summary). Use this for the tracking-update prepare
            steps where the previous snapshot is already injected into task_prompt
            via {prev}, so including it here would only dilute the reviewer's attention.
        include_identity: When True (default), prepend the genre-specific creative
            writer identity ("你是一位资深…作家") before the settings block. Snapshot
            台账 steps (foreshadowing/phase_summary) pass False so they get a bare
            settings block, then splice on their own "数据维护员/审核员" identity in
            generate()/llm_self_review() — keeping the strict data-maintenance framing
            while still injecting full settings.
        deep_character_view: 人物档案渲染深度。False（默认，写正文/常规 context）注入操作
            视图（role/外貌/口吻/性格/能力/动机/处境/关系）；True（outline/arc/consistency
            规划）追加深层视图（隐藏人设/全书弧光/底牌契约），供战力基线/长线设计校验。
    """
    parts: list[str] = []

    # 系统身份前缀按题材加载（提示词包不入 state，仅按 state.genre 取用）
    if include_identity:
        pack = get_prompt_pack(state.genre, state.novel_name)
        parts.append(f"{pack.flavor.system_identity}\n以下是本次作品的核心设定，请严格遵守：\n")

    # User inputs
    # Phase 0 基础参数：`novel_name` 空则不占位（若走到这里说明 collect_user_inputs 必填校验被绕过，
    # 这是上游 bug 应就地暴露而非在 context 层修补）；其余 6 字段空时输出显式占位——
    # 让 LLM 感知"用户没明说" + 附带安全兜底行为指令（光说"未设定"反而更放飞），避免下游 prompt
    # 静默丢失字段头部导致 LLM 瞎编。
    if state.novel_name:
        parts.append(f"【小说名称】{state.novel_name}")
    parts.append(
        f"【小说类型】{state.genre}" if state.genre
        else "【小说类型】未设定(按通用大众题材处理)"
    )
    parts.append(
        f"【写作风格】{state.writing_style}" if state.writing_style
        else "【写作风格】未设定,请按题材通用文风自然呈现,不要额外增添强烈风格标签"
    )
    parts.append(
        f"【目标读者】{state.target_audience}" if state.target_audience
        else "【目标读者】未设定,请按题材主流读者群自然呈现"
    )
    parts.append(
        f"【核心基调】{state.core_tone}" if state.core_tone
        else "【核心基调】未设定,请按情节内在逻辑自然呈现,不要人为渲染额外基调"
    )
    parts.append(
        f"【每章字数】{state.chapter_word_count}" if state.chapter_word_count
        else "【每章字数】未设定(按默认 3000 字左右自适应)"
    )
    parts.append(
        f"【总字数目标】{state.total_word_count}" if state.total_word_count
        else "【总字数目标】未设定(按情节需要收束,不追求特定总量)"
    )

    # Foundation results
    if state.core_theme:
        parts.append(f"\n【核心主题与立意】\n{state.core_theme}")
    if state.world_building:
        parts.append(f"\n【世界观设定】\n{state.world_building}")
    # 力量体系是本作已定稿的正式设定，被动罗列改成祈使约束——避免下游生成/审核 prompt
    # 编造未在其中定义的境界、流派、体系名词。header 前缀仍以【力量体系 开头，
    # 与 llm.py _SYSTEM_CONTEXT_TOP_SECTIONS 白名单同步。
    if state.power_system:
        parts.append(
            "\n【力量体系（本作已定稿，创作时必须严格遵循）】\n"
            f"{state.power_system}\n"
            "以上力量体系为本作正式设定：\n"
            "- 所有涉及能力、修炼、晋升、体系名词的描写必须严格落入上述框架；\n"
            "- 禁止虚构未在其中定义的新境界、新流派、新体系；\n"
            "- 如需引入新概念，必须显式声明为在此体系内的具体位置或分支,不得自成体系。"
        )
    if state.core_conflicts:
        parts.append(f"\n【核心冲突】\n{state.core_conflicts}")
    if state.overall_outline:
        parts.append(f"\n【整体大纲与结局】\n{state.overall_outline}")
    # 人物档案：从卡库渲染（真源是 entity_cards 的 CharacterCard，取代原 character_profiles 散文）。
    # deep_character_view 控制操作视图 vs 深层视图；getattr 兜底老 state / 缺字段子图。
    profiles = format_character_profiles_from_cards(
        getattr(state, "entity_cards", []) or [], deep=deep_character_view
    )
    if profiles:
        parts.append(f"\n【人物档案】\n{profiles}")

    # Dynamic tracking fields — omitted when the caller already injects prev snapshot
    # into task_prompt (tracking-update steps), to avoid diluting reviewer attention.
    if state.current_arc_outline:
        parts.append(f"\n【本批章节弧线大纲】\n{state.current_arc_outline}")
    if not exclude_snapshots:
        if state.foreshadowing:
            # 数据层面保留全部已收伏笔，上下文显示层面只过滤近5章
            formatted = _format_foreshadowing_for_context(state.foreshadowing, state.total_chapters_written)
            if formatted:
                parts.append(f"\n【伏笔台账（最新）】\n{formatted}")
        if state.phase_summary:
            parts.append(f"\n【阶段固化数据（最新）】\n{state.phase_summary}")
        # 装备/物品全局真源：从实体卡库渲染（phase_summary 已移除【装备/道具】，真源改由卡库承载）。
        # getattr 兜底——老 state 快照 / 尚未加 entity_cards 的子图 state 缺字段时降级为无装备段。
        equipment = format_equipment_for_context(getattr(state, "entity_cards", []) or [])
        if equipment:
            parts.append(f"\n【登场实体卡·装备/物品（本作真源，写作须严格遵守其归属/状态）】\n{equipment}")

    return "\n".join(parts)


# ── chapter context window ─────────────────────────────────────────────────────

def build_chapter_context(state: _ContextState) -> str:
    """Build the context window for the next chapter.

    Window (at most 5 chapters back):
      - nearest 2: full content (from disk chapters/)
      - next 3 before that: summary only (from state)
      - anything older: ignored
    """
    total = state.total_chapters_written
    if total == 0:
        return ""

    full_start = max(0, total - FULL_COUNT)
    summary_start = max(0, full_start - SUMMARY_COUNT)

    parts: list[str] = []

    # Summary section (up to 3 chapters, header only emitted when entries exist)
    if summary_start < full_start:
        summary_entries: list[str] = []
        for i in range(summary_start, full_start):
            chapter_num = i + 1
            title = state.all_chapter_titles[i] if i < len(state.all_chapter_titles) else f"第{chapter_num}章"
            summary = state.all_chapter_summaries[i] if i < len(state.all_chapter_summaries) else ""
            if summary:
                summary_entries.append(f"第{chapter_num}章《{title}》：{summary}")
            else:
                _logger.warning("Chapter %d has no summary in state; omitting from context.", chapter_num)
        if summary_entries:
            parts.append("【近期章节概要（供参考）】")
            parts.extend(summary_entries)

    # Full content section (header only emitted when at least one entry is produced)
    chapters_dir = get_output_dir(state.novel_name) / "chapters"
    full_entries: list[str] = []
    for i in range(full_start, total):
        chapter_num = i + 1
        title = state.all_chapter_titles[i] if i < len(state.all_chapter_titles) else f"第{chapter_num}章"
        filename = chapters_dir / chapter_filename(chapter_num, title)
        try:
            content = filename.read_text(encoding="utf-8")
            full_entries.append(f"\n--- 第{chapter_num}章《{title}》 ---\n{content}")
        except OSError:
            summary = state.all_chapter_summaries[i] if i < len(state.all_chapter_summaries) else ""
            if summary:
                _logger.warning(
                    "Chapter %d file not found (%s); falling back to summary.", chapter_num, filename
                )
                full_entries.append(f"第{chapter_num}章《{title}》（概要）：{summary}")
            else:
                _logger.warning(
                    "Chapter %d file not found (%s) and no summary available; chapter omitted from context.",
                    chapter_num, filename,
                )
    if full_entries:
        parts.append("【最近章节完整内容（请保持情节连贯）】")
        parts.extend(full_entries)

    return "\n".join(parts)
