"""Task prompt constants for each generation step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


class _PromptState(Protocol):
    character_status_history: list[str]
    character_relations_history: list[str]
    foreshadowing_history: list[str]
    phase_summary_history: list[str]

# Phase 1: Foundation prompts

CORE_THEME_PROMPT = """请为本小说创作【核心主题与立意】。

要求：
- 用200-400字阐述小说的核心主题、价值观、哲学命题
- 明确作品想传递的核心思想
- 确保主题与类型、基调、目标读者相符

请直接输出主题内容，不需要标题。"""

WORLD_BUILDING_PROMPT = """请为本小说创作【世界观设定】。

要求：
- 详细描述故事发生的时代背景、地理环境、社会结构
- 包括独特的规则体系（魔法/科技/社会规范等，视类型而定）
- 说明世界的历史脉络与当前局势
- 字数：400-800字

请直接输出世界观内容，不需要标题。"""

CORE_CONFLICTS_PROMPT = """请为本小说设计【核心冲突】。

要求：
- 明确主要冲突类型（人与人、人与自然、人与社会、人与自我等）
- 列出2-4个核心冲突层次，并说明各层次的具体表现
- 冲突需与世界观、主题深度契合
- 字数：300-600字

请直接输出冲突设计内容，不需要标题。"""

def overall_outline_prompt(total_word_count: str) -> str:
    word_count_desc = f"{total_word_count}字" if total_word_count else "长篇"
    return f"""请为本小说制定【整体大纲与结局】。

请为本书撰写高自由度、长线框架型全书主线脉络大纲。
本次大纲为顶层战略框架，仅锁定全书四段式起承转合、每卷核心基调、阶段目标、人物整体弧光、全局势力格局，不锁定具体章节细节、不固定配角命运、不固定具体战斗方式、不固定具体情感桥段、不锁死单场事件结果。
要求：
全书分四卷，明确每卷阶段定位、核心主线、阶段困境、整体剧情走向，搭建{word_count_desc}长线骨架。
只定义「大方向和最终落点」，预留大量支线、临场变故、随机事件、新增角色、新增势力的发散空间。
人物仅锁定整体成长弧光，不锁定阶段性情绪、不固定相遇 / 冲突 / 牺牲节点，保留人物动态变化空间。
怪物体系、地形利用、战斗战术、资源获取、人情博弈细节全部留白，交由后续分批次小大纲落地。
结局只锁定基调与最终立意，不锁死具体收尾事件，保留开放式调整空间。
整体逻辑闭环、层次清晰、节奏递进，不限制后期剧情发散、扩充、微调。

请直接输出大纲内容，不需要标题。"""

CHARACTER_PROFILES_PROMPT = """请为本小说创建【人物档案】。

要求：
- 主角：详细描述背景、性格、动机、成长弧线
- 主要配角（2-4人）：简要描述各自特点与作用
- 反派/对立角色：描述其动机与与主角的关系
- 确保人物关系清晰，避免相互矛盾
- 500-2000字

请直接输出人物档案内容，不需要标题。"""

# Phase 2: Chapter prompts

def titles_prompt(all_titles: list[str], chapter_context: str = "") -> str:
    """Build the prompt for generating next batch of BATCH_SIZE chapter titles."""
    from noval_workflow.config import BATCH_SIZE

    existing = ""
    if all_titles:
        existing = "\n\n已有章节标题（请勿重复）：\n" + "\n".join(
            f"{i+1}. {t}" for i, t in enumerate(all_titles)
        )

    context_section = ""
    if chapter_context:
        context_section = f"\n\n【前文故事进展（请据此规划后续走向）】\n{chapter_context}"

    return f"""请为本小说生成下{BATCH_SIZE}章的章节标题。{existing}{context_section}

要求：
- 每行一个标题，共{BATCH_SIZE}行
- 标题简洁有力（4-12字），与故事情节紧密相关
- 不要添加序号、标点或其他前缀
- 标题不得与已有章节重复
- 标题须符合系统提示中的整体大纲方向，体现故事在当前阶段应有的发展走向
- 标题须与前文章节保持时间线与情节的连贯，不得跳跃或产生矛盾
- {BATCH_SIZE}个标题之间应形成自然的叙事流，层层递进，避免互不相关的孤立命名

请直接输出{BATCH_SIZE}个标题，每行一个。"""


def chapter_prompt(title: str, chapter_num: int, all_titles: list[str], chapter_context: str = "") -> str:
    """Build the prompt for writing a chapter."""
    all_titles_text = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(all_titles)
    )

    context_section = ""
    if chapter_context:
        context_section = f"\n\n【前文内容参考】\n{chapter_context}"

    return f"""请撰写第{chapter_num}章：《{title}》

全书章节目录（供参考）：
{all_titles_text}{context_section}

要求：
- 严格遵守系统提示中的人物设定，不得出现人物关系错乱
- 情节连贯，与前述章节内容自然衔接
- 保持设定的写作风格与基调
- 字数接近设定的每章字数目标

【重要输出规范】
输出必须是章节正文本身，从第一句叙述文字开始，直接进入故事内容。

❌ 错误示例（绝对禁止）：
- "我将第三段第二句改为……"
- "原文：xxx → 修改为：xxx"
- "建议将'寒风'替换为'朔风'，以增强意境"
- "以下是修改后的版本："
- "根据审稿意见，我对以下内容进行了调整：……"
- 任何以"修改""调整""替换""更改""优化"为开头的句子

✅ 正确示例：
直接输出正文内容，例如："夜色沉沉，烛火摇曳……"

请直接输出章节正文内容，从正文第一句话开始。"""


# Phase 2.5: Arc outline and dynamic tracking prompts

def arc_outline_prompt(state: "NovelState") -> str:
    """Build the prompt for generating a mini arc outline for the current batch."""
    from noval_workflow.config import BATCH_SIZE, SUMMARY_COUNT

    prev_section = ""
    if state.all_chapter_summaries:
        recent = state.all_chapter_summaries[-SUMMARY_COUNT:]
        prev_section = f"\n\n【前文故事摘要（最近{SUMMARY_COUNT}章）】\n" + "\n".join(
            f"第{state.total_chapters_written - len(recent) + i + 1}章摘要：{s}"
            for i, s in enumerate(recent)
            if s
        )

    max_words = BATCH_SIZE * 500
    return f"""请为本批接下来的 {BATCH_SIZE} 章规划故事弧线大纲。{prev_section}

# 角色：你是专业网文分章弧线大纲撰写师
## 整体约束
1. 严格承接上一批大纲最终结尾情节，情节逻辑连贯、无断层，全程贴合作品整体主线大纲，不偏离核心世界观、势力设定、人物人设与核心冲突。
2. 本批次所有章节大纲总字数严格控制在 {max_words} 以内；**单章节内容节点文字不得超过500字**，精简表述，拒绝冗余描写、抒情、旁白。
3. 仅输出结构化章节大纲，不撰写正文内容、不生成章节标题，仅为标题、正文创作提供明确锚点。

## 单章节固定必填字段（每章必须依次列出，缺一不可）
【章节X】
1. 本章核心事件：一句话概括本章主线行为与场景
2. 人物行动：核心角色、配角的具体动作、分工、互动行为
3. 情节转折：本章出现的冲突、反转、变故、突发危机
4. 节奏&情绪锚点：标注本章节奏（平缓/紧张/爆发/悬疑）、核心情绪（愤怒/恐惧/释然/警惕等）、网文看点（爽点/悬念/铺垫/虐点）
5. 伏笔&线索：本章新增伏笔、回收前文伏笔、遗留待解线索
6. 创作锚点：为章节标题、正文细节描写提供关键词/方向指引
7. 下章衔接指引：本章收尾状态，明确下一章开篇切入方向

## 内容创作规则
1. 严守作品既定设定：类型一致、战力体系、物资规则、队伍规矩、人物关系、势力矛盾，不新增私设、不强行降智/拔高角色。
2. 冲突设计循序渐进，支线服务主线，不随意新增无关人物、无关支线，避免剧情散乱。
3. 动作、对话、冲突符合人物性格，角色行为逻辑自洽，保持人设统一。
4. 涉及战斗、对峙、逃生场景，写明攻防动作、敌我态势，细节具备可落地性。
5. 物资、伤口、尸变、环境等细节贴合末日校园世界观，逻辑严谨。

## 格式与文字要求
1. 统一使用上方固定字段排版，段落清晰，字段区分明确，不用花哨格式、表情、特殊符号。
2. 文字书面化、精炼化，短句为主，表意精准，不使用网络口水话、情绪化吐槽。
3. 字数二次自检：单章≤500字，整批合计≤{max_words}，超标自动精简压缩。

## 补充兜底规则
1. 若上一批衔接信息缺失，优先沿用最近主线冲突、人物状态、场景位置续写。
2. 关键反派、核心配角的行为保持前后一致，恩怨、矛盾持续延续。
3. 所有伏笔标注清晰，做到“有埋必有收”，跨章节线索做好标记。"""


def character_status_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating character dynamic status."""
    prev = ""
    if state.character_status_history:
        prev = f"\n\n【上次人物状态快照】\n{state.character_status_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新状态）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【人物动态状态】。{prev}{chapter_section}

要求：
- 输出完整的当前人物状态快照，涵盖主角及所有主要配角
- 上次快照中的每位人物都必须出现在本次输出中，状态未变者直接沿用原文
- 本批有变化的状态用【变化】标注，说明具体变动
- 格式清晰，便于后续章节创作时快速查阅
- 尽量精炼，不超过500字

请直接输出更新后的人物动态状态，不需要标题。"""


def character_relations_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating character relations and faction dynamics."""
    prev = ""
    if state.character_relations_history:
        prev = f"\n\n【上次关系/势力快照】\n{state.character_relations_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新关系）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【人物关系/势力格局】。{prev}{chapter_section}

要求：
- 完整列出上次快照中所有的人物关系与势力格局，状态未变者直接沿用原文
- 本批关系发生转变的人物对，用【变化】标注并说明原因
- 记录各势力当前格局与力量对比，标注本批新增或变化的势力动向
- 尽量精炼，不超过500字

请直接输出更新后的人物关系/势力格局，不需要标题。"""


def foreshadowing_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating the foreshadowing ledger."""
    prev = ""
    if state.foreshadowing_history:
        prev = f"\n\n【上次伏笔台账】\n{state.foreshadowing_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此核对伏笔）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【伏笔台账】。{prev}{chapter_section}

要求：
- 【悬置】列出当前所有仍待兑现的伏笔，必须包含上次台账中全部悬置项，本批无变化者原文保留
- 【新增】标注本批章节中首次埋下的新伏笔
- 【已收】标注本批被兑现或回收的伏笔（【是否已回收】"是"）
  - 需要调整顺序到【悬置】下方

**格式要求**

## 单条伏笔固定结构（必须全覆盖）
-------------------------------------
【伏笔编号】F00
【伏笔名称】4-12字极简概括
【埋点批次】当前创作批次 / 章节区间
【当前潜伏表现】浅层、日常、隐蔽、不突兀的细节铺垫，读者看不出是伏笔
【核心作用】支撑后期人设反转、剧情冲突、世界观闭环、势力博弈、情感弧光等
【预定回收区间】仅锁定大阶段（卷/批次范围，不锁具体章节）
【自由度】高 / 中 / 低
【是否已回收】是 / 否



请直接输出更新后的伏笔台账，不需要标题。"""


def phase_summary_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating phase-frozen hard data."""
    prev = ""
    if state.phase_summary_history:
        prev = f"\n\n【上次阶段固化数据】\n{state.phase_summary_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新硬性数据）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【阶段固化数据】。{prev}{chapter_section}

要求：
- 完整保留上次快照中所有硬性数据，本批无变化的项目直接沿用原文
- 主角等级/境界/能力：更新本批有变化的部分，无变化则原文保留
- 装备/技能/道具：列出主角当前持有的所有重要项目，除非本批明确失去/消耗
- 资源/人脉/势力：记录当前全部资源状态，标注本批新增或变化项【变化】
- 其他硬性数据（承诺、债务、特殊限制等）：全量保留，标注本批新增项
- 尽量精炼，不超过500字

请直接输出更新后的阶段固化数据，不需要标题。"""


SUMMARY_PROMPT = """请为以下章节内容生成简洁的情节概要。

章节标题：{title}

章节内容：
{content}

要求：
- 概要字数：100-200字
- 包含本章的关键情节转折点
- 包含出现的主要人物及其行动
- 概要仅供后续创作参考，语言简洁精准

请直接输出概要内容，不需要标题前缀。"""


# LLM self-review prompts

CORE_THEME_REVIEW_PROMPT = """请审核以下【核心主题与立意】：

{draft}

审核要点：
1. 主题是否清晰、有深度，而非泛泛而谈？
2. 是否与小说类型、基调、目标读者相符？
3. 作品想传递的核心思想是否明确？
4. 字数是否符合要求（200-400字）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

WORLD_BUILDING_REVIEW_PROMPT = """请审核以下【世界观设定】：

{draft}

审核要点：
1. 时代背景、地理环境、社会结构是否描述完整？
2. 规则体系（魔法/科技/社会规范等）是否自洽，无内部矛盾？
3. 是否为后续冲突和人物行动提供了充分的舞台？
4. 字数是否符合要求（400-800字）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CORE_CONFLICTS_REVIEW_PROMPT = """请审核以下【核心冲突】：

{draft}

审核要点：
1. 是否列出了 2-4 个层次分明的核心冲突？
2. 冲突类型是否多样（人与人/人与社会/人与自我等）？
3. 是否与世界观设定、核心主题深度契合？
4. 字数是否符合要求（300-600字）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

OVERALL_OUTLINE_REVIEW_PROMPT = """请审核以下【整体大纲与结局】：

{draft}

审核要点：
1. 是否覆盖起承转合四个阶段，各阶段篇幅分配合理？
2. 各阶段之间的因果逻辑是否成立，情节推进自然？
3. 结局是否与核心冲突、主题相呼应，令人信服？
4. 是否明确了结局走向（开放/封闭，悲剧/喜剧等）？
5. 字数是否符合要求（2500-3500字）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CHARACTER_PROFILES_REVIEW_PROMPT = """请审核以下【人物档案】：

{draft}

审核要点：
1. 主角的背景、性格、动机、成长弧线是否完整且有说服力？
2. 主要配角与反派是否各有特点，不互相重叠？
3. 人物之间的关系是否清晰，无自相矛盾之处？
4. 人物设定是否与世界观、核心冲突相匹配？
5. 字数是否符合要求（500-2000字）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

FOUNDATION_REVIEW_PROMPT = """请对以下内容进行严格审核：

{draft}

审核要点：
1. 内容是否与小说类型、风格、基调相符？
2. 是否存在内部逻辑矛盾？
3. 是否与已确定的其他设定（主题/世界观/冲突/人物）相矛盾？
4. 内容质量是否达到专业水准？

如果内容质量合格、无明显问题，请只输出：无问题
如果有需要改进的地方，请具体指出问题并给出修改建议。"""

CHAPTER_REVIEW_PROMPT = """请对以下章节内容进行审核：

{draft}

审核要点：
1. 人物关系是否有错乱（最重要）？
2. 人物性格是否与人物档案一致？
3. 情节是否符合故事走向？
4. 是否存在前后矛盾？

如果内容质量合格、无明显问题，请只输出：无问题
如果有需要改进的地方，请具体指出问题并给出修改建议。"""

def _titles_review_prompt() -> str:
    from noval_workflow.config import BATCH_SIZE
    return f"""请审核以下章节标题：

{{draft}}

审核要点：
1. 标题数量是否恰好为{BATCH_SIZE}个（每行一个）？
2. 是否存在重复或高度相似的标题？
3. 标题是否与故事走向一致？
4. 标题是否简洁有力（无编号前缀）？
5. 标题字数是否在合理范围内（建议12字以内）？
6. 标题是否具有吸引力和悬念感？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

TITLES_REVIEW_PROMPT: str = _titles_review_prompt()

def _arc_outline_review_prompt() -> str:
    from noval_workflow.config import BATCH_SIZE
    max_words = BATCH_SIZE * 500
    return f"""# 角色：你是专业网文弧线大纲质检专家
你的任务是严格审核以下批次弧线大纲，确保其格式规范、内容可落地、逻辑自洽。

## 待审核内容
{{draft}}

## 审核要点
1. 【格式结构】是否按【章节X】分段？每章是否包含全部7个必填字段（本章核心事件 / 人物行动 / 情节转折 / 节奏&情绪锚点 / 伏笔&线索 / 创作锚点 / 下章衔接指引）？
2. 【字数约束】单章内容是否超过500字？全批合计是否超过{max_words}字？
3. 【情节承接】是否与上一批结尾情节连贯，无断层、无跳跃矛盾？
4. 【大纲对齐】是否贴合作品整体主线大纲，未偏离核心世界观、势力设定、人物人设？
5. 【创作锚点】各章"创作锚点"字段是否具体，可供标题和正文创作直接使用？
6. 【伏笔标注】新增伏笔、回收伏笔是否在"伏笔&线索"字段中明确标注？

## 输出规范
如内容合格，只输出：无问题
否则逐条指出问题，并给出具体修改建议。"""

ARC_OUTLINE_REVIEW_PROMPT: str = _arc_outline_review_prompt()

CHARACTER_STATUS_REVIEW_PROMPT = """请审核以下人物动态状态更新：

{draft}

审核要点：
1. 是否准确反映了最新章节中人物的状态变化？
2. 是否与人物档案及之前状态保持一致？
3. 关键人物是否都有涵盖？
4. 信息是否清晰、便于后续创作参考？
5. 与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CHARACTER_RELATIONS_REVIEW_PROMPT = """请审核以下人物关系/势力格局更新：

{draft}

审核要点：
1. 是否准确反映了最新章节中关系的变化？
2. 是否存在与前文矛盾的关系描述？
3. 主要势力格局是否清晰？
4. 信息是否简洁易用？
5. 与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

FORESHADOWING_REVIEW_PROMPT = """请审核以下伏笔台账更新：

{draft}

审核要点：
1. 新增伏笔是否确实在最新章节中出现？
2. 已收伏笔是否确实在最新章节中兑现？
3. 悬置伏笔列表是否完整，无遗漏？
4. 格式是否清晰（新增/已收/悬置标注）？
5. 与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

格式要求：

## 单条伏笔固定结构（必须全覆盖）
-------------------------------------
【伏笔编号】F00
【伏笔名称】4-12字极简概括
【埋点批次】当前创作批次 / 章节区间
【当前潜伏表现】浅层、日常、隐蔽、不突兀的细节铺垫，读者看不出是伏笔
【核心作用】支撑后期人设反转、剧情冲突、世界观闭环、势力博弈、情感弧光等
【预定回收区间】仅锁定大阶段（卷/批次范围，不锁具体章节）
【自由度】高 / 中 / 低
【是否已回收】是 / 否


如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

PHASE_SUMMARY_REVIEW_PROMPT = """请审核以下阶段固化数据更新：

{draft}

审核要点：
1. 主角等级/境界数据是否与最新章节一致？
2. 装备/技能/道具信息是否有遗漏或错误？
3. 资源/人脉数据是否准确？
4. 是否有与前文设定矛盾的硬性数据？
5. 与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""
