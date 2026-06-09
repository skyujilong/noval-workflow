"""Task prompt constants for each generation step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


class _PromptState(Protocol):
    character_status: str
    character_relations: str
    foreshadowing: str
    phase_summary: str
    total_chapters_written: int

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
    return f"""你是深耕长篇架构的资深小说作家，擅长搭建长线开放式长篇故事顶层框架。
任务：完整搭建本书四卷式整体顶层大纲 + 全局结局定位，只做战略长线骨架，绝不填充章节细碎内容。
严格遵守以下硬性创作规则：
全书固定四段式起承转合，划分为四卷，逐一写明每一卷：阶段定位、核心主线、该卷整体基调、阶段核心目标、卷内核心困境、整卷大势走向、高潮设计、终极威胁【看书的题材是否要出这个选项内容】；全书体量：{word_count_desc}。
双线并行设计：一条明主线贯穿四卷全程，一条隐藏暗线同步铺展，暗线最终会与主线交汇完成逻辑闭环。
人物规则：仅敲定所有核心主角完整成长弧光大轨迹，不锁定任意阶段情绪波动、相遇时间、冲突时机、牺牲与否、互动桥段，全程保留人物动态调整空间。
势力格局：只梳理四卷全局势力演变大势、阵营强弱更迭大趋势，不锁定小派系摩擦、单次博弈胜负、局部势力覆灭时间点。
强制留白清单，以下所有细节一律不写、不预设、不规划：具体章节剧情、配角生死命运、单场战斗过程与打法、怪物对战细节、地形实操利用、资源搜集手段、男女情感具体桥段、单次突发事件结果、临时新增角色 / 新增势力的设定。所有微观落地内容全部留给后续细分小大纲填充。
结局规范：仅锁定结局整体基调、全书核心立意两大关键项；结局具体收尾场景、角色最终细碎归宿、收尾事件全部留白，支持后续开放式微调、小幅改写。
整体硬性标准：四层卷目节奏层层递进，整体故事逻辑自洽闭环，框架具备极强延展性，允许后续剧情扩充、支线追加、局部剧情微调改动。
输出要求：直接输出纯大纲正文，无需额外开场白、解释、多余标题，四卷内容分段清晰区分。"""

CHARACTER_PROFILES_PROMPT = """请为本小说创建【人物档案】。

请根据全书整体大纲、剧情脉络与世界观设定，生成一套逻辑自洽、人设立体、无 OOC、适配全篇剧情的核心人物档案，严格遵循以下通用创作规则：

人设全程贴合作品世界观、剧情走向、势力迭代与明暗主线，人物性格、行为动机、价值立场、成长轨迹完全自洽，无前后矛盾、无逻辑割裂、无崩坏人设。
主角档案深度精细化撰写，完整覆盖：背景履历、外在特质、内在性格、原生弱点、核心诉求、阶段性成长弧光、团队 / 剧情定位、个人底线与行事准则，成长轨迹随剧情递进迭代，具备完整人物闭环。
主要配角精简精准选取 2-4 人，重点撰写专属能力特质、核心剧情职能、团队价值、人物短板，以及对主角成长、剧情推进的关键作用，拒绝流水账、无效信息与工具人化设定。
对立 / 反派角色分层撰写，区分阶段性反派与终极核心反派，清晰标注人物原生动机、行事逻辑、立场根源、与主角阵营的核心冲突、阶段剧情定位及退场逻辑，拒绝脸谱化纯善恶人设，保留人性与立场复杂性。
统一梳理全员人物关系、羁绊联结、立场对立体系，情感羁绊、团队羁绊、敌我冲突完全闭环，无逻辑漏洞、无狗血割裂设定。
全文文风贴合作品整体调性，简洁高级、写实立体，字数控制在 500-2000 字，适配官方人设档案标准。
所有人物摒弃单一扁平标签，善恶、取舍、抉择、立场均贴合剧情语境，保留人物复杂性与成长性，全程规避人设固化、行为割裂问题。"""

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

# 7-field format shared by arc_outline_prompt and _rewrite_arc_with_ai
ARC_CHAPTER_FORMAT = """\
## 单章节固定必填字段（每章必须依次列出，缺一不可）
【章节X】
1. 本章核心事件：一句话概括本章主线行为与场景
2. 人物行动：核心角色、配角的具体动作、分工、互动行为
3. 情节转折：本章出现的冲突、反转、变故、突发危机
4. 节奏&情绪锚点：标注本章节奏（平缓/紧张/爆发/悬疑）、核心情绪（愤怒/恐惧/释然/警惕等）、网文看点（爽点/悬念/铺垫/虐点）
5. 伏笔&线索：本章新增伏笔、回收前文伏笔、遗留待解线索
6. 创作锚点：为章节标题、正文细节描写提供关键词/方向指引
7. 下章衔接指引：本章收尾状态，明确下一章开篇切入方向"""


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

    is_first_batch = state.total_chapters_written == 0
    continuity_rule = (
        "1. 作为本书第一批章节，请严格按照整体大纲的开篇定位规划故事起点，奠定世界观、人物关系与核心冲突的基调。"
        if is_first_batch else
        "1. 严格承接上一批大纲最终结尾情节，情节逻辑连贯、无断层，全程贴合作品整体主线大纲，不偏离核心世界观、势力设定、人物人设与核心冲突。"
    )

    max_words = BATCH_SIZE * 500
    return f"""请为本批接下来的 {BATCH_SIZE} 章规划故事弧线大纲。{prev_section}

# 角色：你是专业网文分章弧线大纲撰写师
## 整体约束
{continuity_rule}
2. 本批次所有章节大纲总字数严格控制在 {max_words} 以内；**单章节内容节点文字不得超过500字**，精简表述，拒绝冗余描写、抒情、旁白。
3. 仅输出结构化章节大纲，不撰写正文内容、不生成章节标题，仅为标题、正文创作提供明确锚点。

{ARC_CHAPTER_FORMAT}

## 内容创作规则
1. 严守作品既定设定：类型一致、战力体系、物资规则、队伍规矩、人物关系、势力矛盾，不新增私设、不强行降智/拔高角色。
2. 冲突设计循序渐进，支线服务主线，不随意新增无关人物、无关支线，避免剧情散乱。
3. 动作、对话、冲突符合人物性格，角色行为逻辑自洽，保持人设统一。
4. 涉及战斗、对峙、逃生场景，写明攻防动作、敌我态势，细节具备可落地性。
5. 物资、伤亡、环境等细节贴合本作世界观设定，逻辑严谨。

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


def _prune_collected_foreshadowing(ledger: str, current_chapter: int) -> str:
    """Remove 【已收】entries whose 【回收章节】is more than _FORESHADOW_PRUNE_DISTANCE chapters back.

    Each entry is delimited by the dashed separator line. Entries without a
    【回收章节】field (older format or 【是否已回收】否) are kept as-is.
    """
    import re

    separator = "-------------------------------------"
    blocks = ledger.split(separator)
    kept: list[str] = []
    for block in blocks:
        # Check if this block is a collected entry
        if "【是否已回收】是" in block:
            m = re.search(r"【回收章节】第?(\d+)章?", block)
            if m:
                collected_at = int(m.group(1))
                if current_chapter - collected_at > _FORESHADOW_PRUNE_DISTANCE:
                    continue  # physically drop this entry
        kept.append(block)
    return separator.join(kept)


def foreshadowing_prompt(state: _PromptState, chapter_context: str = "") -> str:
    """Build the prompt for updating the foreshadowing ledger."""
    current_chapter = state.total_chapters_written  # chapters completed so far
    current_chapter_info = f"第{current_chapter}章" if current_chapter > 0 else "起始"

    prev = ""
    if state.foreshadowing:
        pruned = _prune_collected_foreshadowing(state.foreshadowing, current_chapter)
        prev = f"\n\n【上次伏笔台账】\n{pruned}"

    chapter_section = ""
    if chapter_context:
        chapter_section = f"\n\n【近期章节内容（请据此核对伏笔）】\n{chapter_context}"

    carry_over = "\n- 【悬置】列出当前所有仍待兑现的伏笔，必须包含上次台账中全部悬置项，本批无变化者原文保留" if prev else "\n- 【悬置】列出当前章节中出现的所有待兑现伏笔"
    return f"""请根据已完成的章节内容，更新【伏笔台账】。当前所处章节：{current_chapter_info}。{prev}{chapter_section}

要求：{carry_over}
- 【新增】标注本批章节中首次埋下的新伏笔
- 【已收】标注本批被兑现或回收的伏笔（【是否已回收】"是"，并填写【回收章节】）
  - 需要调整顺序到【悬置】下方
  - 已回收的伏笔，在当前章节减去回收章节超过5章的，可以直接删除，用来节省上下文。

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
【回收章节】第X章（仅【是否已回收】为"是"时填写，否则留空）



请直接输出更新后的伏笔台账，不需要标题。"""


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

**固定输出格式（每位关键角色一组，按角色分块）**

角色：XXX
【等级/境界】（当前实力层级，≤20字）
【核心能力】（已掌握的关键技能/能力，每条≤20字，可多条）
【装备/道具】（当前持有的重要物品，每条≤20字，可多条）
【资源/人脉】（可调用的资源、关键人脉，每条≤20字，可多条）
【承诺/债务】（未了结的承诺、欠债、义务，每条≤20字，无则写"无"）
【特殊限制】（对该角色行动有约束的条件，每条≤20字，无则写"无"）

请直接输出更新后的阶段固化数据，不需要额外标题。"""


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
5. 字数是否接近系统设定的每章字数目标？
6. 情节走向是否符合系统提示中当前批次的弧线大纲？

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
1. 【格式】每位关键角色是否均有独立分块？每块是否包含全部4个固定字段：【当前位置】【情绪/状态】【当前目标】【关键处境】？
2. 【准确性】各字段内容是否与最新章节一致，有无遗漏或错误？
3. 【字数】【当前位置】≤15字，【情绪/状态】≤15字，【当前目标】≤20字，【关键处境】≤30字？
4. 【一致性】是否与人物档案及前文设定保持一致？
5. 【完整性】与上次快照相比，是否有角色或字段被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

CHARACTER_RELATIONS_REVIEW_PROMPT = """请审核以下人物关系/势力格局更新：

{draft}

审核要点：
1. 【格式】是否分为【人物关系】和【势力格局】两块？人物关系是否为"角色A → 角色B：描述"格式？势力格局是否为"势力名：状态描述"格式？
2. 【字数】人物关系每条描述≤20字，势力格局每条≤30字？
3. 【准确性】是否准确反映了最新章节中关系的变化？有无与前文矛盾的描述？
4. 【完整性】与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

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
1. 【格式】每位关键角色是否均有独立分块？每块是否包含全部6个固定字段：【等级/境界】【核心能力】【装备/道具】【资源/人脉】【承诺/债务】【特殊限制】？
2. 【准确性】各字段内容是否与最新章节一致，有无遗漏或错误？
3. 【矛盾】是否有与前文设定矛盾的硬性数据？
4. 【完整性】与上次快照相比，是否有角色或条目被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""
