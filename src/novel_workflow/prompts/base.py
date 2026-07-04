"""提示词包核心：GenreFlavor（题材差异化片段）+ PromptPack（通用脚手架 + 风味组装）。

设计要点：
- 通用脚手架（人设合规、剧情双线、章节节奏、世界观合规、去机械化、输出规范、
  titles 的"每行一个/不重复"、arc 的 7 字段格式等）放本文件，所有题材共享。
- 题材专属内容（身份描述、章节文风规则、风格示例、各步骤聚焦补充、章节审核
  文风检查清单）由 GenreFlavor 提供，每个题材文件只填差异化部分。
- 提示词包对象不入 langgraph state；节点执行时按 state.genre 通过
  registry.get_prompt_pack() 加载。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Union

if TYPE_CHECKING:
    from noval_workflow.state import NovelState


# ── 共享常量 ───────────────────────────────────────────────────────────────────

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


# 7-field format shared by arc_outline_prompt (本文件) 与 arc_edit_subgraph 的内联大纲提示词
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


def _extract_arc_chapter_block(arc_outline: str, batch_pos: int) -> str:
    """从「本批弧线大纲」中抽取第 batch_pos 章（1-based，按批内出现顺序）的固定字段块。

    弧线大纲按 ARC_CHAPTER_FORMAT 以【章节X】分隔；X 既可能是批内序号也可能是全书序号，
    故按「出现顺序」定位而非字面数字匹配，对两种编号方式都鲁棒。无法切分（格式异常或
    章节段落数不足 batch_pos）时返回空串，调用方回退到系统提示中的整批大纲。
    """
    if not arc_outline or batch_pos < 1:
        return ""
    headers = list(re.finditer(r"【\s*章节[^】]*】", arc_outline))
    if len(headers) < batch_pos:
        return ""
    start = headers[batch_pos - 1].start()
    end = headers[batch_pos].start() if batch_pos < len(headers) else len(arc_outline)
    return arc_outline[start:end].strip()


class _PromptState(Protocol):
    """台账类提示词所需的状态结构类型（ledger.py 使用）。"""
    character_status: str
    character_relations: str
    foreshadowing: Union[str, dict]  # 支持旧格式（str）和新结构化格式（dict）
    phase_summary: str
    total_chapters_written: int


# ── GenreFlavor：题材差异化片段 ───────────────────────────────────────────────


@dataclass
class GenreFlavor:
    """单一题材的差异化风味片段。通用脚手架由 PromptPack 组装，这里只填差异。

    必填字段是题材调优的主要面；可选 *_focus 默认空串，追加到对应步骤的通用
    脚手架末尾，用于补充题材聚焦要求，不影响默认结构。
    """

    # ── 必填：题材身份与主要调优面 ──────────────────────────────────────────
    system_identity: str
    """替换 build_foundation_context / overall_outline / character_profiles /
    chapter_prompt 开头的身份描述。应为一段完整的身份陈述，以句号结尾。"""

    chapter_style_rules: str
    """替换 chapter_prompt 中的"文体风格"段（含对话占比、镜头感等文风规则）。
    每个题材在此定义自己的叙事风格。"""

    chapter_example: str
    """替换 chapter_prompt 中的风格示例块（❌/✅ 对照示例），用本题材的典型场景。"""

    chapter_review_checklist: str
    """注入 CHAPTER_REVIEW_PROMPT 的 {style_checklist} 占位，作为章节审核的
    文风合规检查清单。"""

    # ── 可选：各创作步骤的题材聚焦补充（默认空串）──────────────────────────
    core_theme_focus: str = ""
    """核心主题步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    world_building_focus: str = ""
    """世界观构建步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    core_conflicts_focus: str = ""
    """核心冲突步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    character_profiles_focus: str = ""
    """角色档案步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    overall_outline_focus: str = ""
    """总大纲步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    titles_focus: str = ""
    """标题生成步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    arc_focus: str = ""
    """故事弧步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""

    # ── 自进化：历次人工反馈沉淀的强制整改要点（默认空）──────────────────────
    evolved_directives: str = ""
    """按小说累积的「历史整改要点」，来源于人工打回意见的提炼/整改库导入。
    追加到 chapter_prompt 末尾并声明为最高优先级：与上文冲突时以本节为准，
    本节内多条冲突时以更靠后（更新）者为准。默认空 → 对现有题材零影响。"""


# ── PromptPack：通用脚手架 + 风味组装 ─────────────────────────────────────────


def evolved_directives_block(directives: str) -> str:
    """把「历史整改要点」渲染成置于提示词末尾的最高优先级段；空则返回空串。

    章节正文/弧线大纲的首轮 prepare（chapter_prompt/arc_outline_prompt）与打回重跑
    （subgraph.generate 补注入）共用本函数，保证两处注入的整改文案完全一致。
    与上文任何规则/示例冲突时一律以本节为准；本节内多条冲突以更靠后（更新）者为准。
    """
    directives = directives.strip()
    if not directives:
        return ""
    return (
        "\n\n### ⚠️ 历史整改要点（最高优先级，务必执行）\n"
        "以下为依据历次人工反馈沉淀的强制修正项。"
        "**若与上文任何规则、风格示例或设定冲突，一律以本节为准**；"
        "本节内多条要点若彼此冲突，以更靠后（更新）的为准。\n"
        f"{directives}"
    )


class PromptPack:
    """完整提示词包。由 registry.get_prompt_pack(genre) 实例化，节点按 state.genre 加载。"""

    def __init__(self, genre: str, flavor: GenreFlavor):
        self.genre = genre
        self.flavor = flavor

    # ── Foundation 静态提示词（通用脚手架 + 可选 focus 追加）─────────────────

    @property
    def core_theme_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.core_theme_focus}" if self.flavor.core_theme_focus else ""
        return f"""请为本小说创作【核心主题与立意】。

要求：
- 用200-400字阐述小说的核心主题、价值观、哲学命题
- 明确作品想传递的核心思想
- 确保主题与类型、基调、目标读者相符{focus}

请直接输出主题内容，不需要标题。"""

    @property
    def world_building_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.world_building_focus}" if self.flavor.world_building_focus else ""
        return f"""请为本小说创作【世界观设定】。

要求：
- 详细描述故事发生的时代背景、地理环境、社会结构
- 包括独特的规则体系（魔法/科技/社会规范等，视类型而定）
- 说明世界的历史脉络与当前局势
- 字数：400-800字{focus}

请直接输出世界观内容，不需要标题。"""

    @property
    def core_conflicts_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.core_conflicts_focus}" if self.flavor.core_conflicts_focus else ""
        return f"""请为本小说设计【核心冲突】。

要求：
- 明确主要冲突类型（人与人、人与自然、人与社会、人与自我等）
- 列出2-4个核心冲突层次，并说明各层次的具体表现
- 冲突需与世界观、主题深度契合
- 字数：300-600字{focus}

请直接输出冲突设计内容，不需要标题。"""

    @property
    def character_profiles_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.character_profiles_focus}" if self.flavor.character_profiles_focus else ""
        return f"""## 角色定位

{self.flavor.system_identity}

## 任务目标

为全书生成可对接四卷式大纲、适配明暗双线、分层立体的全套核心人物档案。

## 硬性创作规则

- **人设双层面强制拆分**：所有核心角色必须写出【表层公开人设（读者视角）】+【深层隐藏人设（作者暗线视角）】，表层合理自然、深层预埋伏笔，两层人设不冲突、可后期完美反转收束，全程服务主线剧情与暗线揭秘。
- **严格绑定四卷成长体系**：每位核心人物必须拥有四卷阶段性弧光轨迹，只写心性、立场、羁绊、认知的迭代大势，不填充具体情节、互动细节、台词桥段。
- **双线绑定规则**：人物秘密、异常行为、隐藏能力、立场偏差全部作为暗线素材，均匀预埋至四卷剧情，做到明线推进主线、暗线推进人物真相与信任崩塌 / 重建，双线深度咬合。
- **人设绝对自洽**：所有角色具备明确软肋、原生缺陷、心理枷锁、立场理由，无绝对善恶，所有对立、抉择、背叛、牺牲均源于人物底层逻辑，杜绝脸谱化、工具人、强行降智。
- **视觉标识轻描淡写**：每位核心角色最多保留 1 个低调、自然的视觉锚点或行为特征（如眼镜、旧围巾、攥袖口等），仅用于快速辨识，不用于高频复读。人设通过对话、选择、反应建立，禁止靠口头禅、固定动作、服饰细节反复刷标签。
- **严格沿用全局留白规则**：只撰写人物骨架设定、底层逻辑、成长大势、立场羁绊、能力短板、秘密底色。禁止撰写具体日常、具体互动、具体台词、具体战斗画面、细碎心理活动。
- **反派分层设计**：区分「阶段功能性反派」与「终极根源反派」，明确动机根源、冲突本质、阶段性作用、闭环退场逻辑，保留人性复杂度。
- **人物关系闭环**：全员羁绊围绕主角构建 —— 情感位、信任位、冲突位、对立位、功能位清晰，关系演变贴合四卷剧情推进，无割裂、无狗血、无逻辑 BUG。{focus}

## 输出规范

- 主角档案精细化全覆盖，配角精简高质不冗余，反派立体不扁平。
- 整体文风官方、干净、立体，逻辑闭环、伏笔可落地、支持长期连载不崩人设。
- **直接输出人物档案正文，无需额外开场白、解释、标题套话。**"""

    @property
    def summary_prompt(self) -> str:
        """章节概要提示词，与题材无关，返回共享常量。"""
        return SUMMARY_PROMPT

    # ── 动态提示词（通用脚手架 + 风味片段）──────────────────────────────────

    def overall_outline_prompt(self, total_word_count: str) -> str:
        """生成全书四卷式整体顶层大纲 + 全局结局定位。"""
        word_count_desc = f"{total_word_count}字" if total_word_count else "长篇"
        focus = f"\n- 题材聚焦：{self.flavor.overall_outline_focus}" if self.flavor.overall_outline_focus else ""
        return f"""{self.flavor.system_identity}
任务：搭建本书四卷式整体顶层大纲 + 全局结局定位，只做战略骨架，不填充具体章节、台词、场景细节。
严格遵守以下硬性创作规则：
全书固定四段式起承转合，划分为四卷。每卷必须写明：阶段定位、本卷核心事件、主角与核心角色关系变化、卷内人物群像互动大势、阶段性情绪落点、高潮设计、本卷结束时主角/主角团状态变化；全书体量：{word_count_desc}。
双线并行设计：一条明主线为外部事件/任务/冒险推进线，一条隐藏暗线为角色关系/信任/身份揭秘线，暗线最终与主线交汇完成情感与逻辑闭环。
人物规则：仅敲定主角+核心配角群的人物关系演变、立场变化、成长弧光大轨迹，不锁定具体相遇时机、对话内容、互动桥段、搞笑场景、情感爆发台词。保留角色动态调整空间。
势力/规则格局：只梳理世界观规则、组织/势力关系的大势变化，不锁定单次冲突胜负、临时规则、新增小团体。
强制留白清单，以下细节一律不写、不预设、不规划：具体章节剧情、具体台词与吐槽、角色内心独白、搞笑桥段、日常场景细节、单场战斗过程、情感互动细节、一次性的突发事件结果、临时新增角色/势力的设定。所有微观内容留给后续细分小大纲。
结局规范：仅锁定结局情感基调、主角与核心角色关系终态、全书核心立意；具体收尾场景、角色最终细碎归宿、收尾台词全部留白。
整体硬性标准：四卷节奏层层递进，主角视角清晰，角色群像关系闭环，逻辑自洽，框架具备强延展性。{focus}
输出要求：直接输出纯大纲正文，无需开场白、解释、标题，四卷内容分段清晰。"""

    def titles_prompt(self, all_titles: list[str], chapter_context: str = "", arc_outline: str = "") -> str:
        """生成下 BATCH_SIZE 章的章节标题。

        arc_outline 为本批弧线大纲（含 BATCH_SIZE 个【章节X】分段）。提供时，要求生成的
        BATCH_SIZE 个标题与弧线大纲的章节分段按出现顺序一一对应——因为正文创作时会把标题与
        对应分章大纲同时注入（见 chapter_prompt），标题与分章大纲对齐才能避免二者打架。
        """
        from noval_workflow.config import BATCH_SIZE

        existing = ""
        if all_titles:
            existing = "\n\n已有章节标题（请勿重复）：\n" + "\n".join(
                f"{i+1}. {t}" for i, t in enumerate(all_titles)
            )

        context_section = ""
        if chapter_context:
            context_section = f"\n\n【前文故事进展（请据此规划后续走向）】\n{chapter_context}"

        # 弧线大纲对齐：把整批分章大纲塞进任务提示，并要求标题与分段按顺序一一对应。
        arc_section = ""
        arc_rule = ""
        if arc_outline:
            arc_section = (
                f"\n\n【本批章节弧线大纲（每个标题对应其中一个章节分段，按顺序一一对应）】\n{arc_outline}"
            )
            arc_rule = (
                f"\n- {BATCH_SIZE}个标题须与上方【本批章节弧线大纲】的章节分段**按出现顺序一一对应**："
                "第1个标题对应第1个章节分段，依此类推；每个标题须精准概括其对应章节的核心事件，"
                "不得错位、合并或遗漏（正文创作会以标题+对应分章大纲共同作为依据）"
            )

        focus = f"\n- {self.flavor.titles_focus}" if self.flavor.titles_focus else ""

        return f"""请为本小说生成下{BATCH_SIZE}章的章节标题。{existing}{context_section}{arc_section}

要求：
- 每行一个标题，共{BATCH_SIZE}行
- 标题简洁有力（4-12字），与故事情节紧密相关
- 不要添加序号、标点或其他前缀
- 标题不得与已有章节重复
- 标题须符合系统提示中的整体大纲方向，体现故事在当前阶段应有的发展走向
- 标题须与前文章节保持时间线与情节的连贯，不得跳跃或产生矛盾
- {BATCH_SIZE}个标题之间应形成自然的叙事流，层层递进，避免互不相关的孤立命名{arc_rule}{focus}

请直接输出{BATCH_SIZE}个标题，每行一个。"""

    def _evolved_directives_section(self) -> str:
        """本 pack 当前 flavor 的整改段（章节正文/弧线大纲共用）。见 evolved_directives_block。"""
        return evolved_directives_block(self.flavor.evolved_directives)

    def chapter_prompt(
        self,
        title: str,
        chapter_num: int,
        all_titles: list[str],
        chapter_context: str = "",
        arc_outline: str = "",
        batch_pos: int = 0,
        batch_total: int = 0,
    ) -> str:
        """生成章节正文。通用骨架 + 题材文风规则 + 题材示例。

        arc_outline/batch_pos/batch_total 用于把「本批弧线大纲」中专属本章的那一段
        显式锚定到任务提示词里：batch_pos 为本章在当前批次内的序号（1-based），
        batch_total 为本批章节数。整批弧线大纲仍在 system_context 中，供铺垫参考。
        """
        all_titles_text = "\n".join(
            f"{i+1}. {t}" for i, t in enumerate(all_titles)
        )

        context_section = ""
        if chapter_context:
            context_section = f"\n\n【前文内容参考】\n{chapter_context}"

        # 自进化整改要点段（章节正文/弧线大纲共用），置于全文末尾＝收尾约束、最高优先级。
        evolved_section = self._evolved_directives_section()

        # 弧线大纲锚点：显式告知 LLM 当前是本批第几章，并把对应分章大纲抽出作为首要依据。
        arc_section = ""
        arc_rule = ""
        if arc_outline and batch_pos:
            pos_desc = f"本批第 {batch_pos}" + (f"/{batch_total}" if batch_total else "") + " 章"
            block = _extract_arc_chapter_block(arc_outline, batch_pos)
            if block:
                arc_section = (
                    f"\n\n【本章对应弧线大纲锚点（{pos_desc}）】\n{block}\n"
                    "（以上是本批弧线大纲中专属本章的设计，为本章创作的首要依据；本批其余章节"
                    "大纲见系统提示【本批章节弧线大纲】，用于把握整体走向并为后续章节做铺垫。）"
                )
            else:
                arc_section = (
                    f"\n\n【本章定位】{pos_desc}。本章对应的分章弧线大纲见系统提示中的"
                    "【本批章节弧线大纲】，请定位到对应章节并据此创作。"
                )
            arc_rule = (
                "\n6. 弧线大纲对齐：严格落实【本章对应弧线大纲锚点】中的核心事件、人物行动、"
                "情节转折、节奏情绪与伏笔线索，本章只推进属于本章的进度，不抢写后续章节内容；"
                "同时为本批后续章节所需的人物、关系、线索与伏笔做好必要的前置铺垫，让分章之间自然咬合。"
            )

        return f"""{self.flavor.system_identity}

请撰写第{chapter_num}章：《{title}》

全书章节目录（供参考）：
{all_titles_text}{context_section}{arc_section}

### 核心创作强制规则
1. 人设严格合规：100%遵循全书官方人物档案，守住角色性格、行事底线、核心动机，**严禁OOC、人设崩坏、性格前后矛盾**；人物关系、阵营、立场保持连贯统一。专属小动作、外形标识、口头禅等标志特征，仅在情绪转折或剧情关键点自然露出，普通场景中禁止高频复读。
2. 剧情与双线要求：承接前文情节、细节与已有伏笔，明线正常推进主线剧情，**暗线循序渐进埋设线索、释放疑点**，不强行揭秘、不中断伏笔，明暗双线自然咬合。
3. 文体风格：
{self.flavor.chapter_style_rules}
4. 章节节奏：单章结构完整，中段设置小冲突/悬念/情绪波动，**章节结尾预留剧情钩子**，引导下一章内容；全章字数贴近预设单章标准字数。
5. 世界观合规：严格遵循本作世界观、势力规则、场景设定，不新增脱离原著的设定与道具。{arc_rule}

### 【关键去机械化：人物动作克制规则】
角色专属癖好、标志性小动作、口头禅、信物特征，**禁止高频、机械、重复性刷人设**。
- 每章中，同一角色的口头禅或标志性动作**最多自然出现 1-2 次**，超出即视为复读。
- 仅在角色出现：情绪波动、内心警惕、紧张迟疑、剧情转折、伏笔触发时**选择性露出**。
- 普通日常对话、走路、平淡场景一律弱化隐藏标志动作，保持真人自然感，杜绝AI复读式人设描写。

### 风格参考示例
{self.flavor.chapter_example}{evolved_section}

### 输出硬性规范（严格执行）
仅输出**章节纯正文**，开篇直接进入故事叙述，无额外解释、说明、修改备注、格式标注、开场白、结束语。

❌ 绝对禁止出现：修改说明、调整建议、原文对照、批注、解读、任务复述等一切非正文内容。
✅ 格式示例：直接以故事第一句起笔，连贯书写全文。

请直接输出章节正文"""

    def arc_outline_prompt(self, state: "NovelState") -> str:
        """生成本批 BATCH_SIZE 章的故事弧线大纲。通用 7 字段格式 + 题材聚焦。"""
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
        focus = f"\n- 题材聚焦：{self.flavor.arc_focus}" if self.flavor.arc_focus else ""

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
6. 人物行动以互动、对话、关系变化为核心，事件推进由角色反应与选择驱动，而非纯外部任务推进。{focus}

## 格式与文字要求
1. 统一使用上方固定字段排版，段落清晰，字段区分明确，不用花哨格式、表情、特殊符号。
2. 文字书面化、精炼化，短句为主，表意精准，不使用网络口水话、情绪化吐槽。
3. 字数二次自检：单章≤500字，整批合计≤{max_words}，超标自动精简压缩。

## 补充兜底规则
1. 若上一批衔接信息缺失，优先沿用最近主线冲突、人物状态、场景位置续写。
2. 关键反派、核心配角的行为保持前后一致，恩怨、矛盾持续延续。
3. 所有伏笔标注清晰，做到“有埋必有收”，跨章节线索做好标记。{self._evolved_directives_section()}"""
