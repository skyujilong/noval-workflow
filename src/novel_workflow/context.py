"""Build context strings from accumulated NovelState fields."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Protocol

from noval_workflow.config import FULL_COUNT, SUMMARY_COUNT


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
    core_conflicts: str
    overall_outline: str
    character_profiles: str
    # Phase 2.5 — dynamic tracking
    current_arc_outline: str
    character_status: str
    character_relations: str
    foreshadowing: str
    phase_summary: str
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

def build_foundation_context(state: _ContextState, *, exclude_snapshots: bool = False) -> str:
    """Serialize approved foundation fields into a structured system prompt string.

    Only includes non-empty fields, so the context grows as Phase 1 progresses.

    Args:
        exclude_snapshots: When True, omit the four dynamic snapshot fields
            (character_status/relations/foreshadowing/phase_summary). Use this
            for the tracking-update prepare steps where the previous snapshot is
            already injected into task_prompt via {prev}, so including it here
            would only dilute the reviewer's attention.
    """
    parts: list[str] = []

    parts.append("你是一位擅长轻小说（ライトノベル）创作的资深作家与架构编辑，擅长以角色群像、对话关系与强主角视角推进故事。以下是本次作品的核心设定，请严格遵守：\n")

    # User inputs
    if state.novel_name:
        parts.append(f"【小说名称】{state.novel_name}")
    if state.genre:
        parts.append(f"【小说类型】{state.genre}")
    if state.writing_style:
        parts.append(f"【写作风格】{state.writing_style}")
    if state.target_audience:
        parts.append(f"【目标读者】{state.target_audience}")
    if state.core_tone:
        parts.append(f"【核心基调】{state.core_tone}")
    if state.chapter_word_count:
        parts.append(f"【每章字数】{state.chapter_word_count}")
    if state.total_word_count:
        parts.append(f"【总字数目标】{state.total_word_count}")

    # Foundation results
    if state.core_theme:
        parts.append(f"\n【核心主题与立意】\n{state.core_theme}")
    if state.world_building:
        parts.append(f"\n【世界观设定】\n{state.world_building}")
    if state.core_conflicts:
        parts.append(f"\n【核心冲突】\n{state.core_conflicts}")
    if state.overall_outline:
        parts.append(f"\n【整体大纲与结局】\n{state.overall_outline}")
    if state.character_profiles:
        parts.append(f"\n【人物档案】\n{state.character_profiles}")

    # Dynamic tracking fields — omitted when the caller already injects prev snapshot
    # into task_prompt (tracking-update steps), to avoid diluting reviewer attention.
    if state.current_arc_outline:
        parts.append(f"\n【本批章节弧线大纲】\n{state.current_arc_outline}")
    if not exclude_snapshots:
        if state.character_status:
            parts.append(f"\n【人物动态状态（最新）】\n{state.character_status}")
        if state.character_relations:
            parts.append(f"\n【人物关系/势力动态（最新）】\n{state.character_relations}")
        if state.foreshadowing:
            parts.append(f"\n【伏笔台账（最新）】\n{state.foreshadowing}")
        if state.phase_summary:
            parts.append(f"\n【阶段固化数据（最新）】\n{state.phase_summary}")

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
