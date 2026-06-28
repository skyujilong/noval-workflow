"""Task prompt constants for each generation step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Union

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


class _PromptState(Protocol):
    character_status: str
    character_relations: str
    foreshadowing: Union[str, dict]  # 支持旧格式（str）和新结构化格式（dict）
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
    return f"""你是擅长轻小说架构的资深作家，擅长以【角色群像 + 对话关系 + 强主角视角】搭建四卷式长篇顶层框架。
任务：搭建本书四卷式整体顶层大纲 + 全局结局定位，只做战略骨架，不填充具体章节、台词、场景细节。
严格遵守以下硬性创作规则：
全书固定四段式起承转合，划分为四卷。每卷必须写明：阶段定位、本卷核心事件、主角与核心角色关系变化、卷内人物群像互动大势、阶段性情绪落点、高潮设计、本卷结束时主角/主角团状态变化；全书体量：{word_count_desc}。
双线并行设计：一条明主线为外部事件/任务/冒险推进线，一条隐藏暗线为角色关系/信任/身份揭秘线，暗线最终与主线交汇完成情感与逻辑闭环。
人物规则：仅敲定主角+核心配角群的人物关系演变、立场变化、成长弧光大轨迹，不锁定具体相遇时机、对话内容、互动桥段、搞笑场景、情感爆发台词。保留角色动态调整空间。
势力/规则格局：只梳理世界观规则、校园/组织/势力关系的大势变化，不锁定单次冲突胜负、临时规则、新增社团或小团体。
强制留白清单，以下细节一律不写、不预设、不规划：具体章节剧情、具体台词与吐槽、角色内心独白、搞笑桥段、日常场景细节、单场战斗过程、情感互动细节、一次性的突发事件结果、临时新增角色/势力的设定。所有微观内容留给后续细分小大纲。
结局规范：仅锁定结局情感基调、主角与核心角色关系终态、全书核心立意；具体收尾场景、角色最终细碎归宿、收尾台词全部留白。
整体硬性标准：四卷节奏层层递进，主角视角清晰，角色群像关系闭环，逻辑自洽，框架具备强延展性，方便后续改编为漫画/动画脚本。
输出要求：直接输出纯大纲正文，无需开场白、解释、标题，四卷内容分段清晰。"""

CHARACTER_PROFILES_PROMPT = """## 角色定位

你是精通轻小说立体人设、双线叙事、漫改人设架构的资深创作者。

## 任务目标

为全书生成可对接四卷式大纲、适配明暗双线、支持漫画 / 动画改编、零 OOC、分层立体的全套核心人物档案。

## 硬性创作规则

- **人设双层面强制拆分**：所有核心角色必须写出【表层公开人设（读者视角）】+【深层隐藏人设（作者暗线视角）】，表层合理自然、深层预埋伏笔，两层人设不冲突、可后期完美反转收束，全程服务主线求生剧情与暗线身份揭秘。
- **严格绑定四卷成长体系**：每位核心人物必须拥有四卷阶段性弧光轨迹，只写心性、立场、羁绊、认知的迭代大势，不填充具体情节、互动细节、台词桥段。
- **双线绑定规则**：人物秘密、异常行为、隐藏能力、立场偏差全部作为暗线素材，均匀预埋至四卷剧情，做到明线推进生存冒险、暗线推进人物真相与信任崩塌 / 重建，双线深度咬合。
- **人设绝对自洽**：所有角色具备明确软肋、原生缺陷、心理枷锁、立场理由，无绝对善恶，所有对立、抉择、背叛、牺牲均源于人物底层逻辑，杜绝脸谱化、工具人、强行降智。
- **视觉标识轻描淡写**：每位核心角色最多保留 1 个低调、自然的视觉锚点或行为特征（如眼镜、旧围巾、攥袖口等），仅用于快速辨识，不用于高频复读。人设通过对话、选择、反应建立，禁止靠口头禅、固定动作、服饰细节反复刷标签。
- **严格沿用全局留白规则**：只撰写人物骨架设定、底层逻辑、成长大势、立场羁绊、能力短板、秘密底色。禁止撰写具体日常、具体互动、具体台词、具体战斗画面、细碎心理活动。
- **反派分层设计**：区分「阶段功能性反派」与「终极根源反派」，明确动机根源、冲突本质、阶段性作用、闭环退场逻辑，保留人性复杂度。
- **人物关系闭环**：全员羁绊围绕主角构建 —— 情感位、信任位、冲突位、对立位、功能位清晰，关系演变贴合四卷剧情推进，无割裂、无狗血、无逻辑 BUG。

## 输出规范

- 主角档案精细化全覆盖，配角精简高质不冗余，反派立体不扁平。
- 整体文风官方、干净、立体、适配轻小说出版级人设档案，逻辑闭环、伏笔可落地、支持长期连载不崩人设。
- **直接输出人物档案正文，无需额外开场白、解释、标题套话。**"""

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

    return f"""你是深耕日系轻小说创作多年的知名职业作家，擅长校园群像、灾变求生题材，精通明暗双线叙事、伏笔预埋，笔下人物立体鲜活，文风适配漫画与动画改编。
    
请撰写第{chapter_num}章：《{title}》

全书章节目录（供参考）：
{all_titles_text}{context_section}

### 核心创作强制规则
1. 人设严格合规：100%遵循全书官方人物档案，守住角色性格、行事底线、核心动机，**严禁OOC、人设崩坏、性格前后矛盾**；人物关系、阵营、立场保持连贯统一。专属小动作、外形标识、口头禅等标志特征，仅在情绪转折或剧情关键点自然露出，普通场景中禁止高频复读。
2. 剧情与双线要求：承接前文情节、细节与已有伏笔，明线正常推进主线剧情，**暗线循序渐进埋设线索、释放疑点**，不强行揭秘、不中断伏笔，明暗双线自然咬合。
3. 文体风格（标准日系轻小说）：
   - 采用**主角限知视角**，视角贯穿全章，不随意跳转；
   - 大量对话、句式短句化、段落细碎，营造呼吸感，拒绝大段冗长铺叙；
   - 侧重感官描写、人物微动作、神态特写，场景描写服务角色情绪与氛围；
   - 适度加入主角细腻心绪、内心吐槽，不泛滥、不脱离人物性格；
   - 以人物对话、互动、行为作为主要剧情驱动力，对话简洁自然，贴合角色身份。
4. 镜头与漫改适配：关键画面、情绪爆发点、场景转折处做镜头式特写，画面感突出；但避免把角色标志性道具/动作做成机械复读标签，同一标志特征在单章中最多自然出现 1-2 次。
5. 章节节奏：单章结构完整，中段设置小冲突/悬念/情绪波动，**章节结尾预留剧情钩子**，引导下一章内容；全章字数贴近预设单章标准字数。
6. 世界观合规：严格遵循本作世界观、势力规则、场景设定，不新增脱离原著的设定与道具。

### 【关键去机械化：人物动作克制规则】
角色专属癖好、标志性小动作、口头禅、信物特征，**禁止高频、机械、重复性刷人设**。
- 每章中，同一角色的口头禅或标志性动作**最多自然出现 1-2 次**，超出即视为复读。
- 仅在角色出现：情绪波动、内心警惕、紧张迟疑、剧情转折、伏笔触发时**选择性露出**。
- 普通日常对话、走路、平淡场景一律弱化隐藏标志动作，保持真人自然感，杜绝AI复读式人设描写。

### 【对话占比专项规则】
**整体对话占比60%-70%**，除以下情况可酌情减少外，其他场景一律严格要求60%以上占比：
- 单人独处、暗中观察、埋设伏笔的桥段，适当降低对话比例，以动作、神态、简短思绪为主。

禁止添加无意义闲聊、水台词凑篇幅，所有对话贴合人物身份与当下状态，服务剧情与人物关系。

❌ 错误示例（对话太少，叙述中式化、沉闷）：
> 林默走到窗边，望着外面灰蒙蒙的天空。街道上一片死寂，只有远处偶尔传来丧尸的低吼。他握紧手中的棒球棍，心中暗自思索着接下来该怎么办。他回头看了眼苏晓，发现她正紧张地抱着膝盖。气氛压抑得让人喘不过气。

✅ 正确示例（对话占比高，短句、神态、互动穿插，轻小说风格）：
> "喂，你别再靠窗了。"苏晓压低声音，手指死死攥着外套下摆。
> "我知道。"林默把棒球棍往肩上一扛，眼睛却没离开楼下那只晃过去的丧尸，"但它好像……闻不到我们？"
> "你确定？"
> "不确定。"他终于转过身，嘴角扯出一个很淡的笑，"所以你能不能先把手松开？你再攥下去，那件衣服就报废了。"
> 苏晓愣了一下，低头看向自己的手指。她慢慢松开，声音轻得像呼吸："……我控制不住。"

### 输出硬性规范（严格执行）
仅输出**章节纯正文**，开篇直接进入故事叙述，无额外解释、说明、修改备注、格式标注、开场白、结束语。

❌ 绝对禁止出现：修改说明、调整建议、原文对照、批注、解读、任务复述等一切非正文内容。
✅ 格式示例：直接以故事第一句起笔，连贯书写全文。

请直接输出章节正文"""


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
6. 人物行动以互动、对话、关系变化为核心，事件推进由角色反应与选择驱动，而非纯外部任务推进。

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

**固定输出格式（每位关键角色一组，按角色分块）**

角色：XXX
【当前状态/定位】（当前实力层级、身份或队伍中的角色定位，≤20字）
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

CHARACTER_PROFILES_REVIEW_PROMPT = """作为资深轻小说创作者，请审核以下【人物档案】：

{draft}

主角塑造：背景履历、性格特质、行为动机、原生弱点、核心诉求、四卷阶段性成长弧光是否完整、逻辑自洽、具备说服力，无人设断层。
角色差异化：主要配角、阶段性反派、终极反派人设区分度是否足够，能力、性格、立场、职能无重复重叠，拒绝同质化、工具人角色。
人物关系：全员羁绊、阵营立场、情感联结、敌我冲突是否清晰统一，无前后矛盾、逻辑漏洞、狗血割裂设定。
世界观适配：所有角色的能力、立场、过往、行事逻辑，是否贴合本作世界观规则与核心剧情冲突。
视觉 & 记忆点：每位核心角色具备可辨识但不喧宾夺主的低调特征；核查人物档案是否过度堆砌口头禅、标志动作或服饰标签，正文中是否可能触发高频复读。适配漫画、动画镜头表现，但拒绝标签化复读。
双线适配：区分角色表层公开人设与深层隐藏暗线人设，核查两层人设是否互不冲突、伏笔预埋自然，可支撑后续身份揭秘、剧情反转。
人设稳定性：排查 OOC 风险，角色性格、底线、行事准则是否统一，善恶立场具备复杂性，无脸谱化、强行降智设计。
篇幅规范：整体总字数是否控制在 500-2000 字区间。

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
2. 人物性格是否与人物档案一致，是否存在OOC或人设崩坏？
3. 情节是否符合故事走向，明暗双线是否自然咬合？
4. 是否存在前后矛盾或伏笔中断？
5. 字数是否接近系统设定的每章字数目标？
6. 情节走向是否符合系统提示中当前批次的弧线大纲？
7. 轻小说风格合规性：
   - 是否采用主角限知视角，视角是否稳定不随意跳转？
   - 对话占比是否达到60%-70%，是否存在叙述过多、对话过少的中式沉闷写法？
   - 是否存在口头禅、标志性动作、服饰细节等机械复读（单章出现超过1-2次即视为问题）？
   - 是否以人物对话、互动、行为驱动剧情，而非大段环境/心理铺叙？
8. 章节结尾是否预留剧情钩子，是否能引导下一章？
9. 是否直接输出正文，无修改说明、批注、开场白、结束语等非正文内容？

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

FORESHADOWING_REVIEW_PROMPT = """请审核以下伏笔台账更新（JSON 格式）：

{draft}

审核要点：
1. JSON 格式是否有效，无语法错误？
2. 新增伏笔是否确实在最新章节中出现？
3. 已收伏笔是否确实在最新章节中兑现？
4. pending（悬置）伏笔列表是否完整，无遗漏？
5. 与上次快照相比，是否有条目被无故遗漏？（未变化的项目应在本次输出中保留）

JSON 字段规范：
- pending 数组：悬置（未回收）的伏笔，每个对象包含：id, name, planted_batch, current_appearance, core_purpose, planned_recovery_range, freedom
- collected 数组：已收（已兑现）的伏笔，每个对象除上述字段外还必须包含 recovered_at_chapter
- planted_batch：必须是纯数字（不要有"第X批"等文字）
- recovered_at_chapter：必须是纯数字（不要有"第X章"等文字）
- freedom：只能是 "高"、"中"、"低" 三者之一

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""

# 伏笔精简分析提示词（仅在审核通过后调用）

FORESHADOW_PRUNE_ANALYSIS_PROMPT = """请分析以下伏笔台账，给出精简建议。

【参考上下文】
近3章章节概要：{recent_summaries}

全书章节标题（共{all_titles_count}章）：
{all_titles}

世界观设定：
{world_building}

人物档案：
{character_profiles}

【当前伏笔台账 JSON】
{foreshadowing_json}

【精简规则】
1. S级核心伏笔（与主线/主角成长/核心谜团强相关）：必须全部保留，不标注删除
2. A级次要伏笔（支线、配角相关）：最多保留最近10个，老的建议删除
3. 已收伏笔（collected）：超过5章且非S级的，建议从列表中移除（已兑现无需跟踪）
4. 同类型重复伏笔：建议合并或删除
5. planted_batch 越小表示埋点批次，数值越小越老，优先建议删除老的

【输出格式】
请严格按以下JSON格式输出，不要包含任何额外说明文字：
{{
  "s_level_count": 3,
  "a_level_count": 8,
  "to_delete": [
    {{
      "id": "F01",
      "name": "伏笔名称",
      "reason": "已回收超过5章，非核心伏笔"
    }}
  ],
  "suggestion": "整体精简建议（一句话）"
}}

【重要提醒】
- to_delete 数组只包含建议删除的伏笔ID和名称
- S级核心伏笔绝对不能出现在 to_delete 中
- A级伏笔超过10个时，优先建议删除 planted_batch 最小（最老）的
- 如果当前伏笔数量很少（≤5个），to_delete 可以为空数组
- 只分析 pending 数组中的伏笔，collected 只在超过5章且非S级时才建议删除
"""

PHASE_SUMMARY_REVIEW_PROMPT = """请审核以下阶段固化数据更新：

{draft}

审核要点：
1. 【格式】每位关键角色是否均有独立分块？每块是否包含全部6个固定字段：【当前状态/定位】【核心能力】【装备/道具】【资源/人脉】【承诺/债务】【特殊限制】？
2. 【准确性】各字段内容是否与最新章节一致，有无遗漏或错误？
3. 【矛盾】是否有与前文设定矛盾的硬性数据？
4. 【完整性】与上次快照相比，是否有角色或条目被无故遗漏？（未变化的项目应在本次输出中保留）

如内容合格，只输出：无问题
否则指出具体问题并给出修改建议。"""
