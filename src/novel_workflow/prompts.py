"""Task prompt constants for each generation step."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from noval_workflow.state import NovelState

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

OVERALL_OUTLINE_PROMPT = """请为本小说制定【整体大纲与结局】。

要求：
- 按照起承转合结构规划全书脉络
- 分阶段描述故事走向（开篇、发展、高潮、结局）
- 明确结局走向（开放/封闭，悲剧/喜剧/悲喜交加）
- 确保结局与核心冲突、主题呼应
- 字数：2500–3500字

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

    return f"""请为本批接下来的 {BATCH_SIZE} 章规划故事弧线大纲。{prev_section}

要求：
- 用200-400字规划本批章节的核心故事弧线节点
- 列出各节点的主要事件、人物行动、情节转折
- 确保本批弧线与整体大纲方向一致，并在上一批结束处自然衔接
- 为后续生成标题和章节内容提供方向锚点

请直接输出本批弧线大纲内容，不需要标题。"""


def character_status_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """Build the prompt for updating character dynamic status."""
    prev = ""
    if state.character_status_history:
        prev = f"\n\n【上次人物状态快照】\n{state.character_status_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新状态）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【人物动态状态】。{prev}{chapter_section}

要求：
- 涵盖主角及主要配角的当前状态（位置、情绪、目标、处境）
- 记录本批章节中发生的重要变化
- 格式清晰，便于后续章节创作时快速查阅
- 字数：150-300字

请直接输出更新后的人物动态状态，不需要标题。"""


def character_relations_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """Build the prompt for updating character relations and faction dynamics."""
    prev = ""
    if state.character_relations_history:
        prev = f"\n\n【上次关系/势力快照】\n{state.character_relations_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新关系）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【人物关系/势力格局】。{prev}{chapter_section}

要求：
- 记录主要人物之间的关系变化（友好/敌对/中立/合作）
- 记录各势力的当前格局与力量对比
- 标注本批章节中发生的关系转变
- 字数：150-300字

请直接输出更新后的人物关系/势力格局，不需要标题。"""


def foreshadowing_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """Build the prompt for updating the foreshadowing ledger."""
    prev = ""
    if state.foreshadowing_history:
        prev = f"\n\n【上次伏笔台账】\n{state.foreshadowing_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此核对伏笔）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【伏笔台账】。{prev}{chapter_section}

要求：
- 列出本批新增的伏笔（标注"新增"）
- 列出本批已收回/兑现的伏笔（标注"已收"）
- 列出仍悬置等待兑现的伏笔（标注"悬置"）
- 格式清晰，每条伏笔一行
- 字数：100-250字

请直接输出更新后的伏笔台账，不需要标题。"""


def phase_summary_prompt(state: "NovelState", chapter_context: str = "") -> str:
    """Build the prompt for updating phase-frozen hard data."""
    prev = ""
    if state.phase_summary_history:
        prev = f"\n\n【上次阶段固化数据】\n{state.phase_summary_history[-1]}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【已完成章节内容（请据此更新硬性数据）】\n{chapter_context}"

    return f"""请根据已完成的章节内容，更新【阶段固化数据】。{prev}{chapter_section}

要求：
- 记录主角的当前等级/境界/能力水平
- 记录主角的重要装备、技能、道具
- 记录主角当前掌握的资源/人脉/势力
- 记录其他需要在后续创作中严格遵守的硬性数据
- 字数：150-300字

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

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

TITLES_REVIEW_PROMPT: str = _titles_review_prompt()

ARC_OUTLINE_REVIEW_PROMPT = """请审核以下批次小号大纲：

{draft}

审核要点：
1. 是否覆盖了本批所有章节应有的故事节点？
2. 是否与整体大纲方向保持一致，无明显偏离？
3. 弧线节点是否层次分明，有起伏变化？
4. 是否与前文故事自然衔接，无跳跃矛盾？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CHARACTER_STATUS_REVIEW_PROMPT = """请审核以下人物动态状态更新：

{draft}

审核要点：
1. 是否准确反映了最新章节中人物的状态变化？
2. 是否与人物档案及之前状态保持一致？
3. 关键人物是否都有涵盖？
4. 信息是否清晰、便于后续创作参考？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CHARACTER_RELATIONS_REVIEW_PROMPT = """请审核以下人物关系/势力格局更新：

{draft}

审核要点：
1. 是否准确反映了最新章节中关系的变化？
2. 是否存在与前文矛盾的关系描述？
3. 主要势力格局是否清晰？
4. 信息是否简洁易用？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

FORESHADOWING_REVIEW_PROMPT = """请审核以下伏笔台账更新：

{draft}

审核要点：
1. 新增伏笔是否确实在最新章节中出现？
2. 已收伏笔是否确实在最新章节中兑现？
3. 悬置伏笔列表是否完整，无遗漏？
4. 格式是否清晰（新增/已收/悬置标注）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

PHASE_SUMMARY_REVIEW_PROMPT = """请审核以下阶段固化数据更新：

{draft}

审核要点：
1. 主角等级/境界数据是否与最新章节一致？
2. 装备/技能/道具信息是否有遗漏或错误？
3. 资源/人脉数据是否准确？
4. 是否有与前文设定矛盾的硬性数据？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""
