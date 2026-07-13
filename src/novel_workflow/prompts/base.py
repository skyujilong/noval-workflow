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
    from noval_workflow.state import ChapterPlanItem, NovelState


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


# 底层设定「逻辑硬约束 + 输出前自检」——core_theme / world_building / core_conflicts /
# overall_outline 四个生成 prompt 共享追加，从源头压制降智、悬空前提、跨设定矛盾。
# 对首步 core_theme（前置设定为空）「跨设定一致」一条自然空转，无害。
_FOUNDATION_RIGOR = """
【底层设定硬约束（必须满足，否则重写）】
- 因果闭环：凡"已声明会在故事中生效"的机制 / 规则 / 势力，其成因、代价、边界须能自圆其说，不靠"天生如此 / 因为剧情需要"搪塞。这不要求把世界写满——见下条"强延展、留白"。
- 跨设定一致：必须与系统上下文中【已定稿的前置设定】（题材 / 基调 / 主题 / 世界观 / 冲突等）零矛盾；若发现潜在冲突，主动调和并以前置设定为准，不得另起炉灶推翻已定稿内容。
- 反降智：任何角色、势力、规则都不得为"推进剧情"而违背自身能力、动机、常识或既定实力；关键转折不得依赖巧合、对手忽然变蠢、或凭空掉落的能力 / 资源。
- 强延展、留白：只搭骨架与底层逻辑，为下游大纲 / 人物预留扩展空间，不写死一次性细节、不锁死力量上限与终局真相。有意保留的未解之谜 / 更高层级未知属于合格留白，不算"悬空前提"，点明为悬念即可，无需当场补全成因。

【输出前自检（逐条自问，全部通过才输出，否则改到通过）】
1. 是否有"已声明会生效的机制"无法回答"为什么成立"、只是凭空规定？——若有，补足因果或删除（有意标明为悬念的留白不在此列，予以保留）。
2. 是否与前置已定稿设定存在矛盾、或与其内在逻辑冲突？——若有，以前置为准调和。
3. 是否存在为剧情效果而降智、靠巧合硬凑的环节？——若有，改成由设定内在逻辑自然导出。
"""


# 8-field format shared by arc_outline_prompt (本文件) 与 arc_edit_subgraph 的内联大纲提示词
# 档位字段置顶：先定"章性"再填内容，从源头允许淡章/铺垫章存在，避免章章强行塞转折导致赶进度。
ARC_CHAPTER_FORMAT = """\
## 单章节固定必填字段（每章必须依次列出，缺一不可）
【章节X】
0. 本章档位：从「铺垫/缓冲/推进/转折/爆发/回落」六档中选一个，作为本章节奏密度与叙事重量的总定位（铺垫/缓冲章不强行塞硬转折，推进章承载主线小步走，转折/爆发章才集中爽点/反转/冲突，回落章用于高潮后的情绪沉淀）
1. 本章核心事件：一句话概括本章主线行为与场景（铺垫/缓冲章此处可以是相对静态的人物互动/心理沉淀/场景铺陈，不必有激烈事件）
2. 人物行动：核心角色、配角的具体动作、分工、互动行为
3. 情节节点：本章的主要冲突/推进/变化——转折/爆发章此处写明硬冲突或反转；铺垫/缓冲/回落章此处可以是「人物关系微变」「信息释放」「情绪发酵」「氛围铺陈」等弱节点，不强制要求硬反转/大战
4. 节奏&情绪锚点：标注本章内部节奏曲线（整体档位下允许内部张弛，如"前缓后紧"）、核心情绪（愤怒/恐惧/释然/警惕/怅然/温暖等）、网文看点（本章有则写：爽点/悬念/虐点/反转/钩子；铺垫/缓冲/回落章可写"无强看点，重在氛围/关系/信息"）
5. 伏笔&线索：本章新增伏笔、回收前文伏笔、遗留待解线索；纯过渡章可写"本章无伏笔进出，只做承接"
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


def _extract_chapter_plan_range(
    chapter_plan: "list[ChapterPlanItem]",
    start_chapter: int,
    end_chapter: int,
) -> "list[ChapterPlanItem]":
    """按 [start_chapter, end_chapter] 闭区间切片 chapter_plan。

    空 plan / 空区间 / 切不到条目时返回空 list——调用方按空处理即可，行为对
    「未开启 chapter_plan」的老工程完全透明。
    """
    if not chapter_plan or start_chapter > end_chapter:
        return []
    return [item for item in chapter_plan if start_chapter <= item.chapter <= end_chapter]


def _format_chapter_plan_block(entries: "list[ChapterPlanItem]") -> str:
    """把章节规划条目渲染成简短 markdown,每章一行。

    留一行的紧凑格式,防止喂给下游 prompt 时膨胀 token;字段之间用全角竖线分隔,
    与既有 arc_outline 内的字段风格视觉对齐。空 list 返回空串。
    """
    if not entries:
        return ""
    lines = [
        f"- 第{item.chapter}章｜目标:{item.purpose}｜关键转折:{item.key_turn}｜章末钩子:{item.ending_hook}"
        for item in entries
    ]
    return "\n".join(lines)


def _format_written_chapters_brief(state: "NovelState", max_recent: int = 10) -> str:
    """渲染「已写完章节的标题 + 摘要」精简视图,供 chapter_plan_prompt 消费。

    只取最近 max_recent 章,防止长篇累积后拉爆 token;每章一行 `第N章｜标题｜摘要片段`。
    未写过任何章时返回空串,调用方按空处理。
    """
    if state.total_chapters_written <= 0:
        return ""
    total = state.total_chapters_written
    titles = state.all_chapter_titles[:total]  # 防越界:只取已写完对应的标题
    summaries = state.all_chapter_summaries[:total]
    start = max(0, total - max_recent)
    lines = []
    for idx in range(start, total):
        title = titles[idx] if idx < len(titles) else ""
        summary = summaries[idx] if idx < len(summaries) else ""
        # 摘要过长时截取前 80 字,足够 chapter_plan 用来判断承接
        summary_short = summary[:80] + ("…" if len(summary) > 80 else "")
        lines.append(f"第{idx + 1}章｜{title}｜{summary_short}")
    return "\n".join(lines)


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

    # ── 题材默认建议 ───────────────────────────────────────────────────────
    has_power_system: bool = True
    """本题材是否**默认建议**独立【力量体系】设定——仅作为 NovelState.has_power_system 的初始值来源，
    实际运行时决策统一读 state 字段。默认 True（有超凡力量 / 等级 / 流派的题材：玄幻 / 科幻 / 末日等）；
    现实向题材（都市 / 两性情感 / 通用）置 False。

    脑爆路径由 collect_user_inputs 按抽出的 genre 查此字段兜底写入 state.has_power_system（from_brainstorm=True
    时尊重脑爆聊天页 switch 已经写回的值，不覆盖）；直接填表路径同理由 collect_user_inputs 按 genre 查此字段兜底
    写入 state。三个消费点（route_after_world_building / brainstorm_finalize 抽后剔除 / brainstorm_extract_review
    payload）都读 state.has_power_system，本字段不再是运行时开关。"""

    # ── 可选：各创作步骤的题材聚焦补充（默认空串）──────────────────────────
    core_theme_focus: str = ""
    """核心主题步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    world_building_focus: str = ""
    """世界观构建步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。"""
    power_system_focus: str = ""
    """力量体系步骤的题材聚焦补充，注入对应 prompt 的 focus 占位。默认空 → 对无力量体系
    的题材（纯言情/现实都市等）零影响，此时 power_system_prompt 按"社会竞争/规则体系"泛化。"""
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

    # ── 自进化：历次人工反馈沉淀的强制整改要点（按 review_type 分桶）──────────
    # 三桶各存对应环节的历史整改要点，chapter/arc_outline/scene_beats 相互独立；
    # 一个整改条目可以显式「分发」到多个桶——写入侧决定,消费侧只读自己那一桶。
    evolved_directives_chapter: str = ""
    """章节正文创作的历史整改要点。追加到 chapter_prompt 末尾（最高优先级段）。"""
    evolved_directives_arc_outline: str = ""
    """弧线大纲创作的历史整改要点。追加到 arc_outline_prompt 末尾。"""
    evolved_directives_scene_beats: str = ""
    """章前 scene beats 生成的历史整改要点。追加到 scene_beats_prompt 末尾。"""

    # 老字段（deprecated）：仅用于兼容旧 prompt_overrides.json——加载时会在
    # overrides.py::load_overrides 里迁移到 evolved_directives_chapter。字段本身保留
    # 只为 dataclass 反序列化容错，prompt 组装侧不再读它。
    evolved_directives: str = ""
    """[DEPRECATED] 老单桶字段，加载时迁移到 evolved_directives_chapter；prompt 组装侧不再读。"""


# ── PromptPack：通用脚手架 + 风味组装 ─────────────────────────────────────────


# review_type → 对应 evolved_directives 字段名。这是「按 type 分桶」的唯一映射表——
# prompt 组装侧、subgraph.generate 打回重跑、HTTP apply/reconcile 全走它,避免各处硬编码。
_REVIEW_TYPE_TO_EVOLVED_FIELD: dict[str, str] = {
    "chapter": "evolved_directives_chapter",
    "arc_outline": "evolved_directives_arc_outline",
    "scene_beats": "evolved_directives_scene_beats",
}

# 所有已接入自进化的 evolved_directives 桶字段名——供 overrides/HTTP 层遍历。
EVOLVED_DIRECTIVES_FIELDS: frozenset[str] = frozenset(_REVIEW_TYPE_TO_EVOLVED_FIELD.values())


def evolved_field_for(review_type: str) -> str:
    """把 review_type 映射到 GenreFlavor 字段名。未知类型回退到 chapter(最保守默认)。"""
    return _REVIEW_TYPE_TO_EVOLVED_FIELD.get(review_type, "evolved_directives_chapter")


def get_evolved_directives(flavor: "GenreFlavor", review_type: str) -> str:
    """按 review_type 从 flavor 里取对应桶的文本;未知类型走 chapter 桶。"""
    return getattr(flavor, evolved_field_for(review_type), "")


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
{_FOUNDATION_RIGOR}
请直接输出主题内容，不需要标题。"""

    @property
    def world_building_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.world_building_focus}" if self.flavor.world_building_focus else ""
        return f"""请为本小说创作【世界观设定】。

要求：
- 详细描述故事发生的时代背景、地理环境、社会结构
- 独特的规则体系 / 力量体系（魔法·修炼境界·科技·社会规范等，视类型而定）：体系的结构与规则要写具体、可直接使用——力量来源、境界 / 层级划分、晋升路径与代价、流派 / 职业分类等；只对"最高层级 / 力量源头的终极真相"留白（如更高境界成谜、本源另有隐秘），不当场写死。注：此处只立体系框架，某个角色具体拥有的技能 / 招式写进【人物档案】，不在世界观
- 说明世界的历史脉络与当前大势（当下矛盾张力从何而来）
- 只搭建"舞台、规则与历史"，不写具体剧情走向、主角个人经历、单次冲突的胜负结果
- 至少保留 1-2 处刻意留白的未解之谜 / 更高层级未知，作为后续大纲的可扩展空间（留白只需点到、标明是悬念，不必当场解释成因）
- 字数：400-800字{focus}
{_FOUNDATION_RIGOR}
请直接输出世界观内容，不需要标题。"""

    @property
    def power_system_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.power_system_focus}" if self.flavor.power_system_focus else ""
        return f"""请为本小说创作【力量体系】设定。

力量体系是本书人物凭以行动、竞争、成长的那套「能力规则」——修炼境界 / 科技装备 / 异能进化 / 社会资源与规则等，视题材而定。它须与已定稿的【世界观设定】自洽，并作为后续人物成长、冲突升级、大纲阶段划分的统一标尺。

要求：
- 明确力量来源与底层原理：这套力量从何而来、依托世界观里的哪条规则运作
- 给出清晰的层级 / 境界阶梯（自低到高完整列出各层级名称与分野），并说明晋升路径、晋升所需的资源 / 条件、以及晋升的代价与瓶颈
- 说明流派 / 职业 / 能力方向的分类（若有），以及不同流派之间的相克或差异
- 划定力量的边界与规则红线：什么做不到、什么被禁止、越界的后果——避免后期出现"体系外凭空能力"
- 只对"最高层级 / 力量源头的终极真相"留白（如更高境界成谜、本源另有隐秘），其余框架必须写具体、可直接被人物档案与大纲引用
- 只立"体系框架"，不写某个具体角色拥有的技能 / 招式（那属【人物档案】）、也不写具体剧情走向与单次战斗胜负
- 字数：400-800字{focus}
{_FOUNDATION_RIGOR}
请直接输出力量体系内容，不需要标题。"""

    @property
    def core_conflicts_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.core_conflicts_focus}" if self.flavor.core_conflicts_focus else ""
        return f"""请为本小说设计【核心冲突】。

要求：
- 明确主要冲突类型（人与人、人与自然、人与社会、人与自我等）
- 列出2-4个核心冲突层次，并说明各层次的具体表现
- 冲突需与世界观、主题深度契合
- 字数：300-600字{focus}
{_FOUNDATION_RIGOR}
请直接输出冲突设计内容，不需要标题。"""

    @property
    def character_profiles_prompt(self) -> str:
        focus = f"\n- 题材聚焦：{self.flavor.character_profiles_focus}" if self.flavor.character_profiles_focus else ""
        return f"""## 角色定位

{self.flavor.system_identity}

## 任务目标

为全书生成可对接四卷式大纲、适配明暗双线、分层立体的全套核心人物档案。

## 卡司配额（严格遵守）

- 主角 1 位；核心配角 3-5 位；阶段功能性反派 2-3 位 + 终极根源反派 1 位；关键感情线角色 1-2 位。
- 按此配额生成，不遗漏、不超编；确需增减须服务主线，不得堆砌工具人凑数。

## 硬性创作规则

- **人设双层面强制拆分**：所有核心角色必须写出【表层公开人设（读者视角）】+【深层隐藏人设（作者暗线视角）】，表层合理自然、深层预埋伏笔，两层人设不冲突、可后期完美反转收束，全程服务主线剧情与暗线揭秘。
- **严格绑定四卷成长体系**：每位核心人物必须拥有四卷阶段性弧光轨迹，只写心性、立场、羁绊、认知的迭代大势，不填充具体情节、互动细节、台词桥段。
- **双线绑定规则**：人物秘密、异常行为、隐藏能力、立场偏差全部作为暗线素材，均匀预埋至四卷剧情，做到明线推进主线、暗线推进人物真相与信任崩塌 / 重建，双线深度咬合。
- **能力/底牌契约（硬绑力量体系）**：每位核心角色的能力必须归属【力量体系】设定的层级 / 流派 / 规则，**禁止体系外凭空能力**；开篇实力起点与四卷成长天花板都须落在【力量体系】已划定的境界 / 层级阶梯上。须写明【初始锚点】（开篇实力起点，对应力量体系的哪一层级）与【四卷成长天花板】（卷一→卷四各一句，只写能力上限走势即到达哪个层级，不写具体招式）；若有隐藏杀手锏（底牌），须写明触发条件与反噬 / 代价，作为暗线素材，不得提前于设定卷次解锁。此契约为后续「阶段固化数据」台账的战力校验红线。
- **人设绝对自洽**：所有角色具备明确软肋、原生缺陷、心理枷锁、立场理由，无绝对善恶，所有对立、抉择、背叛、牺牲均源于人物底层逻辑，杜绝脸谱化、工具人、强行降智。
- **视觉标识轻描淡写**：每位核心角色最多保留 1 个低调、自然的视觉锚点或行为特征（如眼镜、旧围巾、攥袖口等），仅用于快速辨识，不用于高频复读。人设通过对话、选择、反应建立，禁止靠口头禅、固定动作、服饰细节反复刷标签。
- **严格沿用全局留白规则**：只撰写人物骨架设定、底层逻辑、成长大势、立场羁绊、能力短板、秘密底色。禁止撰写具体日常、具体互动、具体台词、具体战斗画面、细碎心理活动。
- **反派分层设计**：区分「阶段功能性反派」与「终极根源反派」，明确动机根源、冲突本质、阶段性作用、闭环退场逻辑，保留人性复杂度。
- **人物关系闭环**：全员羁绊围绕主角构建 —— 情感位、信任位、冲突位、对立位、功能位清晰，关系演变贴合四卷剧情推进，无割裂、无狗血、无逻辑 BUG。{focus}

## 输出规范

- 主角档案精细化全覆盖，配角精简高质不冗余，反派立体不扁平。
- 整体文风官方、干净、立体，逻辑闭环、伏笔可落地、支持长期连载不崩人设。
- **直接输出人物档案正文，无需额外开场白、解释、标题套话。**

## 输出前自检（不达标则重写，达标才输出）

1. 每位核心角色是否都写全【表层公开人设】+【深层隐藏人设】两层？
2. 全员关系位是否都指向主角、闭环无孤点（无游离于主线之外的角色）？
3. 每个反派是否都有明确动机根源与闭环退场逻辑？
4. 人物姓名之间是否无同姓、无近音、无中洋混搭、无生僻拗口？
5. 每位角色的能力是否都归属【力量体系】的层级 / 流派、未越界，且初始锚点与【四卷成长天花板】都落在其境界阶梯上？"""

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
{_FOUNDATION_RIGOR}
输出要求：直接输出纯大纲正文，无需开场白、解释、标题，四卷内容分段清晰；四卷骨架总字数约 2500-3500 字（与后续审核口径一致），过短则骨架信息不足、过长则侵占细分大纲的留白空间。"""

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

    def _evolved_directives_section(self, review_type: str = "chapter") -> str:
        """本 pack 当前 flavor 的整改段——按 review_type 分派到对应字段。

        三桶隔离:chapter/arc_outline/scene_beats 各读自己那份。老数据加载时会被
        overrides.py 迁移到 chapter 桶,故未知 review_type 一律走 chapter(最安全默认)。
        """
        directives = get_evolved_directives(self.flavor, review_type)
        return evolved_directives_block(directives)

    def chapter_prompt(
        self,
        title: str,
        chapter_num: int,
        all_titles: list[str],
        chapter_context: str = "",
        arc_outline: str = "",
        batch_pos: int = 0,
        batch_total: int = 0,
        scene_beats: list[dict] | None = None,
        chapter_plan_entry: "ChapterPlanItem | None" = None,
    ) -> str:
        """生成章节正文。通用骨架 + 题材文风规则 + 题材示例。

        arc_outline/batch_pos/batch_total 用于把「本批弧线大纲」中专属本章的那一段
        显式锚定到任务提示词里：batch_pos 为本章在当前批次内的序号（1-based），
        batch_total 为本批章节数。整批弧线大纲仍在 system_context 中，供铺垫参考。

        scene_beats（可选）：本章 scene beats 节拍表；非空时作为「首要依据」注入正文创作
        提示词，并追加第 7 条硬约束「Scene beats 对齐」——逐 beat 展开、打脸四拍必须齐全、
        章尾钩必须落在末 beat 上。为空则走原路径不注入，行为与旧图完全一致。

        chapter_plan_entry（可选）：本章对应的 chapter_plan 条目（4 字段远端锚点）；非空时
        作为「大局锚点」注入,与 arc/beats 是层级关系(远端 → 批级 → 章级),冲突时以更细一层为准,
        它只帮 LLM 把握本章在中景规划中的定位。为空则不注入,向后兼容。
        """
        all_titles_text = "\n".join(
            f"{i+1}. {t}" for i, t in enumerate(all_titles)
        )

        context_section = ""
        if chapter_context:
            context_section = f"\n\n【前文内容参考】\n{chapter_context}"

        # 章节正文创作专属整改要点(chapter 桶),置于全文末尾＝收尾约束、最高优先级。
        evolved_section = self._evolved_directives_section("chapter")

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

        # 远端锚点（章级）：来自 chapter_plan,4 字段的中景导航。层级关系:chapter_plan(远)
        # → arc_outline(批级中景) → scene_beats(章内节拍)。远端锚点用于把握本章在整个滚动
        # 窗口中的定位,与 arc 冲突时以 arc 为准;若两者一致则相互印证,LLM 有更强的对齐信号。
        chapter_plan_section = ""
        chapter_plan_rule = ""
        if chapter_plan_entry is not None:
            chapter_plan_section = (
                f"\n\n【本章远端锚点（来自 chapter_plan，全书第 {chapter_plan_entry.chapter} 章）】"
                f"\n目标：{chapter_plan_entry.purpose}"
                f"\n关键转折：{chapter_plan_entry.key_turn}"
                f"\n章末钩子：{chapter_plan_entry.ending_hook}"
                "\n（以上是滚动章节规划给本章的大局定位,用于把握本章在中景窗口中的位置;"
                "若与弧线锚点冲突,以弧线锚点为准——远端锚点管方向,弧线锚点管细节。）"
            )
            chapter_plan_rule = (
                "\n8. 远端锚点承接：本章的整体走向、关键转折与章末钩子须落在远端锚点上;"
                "如与弧线锚点局部不一致,以弧线锚点为准并主动调和,不得直接推翻远端目标。"
            )

        # Scene beats 节拍表（章级可选）：非空时作为「首要依据」注入，比弧线锚点更细一层。
        # 弧线锚点说「本章要发生什么」，scene beats 说「本章 3-7 个 beat 逐一怎么演」。
        beats_section = ""
        beats_rule = ""
        if scene_beats:
            # 惰性 import 避免循环：scene_beats.py 依赖 base.py 的 _extract_arc_chapter_block。
            from noval_workflow.prompts.scene_beats import format_beats_for_chapter_prompt
            beats_md = format_beats_for_chapter_prompt(scene_beats)
            beats_section = (
                f"\n\n【本章 Scene Beats（章内节拍表，首要依据，逐 beat 展开正文）】\n{beats_md}\n"
                "（以上是本章的场景节拍表。每个 beat 是一段独立场景，beat 之间用空行分场；"
                "beat 的 device_tags 决定该段的叙事装置：setup/buildup/release=三段式爽感；"
                "slap_*=打脸四拍；hook_opening/hook_chapter_end=钩子；foreshadow_*=伏笔；"
                "buffer=缓冲/铺垫/回落。"
                "pacing 决定本段展开密度：slow 段要慢下来写——多写感官细节、生理反应、对话停顿、沉默留白、心理流动，给读者沉浸空间，不要赶；fast 段用短句推进动作、突发转折；medium 平衡叙事。"
                "prose_focus 指明本段重点展开维度（动作/对话/心理/感官/氛围/信息交换），该维度多泼墨、其他维度配合但不抢戏。"
                "严格按 beat 顺序、pacing、prose_focus 与 target_words 分配写作，slow beat 字数给够、fast beat 不拖泥带水。）"
            )
            beats_rule = (
                "\n7. Scene beats 对齐（硬约束）：逐 beat 落实各 beat 的 goal-obstacle-outcome-cost 与"
                " device_tags、pacing、prose_focus；不得漏拍、不得越界写非本章 beat 内容；"
                "pacing=slow 的 beat 必须慢写：展开感官/心理/氛围/对话留白，让读者有时间感受，**绝对禁止把 slow beat 用几句话快速带过**——那是导致全章赶进度的最常见问题；"
                "pacing=fast 的 beat 用短句快推动作/转折，不拖泥带水；"
                "打脸桥段（含任一 slap_* tag）必须四拍完整（嘲讽→沉默→碾压→围观）；"
                "章尾钩（hook_chapter_end）必须落在最后一个 beat 上，在情绪/动作最高点前一秒断章。"
            )

        return f"""{self.flavor.system_identity}

请撰写第{chapter_num}章：《{title}》

全书章节目录（供参考）：
{all_titles_text}{context_section}{arc_section}{chapter_plan_section}{beats_section}

### 核心创作强制规则
1. 人设严格合规：100%遵循全书官方人物档案，守住角色性格、行事底线、核心动机，**严禁OOC、人设崩坏、性格前后矛盾**；人物关系、阵营、立场保持连贯统一。专属小动作、外形标识、口头禅等标志特征，仅在情绪转折或剧情关键点自然露出，普通场景中禁止高频复读。
2. 剧情与双线要求：承接前文情节、细节与已有伏笔，明线正常推进主线剧情，**暗线循序渐进埋设线索、释放疑点**，不强行揭秘、不中断伏笔，明暗双线自然咬合。
3. 文体风格：
{self.flavor.chapter_style_rules}
4. 章节节奏（按档位定密度，禁止赶进度）：
   - 铺垫/缓冲/回落章：以 slow 与 medium 节拍为主，承担氛围铺陈、人物生活化互动、心理沉淀、信息释放；**不强行制造硬冲突/反转/爽点来凑事**——把人写活、把世界写具体、把情绪铺到位，本身就是价值；对话不必句句推进剧情，允许有生活化的闲笔与留白。
   - 推进章：slow/medium/fast 错落推进，主线小步稳走，人物关系/立场/认知有可察觉变化。
   - 转折/爆发章：以 medium+fast 为主，但**爽点/反转之前必须有 slow 蓄势段**（用感官细节、生理反应、对话停顿把张力拉满后再爆），不要一上来就炸；结尾在最高点前断章留钩子。
   - 任何档位章都禁止"事件堆叠式快进"——不要把剧情节点一口气列完交差，每个节点要有对应的情绪/感官/动作/反应去落地，让读者"看见"而不只是"知道发生了什么"。
   - 全章字数贴近预设单章标准字数。结尾按档位预留钩子（重章钩子强、淡章钩子弱或用悬念/情绪余韵收尾）。
5. 世界观合规：严格遵循本作世界观、势力规则、场景设定，不新增脱离原著的设定与道具。{arc_rule}{beats_rule}{chapter_plan_rule}

### 【关键去机械化&反赶进度：让文字"呼吸"起来】
- 人物标志特征克制：角色专属癖好、标志性小动作、口头禅、信物特征**禁止高频、机械、重复性刷人设**。每章同一角色的口头禅或标志动作最多自然出现 1-2 次；仅在情绪波动、紧张迟疑、剧情转折、伏笔触发时选择性露出；普通日常场景弱化隐藏，保持真人自然感。
- 情绪不贴标签：禁止用"心中一凛/怒火中烧/暗自吃惊/不由得/竟然/居然/缓缓地/默默地"等AI高频套话标签情绪；要用动作（攥拳、别开视线、喉结滚动）、生理反应（手心出汗、后脊发凉、心跳声盖过周围）、环境映射（风突然冷了半分、灯花跳了一下）、对话节奏变化（停顿、打断、答非所问）来**展示**情绪，让读者自己感受到。
- 句式段落错落：禁止全篇长度相近的"均匀段落"——要有单句成段的冲击、有长句流淌的沉浸、有对话密集的交锋、有整段描写的铺陈。段落长短不齐是活人的文字节奏。
- 感官落地：关键场景至少激活 2-3 种感官（视觉+听觉+触觉/嗅觉/味觉），不要只写"看见什么"。温度、声音、气味、触感是让场景"立起来"的锚点。
- 对话要有呼吸：人物对话之间允许穿插动作、观察、停顿、沉默，不要像机关枪一样你一句我一句连打到底；**对话的反应节拍本身就在演戏**——迟疑半秒、错开眼神、先做个小动作再开口，比台词本身更有戏。
- 闲笔许可：铺垫/缓冲/回落 beat 允许写少量生活质感细节（一杯茶的温度、窗外的天色、衣料摩擦声、人物无意识的小动作），这不是"水"，是让读者住在故事里的砖——但要服务于氛围/人物心境，不为写而写。

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

        # ── 远端锚点注入:从 chapter_plan 切出本批对应的窗口条目 ──────────────────
        # 目的:让 arc_outline 生成时能看到「本批 5 章的整体走向」,而非只依赖整书大纲
        # + 前文摘要;chapter_plan 未开启 or 未覆盖到本批时自然跳过,行为向后兼容。
        batch_start = state.total_chapters_written + 1
        batch_end = batch_start + BATCH_SIZE - 1
        plan_entries = _extract_chapter_plan_range(state.chapter_plan, batch_start, batch_end)
        chapter_plan_section = ""
        chapter_plan_rule = ""
        if plan_entries:
            plan_block = _format_chapter_plan_block(plan_entries)
            chapter_plan_section = (
                f"\n\n【本批远端锚点（来自 chapter_plan，本批 {BATCH_SIZE} 章的整体走向 / 转折 / 钩子）】\n"
                f"{plan_block}"
            )
            chapter_plan_rule = (
                "\n8. 本批各章档位与情节节点须与「远端锚点」中的 `目标 / 关键转折 / 章末钩子` 对齐;"
                "如与整体大纲局部冲突,以整体大纲为准并主动调和,不得直接推翻锚点。"
            )

        is_first_batch = state.total_chapters_written == 0
        continuity_rule = (
            "1. 作为本书第一批章节，请严格按照整体大纲的开篇定位规划故事起点，奠定世界观、人物关系与核心冲突的基调。"
            if is_first_batch else
            "1. 严格承接上一批大纲最终结尾情节，情节逻辑连贯、无断层，全程贴合作品整体主线大纲，不偏离核心世界观、势力设定、人物人设与核心冲突。"
        )

        max_words = BATCH_SIZE * 500
        focus = f"\n- 题材聚焦：{self.flavor.arc_focus}" if self.flavor.arc_focus else ""

        return f"""请为本批接下来的 {BATCH_SIZE} 章规划故事弧线大纲。{prev_section}{chapter_plan_section}

# 角色：你是专业网文分章弧线大纲撰写师
## 整体约束
{continuity_rule}
2. 本批次所有章节大纲总字数严格控制在 {max_words} 以内；**单章节内容节点文字不得超过500字**，精简表述，拒绝冗余描写、抒情、旁白。
3. 仅输出结构化章节大纲，不撰写正文内容、不生成章节标题，仅为标题、正文创作提供明确锚点。

{ARC_CHAPTER_FORMAT}

## 档位分配与节奏张弛（最高优先级，决定整批弧线的呼吸感）
1. 每批 {BATCH_SIZE} 章必须呈现波浪式密度，**禁止章章高燃/章章强转折**。档位分布硬约束（合计 {BATCH_SIZE} 章）：
   - 爆发 + 转折 ≤ 40%（每批最多 {int(BATCH_SIZE*0.4)} 章承担硬爽点/反转/大战）
   - 铺垫 + 缓冲 + 回落 ≥ 30%（每批至少 {max(1, BATCH_SIZE//3)} 章承担蓄势、人物互动、氛围、情绪沉淀、信息释放）
   - 推进章补足其余配额，承担主线小步稳走
2. 首批开篇例外：首批 1-2 章允许密度稍高（用于立世界观/钩子），但仍须留 1 章做人物/氛围铺陈，避免开局就炸完所有牌。
3. 档位错排：禁止连续 2 章以上同属爆发/转折，高潮之间必须插入铺垫/缓冲/推进让读者喘口气；同样，铺垫/缓冲不连续超 2 章，防止拖。

## 内容创作规则
1. 严守作品既定设定：类型一致、战力体系、物资规则、队伍规矩、人物关系、势力矛盾，不新增私设、不强行降智/拔高角色。
2. 按档位叙事（关键！）：
   - 爆发/转折章：硬冲突、反转、打脸、身份揭晓、大战；情节节点字段写明具体爆点；爽点/虐点/钩子必须落到实处。
   - 推进章：主线小步前进，人物关系/立场/认知有可察觉但不炸裂的变化；允许有小冲突但不抢后续爆发章的戏。
   - 铺垫/缓冲/回落章：承担氛围铺陈、人物日常互动、信息交换、情绪沉淀、伏笔静置发酵、势力态势过渡；核心事件与情节节点字段写“这一章做了什么非事件性的推进”（如两人关系走近半分、主角心境转变、读者获得关键信息），**不要硬塞硬冲突/反转/打脸来凑数**——淡章的价值在于让读者喘息、为下一波蓄势，写得扎实同样重要。
3. 冲突设计循序渐进，支线服务主线，不随意新增无关人物、无关支线，避免剧情散乱。
4. 动作、对话、冲突符合人物性格，角色行为逻辑自洽，保持人设统一；淡章里允许生活化对白、片刻松弛，对话不必句句带刀。
5. 涉及战斗、对峙、逃生场景（仅爆发/转折/部分推进章需要），写明攻防动作、敌我态势，细节具备可落地性；铺垫/缓冲章不强行安排战斗。
6. 物资、伤亡、环境等细节贴合本作世界观设定，逻辑严谨。
7. 人物行动以互动、对话、关系变化为核心，事件推进由角色反应与选择驱动，而非纯外部任务推进。{focus}

## 格式与文字要求
1. 统一使用上方固定字段排版，段落清晰，字段区分明确，字段 0（本章档位）必须位于最前，不用花哨格式、表情、特殊符号。
2. 文字书面化、精炼化，短句为主，表意精准，不使用网络口水话、情绪化吐槽；淡章的“精炼”指不灌水，不等于把场景一笔带过——人物互动、氛围细节、情绪流动的关键字要写到位。
3. 字数二次自检：单章≤500字，整批合计≤{max_words}，超标自动精简压缩；淡章可更短（300-400字），爆发章可顶到 500字上限。

## 补充兜底规则
1. 若上一批衔接信息缺失，优先沿用最近主线冲突、人物状态、场景位置续写。
2. 关键反派、核心配角的行为保持前后一致，恩怨、矛盾持续延续；淡章里配角可以有生活化露出（不必每次出场都推动主线），强化“活人感”。
3. 所有伏笔标注清晰，做到“有埋必有收”，跨章节线索做好标记；淡章是埋小伏笔、放暗线信息的最佳位置，不要错过。{chapter_plan_rule}{self._evolved_directives_section("arc_outline")}"""

    def chapter_plan_prompt(
        self,
        state: "NovelState",
        start_chapter: int,
        end_chapter: int,
        locked_entries: "list[ChapterPlanItem]",
    ) -> str:
        """滚动章节规划(chapter_plan)提示词：一次生成 [start_chapter, end_chapter] 闭区间的
        章节规划条目,严格 JSON 数组,每条 4 字段(chapter/purpose/key_turn/ending_hook)。

        locked_entries 是已写完段(chapter <= total_chapters_written)的历史条目,只作为承接
        参考,LLM **禁止**修改或重复输出这些章号——save_chapter_plan 兜底合并保留历史。
        """
        import json
        from dataclasses import asdict

        count = end_chapter - start_chapter + 1
        is_first_plan = state.total_chapters_written == 0

        continuity_rule = (
            "本次是首次章节规划,请紧扣整体大纲的开篇定位,奠定世界观、人物关系与核心冲突的基调;前几章允许略慢热但必须挂钩子。"
            if is_first_plan else
            "本次是滚动重规划,请严格承接已写完章节的伏笔、人物状态、势力格局与情绪走向;不要另起炉灶推翻已发生的剧情。"
        )

        written_brief = _format_written_chapters_brief(state)
        written_section = (
            f"\n\n【已写完章节速览（最近 10 章,供承接参考）】\n{written_brief}"
            if written_brief else ""
        )

        # 已锁定的历史条目:LLM 必须原样承接,不能重复输出这些章号
        if locked_entries:
            locked_json = json.dumps(
                [asdict(item) for item in locked_entries],
                ensure_ascii=False,
                indent=2,
            )
            locked_section = (
                "\n\n【已锁定的历史章节规划条目（章号 1 ~ "
                f"{state.total_chapters_written},供承接参考,严禁修改或重复输出这些章号）】\n"
                f"{locked_json}"
            )
        else:
            locked_section = ""

        # 状态快照:让 LLM 感知当前进度
        status_lines = []
        if state.character_status:
            status_lines.append(f"【人物动态状态】\n{state.character_status}")
        if state.character_relations:
            status_lines.append(f"【人物关系/势力格局】\n{state.character_relations}")
        if state.foreshadowing:
            fs_json = json.dumps(state.foreshadowing, ensure_ascii=False, indent=2)
            status_lines.append(f"【伏笔台账】\n{fs_json}")
        if state.phase_summary:
            status_lines.append(f"【阶段固化数据】\n{state.phase_summary}")
        status_section = ("\n\n" + "\n\n".join(status_lines)) if status_lines else ""

        # 关键转折与钩子的分布约束——防止 30-50 章章章硬转折/章章平淡
        peak_max = max(3, count // 8)  # 约 12.5%~25% 的强转折上限,给节奏留呼吸
        peak_min = max(2, count // 12)  # 至少 8%~15% 的强转折,保证长弧线不塌
        return f"""请为本作品规划一份 {count} 章的**中景章节规划**(chapter_plan)。{written_section}{locked_section}{status_section}

# 角色:你是长篇网文的中景大纲规划师,负责在「整书大纲」与「批级弧线」之间,给出一份 {count} 章的滚动路线图。

## 本次任务范围
只输出章号 {start_chapter} - {end_chapter}(闭区间,共 {count} 条)的新条目,**严禁**输出其他章号,**严禁**重复输出「已锁定的历史条目」中的章号。

## 输出契约(严格 JSON,无任何附加文本)
1. 直接输出一个 JSON 数组,第一个字符是 `[`,最后一个字符是 `]`。
2. **禁止** markdown 围栏(如 ```json)、**禁止**前置解释、**禁止**任何解释性文字。
3. 数组元素**必须**为对象,**必须**包含且仅包含 4 个字段:
   - `chapter`: 整数,全书章号(1-based),范围 [{start_chapter}, {end_chapter}],严格连续升序。
   - `purpose`: 字符串,本章要完成的「活」/目标,一句话概括(≤40 汉字)。
   - `key_turn`: 字符串,本章关键转折点/看点(≤40 汉字);淡章可写「无强转折,以XX铺垫为主」。
   - `ending_hook`: 字符串,本章结尾钩子/悬念(≤30 汉字)。
4. 每条对象**必须**齐 4 字段,缺一 fail;字段值**不得为空字符串**,不得写「见后续」「待定」等占位。

## 最短合规样本
[
  {{"chapter": {start_chapter}, "purpose": "主角初入宗门被欺辱,埋下反击契机", "key_turn": "被逼签下不平等契约", "ending_hook": "契约上多出一枚未知血印"}},
  {{"chapter": {start_chapter + 1}, "purpose": "主角首次动用血印之力,惊觉自身异常", "key_turn": "血印驱使神秘古卷显形", "ending_hook": "古卷第一页浮出祖师名讳"}}
]

## 常见错误(禁止)
❌ 加 markdown 围栏 ```json ... ```
❌ 数组前写「以下是规划:」等解释
❌ 章号跳号或倒序,或与「已锁定条目」章号重复
❌ 字段用中文键名(用「目标」代替 `purpose`)
❌ 4 字段缺一,或字段值写空串/「待定」
❌ 章章都是强转折(违反下方分布约束)

## 内容创作约束
{continuity_rule}
1. 本 {count} 章须与整体大纲的阶段定位对齐(起承转合/四卷式),不要提前爆完终局。
2. 转折分布(硬约束,决定节奏呼吸):
   - `key_turn` 中「强转折/爆发/反转/身份揭晓/大战」类的高密度章节数量应在 [{peak_min}, {peak_max}] 之间。
   - 其他章为推进/铺垫/缓冲/回落,`key_turn` 写具体的低密度进展(如「关系推进」「信息释放」「情绪沉淀」)。
   - **禁止**连续 3 章以上高密度转折;高潮之间**必须**插入至少 1 章铺垫/缓冲。
3. `ending_hook` 每章必须落到实处,不得写「进入下一战」「揭开真相」这种空钩子;要具体到「谁做了什么/看到了什么/说了什么」。
4. 伏笔挂钩:埋伏笔的章要在 `purpose` 或 `key_turn` 里点明「埋下 XX」;回收的章要点明「回收前文 XX」。跨此窗口的伏笔可留白。
5. 严守作品既定设定(题材/世界观/力量体系/人物关系),不新增私设、不降智/拔高角色。

## 输出前自检(全部通过才输出)
1. 是否严格 `[` 开头 `]` 结尾,无围栏无解释?
2. 章号是否 {start_chapter} → {end_chapter} 连续升序、共 {count} 条?
3. 每条是否齐 4 字段、值非空、字数达标?
4. 强转折章数是否在 [{peak_min}, {peak_max}] 之间?是否有连续 3+ 章硬转折?
5. 是否与已写完段的伏笔/人物状态自然承接、无矛盾?

直接输出 JSON 数组,不要输出任何其他内容。"""

