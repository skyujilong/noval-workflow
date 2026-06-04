"""Task prompt constants for each generation step."""

from __future__ import annotations

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
- 字数：500-1000字

请直接输出大纲内容，不需要标题。"""

CHARACTER_PROFILES_PROMPT = """请为本小说创建【人物档案】。

要求：
- 主角：详细描述背景、性格、动机、成长弧线
- 主要配角（2-4人）：简要描述各自特点与作用
- 反派/对立角色：描述其动机与与主角的关系
- 确保人物关系清晰，避免相互矛盾
- 字数：500-1000字

请直接输出人物档案内容，不需要标题。"""

# Phase 2: Chapter prompts

def titles_prompt(all_titles: list[str], chapter_context: str = "") -> str:
    """Build the prompt for generating next batch of 5 chapter titles."""
    existing = ""
    if all_titles:
        existing = "\n\n已有章节标题（请勿重复）：\n" + "\n".join(
            f"{i+1}. {t}" for i, t in enumerate(all_titles)
        )

    context_section = ""
    if chapter_context:
        context_section = f"\n\n【前文故事进展（请据此规划后续走向）】\n{chapter_context}"

    return f"""请为本小说生成下5章的章节标题。{existing}{context_section}

要求：
- 每行一个标题，共5行
- 标题简洁有力（4-12字），与故事情节紧密相关
- 不要添加序号、标点或其他前缀
- 标题不得与已有章节重复
- 标题须符合系统提示中的整体大纲方向，体现故事在当前阶段应有的发展走向
- 标题须与前文章节保持时间线与情节的连贯，不得跳跃或产生矛盾
- 5个标题之间应形成自然的叙事流，层层递进，避免互不相关的孤立命名

请直接输出5个标题，每行一个。"""


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

TITLES_REVIEW_PROMPT = """请审核以下章节标题：

{draft}

审核要点：
1. 标题数量是否恰好为5个（每行一个）？
2. 是否存在重复或高度相似的标题？
3. 标题是否与故事走向一致？
4. 标题是否简洁有力（无编号前缀）？

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""
