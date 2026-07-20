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
from typing import TYPE_CHECKING, Callable, Optional, Protocol

from noval_workflow.volume_utils import volume_cast_card, volume_position_card

if TYPE_CHECKING:
    from noval_workflow.state import ChapterPlanItem, NovelState

    # chapter_plan_prompt_builder 的完整签名：与 PromptPack.chapter_plan_prompt 对应。
    # 各题材 flavor 可选提供,若 None 则回退到 base 的 _default_chapter_plan_prompt(中性版)。
    ChapterPlanPromptBuilder = Callable[
        ["NovelState", int, int, "list[ChapterPlanItem]"], str
    ]


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


# 8-field format shared by arc_outline_prompt (本文件) 与 chapter_plan_edit_subgraph 的弧线派生提示词
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


# 【档位分配与节奏张弛】base 通用默认模板。
# 使用 .format() 展开占位——因为 GenreFlavor.arc_rhythm_override 是纯字符串（不能嵌
# f-string 表达式），故 base 默认版本也统一走 .format() 机制，保持与 override 的
# 拼装路径完全一致。占位含义见 GenreFlavor.arc_rhythm_override docstring。
DEFAULT_ARC_RHYTHM_TEMPLATE = """## 档位分配与节奏张弛（最高优先级，决定整批弧线的呼吸感）
1. 每批 {BATCH_SIZE} 章必须呈现波浪式密度，**禁止章章高燃/章章强转折**。档位分布硬约束（合计 {BATCH_SIZE} 章）：
   - 爆发 + 转折 ≤ 40%（每批最多 {batch_default_burst} 章承担硬爽点/反转/大战）
   - 铺垫 + 缓冲 + 回落 ≥ 30%（每批至少 {batch_default_calm} 章承担蓄势、人物互动、氛围、情绪沉淀、信息释放）
   - 推进章补足其余配额，承担主线小步稳走
2. 首批开篇例外：首批 1-2 章允许密度稍高（用于立世界观/钩子），但仍须留 1 章做人物/氛围铺陈，避免开局就炸完所有牌。
3. 档位错排：禁止连续 2 章以上同属爆发/转折，高潮之间必须插入铺垫/缓冲/推进让读者喘口气；同样，铺垫/缓冲不连续超 2 章，防止拖。"""


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
        f"- 第{item.chapter}章[{item.intensity or '推进'}]｜目标:{item.purpose}｜关键事件:{item.key_turn}｜章末钩子:{item.ending_hook}"
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
    foreshadowing: dict  # 结构化格式 {"pending": [...], "collected": [...]}
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

    arc_rhythm_override: str = ""
    """[可选] 题材专属【档位分配与节奏张弛】段，非空时**完全替换** base 通用档位约束
    （即 arc_outline_prompt 里的默认 DEFAULT_ARC_RHYTHM_TEMPLATE 段落）。

    默认空 → 走 base 通用规则（爆发+转折 ≤ 40% / 铺垫+缓冲+回落 ≥ 30%），向后兼容,
    既有题材（末世/修仙/现代言情等）零影响。

    非空时字符串里可以用以下占位（base 拼装时用 .format() 展开）:
      - {BATCH_SIZE}           本批章数（NOVEL_BATCH_SIZE 环境变量）
      - {batch_max_burst}      按题材上限算出的最多爆发章数,如 max(1, int(BATCH_SIZE*0.2))
      - {batch_mid_burst}      中间档爆发上限 max(1, int(BATCH_SIZE*0.3))——反爽文但仍要冒险撑主线的题材用
      - {batch_mid_daily}      中间档日常下限 max(1, int(BATCH_SIZE*0.4))——与 batch_mid_burst 配套
      - {batch_min_daily}      按题材下限算出的最少日常章数,如 max(1, int(BATCH_SIZE*0.5))
      - {batch_default_burst}  base 默认爆发章上限 int(BATCH_SIZE*0.4)
      - {batch_default_calm}   base 默认铺垫章下限 max(1, BATCH_SIZE//3)
    题材通常用前几个;default 系列是给 base 默认模板保底用的。

    用途:搞笑异世界一类反爽文题材,需要爆发上限远低于 base 默认 40% —— 通过 override
    可以整段替换,而非追加,避免与 base 版本并列时数字打架。
    """

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

    # ── 题材专属:chapter_plan_prompt 完全 override ─────────────────────────────
    # 各题材的中景章节规划提示词底层示例差异极大——玄幻讲越阶战斗/机缘,言情讲关系推进/暧昧,
    # 都市讲利益博弈,不再适合走单一 focus 追加模式。各 flavor 通过 builder 提供整份 prompt;
    # None 时回退到 base 中性版(_default_chapter_plan_prompt)。
    #
    # 类型是 Callable 而非 str,overrides.py::_clean 的 isinstance(v, str) 过滤天然把
    # callable 排除,前端 prompt_overrides.json 不能覆盖它——保证 JSON 存储边界安全。
    chapter_plan_prompt_builder: Optional["ChapterPlanPromptBuilder"] = None


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
    def character_cards_prompt(self) -> str:
        """Phase-1 一次性直出全套核心人物的结构化 CharacterCard（取代原 bible 散文）。

        不再「先出散文档案再抽卡」——直接让 LLM 输出 {"new_cards": [CharacterCard...]} 落 entity_cards，
        省一跑 LLM。深层设计承载在 canon 字段里：全书弧光核心角色写；双层人设/底牌契约按 role
        定位「条件触发」（主角/根源反派/关键角色才写，普通配角/非战斗角色留空，避免套路化雷同）。
        返回的是已格式化终稿字符串（含字面 JSON 花括号），不再经二次 .format()。
        """
        focus = f"\n- 题材聚焦：{self.flavor.character_profiles_focus}" if self.flavor.character_profiles_focus else ""
        return f"""## 角色定位

{self.flavor.system_identity}

## 任务目标

为全书一次性生成可对接全书阶段式大纲、适配明暗双线、分层立体的**全套核心人物结构化卡**，直接输出 JSON（不写散文档案）。

## 卡司配额（严格遵守）

- 主角 1 位；核心配角 3-5 位；阶段功能性反派 2-3 位 + 终极根源反派 1 位；关键感情线角色 1-2 位。
- 按此配额生成，不遗漏、不超编；确需增减须服务主线，不得堆砌工具人凑数。
- 大纲/冲突里点名的**关键势力**可一并建卡（type=势力，填 standing）。

## 单张人物卡字段（严格 JSON）

```
{{"name": "角色名（唯一，作主键）", "type": "人物", "aliases": ["别称/绰号，无则空数组"], "summary": "一句话定位（≤30字）", "first_appear_chapter": 1, "role": "单选,只能填一个:主角/主要配角/功能性反派/根源反派/感情线角色/次要角色（身兼多重定位如「主要配角+感情线」只填最主要的一个,禁止拼多个）", "appearance": "体貌基线（身形/气质/年龄段/大致长相,供正文外貌一致性）+ 可选1个识别特征,≤60字", "speech_style": "说话风格/口吻/温度（健谈/毒舌/寡言/温和/跳脱…,≤30字）", "personality": "【表层公开人设】读者视角性格底色", "abilities": "能力底牌一句话摘要（须落【力量体系】层级/流派）", "hidden_persona": "【深层隐藏人设·条件字段】仅主角/根源反派/确有反转设计的关键角色写:暗线秘密/异常/隐藏能力/立场偏差,与表层不冲突、可后期反转;普通配角/功能角色留空,不强凑", "arc_trajectory": "全书弧光:开篇→收官心性/立场/羁绊/认知迭代大势(只写大势不填情节);反派写阶段作用+闭环退场", "ability_contract": "【条件字段】仅战力相关的关键角色/确有需要才写:初始锚点(开篇实力对应力量体系哪层)+全书成长天花板(开篇→收官能力上限走势)+隐藏杀手锏(触发与反噬,不提前解锁);非战斗/次要/纯功能角色留空或只写简单 abilities", "motivation": "开篇当前动机/目标", "current_state": "开篇处境:位置/情绪/状态（≤30字）", "relations": "与主角/他人关系(围绕主角:情感位/信任位/冲突位/对立位/功能位)"}}
```

## 硬性创作规则（沿用 bible）

- **人设双层按需触发**：主角、根源反派、及确有反转设计的关键角色才写 `hidden_persona`（深层隐藏人设），与表层 `personality` 不冲突、可后期完美反转收束；普通配角/功能角色只写 `personality`、留空 `hidden_persona`——不搞全员双层，避免「人人藏秘密/藏铁证」式套路化雷同。
- **严格绑定全书成长**：`arc_trajectory` 只写心性/立场/羁绊/认知的迭代大势，不填充具体情节/互动/台词。
- **能力落体系 + 底牌契约按需**：`abilities` 必须归属【力量体系】层级/流派，禁止体系外凭空能力（全员适用）。`ability_contract`（初始锚点+全书成长天花板+隐藏杀手锏）仅对战力相关的关键角色写，非战斗/次要/纯功能角色留空——不给官僚/文职等角色硬塞「隐藏杀手锏」。写了契约的，隐藏杀手锏须写明触发与反噬、作为暗线素材不得提前解锁；此契约为「阶段固化数据」台账的战力校验红线。
- **人设绝对自洽**：所有角色具备明确软肋/原生缺陷/心理枷锁/立场理由，无绝对善恶，对立/抉择/背叛/牺牲均源于底层逻辑，杜绝脸谱化、工具人、强行降智。
- **外貌给足基线、但别刷标签**：`appearance` 要写清体貌基线（身形/气质/年龄段/大致长相），供后期正文外貌一致、不乱飘；识别特征最多 1 个。人设仍靠对话/选择/反应建立，禁止靠口头禅/固定动作/服饰反复刷标签（反刷标签只约束识别特征，不压制体貌本身）。
- **说话风格拉开差异**：全卡司 `speech_style` 要有温度/句长/口头禅的区分，需有足够健谈/外放的角色带动对话；主角不宜默认寡言话少；忌全员冷/沉默/话少，否则对话推不动剧情。
- **命名可读、可区分、贴世界观**：避开烂大街网文姓（叶/萧/林/楚/苏/慕容），避生僻拗口字（读者打不出、记不住）；配角之间拉开区分度（别都两字、都一个声调）；反派可用文雅冷静的名（比脸谱化更瘆人）；命名语域贴合世界观设定，别中洋混搭违和。血缘关系（兄弟/家族）同姓是合理的，不算撞名。
- **留白规则**：只写骨架设定/底层逻辑/成长大势/立场羁绊/能力短板/秘密底色，禁止具体日常/互动/台词/战斗画面/细碎心理。
- **反派分层设计**：区分功能性反派与根源反派，`role` 如实标注，`arc_trajectory` 写明动机根源/阶段作用/闭环退场逻辑，保留人性复杂度。
- **人物关系闭环**：全员 `relations` 围绕主角构建，情感/信任/冲突/对立/功能位清晰，无孤点、无狗血、无逻辑 BUG。{focus}

## 输出格式（严格 JSON 对象，无 markdown 围栏）

直接输出如下结构，不要包裹在 ```json 里，不要有解释文字：

```
{{"new_cards": [ /* 全套核心人物卡，每张字段如上；关键势力卡另附 */ ]}}
```

## 输出前自检（不达标则重写，达标才输出）

1. 卡司配额是否齐全、主角唯一、无工具人凑数？
2. 该写 `hidden_persona` 的角色（主角/根源反派/关键反转角色）写了、其余角色没硬凑，且写了的可反转收束？
3. 每张卡 `role` 是否为六枚举之一？
4. 各角色 `abilities` 是否归属【力量体系】？写了 `ability_contract` 的角色初始锚点与全书成长天花板是否落在境界阶梯上、非战斗角色是否未硬塞契约？
5. `relations` 是否都指向主角、闭环无孤点？姓名是否避开烂大街姓/生僻拗口、配角彼此区分得开、语域贴世界观（血缘同姓属正常，不算问题）？
6. 外貌是否都给了体貌基线（不只单个配饰/印记）？全卡司说话风格是否拉开差异、没有全员寡言话少？

请直接输出 JSON 对象。"""

    @property
    def summary_prompt(self) -> str:
        """章节概要提示词，与题材无关，返回共享常量。"""
        return SUMMARY_PROMPT

    # ── 动态提示词（通用脚手架 + 风味片段）──────────────────────────────────

    def overall_outline_prompt(self, total_word_count: str) -> str:
        """生成全书方向性战略骨架 + 全局结局定位（只给方向趋势、不写具体事件；不预设卷数/卷长——卷与具体事件由后续 volumes / chapter_plan 滚动落地）。"""
        # word_count_desc 直接用用户原文(如"50万字"),不再额外拼"字"——历史遗留双字 bug 修复
        word_count_desc = total_word_count if total_word_count else "长篇"
        focus = f"\n- 题材聚焦：{self.flavor.overall_outline_focus}" if self.flavor.overall_outline_focus else ""
        return f"""{self.flavor.system_identity}
任务：搭建本书**方向性战略骨架 + 全局结局定位**，只做战略层顶层规划，不填充具体章节、台词、场景细节，也**不预先划分卷数、不锁定每卷章数**（分卷在写作推进中按内容量滚动生成）。
严格遵守以下硬性创作规则：
按「起（引入）→承（展开）→转（升级/高潮）→合（收束）」勾勒全书阶段推进的大脉络，各阶段只写**方向与趋势**：阶段定位、矛盾升级的方向、主角与核心角色关系演变的大轨迹、人物群像互动大势、阶段情绪基调走向、阶段末主角团处境的定性变化。**任何一段都不要写具体高潮场景、具体事件经过、具体数值/等级/道具、单次胜负结果——这些是卷级/章级的活,一律留给后续 volumes 与 chapter_plan 临场决定**。越靠后的阶段(尤其「合」)越只给方向、越不锁死实现,给滚动生成留足后期适应空间。**这些阶段是叙事节拍，不是硬性卷划分——不要写「第一卷/第二卷」式的固定卷号切分**。全书体量：{word_count_desc}。
双线并行设计：一条明主线为外部事件/任务/冒险推进线，一条隐藏暗线为角色关系/信任/身份揭秘线，暗线最终与主线交汇完成情感与逻辑闭环。
人物规则：仅敲定主角+核心配角群的人物关系演变、立场变化、成长弧光大轨迹，不锁定具体相遇时机、对话内容、互动桥段、搞笑场景、情感爆发台词。保留角色动态调整空间。
势力/规则格局：只梳理世界观规则、组织/势力关系的大势变化，不锁定单次冲突胜负、临时规则、新增小团体。
强制留白清单，以下细节一律不写、不预设、不规划：具体章节剧情、具体台词与吐槽、角色内心独白、搞笑桥段、日常场景细节、单场战斗过程、任一阶段高潮的具体经过与结果、情感互动细节、一次性的突发事件结果、临时新增角色/势力的设定、具体等级/金钱/道具数值。所有微观内容留给后续细分小大纲。
结局规范：仅锁定结局情感基调、主角与核心角色关系终态、全书核心立意；具体收尾场景、角色最终细碎归宿、收尾台词全部留白。
整体硬性标准：阶段节奏层层递进，主角视角清晰，角色群像关系闭环，逻辑自洽，框架具备强延展性、可支撑长篇连载滚动展开。{focus}
{_FOUNDATION_RIGOR}
输出要求：直接输出纯大纲正文，无需开场白、解释、标题，各阶段分段清晰；战略骨架总字数约 1200-1800 字（与后续审核口径一致），宁可偏短、点到方向为止——过长必然侵占 volumes / chapter_plan 的留白空间、把后期发展提前写死。"""

    def volumes_prompt(self, overall_outline: str, lookahead: int = 2) -> str:
        """规划开篇前 (1+lookahead) 卷——第 1 卷激活（要立即展开），其余为前瞻草稿。

        滚动生成卷 + 前瞻队列：开书一次规划「1 激活卷 + N 草稿卷」；草稿卷只出方向骨架、
        不锁章号，给当前卷规划提供中期地图，轮到时再由 save_volumes 权威锁章号转正。
        契约（关键，与 nodes/volumes._parse_volume_drafts 对齐）：
          - 输出 `{"volumes": [激活卷, 草稿1, ...]}`，数组长度 = 1 + lookahead
          - 激活卷（第 1 项）4 字段 title/summary/setup_for_next/chapters（本卷章数）
          - 草稿卷（其余项）3 字段 title/summary/setup_for_next（无 chapters）
          - index/chapter_start/planned_end/status 由后端权威赋值，LLM 不出绝对章号
        """
        total = 1 + lookahead
        return f"""你是网文分卷结构化规划助手。任务：为本书规划开篇的前 {total} 卷，返回严格 JSON 对象。
第 1 卷是**要立即展开写作的激活卷**，第 2-{total} 卷是**前瞻草稿卷**（只给方向、不写细节，用于规划当前卷时提供中期地图）。

# 输入：整体大纲（全书战略方向）
{overall_outline}

# 硬约束
1. 输出**纯 JSON 对象**（以 {{ 开头、}} 结尾），不要 markdown 代码围栏（```），不要任何解释文字。
2. 对象仅含一个字段 `volumes`：一个长度为 {total} 的数组。
   - 激活卷（数组第 1 项）含 4 字段：
     · title: str（卷名，如「第一卷 · 少年入宗」，≤20 字）
     · summary: str（本卷主线目标 + 情绪基调 + 收尾状态，≤80 字）
     · setup_for_next: str（卷尾为下一卷埋的钩子/悬念/角色转折，具体、非套话）
     · chapters: int（本卷**章数**，按内容量判断；松区间 15-50 章）
   - 草稿卷（第 2 项起）只含 3 字段 title / summary / setup_for_next（**不要 chapters**——草稿卷不定章数，轮到展开时再定）。
3. **卷是一个完整的小故事**：起（引入舞台/人物/目标）→承（展开铺垫）→转（本卷高潮/关键转折）→合（收束 + 埋下一卷钩）。
4. **激活卷（卷1）要具体、可直接展开**；**草稿卷只给方向骨架**——写清本卷大致要发生什么、承接前一卷什么钩即可，summary 精炼，不写章级细节。
5. 后续每卷从前一卷 setup_for_next 自然承接，整体沿 overall_outline 的阶段推进、不重复不倒退。
6. 不要输出 index / chapter_start / planned_end / status 等字段，它们由系统权威赋值。

# 输出样例（仅示字段格式；实际 volumes 长度以硬约束 {total} 为准）
{{"volumes": [{{"title": "第一卷 · 破题", "summary": "主角从平凡卷入江湖，初识伙伴与劲敌，卷末踏入更大舞台", "setup_for_next": "母亲遗物半张地图指向禁地", "chapters": 28}}, {{"title": "第二卷 · 入局", "summary": "循地图进入禁地，牵出隐藏势力，身世露端倪", "setup_for_next": "宿敌登场"}}]}}

现在开始，直接输出 JSON 对象："""

    def volumes_prompt_rolling(
        self,
        overall_outline: str,
        prior_volumes_brief: str,
        total_chapters_written: int,
        next_index: int,
        next_chapter_start: int,
        prev_setup_for_next: str,
        lookahead: int = 2,
    ) -> str:
        """滚动重新规划从第 next_index 卷起的 (1+lookahead) 卷——激活卷承接上一卷卷尾钩，其余前瞻草稿。

        每次滚动只重新生成「未开始的卷」；已排产/已写的卷（prior_volumes_brief）冻结、不改动。
        契约同首卷（`{"volumes":[...]}`，激活卷含 chapters、草稿卷不含），只是输入换成
        「已写进度 + 已冻结卷节选 + 上一卷卷尾钩」，要求激活卷自然承接、推进下一阶段、不重复已写内容。
        """
        total = 1 + lookahead
        last_index = next_index + lookahead
        prev_hook = prev_setup_for_next.strip() or "（上一卷未显式埋钩，请自行从整体大纲下一阶段接续）"
        return f"""你是网文分卷结构化规划助手。本书正在连载，现需重新规划**从第 {next_index} 卷起的后续 {total} 卷**（第 {next_index} 卷是即将展开的激活卷，第 {next_index + 1}-{last_index} 卷是前瞻草稿），返回严格 JSON 对象。

# 整体大纲（全书战略方向）
{overall_outline}

# 已排产/已写的卷（节选，已冻结——不要改动、不要重复）
{prior_volumes_brief}

# 当前进度
- 全书已写完 {total_chapters_written} 章
- 上一卷卷尾埋的钩：{prev_hook}
- 第 {next_index} 卷将从第 {next_chapter_start} 章开始（系统已锁定，你无需输出章号）

# 硬约束
1. 输出**纯 JSON 对象**（以 {{ 开头、}} 结尾），不要 markdown 围栏，不要解释文字。
2. 对象仅含 `volumes` 数组，长度 {total}：第 1 项 = 第 {next_index} 卷（激活卷，4 字段含 chapters）；其余 = 前瞻草稿卷（3 字段，无 chapters）。
3. 激活卷必须**自然承接上一卷卷尾的钩子/悬念**，推进 overall_outline 下一阶段，**不重复已写内容、不倒退**。
4. **激活卷要具体可展开**；草稿卷只给方向骨架，可基于最新剧情走向自由调整（这些卷尚未开写）。
5. 每卷是完整小故事（起承转合 + 卷末埋钩）；若某卷为全书收官卷，其 setup_for_next 可说明「本作终卷」。
6. 不要输出 index/chapter_start/planned_end/status 等字段（系统权威赋值）。

# 输出样例（仅示字段格式；实际 volumes 长度以硬约束 {total} 为准）
{{"volumes": [{{"title": "第 {next_index} 卷 · 风起", "summary": "承接上一卷悬念，主角踏入新舞台，卷末揭开一层真相", "setup_for_next": "盟友真实身份浮出水面", "chapters": 32}}, {{"title": "第 {next_index + 1} 卷 · 潮涌", "summary": "新势力入局，矛盾升级", "setup_for_next": "关键抉择迫近"}}]}}

现在开始，直接输出 JSON 对象："""

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
        state: "NovelState | None" = None,
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

        state（可选）：传入 NovelState 以启用【当前卷位置】注入。为空则不注入（旧调用点/单测
        不受影响）；prepare_chapter 会传入，让本章创作能感知横向分卷定位（卷内位置、上下卷）。
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

        # 【当前卷位置】——横向分卷位置卡，非空时插在头部让本章创作感知卷内定位。
        # state 参数为空（旧调用点/单测）或 volumes 空时返回 ""，不影响原逻辑。
        volume_section = ""
        if state is not None:
            card = volume_position_card(state)
            if card:
                volume_section = f"\n\n{card}"

        return f"""{self.flavor.system_identity}

请撰写第{chapter_num}章：《{title}》{volume_section}

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
- 修辞为剧情服务，忌无缘无故：每个比喻/形容都要问一句"它让读者更懂、更爽、更有画面了吗"——没用就删。一段最多一个比喻且必须服务情绪或画面；爽点、战斗优先用具体动作和细节，不优先堆比喻，禁止为"显文艺"而叠喻、排比、华丽形容。
- 忌同义反复与极端词：一个意思别用几个近义词说两三遍（"他非常生气，他怒了"——留最准的一个，最好换成动作）；"非常/极其/极大/无比/十分/特别"这类程度词删九成，程度靠具体画面给（不写"压力非常大"，写"三天没合眼，烟灰缸堆成小山"）。
- 不写说明书：不要停下来给读者讲机制原理、招式为何生效、规则如何运作、人物动机来龙去脉——用动作与结果演出来，留白让读者自己拼。战斗与金手指是"打出来/使出来"给人看，不是"解释清楚"给人听。
- 标点克制守规范：破折号最易暴露机器感，非必要不用，一章至多一两次；省略号一律用"……"（不写 ... 或 。。。）；并列用顿号"、"，不用句号一刀刀切开；对话与引语用中文弯双引号（""），嵌套才用弯单引号（''），不用直角引号「」『』。
- 开篇不倾泻背景：开头先落地"当下的场景、动作与处境"抓住读者；人物身世、数值设定、金手指来历、势力关系等背景信息，打散到后文用得上时借情节自然带出，严禁在开篇几段集中交代设定（最典型的劝退写法）。

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

        # ── 位置卡:显式告诉 LLM「你在全书哪个位置写、下一批要写哪些章」 ──────────
        # 修复缺陷:此前 LLM 只能从前文摘要头部「第 X 章摘要」暗示章号,没有显式位置说明,
        # 容易在「是不是该收尾 / 是不是还早」这类阶段判断上飘。这里补一段头部锚点段。
        # 目标章数字段 state.total_word_count 是字符串目标(如「50 万字」),不解析,原样透传。
        done = state.total_chapters_written
        plan_coverage_note = ""
        if state.chapter_plan and state.chapter_plan_planned_upto:
            plan_coverage_note = (
                f" · chapter_plan 已前瞻到第 {state.chapter_plan_planned_upto} 章"
                f"({len(plan_entries)} 条锚点覆盖本批)"
                if plan_entries else
                f" · chapter_plan 已前瞻到第 {state.chapter_plan_planned_upto} 章(本批未覆盖)"
            )
        position_section = (
            "\n\n【本批位置卡】\n"
            f"- 本批将规划：全书第 {batch_start} — {batch_end} 章（闭区间,共 {BATCH_SIZE} 章）\n"
            f"- 已完成：{done} 章\n"
            f"- 全书目标篇幅：{state.total_word_count or '未设定'}"
            f"{plan_coverage_note}"
        )

        # 【当前卷位置】——横向分卷位置卡，让 LLM 知道本批处于哪一卷、卷进度、上下卷。
        # 未启用分卷（state.volumes==[]）时 volume_position_card 返回 ""，不影响原逻辑。
        volume_card = volume_position_card(state)
        volume_section = f"\n\n{volume_card}" if volume_card else ""

        # 【本卷花名册】——卷级登场阵容（返场弧线 + 新登场名单）；未生成/陈旧时返回 "" 不注入。
        cast_card = volume_cast_card(state)
        cast_section = f"\n\n{cast_card}" if cast_card else ""

        is_first_batch = state.total_chapters_written == 0
        continuity_rule = (
            "1. 作为本书第一批章节，请严格按照整体大纲的开篇定位规划故事起点，奠定世界观、人物关系与核心冲突的基调。"
            if is_first_batch else
            "1. 严格承接上一批大纲最终结尾情节，情节逻辑连贯、无断层，全程贴合作品整体主线大纲，不偏离核心世界观、势力设定、人物人设与核心冲突。"
        )

        max_words = BATCH_SIZE * 500
        focus = f"\n- 题材聚焦：{self.flavor.arc_focus}" if self.flavor.arc_focus else ""

        # 【档位分配与节奏张弛】段:题材可通过 arc_rhythm_override 完全覆盖 base 通用版本。
        # 用 .format() 展开 BATCH_SIZE 等占位——因为 override 字段是纯字符串,不能在其中
        # 嵌 f-string 表达式。故 base 默认版本也统一走同一套占位机制,行为等价。
        rhythm_kwargs = {
            "BATCH_SIZE": BATCH_SIZE,
            "batch_default_burst": int(BATCH_SIZE * 0.4),
            "batch_default_calm": max(1, BATCH_SIZE // 3),
            "batch_max_burst": max(1, int(BATCH_SIZE * 0.2)),
            "batch_mid_burst": max(1, int(BATCH_SIZE * 0.3)),  # 反爽文但要冒险撑主线的中间档:~30% 爆发上限
            "batch_min_daily": max(1, int(BATCH_SIZE * 0.5)),
            "batch_mid_daily": max(1, int(BATCH_SIZE * 0.4)),  # 与 batch_mid_burst 配套:日常仍是主体但让出冒险空间,~40% 下限
        }
        rhythm_template = (
            self.flavor.arc_rhythm_override
            if self.flavor.arc_rhythm_override
            else DEFAULT_ARC_RHYTHM_TEMPLATE
        )
        rhythm_section = rhythm_template.format(**rhythm_kwargs)

        return f"""请为本批接下来的 {BATCH_SIZE} 章（全书第 {batch_start} — {batch_end} 章）规划故事弧线大纲。{volume_section}{cast_section}{position_section}{prev_section}{chapter_plan_section}

# 角色：你是专业网文分章弧线大纲撰写师
## 整体约束
{continuity_rule}
2. 本批次所有章节大纲总字数严格控制在 {max_words} 以内；**单章节内容节点文字不得超过500字**，精简表述，拒绝冗余描写、抒情、旁白。
3. 仅输出结构化章节大纲，不撰写正文内容、不生成章节标题，仅为标题、正文创作提供明确锚点。

{ARC_CHAPTER_FORMAT}

{rhythm_section}

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
        """滚动章节规划(chapter_plan)提示词——委托到题材 flavor 的 builder。

        chapter_plan 的底层示例(主角能动性/爽点清单/合规样本)题材差异极大——玄幻讲越阶
        战斗/机缘,言情讲关系推进/暧昧,都市讲利益博弈,单一 focus 追加压不住。所以每个
        题材 flavor 通过 chapter_plan_prompt_builder 提供整份 prompt;None 时回退到
        base 的 _default_chapter_plan_prompt(中性版)。

        locked_entries 是已写完段(chapter <= total_chapters_written)的历史条目,只作为
        承接参考,LLM **禁止**修改或重复输出这些章号——save_chapter_plan 兜底合并保留历史。
        """
        builder = self.flavor.chapter_plan_prompt_builder
        if builder is not None:
            return builder(state, start_chapter, end_chapter, locked_entries)
        return _default_chapter_plan_prompt(state, start_chapter, end_chapter, locked_entries)


# ── chapter_plan_prompt 复用辅助 ──────────────────────────────────────────────
# 供 base 中性版与各题材 flavor 的 builder 复用,减少重复代码。


def format_chapter_plan_state_snapshot(state: "NovelState") -> str:
    """把 state 里的台账快照(伏笔/阶段固化)组装成 chapter_plan 提示词的「状态注入」段。
    所有 flavor builder 共享此函数,避免各处重复。

    人物动态（处境/关系）不在此注入——已并入 CharacterCard，由 system_context 经
    build_foundation_context 统一渲染，避免与卡库双源。无任何非空字段时返回空串。
    """
    import json

    status_lines: list[str] = []
    if state.foreshadowing:
        fs_json = json.dumps(state.foreshadowing, ensure_ascii=False, indent=2)
        status_lines.append(f"【伏笔台账】\n{fs_json}")
    if state.phase_summary:
        status_lines.append(f"【阶段固化数据】\n{state.phase_summary}")
    return ("\n\n" + "\n\n".join(status_lines)) if status_lines else ""


def format_chapter_plan_locked_section(
    state: "NovelState", locked_entries: "list[ChapterPlanItem]"
) -> str:
    """把「已锁定的历史章节规划条目」渲染为提示词段;无历史时返回空串。

    章号范围按实际传入的 locked_entries 取(可能是本卷之前的一段窗口,非整段 1~已写)。
    """
    if not locked_entries:
        return ""
    import json
    from dataclasses import asdict

    locked_json = json.dumps(
        [asdict(item) for item in locked_entries],
        ensure_ascii=False,
        indent=2,
    )
    first_ch = locked_entries[0].chapter
    last_ch = locked_entries[-1].chapter
    return (
        f"\n\n【已锁定的历史章节规划条目（章号 {first_ch} ~ {last_ch}，"
        "供承接参考，严禁修改或重复输出这些章号）】\n"
        f"{locked_json}"
    )


def compute_chapter_plan_quotas(count: int) -> dict:
    """按本次规划章数算 7 档配额上下界与主角能动性阈值。所有 builder 共享同一套算法,
    保证不同题材下节奏骨架一致(只有档位内涵与爽点清单题材化,配额比例不变)。
    """
    return {
        "count": count,
        "burst_max": max(2, count // 5),           # 爆发章上限（约20%）
        "burst_min": max(1, count // 7),           # 爆发章下限（约14%）
        "big_turn_max": max(1, count // 6),        # 大转折上限（约16%,与爆发合计≤35%）
        "small_turn_min": max(2, count // 8),      # 小转折下限（约12-15%）
        "lull_streak_max": 2,                       # 连续淡章上限（铺垫/缓冲/回落）
        "passive_streak_max": 2,                    # 主角连续被动承压上限
        "win_cadence": 5,                           # 每N章必须有一次主角时刻/爽点
        "core_hook_payoff_max": 12,                 # 核心冲突钩子铺到兑现上限（章数）
    }


@dataclass(frozen=True)
class ChapterPlanGenreSpec:
    """chapter_plan_prompt 的题材差异化拼图——每个 flavor builder 提供一份 spec,由
    render_chapter_plan_prompt 组装成完整提示词。所有字段有中性默认值,不填即回退。

    设计要点:
    - 通用骨架(输出契约/档位分配比例/配角伏笔/常见格式错误/自检项)由 render 统一提供,
      各题材不重复。
    - 题材差异只体现在:合规样本/主角能动性清单/看点清单/大纲对齐补充/钩子反模板补充/
      档位语义重解释/常见错误(题材向)。
    - 全 frozen dataclass:一次实例化,不可变,可作 module 常量安全共享。
    """

    # 「最短合规样本」的两条示例(会拿到 start_chapter 变量做 f-string 化插值),
    # 用 {start_chapter} 占位符——render 时替换。
    sample_entry_1: str = (
        '{{"chapter": {start_chapter}, "purpose": "主角初入陌生环境被排挤，埋下反制契机", '
        '"key_turn": "无意间抓到关键信息，看破对手一处破绽", '
        '"ending_hook": "主角把这条信息写进随身笔记，只画了一个圈", "intensity": "铺垫"}}'
    )
    sample_entry_2: str = (
        '{{"chapter": {start_chapter_plus_1}, "purpose": "主角首次主动出手，展露真实一面", '
        '"key_turn": "利用信息差反将一军，被暗中观察者留意", '
        '"ending_hook": "观察者在名册上悄悄把主角标了颜色", "intensity": "小转折"}}'
    )

    # 「主角能动性」清单——列出本题材下「主角时刻」的具体形态
    agency_examples: str = (
        "主动决策、关键胜利或收获、能力或身份被目击、信息优势、关系突破、获得关键契机"
    )

    # 「看点密度」清单——本题材下的看点具体形态,每一条一行,不带项目符号(render 加)
    payoff_types: tuple[str, ...] = (
        "主角关键胜利或反制（对手吃瘪/情势翻盘）",
        "隐藏能力 / 身份 / 底牌被目击，引起关键人物关注",
        "关键信息优势（知道别人不知道的事）",
        "获得关键契机（资源 / 人脉 / 传承 / 情感突破 / 关系升级）",
        "主要人物关系推进（羁绊、CP、盟友、宿敌）的实质变化",
    )

    # 「档位语义重解释」——若本题材的 7 档语义与通用不同(如 romance 的爆发=关系巅峰),
    # 提供 override;为空则用通用语义。key 是 7 档档位名,value 是本题材下的一句话解释。
    intensity_semantics_override: tuple[tuple[str, str], ...] = ()

    # 「大纲对齐」段第 3 条(跃迁前必须铺垫)的题材化具体形式,如玄幻=「修炼/悟道/受挫」、
    # 都市=「学习/积累/失落/受伤」、romance=「误会/心结/情感受挫」。为空用通用词。
    escalation_prerequisites: str = "学习、积累、失落、休整、思考、试错"

    # 「钩子反模板」的题材专属追加条目——通用的「脚步声/黑影/眼前一幕」已经在 render 里,
    # 这里追加本题材容易犯的套路(如 romance 的「XX 突然表白」、玄幻的「XX 出手了」)。
    # 每条一行,不带项目符号。
    genre_hook_antipatterns: tuple[str, ...] = ()

    # 「题材常见错误」的追加条目——通用错误已在 render 里,这里追加本题材容易踩的坑
    # (如 urban 提醒 ban 玄幻词汇、romance 提醒不许纯甜/纯虐连续)。每条一行,不带 ❌ 前缀。
    genre_common_mistakes: tuple[str, ...] = ()

    # 「题材附加硬约束」——romance 的甜虐塌陷防护、xianxia 的每 N 章一次境界推进等,
    # 追加到「档位分配」段之后作为「题材专属节奏约束」。为空则不追加。
    genre_extra_rhythm_rules: str = ""


def render_chapter_plan_prompt(
    state: "NovelState",
    start_chapter: int,
    end_chapter: int,
    locked_entries: "list[ChapterPlanItem]",
    spec: ChapterPlanGenreSpec,
) -> str:
    """chapter_plan_prompt 的参数化渲染器——通用骨架 + spec 提供的题材差异化片段。

    所有 flavor builder 都调用本函数并传自己的 spec;base 的中性版直接用 spec 默认值。
    """
    count = end_chapter - start_chapter + 1
    is_first_plan = state.total_chapters_written == 0

    continuity_rule = (
        "本次是首次章节规划，请紧扣整体大纲的开篇定位，奠定世界观、人物关系与核心冲突的基调；前 2-3 章允许慢热但必须挂钩子。"
        if is_first_plan else
        "本次是滚动重规划，请严格承接已写完章节的伏笔、人物状态、势力格局与情绪走向；不要另起炉灶推翻已发生的剧情。"
    )

    written_brief = _format_written_chapters_brief(state)
    written_section = (
        f"\n\n【已写完章节速览（最近 10 章，供承接参考）】\n{written_brief}"
        if written_brief else ""
    )
    locked_section = format_chapter_plan_locked_section(state, locked_entries)
    status_section = format_chapter_plan_state_snapshot(state)

    # 【当前卷位置】——横向分卷位置卡；未启用分卷时为空串不注入。
    volume_card = volume_position_card(state)
    volume_section = f"\n\n{volume_card}" if volume_card else ""

    # 【本卷花名册】——卷级登场阵容，让章节规划知道本卷谁登场/各自本卷弧线；未生成/陈旧时不注入。
    cast_card = volume_cast_card(state)
    cast_section = f"\n\n{cast_card}" if cast_card else ""

    q = compute_chapter_plan_quotas(count)
    burst_max = q["burst_max"]
    burst_min = q["burst_min"]
    big_turn_max = q["big_turn_max"]
    small_turn_min = q["small_turn_min"]
    lull_streak_max = q["lull_streak_max"]
    passive_streak_max = q["passive_streak_max"]
    win_cadence = q["win_cadence"]
    core_hook_payoff_max = q["core_hook_payoff_max"]

    # 7 档档位语义:通用默认 + 题材覆盖(romance 会把爆发/大转折等语义换成情感线内涵)
    default_intensity_semantics: dict[str, str] = {
        "铺垫": "环境描写/人物登场/日常铺陈，低张力",
        "缓冲": "高潮后休整/关系深化/情绪消化，给读者呼吸",
        "推进": "主线小步进展/信息推进/关系微变，中度张力（主体档位）",
        "小转折": "小高潮/关键胜利或收获/关系突破/关键信息揭露",
        "大转折": "身份揭晓/核心反转/重大挫折/立场逆转",
        "爆发": "核心冲突兑现/大高潮/关键节点集中释放",
        "回落": "高潮后的余波/代价展现/情绪收尾/新平衡建立",
    }
    for level, meaning in spec.intensity_semantics_override:
        default_intensity_semantics[level] = meaning
    intensity_block = "\n".join(
        f"     * `{level}` — {default_intensity_semantics[level]}"
        for level in ("铺垫", "缓冲", "推进", "小转折", "大转折", "爆发", "回落")
    )

    # 合规样本:sample_entry_{1,2} 中的 {start_chapter}/{start_chapter_plus_1} 占位符渲染
    sample_1 = spec.sample_entry_1.format(
        start_chapter=start_chapter,
        start_chapter_plus_1=start_chapter + 1,
    )
    sample_2 = spec.sample_entry_2.format(
        start_chapter=start_chapter,
        start_chapter_plus_1=start_chapter + 1,
    )

    payoff_block = "\n".join(f"   - {p}" for p in spec.payoff_types)

    # 通用钩子反模板 + 题材追加
    generic_hook_bans = [
        "「XX的脚步声传来」「门外传来XX声音」",
        "「XX突然出现/突然出现了」「一道黑影闪过」「一道身影出现」",
        "「XX看到了让他震惊的一幕」「眼前的景象让他惊呆了」",
        "「等待他们的是...」「接下来会发生什么」「故事才刚刚开始」",
    ]
    hook_ban_block = "\n".join(f"- {h}" for h in generic_hook_bans + list(spec.genre_hook_antipatterns))

    # 通用常见错误 + 题材追加
    generic_mistakes = [
        "加 markdown 围栏 ```json ... ```",
        "数组前写「以下是规划：」等解释",
        "章号跳号或倒序，或与「已锁定条目」章号重复",
        "字段用中文键名（用「目标」代替 `purpose` /「档位」代替 `intensity`）",
        "5 字段缺一，或字段值写空串/「待定」/「无强转折，以XX铺垫为主」",
        "章章都是强转折（违反节奏分布约束）",
        "intensity 写「快」「慢」「强」「弱」「高」「低」等非 7 档枚举值",
        "ending_hook 写「XX 传来脚步声」「黑影闪过」「等待他们的是...」等套路伪钩子",
        "key_turn 写「无强转折」「以铺垫为主」等套话（必须写具体事件，哪怕是淡章也要写明具体推进了什么）",
    ]
    mistakes_block = "\n".join(f"❌ {m}" for m in generic_mistakes + list(spec.genre_common_mistakes))

    genre_extra_rhythm = f"\n\n{spec.genre_extra_rhythm_rules}" if spec.genre_extra_rhythm_rules else ""

    return f"""请为本作品规划**本卷** {count} 章的**中景章节规划**（chapter_plan）。{volume_section}{cast_section}{written_section}{locked_section}{status_section}

# 角色：你是长篇网文的中景大纲规划师，负责在「整书大纲」与「批级弧线」之间给出**当前整卷** {count} 章的路线图。

## 本次任务范围
只输出章号 {start_chapter} - {end_chapter}（闭区间，共 {count} 条）的新条目，**严禁**输出其他章号，**严禁**重复输出「已锁定的历史条目」中的章号。**严格停在第 {end_chapter} 章**——超出 {end_chapter} 的条目会被系统直接丢弃（本次规划覆盖当前整卷 [第 {start_chapter} 章, 第 {end_chapter} 章]，后续卷由下一轮滚动卷规划展开），多写纯属浪费 token。头部卷位置卡的「后续卷前瞻」只是中期方向地图，供你为当前卷提前埋线、铺垫、呼应用，**不要**为后续卷输出任何章节条目。

## 输出契约（严格 JSON，无任何附加文本）
1. 直接输出一个 JSON 数组，第一个字符是 `[`，最后一个字符是 `]`。
2. **禁止** markdown 围栏（如 ```json）、**禁止**前置解释、**禁止**任何解释性文字。
3. 数组元素**必须**为对象，**必须**包含且仅包含 5 个字段：
   - `chapter`：整数，全书章号（1-based），范围 [{start_chapter}, {end_chapter}]，严格连续升序。
   - `purpose`：字符串，本章要完成的「活」/目标，一句话概括（≤40 汉字）。
   - `key_turn`：字符串，本章关键事件/看点（≤40 汉字），**必须写具体事件**，**禁止写「无强转折，以XX铺垫为主」「无」「略」「见后续」「待定」等套话占位**。
   - `ending_hook`：字符串，本章结尾钩子/悬念（≤30 汉字），**必须是具体的人做了具体的事/揭示了具体信息/做出了具体选择**。**禁止**「XX 脚步声传来」「XX 出现在门口」「XX 看到了什么」「XX 传来声音」「一道黑影闪过」这类套路伪钩子。
   - `intensity`：字符串，本章节奏档位，**必须**是下列 7 个值之一（中文，原样输出，不要改写）：
{intensity_block}
4. 每条对象**必须**齐 5 字段，缺一 fail；字符串字段值**不得为空字符串**，不得写「见后续」「待定」「无」等占位。

## 最短合规样本（题材化示范）
[
  {sample_1},
  {sample_2}
]

## 常见错误（禁止）
{mistakes_block}

## 内容创作硬约束
{continuity_rule}

### 一、档位分配（反塌陷硬约束）
1. 总 {count} 章中：
   - `爆发` 档章数 ∈ [{burst_min}, {burst_max}]（约14-20%，全书/本卷关键高潮）
   - `大转折` 档章数 ≤ {big_turn_max}（与爆发合计不超过35%）
   - `小转折` 档章数 ≥ {small_turn_min}（每5-8章必须有一次可感知的推进/胜利/揭露）
   - `铺垫`+`缓冲`+`回落` 合计 25-35%，张弛有度
   - `推进` 为主体档位，占 30-40%
2. **禁止连续 {lull_streak_max+1} 章以上都是铺垫/缓冲/回落**（节奏塌陷）；淡章之间必须插入推进或小转折。
3. **禁止连续 2 章以上爆发/大转折**（节奏窒息）；两个爆发/大转折之间至少隔 1-2 章缓冲或推进。{genre_extra_rhythm}

### 二、主角能动性（反被动硬约束）
1. **禁止主角连续 {passive_streak_max+1} 章以上纯被动承压**（被欺负/被调查/被驳回/被刁难/被追赶却无反制）。主角被动章之后必须紧跟至少 1 章主角**主动决策 / 主动出手 / 获得关键契机 / 关系或立场主导**的章节。
2. 每 {win_cadence} 章内主角必须有至少一次「主角时刻」——本题材下的具体形态：**{spec.agency_examples}**。读者必须能感受到主角有能动性。
3. 开篇前10章（新手期）主角可以略被动，但最迟第8章必须出现第一次明确的主动出手或关键收获。

### 三、看点密度（网文节奏硬约束）
1. 本规划作为网文连载章节，**看点密度不低于每4章1次**。本题材下的看点具体形态如下：
{payoff_block}
2. 核心冲突事件从埋钩子到兑现不超过 {core_hook_payoff_max} 章，中间用小转折维持张力，禁止"一路被压制到终局才反击"。

### 四、配角与伏笔（反遗忘硬约束）
1. 已登场的重要配角（暗线人物/反派/CP/队友）**每5-8章必须有一次推进或深化**，禁止长期消失后突然信息倾倒。
2. 每5章范围内至少埋1条新伏笔或推进1条已有伏笔；**伏笔埋后15章内必须有阶段性推进**（哪怕只是再次提及），禁止无限悬空。
3. 新出场的重要人物（首秀章）必须在 purpose 里标注「首次登场」，并在 key_turn 里给出辨识度标签（外貌/口头禅/身份标识）。
4. 头部若提供了本卷登场花名册（返场阵容 + 新登场名单 + 本卷主线），请据此安排：返场角色在本卷的登场/推进章节要落到其「本卷弧线」上；新登场的重要角色/关键道具要选合理首秀章并提前铺垫呼应。**勿临时引入花名册之外的重要新角色**（一次性过场龙套不受限）。
4. **登场必须事件驱动,禁止「角色介绍流水账」**：任何重要人物的首秀章,purpose 必须是一桩正在发生的具体事件 / 冲突 / 需求（该角色因这件事被卷入或主动介入),登场只是这桩事件的副产品——**禁止**把某章的 purpose 写成「介绍角色 X / 引出队友 Y」式纯登场秀；**禁止**连续多章每章只为引入一个新角色地排队登场（一次最多带出 1 位重要人物,且该章须同时推进一件已在进行的事）。

### 五、钩子反模板（禁用套路）
ending_hook **禁止**使用以下套路：
{hook_ban_block}
钩子必须是**具体的信息点**：谁说了什么具体的话、谁做了什么具体的动作、揭示了什么具体的事实、主角做出了什么具体的决定。

### 六、大纲与设定对齐
1. 本 {count} 章须与整体大纲的阶段定位对齐，不要提前爆完终局。
2. 严守作品既定设定（题材/世界观/力量或规则体系/人物关系），不新增私设、不降智/拔高角色。
3. 能力 / 资源 / 身份 / 立场跃迁**必须有铺垫章在前**（{spec.escalation_prerequisites}），禁止「上一章还没起势，下一章直接跨阶段跳变」的跃迁式升级。
4. **整卷节奏铺排（本次规划的就是当前整卷，其起止章号见头部卷位置卡）**：本 {count} 章要按卷内位置编排密度——卷首几章（前 5 章内）写「本卷开局 / 新阶段定位 / 抛出本卷核心目标」，卷中稳态推进 + 小转折维持张力，卷末几章（倒数 5 章内）集中「本卷收束 + 卷末大高潮 + 埋下一卷钩」。**禁止**把整卷按"平均推进"一路平铺、卷末不收束。

## 输出前自检（全部通过才输出）
1. 是否严格 `[` 开头 `]` 结尾，无围栏无解释？
2. 章号是否 {start_chapter} → {end_chapter} 连续升序、共 {count} 条？
3. 每条是否齐5字段、值非空、字数达标、intensity是7档枚举之一？
4. key_turn是否都写了具体事件，没有「无强转折，以XX铺垫为主」套话？
5. ending_hook是否都是具体事件/信息，没有「脚步声」「黑影」套路？
6. 档位分布是否满足硬约束（爆发≤{burst_max}、小转折≥{small_turn_min}、无连续3章淡/爆发）？
7. 主角是否有连续3章以上被动承压？每{win_cadence}章内是否有主角时刻？
8. 配角/暗线是否每5-8章有推进，无长期消失？
9. 新角色登场是否都事件驱动（首秀章 purpose 是一桩正在发生的事而非「介绍角色X」），无连续多章排队登场的流水账？
10. 是否与已写完段的伏笔/人物状态自然承接、无矛盾？

直接输出 JSON 数组，不要输出任何其他内容。"""


def _default_chapter_plan_prompt(
    state: "NovelState",
    start_chapter: int,
    end_chapter: int,
    locked_entries: "list[ChapterPlanItem]",
) -> str:
    """中性版 chapter_plan_prompt——通用题材 / 未提供 builder 的 flavor 回退用。
    直接调用 render_chapter_plan_prompt 并传默认 spec(不特化任何题材)。
    """
    return render_chapter_plan_prompt(
        state, start_chapter, end_chapter, locked_entries, ChapterPlanGenreSpec()
    )

