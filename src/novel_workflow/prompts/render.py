"""三层 prompt 架构的核心：类型定义 + 身份注册表 + L1 构建器 + 渲染器。

架构分层（解决"system 塞大量资料稀释主线"问题）：
- L1 system  ：角色身份 + 硬契约（不可违反底线）+ 任务契约 + 优先级约定。瘦、稳定、重试不变。
- L2 context ：参考资料（已定稿设定/动态台账/前文窗口/本章锚点）。按步骤声明、可裁剪。
- L3 task    ：本次具体指令 + 输出格式 + 历史整改要点（最高"软"优先级）。每步不同、重试只换它。

注意力布局（U 型注意力：开头 primacy / 末尾 recency 强，中部弱）：
- 硬契约占 system primacy + task 开头锚定句（双 primacy 端点）--不可推翻的底线。
- evolved_directives + 输出格式占 task 末尾 recency--自进化产物拿最强执行注意力。
- 软契约（字数/风格偏好）+ 参考资料放中部弱区--可被两端覆盖、可容忍弱注意力。

与自进化的关系：evolved_directives 在 task 末尾，能覆盖"软契约"，但碰不到两端硬契约。
distill 前置侦测撞硬契约时升级人工（P0 暂不实现 distill 侧改动，仅在此声明 HARD_CONTRACTS
单一真源，供后续 distill 比对 + L1 文案渲染共用，避免两处漂移）。

身份单一真源（SystemRole 注册表）：
- 所有 LLM 调用点通过 SystemRole 枚举指定身份，build_system / build_prepare_fields 强制传 role。
- 身份文本仅在两处存在：GenreFlavor.system_identity（题材创作者，各 flavor 差异化）+
  render.py 的 _ROLE_TEXT 表（其他一切身份）；其余文件（prompts/base.py / review_shared.py /
  nodes/*.py / *_subgraph.py）严禁内联 "你是XX"/"# 角色:" 式身份陈述。
- 静态守卫 test_prompt_identity_guard.py AST 扫全库,发现漏网即 fail。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


# ── 硬契约：单一真源 ───────────────────────────────────────────────────────────
# 既是 L1 system 文案的渲染来源，也是后续 distill 侦测"提案是否撞硬契约"的比对依据。
# 任一处需要枚举硬契约时都走这里，杜绝 L1 文案与 distill 侦测各写一份导致漂移。
# 文案聚焦"不可违反的底线"--作品/系统质量红线，用户反馈（evolved_directives）无权推翻。


@dataclass(frozen=True)
class HardContract:
    """一条硬契约：name 供 distill 比对定位，text 供 L1 渲染展示给 LLM。"""

    name: str  # 短标识，如 "反降智"；distill 侦测时按此匹配
    text: str  # 展示给 LLM 的契约全文


HARD_CONTRACTS: tuple[HardContract, ...] = (
    HardContract(
        name="反降智",
        text=(
            "反降智：任何角色、势力、规则不得为推进剧情而违背自身能力、动机、常识或既定实力；"
            "关键转折不得依赖巧合、对手忽然变蠢、或凭空掉落的能力/资源。"
        ),
    ),
    HardContract(
        name="跨设定一致",
        text=(
            "跨设定一致：必须与本作已定稿的前置设定（题材/基调/主题/世界观/冲突等）零矛盾；"
            "发现潜在冲突以前置设定为准调和，不得另起炉灶推翻已定稿内容。"
        ),
    ),
    HardContract(
        name="因果闭环",
        text=(
            "因果闭环：凡「已声明会在故事中生效」的机制/规则/势力，其成因、代价、边界须能自圆其说，"
            "不靠「天生如此/因为剧情需要」搪塞。有意标明为悬念的留白不在此列。"
        ),
    ),
    HardContract(
        name="强延展留白",
        text=(
            "强延展留白：只搭骨架与底层逻辑，为下游大纲/人物预留扩展空间，"
            "不写死一次性细节、不锁死力量上限与终局真相。"
        ),
    ),
)


# ── 身份注册表 ─────────────────────────────────────────────────────────────────
# 单一真源:所有 LLM 调用的身份文本(除题材创作者从 GenreFlavor.system_identity 组合注入外)
# 统一在此声明。build_system 强制通过 SystemRole 枚举取身份,任何"随手写你是XX"的调用
# 都会被静态守卫 test_prompt_identity_guard.py 拦下。


class SystemRole(str, Enum):
    """LLM 身份枚举。所有需要 SystemMessage 身份的调用点必须指定 role。

    题材创作者例外:role=GENRE_AUTHOR 时需组合 pack.flavor.system_identity 注入,
    因为题材身份是各 flavor 的差异化点,集中到 _ROLE_TEXT 会丢失题材特色。

    枚举值即字符串标识,便于日志/配置文件对照;str 继承允许直接与字符串比较。
    """

    # ── 创作类 ───
    GENRE_AUTHOR = "genre_author"  # 题材作家(需 genre_identity 组合)

    # ── 数据台账类(snapshot 步骤:foreshadowing / phase_summary / initial_status) ───
    SNAPSHOT_MAINTAINER = "snapshot_maintainer"  # 数据维护员
    SNAPSHOT_REVIEWER = "snapshot_reviewer"  # 数据审核员

    # ── 规划辅助类(题材中性) ───
    VOLUME_PLANNER = "volume_planner"  # 分卷规划助手(volumes 步骤)

    # ── 审核类(自审阶段的独立身份,与创作阶段身份区分) ───
    ARC_QC = "arc_qc"  # 弧线大纲质检专家
    CHAPTER_PLAN_QC = "chapter_plan_qc"  # 中景大纲质检专家

    # ── 整卷设定终审类(save_config 冻结前的跨设定闸门) ───
    CONSISTENCY_AUDITOR = "consistency_auditor"  # 设定一致性终审架构师
    SETTINGS_ENGINEER = "settings_engineer"  # 设定修订工程师

    # ── 库管理类(伏笔/实体卡精简子图) ───
    FORESHADOW_LIBRARIAN = "foreshadow_librarian"  # 伏笔台账管理员
    ENTITY_LIBRARIAN = "entity_librarian"  # 实体卡库管理员

    # ── 元系统/自进化(不叠硬契约:propose 阶段允许挑战既有规则) ───
    EVOLUTION_ENGINEER = "evolution_engineer"  # 进化工程师(distill)
    EVOLUTION_EDITOR = "evolution_editor"  # 整改库编辑(refine)
    EVOLUTION_DISSOLVER = "evolution_dissolver"  # 整改消解官(reconcile)

    # ── 脑爆/用户交互(不叠硬契约:与创作产线独立,聊天场景) ───
    BRAINSTORM_COACH = "brainstorm_coach"  # 策划教练
    BRAINSTORM_COMPRESSOR = "brainstorm_compressor"  # 对话纪要员
    BRAINSTORM_ORGANIZER = "brainstorm_organizer"  # 设定整理员
    BRAINSTORM_EXTRACTOR = "brainstorm_extractor"  # 信息抽取员


# 身份文本表(GENRE_AUTHOR 除外——其文案来自各 flavor 的 system_identity 字段)
# 原则:内容原文迁移自各处旁路调用,不改措辞;此处集中后各处删除,身份文案单点定义。
_ROLE_TEXT: dict[SystemRole, str] = {
    # snapshot 类:数据维护员/审核员,区别于创作者身份,让模型走"台账严谨"心态而非"作家发挥"
    SystemRole.SNAPSHOT_MAINTAINER: (
        "你是严谨的小说数据维护员，负责根据任务要求生成或更新各类快照台账数据。"
    ),
    SystemRole.SNAPSHOT_REVIEWER: (
        "你是严谨的小说数据审核员，负责审核各类快照数据的完整性与一致性。"
    ),
    # 分卷规划:题材中性,让模型走"结构化规划"心态,不做题材文风渲染
    SystemRole.VOLUME_PLANNER: "你是网文分卷结构化规划助手。",
    # 弧线/章节大纲的自审身份:与创作阶段的题材作家身份区分,让模型切"质检审校"心态
    SystemRole.ARC_QC: "你是专业网文弧线大纲质检专家。",
    SystemRole.CHAPTER_PLAN_QC: "你是长篇网文的中景大纲质检专家。",
    # 设定一致性总审:中立审校官口吻,不含"请严格遵守",让模型批判性审查
    # 迁自 review_shared.CONSISTENCY_AUDIT_SYSTEM_PROMPT
    SystemRole.CONSISTENCY_AUDITOR: (
        "你是一名资深的小说设定终审架构师。你的职责不是润色文字，而是把一部小说进入正式创作前的"
        "全部底层设定当作一个逻辑系统来体检：跨设定找矛盾、找因果断裂、找降智硬伤。"
        "对送审设定保持批判、审慎，不预设它们正确；只报确实会污染下游大纲 / 正文创作的结构性硬伤，"
        "不吹毛求疵、不纠结遣词与字数。"
    ),
    # 设定一致性 AI 修订:约束"只改被点名的硬伤、保留其余一切",避免借修订之名整篇重写
    # 迁自 review_shared.CONSISTENCY_REVISE_SYSTEM_PROMPT
    SystemRole.SETTINGS_ENGINEER: (
        "你是一名严谨的小说设定修订工程师。给定一份「设定一致性问题清单」和当前全部底层设定，"
        "你的唯一任务是：针对清单里明确点名的硬伤，对相关设定项做最小必要的改写，使矛盾 / 断链 / 降智被消除，"
        "同时**完整保留所有没有问题的内容与表达**。严禁借修订之名整篇重写、润色文字、改动未被点名的设定项，"
        "或引入清单之外的新设定。改动要克制、精准、可追溯到具体某条问题。"
    ),
    # 库管理类:识别关键与碎屑,帮助作者精简上下文
    SystemRole.FORESHADOW_LIBRARIAN: (
        "你是专业的小说伏笔管理专家，擅长识别核心伏笔与次要伏笔，帮助作者精简上下文。"
    ),
    SystemRole.ENTITY_LIBRARIAN: (
        "你是专业的小说实体卡库管理专家，擅长识别关键实体与一次性碎屑，帮助作者精简写作上下文。"
    ),
    # ── 元系统自进化(迁自 evolution.py) ───
    SystemRole.EVOLUTION_ENGINEER: (
        "你是小说创作提示词的「进化工程师」。你的职责：把编辑对某一章的人工修改意见，"
        "提炼成可复用、可执行、简洁去重的写作整改规则，沉淀进后续所有章节的生成提示词。"
        "只产出规则本身，不复述意见、不解释过程。"
    ),
    SystemRole.EVOLUTION_EDITOR: (
        "你是小说创作提示词的「整改库编辑」。你的职责：把一本小说累积的历史整改要点，"
        "拆分、去重、精炼成一条条独立自洽的通用整改条目，供同题材其他小说复用。"
    ),
    SystemRole.EVOLUTION_DISSOLVER: (
        "你是小说创作提示词的「整改消解官」。你的职责：把一本小说历次累积、可能重复甚至"
        "互相矛盾的历史整改要点，重写成一份去重、消解矛盾、逻辑自洽的最终整改清单，"
        "供后续所有章节稳定执行。只做整理消解，不新增原文没有的要求。"
    ),
    # ── 脑爆/用户交互(迁自 nodes/brainstorm.py) ───
    # BRAINSTORM_COACH 原文含 {genres_list} 占位符 + 力量体系分支硬规则,
    # 那些是"动态素材",不属于身份;调用方仍需 _build_brainstorm_system_prompt 处理分支拼接,
    # 只是身份基座从模块级常量搬到这里。
    SystemRole.BRAINSTORM_COACH: (
        """你是一位资深的小说策划与灵感教练。你的任务是通过轻松的多轮对话，
和用户一起脑爆出一部小说的雏形：基础设定（题材、写作风格、目标读者、核心基调、篇幅）、
核心主题立意、世界观框架，以及核心冲突（主角面对的核心矛盾、对抗势力、贯穿全书的主要张力）。

对话原则：
1. 一次只聚焦一两个问题，循序渐进，不要一口气抛出一堆问题。
2. 主动提出有启发性的可选方向供用户挑选，而不是干巴巴地索取信息。
3. 适时小结已经达成的共识，帮助用户看清雏形逐渐成形。
4. 当用户表示满意、或基础信息与主题 / 世界观 / 核心冲突已较完整时，主动提示用户可以「结束脑爆」进入正式创作。
5. 用自然、口语化的中文，简洁有重点。

【结束前必须共同敲定的 7 个基础参数】
在提示用户「结束脑爆」之前，请确认下列 7 项都已经和用户聊清楚（可以是用户主动提，也可以你主动提问引导）：
1. 小说名称
2. 小说类型（必须落在这几个候选之内：{genres_list}——不要引导用户去"武侠""奇幻"等不在候选内的类型；如果讨论中偏离，主动收敛到最近的候选值）
3. 写作风格（如硬核、意识流、白描、幽默轻快、细腻内省等，1-3 个关键词即可）
4. 目标读者（以兴趣 / 身份为主，如青少年男性、职场女性、中年科幻迷；避免使用"18-25 岁"这类人口学标签）
5. 核心基调（如热血励志、压抑沉重、温情治愈、悬疑压抑等，1-3 个关键词即可）
6. 每章字数（如 3000 字、5000 字）
7. 总字数目标（如 30 万字、100 万字）

引导原则：
- 不要一次追问多项——每轮主动提 1-2 项即可，混在自然对话里；
- 允许在同一句里给 2-3 个可选项让用户挑（"你更倾向硬核战斗流还是心理内省流？"）；
- 用户已经明确表达过的项目就不要重复问；
- 上述 7 项与核心主题、世界观、核心冲突齐平；这 7 项没聊清就不要建议用户「结束脑爆」。

【定期小结（每 3-4 轮，或聊完一个大话题时）】
以自然、简短、非机械的方式回顾一次，附在正文末尾即可（不必每一轮都做，避免观感啰嗦）：
- 「目前咱们已经敲定的：<列 3-6 条要点，可涵盖 7 基础参数中已定项 + 主题 / 世界观 / 冲突方向>」
- 「还想跟你聊清楚的：<列 1-3 条剩余项，优先点名 7 基础参数中尚未明确的>」
让用户能一眼看出雏形成型进度，也能主动补足缺项。"""
    ),
    SystemRole.BRAINSTORM_COMPRESSOR: (
        "你是严谨的对话纪要员，擅长把长对话压缩成不丢关键信息的要点概要。"
    ),
    SystemRole.BRAINSTORM_ORGANIZER: (
        "你是一位小说设定整理员。你的唯一职责是把用户和 AI 在脑爆对话里"
        "**已经共同敲定**的完整版本原封不动地整理成一份 markdown 文档——**不改写、不压缩、不补充你自己的理解**。"
    ),
    SystemRole.BRAINSTORM_EXTRACTOR: (
        "你是一位小说信息抽取员。你的唯一任务是从一段脑爆对话历史 + 完整版整理稿里，"
        "把用户和 AI 已经共同敲定的 7 个基础参数抽成一份严格的 JSON。**不同字段有不同的严格度**——"
        "硬事实类字段绝不允许脑补，氛围类字段可以做温和归纳（详见下方规则）。"
    ),
}

# 不叠硬契约的 role 白名单——元级系统调用/用户交互聊天,硬契约不适用:
# - EVOLUTION_*:distill/refine/reconcile 是对"整改规则本身"做元级处理,规则本身可能挑战硬契约,
#   在提炼阶段就叠硬契约会阻断合理规则的沉淀
# - BRAINSTORM_*:脑爆是用户交互聊天,不是创作产线,硬契约("反降智""因果闭环"等)不适用于闲聊
_NO_HARD_CONTRACTS_ROLES: frozenset[SystemRole] = frozenset(
    {
        SystemRole.EVOLUTION_ENGINEER,
        SystemRole.EVOLUTION_EDITOR,
        SystemRole.EVOLUTION_DISSOLVER,
        SystemRole.BRAINSTORM_COACH,
        SystemRole.BRAINSTORM_COMPRESSOR,
        SystemRole.BRAINSTORM_ORGANIZER,
        SystemRole.BRAINSTORM_EXTRACTOR,
    }
)


# ── 兼容别名:snapshot 身份文案的旧引用点 ────────────────────────────────────
# 保留 SNAPSHOT_IDENTITY_MAINTAINER/REVIEWER 常量导出,值指向 _ROLE_TEXT——
# Step 2 会把所有 SNAPSHOT_IDENTITY_MAINTAINER 引用改成 SystemRole.SNAPSHOT_MAINTAINER,
# 迁移完成后删除这两个别名。此处保留是为了 Step 1 只加新 API 不破旧,让本步骤 import 立即绿。
SNAPSHOT_IDENTITY_MAINTAINER = _ROLE_TEXT[SystemRole.SNAPSHOT_MAINTAINER]
SNAPSHOT_IDENTITY_REVIEWER = _ROLE_TEXT[SystemRole.SNAPSHOT_REVIEWER]


# ── 类型定义 ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContextSection:
    """L2 参考资料的一个分区。

    key 用于验收脚本按名检查"某段资料是否存在/缺失"，以及未来按 key 裁剪省 token；
    body 是注入 LLM 的正文；optional 标记该段是否可被步骤按需省略（预留，P0 渲染不裁剪）。
    """

    key: str
    body: str
    optional: bool = False


@dataclass(frozen=True)
class PromptRequest:
    """一次 LLM 调用的三层请求。

    system  = L1：身份 + 硬契约 + 任务契约 + 优先级约定（build_system 产出）。
    context = L2：参考资料分区序列（按步骤声明）。
    task    = L3：本次指令 + 输出格式 + 历史整改要点。
    """

    system: str
    context: tuple[ContextSection, ...] = ()
    task: str = ""


# ── L1 构建器 ──────────────────────────────────────────────────────────────────


def build_system(
    role: SystemRole,
    task_contract: str,
    *,
    genre_identity: str = "",
    identity_substitutions: dict[str, str] | None = None,
) -> str:
    """组装 L1 system prompt:身份 + 硬契约(按 role 决定) + 任务契约 + 优先级约定。

    优先级约定用「位置词」(开篇/中部/末尾)而非内部层名 L1/L2/L3——模型只看得见位置,
    看不见架构命名;位置词才能对应到它实际读到的内容位置。

    身份来源分派:
    - role == GENRE_AUTHOR:身份从 genre_identity 参数取(必填,fail-loud);叠硬契约。
      题材身份是各 flavor 的差异化,不集中到 _ROLE_TEXT,由调用方从 pack.flavor.system_identity
      取值传入,保持题材扩展性。
    - role in _NO_HARD_CONTRACTS_ROLES:身份从 _ROLE_TEXT[role] 取;**不叠硬契约**(元系统/聊天)。
    - 其他:身份从 _ROLE_TEXT[role] 取;叠硬契约。

    identity_substitutions(可选):对 _ROLE_TEXT[role] 中的 {key} 占位符做替换。
    用途:BRAINSTORM_COACH 的身份说明里带 {genres_list}(候选类型清单动态注入),但清单内容
    仍属"身份职责的一部分"而非 task_contract——通过占位符注入保持身份文本单点在 _ROLE_TEXT。
    仅对非 GENRE_AUTHOR 有效(题材身份直接由 genre_identity 参数原样注入,不做占位符处理)。

    fail-loud 约束:
    - GENRE_AUTHOR 必须传非空 genre_identity,否则 ValueError——避免"漏传身份"变成静默"你是"。
    - 非 GENRE_AUTHOR 时传 genre_identity 也 ValueError——避免"两个身份并存"的语义混淆。
    - GENRE_AUTHOR 时传 identity_substitutions 也 ValueError——题材身份不走占位符替换。
    """
    if role == SystemRole.GENRE_AUTHOR:
        if not genre_identity:
            raise ValueError(
                "SystemRole.GENRE_AUTHOR 必须传非空 genre_identity(题材身份,通常来自 pack.flavor.system_identity)"
            )
        if identity_substitutions:
            raise ValueError(
                "SystemRole.GENRE_AUTHOR 不接受 identity_substitutions——题材身份由 genre_identity 原样注入"
            )
        identity = genre_identity
    else:
        if genre_identity:
            raise ValueError(
                f"SystemRole.{role.name} 不接受 genre_identity 参数——非题材身份的文案已在 _ROLE_TEXT 里定义"
            )
        identity = _ROLE_TEXT[role]
        if identity_substitutions:
            for placeholder, value in identity_substitutions.items():
                identity = identity.replace("{" + placeholder + "}", value)

    if role in _NO_HARD_CONTRACTS_ROLES:
        # 元系统/聊天场景:只出身份 + 任务契约,不注入硬契约(硬契约是创作产线的底线红线,
        # 元级 propose/闲聊场景不适用,强行叠加会污染 propose/闲聊的语义空间)
        return f"""{identity}

【任务契约】
{task_contract}
"""

    contracts = "\n".join(f"- {c.text}" for c in HARD_CONTRACTS)
    return f"""{identity}

【硬契约】(不可违反的底线,优先级高于一切指令与历史整改要点)
{contracts}

【任务契约】
{task_contract}

【优先级约定】
本次任务中可能出现多层指令,按以下优先级裁决冲突:
- 任务末尾的「历史整改要点」> 开篇的风格/字数等软性偏好 > 中部的参考资料。
- 冲突时以最末尾的最新整改指令为准,但绝对不得突破上方【硬契约】声明的底线禁区。
"""


# ── 渲染器 ─────────────────────────────────────────────────────────────────────


def render_user(context: str, task: str) -> str:
    """拼 HumanMessage 内容：L2 参考资料 + L3 任务，用顶级分隔符分区。

    与 render() 同源--render() 内部调本函数，避免两处拼装逻辑漂移。
    generate（首轮/重放最新轮）与 llm_self_review 都调本函数拼 user，
    保证「自审也能看到 L2 资料」（旧路径 review_prompt 不含资料导致自审丢资料的问题在此解决）。

    context 为空时退化为纯 task--generate 重放历史轮次时历史 user 无 L2 可恢复，
    但最新轮 L2 由当前 state 重新注入，历史轮 L2 缺失可接受。
    """
    if context:
        return f"【参考资料】\n{context}\n\n【本次任务】\n{task}"
    return task


def render(req: PromptRequest) -> list[BaseMessage]:
    """把 PromptRequest 渲染成 LangChain messages：1 个 SystemMessage + 1 个 HumanMessage。

    L2 + L3 合并进单个 HumanMessage，内部用【参考资料】/【本次任务】顶级分隔符分区。
    不拆成多个 HumanMessage--相邻 HumanMessage 会被拼接，分隔符分区比多 message 更稳，
    且与项目现有【】section 风格一致。L2 为空时 user 退化为纯 task（render_user 处理）。
    """
    sections = [s for s in req.context if s.body]
    ctx = "\n\n".join(s.body for s in sections)
    user = render_user(ctx, req.task)
    return [SystemMessage(content=req.system), HumanMessage(content=user)]


# ── prepare 节点通用 helper ────────────────────────────────────────────────────


def build_prepare_fields(
    *,
    role: SystemRole,
    task_contract: str,
    context: str,
    task: str,
    genre_identity: str = "",
) -> dict[str, str]:
    """所有 prepare 节点统一产出三层桥接字段:system_prompt(L1) / context_prompt(L2) / task_prompt(L3)。

    单一拼装源:杜绝各 prepare 各自手搓三层导致漂移。
    - L1 = build_system(role, task_contract, genre_identity=...)——身份 + 硬契约(按 role 决定) +
      任务契约 + 优先级约定;role 强类型化后,"漏传身份""身份自造"变成静态错误。
    - L2 = context 原样(已由调用方组装好,含设定/台账/前文/锚点;空串允许)。
    - L3 = task 原样(prompt 方法返回的指令串 + 输出格式 + evolved_directives)。

    role/genre_identity 参数校验完全托付 build_system,此处只做透传;返回 dict 不含 review_type/
    reset_review_fields,由 prepare 自行合并(保持 prepare 对 review_type 的控制权)。
    """
    return {
        "system_prompt": build_system(role, task_contract, genre_identity=genre_identity),
        "context_prompt": context,
        "task_prompt": task,
    }
