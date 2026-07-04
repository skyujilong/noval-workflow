"""台账类提示词（character_status / relations / foreshadowing / phase_summary）
与伏笔台账工具函数。

这些提示词与台账格式强相关、与题材无关，所有题材共享。从原 prompts.py 原样迁移。
"""

from __future__ import annotations

from typing import Union

from noval_workflow.prompts.base import _PromptState


def character_status_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating character dynamic status."""
    prev = ""
    if state.character_status:
        prev = f"\n\n【上次人物状态快照】\n{state.character_status}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【近期章节内容（请据此更新状态）】\n{chapter_context}"

    carry_over = "\n- 上次快照中的每位人物都必须出现在本次输出中，状态未变者各字段直接沿用原文" if prev else ""
    return f"""请根据已完成的章节内容，更新【人物动态状态】。{prev}{chapter_section}

要求：
- 输出完整的当前人物状态快照，涵盖主角及所有主要配角{carry_over}
- 本批有变化的字段末尾标注【变化】，说明具体变动
- 严格按照以下固定格式输出，每个人物一组

**固定输出格式（每位关键角色一组，按角色分块）**

角色：XXX
【当前位置】（所在场景/地点，≤15字）
【情绪/状态】（当前心理状态与身体状况，≤15字）
【当前目标】（本阶段的行动目标，≤20字）
【关键处境】（本批最重要的处境变化或持续状态，≤30字，无变化写原来的值，不更新）

请直接输出更新后的人物动态状态，不需要额外标题。"""


def character_relations_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating character relations and faction dynamics."""
    prev = ""
    if state.character_relations:
        prev = f"\n\n【上次关系/势力快照】\n{state.character_relations}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【近期章节内容（请据此更新关系）】\n{chapter_context}"

    carry_over = "\n- 完整列出上次快照中所有的人物关系与势力格局，状态未变者直接沿用原文" if prev else ""
    return f"""请根据已完成的章节内容，更新【人物关系/势力格局】。{prev}{chapter_section}

要求：{carry_over}
- 本批有变化的条目末尾标注【变化】，说明转变原因
- 严格按照以下固定格式分两块输出

**固定输出格式**

【人物关系】
角色A → 角色B：当前关系描述（≤20字）
（有变化时在行末加【变化】，下一行写变化原因，≤20字）

【势力格局】
势力名：当前状态与力量描述（≤30字）
（有变化时在行末加【变化】，下一行写变化原因，≤20字）

请直接输出更新后的人物关系/势力格局，不需要额外标题。"""


_FORESHADOW_PRUNE_DISTANCE = 5  # 已收超过此章数后从上次台账中物理删除


def _migrate_legacy_foreshadowing(ledger: Union[str, dict]) -> dict:
    """将老旧字符串格式的伏笔台账迁移为新的结构化 JSON 格式。

    返回的结构：
    {
        "pending": [  # 悬置伏笔
            {
                "id": "F00",
                "name": "伏笔名称",
                "planted_batch": 1,
                "current_appearance": "当前潜伏表现",
                "core_purpose": "核心作用",
                "planned_recovery_range": "预定回收区间",
                "freedom": "高/中/低"
            }
        ],
        "collected": [  # 已收伏笔
            {
                "id": "F00",
                "name": "伏笔名称",
                "planted_batch": 1,
                "current_appearance": "当前潜伏表现",
                "core_purpose": "核心作用",
                "planned_recovery_range": "预定回收区间",
                "freedom": "高/中/低",
                "recovered_at_chapter": 5
            }
        ]
    }
    """
    # 如果已经是 dict（新格式），直接返回
    if isinstance(ledger, dict):
        return ledger

    # 空字符串返回空结构
    if not ledger or not ledger.strip():
        return {"pending": [], "collected": []}

    import re

    separator = "-------------------------------------"
    blocks = [b.strip() for b in ledger.split(separator) if b.strip()]

    pending = []
    collected = []

    for block in blocks:
        # 提取各字段
        def extract_field(name: str) -> str:
            m = re.search(rf"【{name}】(.*?)(?=\n【|$)", block, re.DOTALL)
            return m.group(1).strip() if m else ""

        entry_id = extract_field("伏笔编号")
        if not entry_id:
            continue  # 无效条目，跳过

        entry = {
            "id": entry_id,
            "name": extract_field("伏笔名称"),
            "planted_batch": 0,  # 默认值，后面尝试解析
            "current_appearance": extract_field("当前潜伏表现"),
            "core_purpose": extract_field("核心作用"),
            "planned_recovery_range": extract_field("预定回收区间"),
            "freedom": extract_field("自由度") or "中",
        }

        # 解析埋点批次（纯数字）
        planted_batch_str = extract_field("埋点批次")
        try:
            m = re.search(r"(\d+)", planted_batch_str)
            if m:
                entry["planted_batch"] = int(m.group(1))
        except (ValueError, TypeError):
            pass

        # 判断是否已回收
        is_collected = "是" in extract_field("是否已回收")
        if is_collected:
            recovered_at_str = extract_field("回收章节")
            try:
                m = re.search(r"第?(\d+)章?", recovered_at_str)
                if m:
                    entry["recovered_at_chapter"] = int(m.group(1))
            except (ValueError, TypeError):
                entry["recovered_at_chapter"] = 0
            collected.append(entry)
        else:
            pending.append(entry)

    return {"pending": pending, "collected": collected}


def _prune_collected_foreshadowing(ledger: Union[str, dict], current_chapter: int) -> dict:
    """【已弃用，仅迁移不删除】将老旧字符串格式迁移为结构化格式。

    注意：不再物理删除旧的已收伏笔，数据层面永久保留全部历史。
    只在上下文显示层面过滤近5章的已收伏笔，参见 _format_foreshadowing_for_context。
    """
    # 仅做迁移，不再过滤删除
    return _migrate_legacy_foreshadowing(ledger)


def _format_foreshadowing_for_context(ledger: dict, current_chapter: int = 0) -> str:
    """将结构化的伏笔台账格式化为易读文本，供 LLM 上下文使用。

    为了减少上下文体积，已收伏笔只显示最近 _FORESHADOW_PRUNE_DISTANCE 章内回收的。
    数据层面仍然保留全部历史，不会丢失。
    """
    if not ledger or (not ledger.get("pending") and not ledger.get("collected")):
        return ""

    lines = []
    separator = "-------------------------------------"

    # pending 全部显示（因为这些还没回收，是活跃伏笔）
    pending_count = len(ledger.get("pending", []))
    if pending_count > 0:
        lines.append("【悬置】")
        for entry in ledger["pending"]:
            lines.extend([
                separator,
                f"【伏笔编号】{entry.get('id', '')}",
                f"【伏笔名称】{entry.get('name', '')}",
                f"【埋点批次】{entry.get('planted_batch', '')}",
                f"【当前潜伏表现】{entry.get('current_appearance', '')}",
                f"【核心作用】{entry.get('core_purpose', '')}",
                f"【预定回收区间】{entry.get('planned_recovery_range', '')}",
                f"【自由度】{entry.get('freedom', '')}",
            ])
        lines.append("")

    # collected 只显示近5章内回收的，但在标题处显示总数
    total_collected = len(ledger.get("collected", []))
    recent_collected = [
        entry for entry in ledger.get("collected", [])
        if current_chapter - entry.get("recovered_at_chapter", 0) <= _FORESHADOW_PRUNE_DISTANCE
    ] if current_chapter > 0 else ledger.get("collected", [])

    if recent_collected:
        if total_collected > len(recent_collected):
            lines.append(f"【已收】（共 {total_collected} 个，仅显示近 {_FORESHADOW_PRUNE_DISTANCE} 章内回收的 {len(recent_collected)} 个）")
        else:
            lines.append("【已收】")
        for entry in recent_collected:
            lines.extend([
                separator,
                f"【伏笔编号】{entry.get('id', '')}",
                f"【伏笔名称】{entry.get('name', '')}",
                f"【埋点批次】{entry.get('planted_batch', '')}",
                f"【当前潜伏表现】{entry.get('current_appearance', '')}",
                f"【核心作用】{entry.get('core_purpose', '')}",
                f"【预定回收区间】{entry.get('planned_recovery_range', '')}",
                f"【自由度】{entry.get('freedom', '')}",
                f"【回收章节】第{entry.get('recovered_at_chapter', 0)}章",
            ])

    return "\n".join(lines)


def foreshadowing_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """构建更新伏笔台账的提示词。"""
    current_chapter = state.total_chapters_written  # chapters completed so far
    current_chapter_info = f"第{current_chapter}章" if current_chapter > 0 else "起始"

    prev = ""
    if state.foreshadowing:
        # 迁移格式（不再物理删除旧伏笔）
        structured = _prune_collected_foreshadowing(state.foreshadowing, current_chapter)
        # 仅显示层面过滤近5章已收伏笔，数据保留完整
        formatted = _format_foreshadowing_for_context(structured, current_chapter)
        if formatted:
            prev = f"\n\n【上次伏笔台账】\n{formatted}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【近期章节内容（请据此核对伏笔）】\n{chapter_context}"

    carry_over = "\n- pending（悬置）：列出当前所有仍待兑现的伏笔，必须包含上次台账中全部悬置项，本批无变化者原文保留" if prev else "\n- pending（悬置）：列出当前章节中出现的所有待兑现伏笔"
    return f"""请根据已完成的章节内容，更新【伏笔台账】。当前所处章节：{current_chapter_info}。{prev}{chapter_section}

要求：{carry_over}
- 【新增】标注本批章节中首次埋下的新伏笔（放在 pending 数组）
- 【已收】标注本批被兑现或回收的伏笔（从 pending 移动到 collected 数组，并填写 recovered_at_chapter）
  - collected 数组中的条目，在当前章节减去回收章节超过5章的，可以直接删除，用来节省上下文。
- pending 中超过5章未回收的伏笔，判断是否还有回收价值，如果没有，可以直接删除，用来节省上下文。

**重要：输出格式要求（必须严格遵守）**

请直接输出纯 JSON，不要包含任何 markdown 代码块标记、解释文字或额外内容。
JSON 结构如下：
{{
    "pending": [  // 悬置伏笔（未回收）
        {{
            "id": "F00",              // 伏笔编号，字符串
            "name": "伏笔名称",       // 4-12字极简概括
            "planted_batch": 1,       // 埋点批次，纯数字
            "current_appearance": "当前潜伏表现",  // 浅层、日常、隐蔽的细节铺垫
            "core_purpose": "核心作用",  // 支撑剧情的作用
            "planned_recovery_range": "预定回收区间",  // 大阶段范围
            "freedom": "高"            // 高 / 中 / 低
        }}
    ],
    "collected": [  // 已收伏笔（已兑现）
        {{
            "id": "F00",
            "name": "伏笔名称",
            "planted_batch": 1,
            "current_appearance": "当前潜伏表现",
            "core_purpose": "核心作用",
            "planned_recovery_range": "预定回收区间",
            "freedom": "高",
            "recovered_at_chapter": 5  // 回收章节，纯数字，必填
        }}
    ]
}}

字段要求：
- planted_batch：纯数字（不要写"第X批"、"批次X"等，只写数字）
- recovered_at_chapter：纯数字（不要写"第X章"，只写数字；仅 collected 数组中的条目需要）
- freedom：只能是 "高"、"中"、"低" 三者之一

请只输出 JSON 字符串，不要有任何其他内容。"""


def phase_summary_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating phase-frozen hard data."""
    prev = ""
    if state.phase_summary:
        prev = f"\n\n【上次阶段固化数据】\n{state.phase_summary}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【近期章节内容（请据此更新硬性数据）】\n{chapter_context}"

    carry_over = "\n- 完整保留上次快照中所有条目，本批无变化者直接沿用原文；有变化者标注【变化】" if prev else ""
    return f"""请根据已完成的章节内容，更新【阶段固化数据】。{prev}{chapter_section}

要求：{carry_over}
- 严格按照以下固定格式输出，每条不超过30字，全部合计不超过500字
- 本批新增或变化的条目末尾标注【变化】
- 【核心能力】不得超出【人物档案】为该角色设定的本卷成长天花板；越界视为战力崩坏，须回退到设定上限

**固定输出格式（每位关键角色一组，按角色分块）**

角色：XXX
【当前状态/定位】（当前实力层级、身份或队伍中的角色定位，≤20字）
【核心能力】（已掌握的关键技能/能力，每条≤20字，可多条）
【装备/道具】（当前持有的重要物品，每条≤20字，可多条）
【资源/人脉】（可调用的资源、关键人脉，每条≤20字，可多条）
【承诺/债务】（未了结的承诺、欠债、义务，每条≤20字，无则写"无"）
【特殊限制】（对该角色行动有约束的条件，每条≤20字，无则写"无"）

请直接输出更新后的阶段固化数据，不需要额外标题。"""


def initial_status_prompt() -> str:
    """构建「人物初始基线（第0章）」提示词：Phase 1 收尾从已定稿设定固化基线数值。

    与 phase_summary_prompt 的区别：本提示词无 prev 快照、无章节内容，数据来源是系统提示中
    的【人物档案】+【世界观设定】；输出格式与 phase_summary 完全一致，使其写入同一个
    state.phase_summary 字段后，能被 Phase 2.5 首批 phase_summary 更新以「完整保留上次快照」
    的 carry-over 方式继承，避免起点漂移。复用 review_type="phase_summary" 走数据维护员身份。
    """
    return """请根据系统提示中的【人物档案】与【世界观设定】，为主角与主要配角固化【人物初始基线（开篇 / 第0章）】。

要求：
- 这是全书开篇尚未发生任何剧情时的起点数值，作为后续阶段固化数据演进的基线，不是剧情推进后的状态
- 只固化人物档案已明确设定、或可由设定合理推断的开篇初始值；不创作剧情、不虚构未设定的能力/装备/资源
- 【核心能力】必须落在人物档案为该角色设定的「卷一 / 初始成长天花板」之内，禁止提前给出后续卷的能力
- 涵盖主角及所有主要配角，每条不超过30字，全部合计不超过500字
- 严格按照以下固定格式输出，每个人物一组

**固定输出格式（每位关键角色一组，按角色分块）**

角色：XXX
【当前状态/定位】（开篇的实力层级、身份或队伍中的角色定位，≤20字）
【核心能力】（开篇已掌握的关键技能/能力，每条≤20字，可多条）
【装备/道具】（开篇持有的重要物品，每条≤20字，可多条）
【资源/人脉】（开篇可调用的资源、关键人脉，每条≤20字，可多条）
【承诺/债务】（开篇已背负的承诺、欠债、义务，每条≤20字，无则写"无"）
【特殊限制】（开篇即对该角色行动有约束的条件，每条≤20字，无则写"无"）

请直接输出人物初始基线，不需要额外标题。"""
