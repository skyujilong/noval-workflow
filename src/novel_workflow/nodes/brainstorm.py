"""Phase -1：灵感脑爆（可选，入口分叉）。

入口分叉：新建小说时先问「进脑爆」还是「直接填表」。选脑爆 → 与 LLM 多轮流式对话
（brainstorm_chat ⇄ brainstorm_respond 自循环），共同脑爆出基础信息 + 核心主题 + 世界观 + 力量体系 + 核心冲突；
经轻量确认后汇合到 prepare_overall_outline，**整段跳过** Phase 1 的 core_theme / world_building /
power_system / core_conflicts 生成审稿（否则再走 prepare 会把脑爆已生成的内容冲掉）。

记忆管理：始终保留最近 _KEEP_ROUNDS 轮完整对话，更早的轮次 LLM 压缩进 brainstorm_summary，
避免上下文无限膨胀。

LangGraph 重放语义：interrupt() resume 会从节点头部重放整个节点。故聊天循环拆为
「只 interrupt 的 brainstorm_chat」与「只调 LLM 的 brainstorm_respond」两个节点，
避免 LLM 被重复调用（与 subgraph.py 的 generate / human_review 拆分一致）。

所有节点保持同步 def：LangGraph 在线程池执行同步节点，LLM 的阻塞式 .invoke() 不会阻塞
事件循环（切勿改成 async def 里直接 await 阻塞调用）。
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from noval_workflow.interrupt_types import InterruptType
from noval_workflow.llm import get_llm
from noval_workflow.state import NovelState

_logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────
# 始终保留的最近完整对话轮数（每轮 = 1 条 human + 1 条 ai）
_KEEP_ROUNDS = 3
_KEEP_MESSAGES = _KEEP_ROUNDS * 2

# 用户结束脑爆的显式信号（不把空串当结束，避免与「空消息」歧义）
_END_SIGNALS = frozenset({"结束脑爆", "结束", "done", "finish", "完成"})

# gate 进入脑爆的信号（其余一律视为「直接填表」）
_ENTER_SIGNALS = frozenset({"脑爆", "brainstorm", "yes", "y", "是", "进入"})

# 7 个基础字段（与 collect_user_inputs / NovelState Phase 0 对齐）
_BASIC_FIELDS = (
    "novel_name", "genre", "writing_style", "target_audience",
    "core_tone", "chapter_word_count", "total_word_count",
)

# 历史条目 kind：v3 引入的 pin 语义。
# - "chat"（缺省）：正常脑爆聊天条目，参与 LLM 素材构建、参与压缩窗口计算。
# - "finalize_draft"：finalize 节点追加的完整版气泡，作为**pin 项穿透压缩流程**：
#     · LLM 视角：`_finalize_material` / `_history_to_messages` 全部过滤掉，防止循环污染
#       （LLM 抄旧完整版 → 用户认为"AI 没听懂我说的修改"→ 又返回聊天 → 再抄一轮）；
#     · 用户视角：永久保留在 history，前端按 kind 顶部加分隔条「已被驳回的旧整理」，
#       用户回看聊天历史时始终能找到那份完整版作为修改参考锚点；
#     · 压缩视角：`_compress` 的 overflow 计算跳过 pin，保证多轮聊天后 pin 项也绝不进 summary。
_KIND_CHAT = "chat"
_KIND_FINALIZE_DRAFT = "finalize_draft"


def _is_pin(entry: dict) -> bool:
    """pin 项判定：kind 字段等于 finalize_draft。缺省或其他值一律视为普通聊天条目。"""
    return entry.get("kind") == _KIND_FINALIZE_DRAFT


def _chat_only(history: list[dict]) -> list[dict]:
    """滤掉 pin 项，只保留普通聊天条目——用于所有喂给 LLM 的场景（素材构建 / 上下文 / 压缩窗口）。

    保序：仅按 kind 过滤，不重排；调用方拿到的 list 顺序与原 history 中 chat 条目的顺序一致。
    """
    return [e for e in history if not _is_pin(e)]

# ── prompts ──────────────────────────────────────────────────────────────────
_BRAINSTORM_SYSTEM_PROMPT_BASE = """你是一位资深的小说策划与灵感教练。你的任务是通过轻松的多轮对话，
和用户一起脑爆出一部小说的雏形：基础设定（题材、写作风格、目标读者、核心基调、篇幅）、
核心主题立意、世界观框架，以及核心冲突（主角面对的核心矛盾、对抗势力、贯穿全书的主要张力）。

对话原则：
1. 一次只聚焦一两个问题，循序渐进，不要一口气抛出一堆问题。
2. 主动提出有启发性的可选方向供用户挑选，而不是干巴巴地索取信息。
3. 适时小结已经达成的共识，帮助用户看清雏形逐渐成形。
4. 当用户表示满意、或基础信息与主题 / 世界观 / 核心冲突已较完整时，主动提示用户可以「结束脑爆」进入正式创作。
5. 用自然、口语化的中文，简洁有重点。"""

# 力量体系分支硬规则：由前端 switch 决定。开关状态实时写回 state.has_power_system，
# 每轮 brainstorm_respond 按 flag 拼进 system prompt 让 AI 引导风格与用户意图对齐——
# 避免"AI 按题材默认引导 vs 用户实际想要"的错位。
_POWER_SYSTEM_ON_RULE = """
【本作力量体系约定：开启】
本作**包含**独立力量体系。世界观有雏形后请**主动引导**用户聊清这套体系——聊的过程中至少覆盖以下维度，
避免只停留在"见习→大师"式的口味级描述：
1. **力量来源与底层原理**：力量是从哪里来的、遵循什么底层规则；
2. **数值化的等级 / 阶位阶梯**：一共分几阶 / 几级、每阶对应的等级区间（如"全职业 6 阶，每阶 10 级共 60 级满级"）、
   阶位之间是否有质变门槛；
3. **每阶的硬性晋升条件**：每阶要满足哪些属性阈值 / 晋升任务 / 机制触发，而非只说"努力就能升"；
4. **每阶 / 每流派解锁的公用技能框架**：每阶职业级公用技能有哪些、解锁等级 / 效果 / 冷却或代价、被动能力如何叠加
   （只立职业级"技能表"框架，不涉及具体角色的独门招式）；
5. **流派 / 职业分类与相克关系**、能力边界与规则红线（杜绝后期"体系外凭空能力"）；
6. **社会侧规则**：认证 / 权限 / 资源分配 / 晋升代价——力量体系如何与世界观里的秩序耦合。

这套体系是全书人物成长与冲突升级的统一标尺，务必聊到"能直接照着写打斗和晋级章节"的颗粒度。"""

_POWER_SYSTEM_OFF_RULE = """
【本作力量体系约定：关闭】
本作**不单列**力量体系。实力/竞争规则融进世界观与冲突即可（如资源、地位、人脉、社会规则）。
**不要主动询问**"力量体系"、"修炼境界"、"异能等级"之类的概念——除非用户明确提出，否则不引入这个维度。"""


def _build_brainstorm_system_prompt(has_power_system: bool) -> str:
    """按作品级 has_power_system 拼脑爆 system prompt。前端 switch 切换后写回 state，
    下一轮 respond 立即感知新 flag——AI 引导风格随开关变化。"""
    rule = _POWER_SYSTEM_ON_RULE if has_power_system else _POWER_SYSTEM_OFF_RULE
    return _BRAINSTORM_SYSTEM_PROMPT_BASE + rule

_COMPRESS_SYSTEM_PROMPT = "你是严谨的对话纪要员，擅长把长对话压缩成不丢关键信息的要点概要。"

_COMPRESS_PROMPT = """以下是一段小说灵感脑爆对话的早期内容（可能已包含一份更早的概要）。
请把它压缩成一份简明的要点概要，保留所有已经确定或倾向的设定、主题、世界观线索与关键决定，
丢弃寒暄和重复内容。直接输出概要正文，不超过 400 字，不要任何前后缀说明。

{material}"""

_FINALIZE_MARKDOWN_SYSTEM_PROMPT = """你是一位小说设定整理员。你的唯一职责是把用户和 AI 在脑爆对话里
**已经共同敲定**的完整版本原封不动地整理成一份 markdown 文档——**不改写、不压缩、不补充你自己的理解**。"""

# has_power_system=True 分支：4 节完整格式（含力量体系）
_FINALIZE_MARKDOWN_PROMPT_WITH_POWER = """以下是一段小说灵感脑爆对话（含早期概要与最近对话）。请把用户和 AI 在
对话中**已经共同敲定的最完整版本**原原本本地整理出来。

**关键约束**：
1. **优先直接使用 AI 在对话中最近一次给出的完整表述**，只做整理（补齐/合并已确认的分散段落），
   **不要重新提炼、不要压缩、不要用你自己的话改写**。
2. 输出一份 markdown 文档，用 `# 一级标题` 分成正好 **4 节**，标题必须严格是这四个（不要加"与立意"、
   "设定"等后缀，也不要用二级标题 `##`）：
   ```
   # 核心主题
   （正文……）

   # 世界观
   （正文……）

   # 力量体系
   （正文……）

   # 核心冲突
   （正文……）
   ```
3. 每节标题下把讨论中已敲定的具体内容原样写出——例如力量体系里对话提到过阶位/等级/职业表就
   **必须全部保留**，包括 Markdown 表格；禁止用"等"字概括；禁止只列名不带数值；禁止把多张表拍平成中文。
4. 若对话里就没聊过某一节，允许留空该节内容（保留 `# 标题` 行，正文只写一句"（对话中未涉及）"即可，
   不要自己脑补）。
5. **禁止在 4 节之外输出任何前言/后语/emoji/口头禅**（如"好的~"、"来看看"、"以下是整理"）。
6. **禁止**在开头包上 ```markdown 代码块围栏——直接从 `# 核心主题` 开始输出正文。

【脑爆对话内容】
{material}"""

# has_power_system=False 分支：3 节格式（不输出力量体系）
_FINALIZE_MARKDOWN_PROMPT_NO_POWER = """以下是一段小说灵感脑爆对话（含早期概要与最近对话）。请把用户和 AI 在
对话中**已经共同敲定的最完整版本**原原本本地整理出来。

**关键约束**：
1. **优先直接使用 AI 在对话中最近一次给出的完整表述**，只做整理（补齐/合并已确认的分散段落），
   **不要重新提炼、不要压缩、不要用你自己的话改写**。
2. 输出一份 markdown 文档，用 `# 一级标题` 分成正好 **3 节**，标题必须严格是这三个（不要加"与立意"、
   "设定"等后缀，也不要用二级标题 `##`），**本作不单列力量体系，绝不要输出 `# 力量体系` 节**：
   ```
   # 核心主题
   （正文……）

   # 世界观
   （正文……）

   # 核心冲突
   （正文……）
   ```
3. 每节标题下把讨论中已敲定的具体内容原样写出——保留 Markdown 表格和具体数值，禁止用"等"字概括。
4. 若对话里就没聊过某一节，允许留空该节内容（保留 `# 标题` 行，正文只写一句"（对话中未涉及）"即可，
   不要自己脑补）。
5. **禁止在 3 节之外输出任何前言/后语/emoji/口头禅**（如"好的~"、"来看看"、"以下是整理"）。
6. **禁止**在开头包上 ```markdown 代码块围栏——直接从 `# 核心主题` 开始输出正文。

【脑爆对话内容】
{material}"""

# ── 工具函数 ─────────────────────────────────────────────────────────────────
def _history_to_messages(history: list[dict]) -> list:
    """把对话历史映射成 langchain 消息序列。

    v3：过滤掉 pin 项（finalize_draft）——LLM 每轮 respond 只看到真实聊天记录，
    绝不把旧完整版当上文喂进去。若不过滤，用户在完整版气泡里看到"力量体系有 6 阶"，
    然后跟 AI 说"改成 5 阶"，AI 会同时看到"6 阶"的旧完整版 + "改成 5 阶"的新指令，
    容易输出摇摆或干脆围着旧完整版展开——观感等同"AI 没听懂修改"。
    """
    messages: list = []
    for entry in _chat_only(history):
        content = entry.get("content", "")
        if entry.get("role") == "human":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    return messages


def _entries_to_text(entries: list[dict]) -> str:
    """把对话条目渲染成「用户：/AI：」纯文本，供压缩 / 抽取的 prompt 使用。"""
    lines = []
    for entry in entries:
        who = "用户" if entry.get("role") == "human" else "AI"
        lines.append(f"{who}：{entry.get('content', '')}")
    return "\n".join(lines)


def _compress(prev_summary: str, overflow: list[dict]) -> str:
    """把旧概要 + 滑出保留窗口的对话轮次压缩成新的简要概要。压缩失败不阻断脑爆。

    ⚠️ 标记 tags=["nostream"]（LangGraph 官方约定的 TAG_NOSTREAM）：
    压缩是 respond 节点内的隐藏后端优化调用，不是用户可见的对话回复。若不打标签，
    messages-tuple 模式会把压缩 LLM 的 chunks 也流到前端，与 respond 的主对话回复
    交织出现在同一节点的 message stream 里——前端会看到聊天气泡中途冒出「1. 题材...」
    这种要点纪要格式的内容（compress 的输出），观感是「断开→冒不相干内容→变回去」。
    加 nostream tag 后 LangGraph 从源头就不广播这次调用的 chunks，前端彻底看不到。
    """
    parts = []
    if prev_summary:
        parts.append(f"【已有概要】\n{prev_summary}")
    parts.append("【需要并入概要的更早对话】")
    parts.append(_entries_to_text(overflow))
    material = "\n".join(parts)
    try:
        # 压缩是每轮聊天的隐藏开销，必须快——关闭思考避免给对话回合再叠加十几秒延迟。
        llm = get_llm(temperature=0.3, label="brainstorm_compress", thinking="disabled")
        result = llm.invoke(
            [
                SystemMessage(content=_COMPRESS_SYSTEM_PROMPT),
                HumanMessage(content=_COMPRESS_PROMPT.format(material=material)),
            ],
            config={"tags": ["nostream"]},  # 别被 messages-tuple 流出到前端
        )
        return result.content.strip()
    except Exception as e:  # noqa: BLE001 — 压缩失败退化为拼接，绝不阻断主流程
        _logger.error("脑爆历史压缩失败，退化为简单拼接：%s", e)
        fallback = prev_summary
        if fallback:
            fallback += "\n"
        return (fallback + _entries_to_text(overflow)).strip()


# ── 节点 ─────────────────────────────────────────────────────────────────────
def brainstorm_gate(state: NovelState) -> dict:
    """入口分叉：进脑爆 or 直接走普通流程。"""
    # 预填短路（langgraph dev 预填全字段）：直接落到 collect，再被其原逻辑跳过
    if all(getattr(state, f) for f in _BASIC_FIELDS):
        return {}
    answer = interrupt({
        "type": InterruptType.BRAINSTORM_GATE.value,
        "message": (
            "开始创作前，要不要先和 AI 一起做一轮「灵感脑爆」？\n"
            "· 进入脑爆 → 多轮对话共同脑爆基础设定、核心主题与世界观\n"
            "· 直接填表 → 走常规的参数填写流程"
        ),
    })
    enter = str(answer or "").strip().lower() in _ENTER_SIGNALS
    return {"from_brainstorm": enter}


def route_after_gate(state: NovelState) -> str:
    return "brainstorm_chat" if state.from_brainstorm else "collect_user_inputs"


def brainstorm_chat(state: NovelState) -> dict:
    """多轮聊天：只 interrupt 拿用户这一条消息（无 LLM，resume 重放无副作用）。

    payload 里带 has_power_system 供前端 switch 显示——用户切换开关时前端会立即通过
    updateThreadState 写回 state（不清 interrupt），本轮 payload 已过时无影响；下一轮进本节点
    时 payload 自然反映最新 flag。
    """
    msg = interrupt({
        "type": InterruptType.BRAINSTORM_CHAT.value,
        "message": "和 AI 一起脑爆吧——说说你的想法，或让 AI 给你些方向。聊得差不多了点「结束脑爆」。",
        "brainstorm_summary": state.brainstorm_summary,
        "brainstorm_history": state.brainstorm_history,
        "has_power_system": state.has_power_system,
    })
    text = str(msg or "").strip()
    if text in _END_SIGNALS:
        return {"brainstorm_done": True}
    # 基于「提交前」的 history 重算完整新 list（覆盖语义 → resume 重放幂等，不重复 append）
    return {"brainstorm_history": state.brainstorm_history + [{"role": "human", "content": text}]}


def route_after_chat(state: NovelState) -> str:
    return "brainstorm_finalize" if state.brainstorm_done else "brainstorm_respond"


def brainstorm_respond(state: NovelState) -> dict:
    """生成 AI 回复（流式由 LangGraph 自动捕获）+ 追加历史 + 必要时压缩。无 interrupt，不会被重放。

    system prompt 按 state.has_power_system 动态拼装——前端 switch 切换后写回 state，本轮
    respond 就能立即按新 flag 引导风格（开/关都有对应硬规则，见 _POWER_SYSTEM_*_RULE）。
    """
    history = state.brainstorm_history
    # 对话上下文：系统提示 + 早期概要（若有）+ 完整近期历史（末条即当前用户提问）
    messages: list = [SystemMessage(content=_build_brainstorm_system_prompt(state.has_power_system))]
    if state.brainstorm_summary:
        messages.append(SystemMessage(content=f"【早期对话概要】\n{state.brainstorm_summary}"))
    messages.extend(_history_to_messages(history))

    # 关闭深度思考：脑爆是交互式多轮聊天，每轮必须秒回 + 流式打字机；开启思考会先空等
    # 十几秒的 reasoning_content（前端只收到空 content chunk），体验等同「不流式」。
    llm = get_llm(temperature=0.8, label="brainstorm_respond", thinking="disabled")
    reply = llm.invoke(messages).content

    new_history = history + [{"role": "ai", "content": reply}]
    new_summary = state.brainstorm_summary

    # 记忆压缩（v3 pin 项穿透）：只对 chat 条目算保留窗口，pin 项（finalize_draft）永远留在原位不进 overflow。
    # 计算方式：按 kind 拆成 chat + pin 两个视图 → 对 chat 视图判断是否溢出 → overflow 只含 chat 条目 →
    # 剩余 chat 尾部保留窗口 + 全部 pin 项，按原顺序合并回 new_history。
    # 效果：用户点结束脑爆产出的完整版无论多久之后都能在历史里翻到，且绝不会被折叠进 summary。
    chat_only = _chat_only(new_history)
    if len(chat_only) > _KEEP_MESSAGES:
        overflow = chat_only[:-_KEEP_MESSAGES]
        new_summary = _compress(state.brainstorm_summary, overflow)
        # 保留 chat 尾窗口 + 全部 pin 项；pin 按原始顺序穿插回来
        kept_chat_ids = {id(e) for e in chat_only[-_KEEP_MESSAGES:]}
        new_history = [
            e for e in new_history
            if _is_pin(e) or id(e) in kept_chat_ids
        ]

    return {"brainstorm_history": new_history, "brainstorm_summary": new_summary}


def _finalize_material(state: NovelState) -> str:
    """把「早期概要 + 完整近期对话历史」拼成 finalize 步用的对话材料。

    v3：过滤掉 pin 项（finalize_draft）——LLM 只看到真实脑爆聊天 + 早期 summary，
    绝不把旧完整版当参考素材。这是 v3 消除"LLM 抄旧完整版造成循环污染"的核心手段：
    用户返回聊天后修改了几处，再次结束脑爆时 LLM 视角完全干净，会根据新的聊天上下文
    重新整理，而不是拿旧完整版当模板改几行。
    """
    return "\n".join([
        f"【早期对话概要】\n{state.brainstorm_summary}" if state.brainstorm_summary else "",
        _entries_to_text(_chat_only(state.brainstorm_history)),
    ]).strip()


def brainstorm_finalize(state: NovelState) -> dict:
    """脑爆结束轮 v2：跑一次可视流式 LLM，把用户已认可的完整版整理成 markdown（4 节一级标题格式），
    写入 state.finalize_markdown + 追加到 brainstorm_history 末条 AI 气泡——用户能在聊天页亲眼
    看到即将变成 review 内容的原文。

    **不再有二次 LLM 抽取**——4 大类字段拆分放在下游 brainstorm_finalize_confirm 节点用纯 python
    正则完成（`_split_finalize_markdown`），从根本上消除"聊天页里认可的内容被 review 面板重写"
    的保真度问题。

    整节点**不加** tags=["nostream"]——LLM chunks 走 messages-tuple 流到前端 BrainstormChat 视图，
    以 AI 气泡形式增量渲染，用户能实时看到打字机效果。

    prompt 分支：按 state.has_power_system 选 4 节 / 3 节格式，让 LLM 从源头就不输出力量体系节
    （避免下游拆分后又要丢弃、有 flag 反复错位风险）。

    失败降级：finalize_markdown 留空——下游 confirm 节点看到空 markdown 时 payload 会显式暴露，
    用户可通过「返回脑爆继续」重试，绝不静默兜底。
    """
    material = _finalize_material(state)

    prompt_template = (
        _FINALIZE_MARKDOWN_PROMPT_WITH_POWER
        if state.has_power_system
        else _FINALIZE_MARKDOWN_PROMPT_NO_POWER
    )

    try:
        # temperature 0.3 求稳（毕竟只是整理，不是创作）；关思考避免让用户干等
        llm = get_llm(temperature=0.3, label="brainstorm_finalize", thinking="disabled")
        # 无 nostream tag：chunks 会流到前端聊天页 AI 气泡末尾
        reply = llm.invoke([
            SystemMessage(content=_FINALIZE_MARKDOWN_SYSTEM_PROMPT),
            HumanMessage(content=prompt_template.format(material=material)),
        ]).content
        markdown = (reply or "").strip()
    except Exception as e:  # noqa: BLE001 — 保留失败降级，下游 confirm 节点显式呈现空态
        _logger.error("脑爆完整版 markdown 生成失败：%s", e)
        markdown = ""

    # 追加到聊天历史：让"结束脑爆"这一步的 AI 气泡就是这份即将变成 review 的完整版原文。
    # v3 保留策略：即便走 back_to_chat 分支也**不剥**这条——用户在聊天页始终能翻到完整版作为
    # "我要改哪里"的参考锚点。为防循环污染（LLM 抄旧完整版），条目打上 kind=finalize_draft，
    # 后续所有喂给 LLM 的场景（_finalize_material / _history_to_messages / _compress）都跳过它。
    new_history = (
        state.brainstorm_history + [{"role": "ai", "content": markdown, "kind": _KIND_FINALIZE_DRAFT}]
        if markdown
        else state.brainstorm_history
    )
    return {
        "finalize_markdown": markdown,
        "brainstorm_history": new_history,
        "finalize_missing_fields": [],  # 由 confirm 节点 use 分支写入；这里先清零，避免上一轮残留
    }


# ── finalize 完整版 markdown → 4 字段的纯 python 切分 ─────────────────────────
# 标题变体候选：LLM 偶尔会漂移到"核心主题与立意"这类扩写，用宽松前缀匹配兜住。
# key 就是要写回的 state 字段名。
_FINALIZE_SECTION_TITLES: dict[str, tuple[str, ...]] = {
    "core_theme": ("核心主题", "主题"),
    "world_building": ("世界观",),
    "power_system": ("力量体系", "力量"),
    "core_conflicts": ("核心冲突", "冲突"),
}
# 一级标题正则：行首 `#`（不含 `##`）+ 空白 + 标题文本 + 行尾。允许标题后带可选的额外文字
# （如"核心主题与立意"）——用 re.match 只检查前缀匹配。
_H1_LINE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _split_finalize_markdown(md: str, has_power_system: bool) -> tuple[dict[str, str], list[str]]:
    """纯 python 按 `# 一级标题` 正则切分 finalize markdown，返回 (字段字典, 缺失字段名)。

    绝对不跑 LLM——这就是 v2 保真度改造的核心：**用户在聊天页看到什么内容，
    就切什么内容到 review 面板**，绝无二次改写空间。

    切分算法：
    1. re.finditer 找出所有 `# xxx` 一级标题的位置；
    2. 每个标题文本按 _FINALIZE_SECTION_TITLES 的候选前缀匹配到对应字段名；
    3. 该标题所属正文 = 从当前标题末尾到下一个一级标题开头（或文本末尾）；
    4. has_power_system=False 时 power_system 不算 missing（即便切不到也不报警告）。

    返回：
    - fields: 只包含成功切到（且正文非空）的字段
    - missing: 4 类中未成功切到 / 正文为空的字段（按 has_power_system 过滤）
    """
    if not md.strip():
        # 空 markdown：4 字段全 missing（力量体系视 flag）
        missing = ["core_theme", "world_building", "power_system", "core_conflicts"]
        if not has_power_system:
            missing.remove("power_system")
        return {}, missing

    # 收集所有一级标题的位置 + 标题文本
    matches = list(_H1_LINE_RE.finditer(md))
    if not matches:
        # 没有任何一级标题：整份文档拆不动，全 missing
        missing = ["core_theme", "world_building", "power_system", "core_conflicts"]
        if not has_power_system:
            missing.remove("power_system")
        return {}, missing

    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        title_text = m.group(1).strip()
        # 用候选前缀反查字段名——宽松匹配"核心主题与立意"这类漂移标题
        matched_field: str | None = None
        for field_name, candidates in _FINALIZE_SECTION_TITLES.items():
            if any(title_text.startswith(c) for c in candidates):
                matched_field = field_name
                break
        if matched_field is None:
            continue  # 未识别的标题，跳过（例如 LLM 意外多输出的节）
        # 正文 = 本标题行结束 → 下一个标题行开始（或文档末尾）
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        if body:
            # 同一字段被多次匹配（不该发生但要防御）→ 保留首次
            fields.setdefault(matched_field, body)

    # 计算 missing：4 类中未切到的
    all_fields = ["core_theme", "world_building", "power_system", "core_conflicts"]
    missing = [f for f in all_fields if f not in fields]
    if not has_power_system:
        # 关闭力量体系时，即便切不到也不算 missing——反正 review 面板也不显示这个字段
        missing = [f for f in missing if f != "power_system"]
        fields.pop("power_system", None)  # 尊重开关：即便 LLM 违规输出了力量体系节也丢弃
    return fields, missing


def brainstorm_finalize_confirm(state: NovelState) -> dict:
    """脑爆结束轮的完整版确认闸门（v2 新增）。

    交互形态：finalize 节点已经把完整版 markdown 流式打到聊天页 AI 气泡里，用户能亲眼看到。
    本节点跳一个 interrupt，让用户从 AI 气泡下方两个按钮中二选一：
      - use          → 纯 python 切分 finalize_markdown → 覆盖 4 字段 → 路由到 brainstorm_extract_review
      - back_to_chat → 剥掉 history 末条（那份完整版）+ 复位 brainstorm_done=False + 清 finalize_markdown
                        → 路由回 brainstorm_chat 继续聊

    payload 里给前端渲染按钮所需的一切；finalize_markdown 也带上，前端可用于回显 / 排查。

    resume 是 dict（前端 buildFinalizeConfirmUse/Back）。非 dict 视为契约故障，回炉聊天不坑住图。
    """
    answer = interrupt({
        "type": InterruptType.BRAINSTORM_FINALIZE_CONFIRM.value,
        "message": "AI 已把咱们敲定的完整版整理到上方消息里。使用这份进入 review，或返回聊天继续调整。",
        "finalize_markdown": state.finalize_markdown,
        "has_power_system": state.has_power_system,
    })

    if not isinstance(answer, dict):
        _logger.error("brainstorm_finalize_confirm 收到非 dict resume：%r，回炉聊天", answer)
        return _finalize_back_to_chat(state)

    action = answer.get("action")
    if action == "use":
        # 纯 python 切分：绝无二次 LLM 改写。切不到的字段名累到 missing，供 review 面板挂警告。
        fields, missing = _split_finalize_markdown(state.finalize_markdown, state.has_power_system)
        out: dict = {"finalize_missing_fields": missing}
        for field_name, value in fields.items():
            out[field_name] = value
        return out

    if action == "back_to_chat":
        return _finalize_back_to_chat(state)

    _logger.error("brainstorm_finalize_confirm 收到未知 action：%r，回炉聊天", action)
    return _finalize_back_to_chat(state)


def _finalize_back_to_chat(state: NovelState) -> dict:
    """back_to_chat 分支的 state patch：只清 finalize_markdown + finalize_missing_fields + 复位
    brainstorm_done=False；**不动 brainstorm_history**。

    v3 策略：那条 finalize_draft 完整版气泡永久留在历史里作为用户"我要改哪里"的参考锚点。
    循环污染由 finalize/respond/compress 三处对 pin 项的过滤兜住——LLM 侧看不到旧完整版，
    用户侧则能翻聊天历史看到「已被驳回的旧整理」（前端按 kind 加分隔条渲染）。
    """
    return {
        "brainstorm_done": False,
        "finalize_markdown": "",
        "finalize_missing_fields": [],
    }


def route_after_finalize_confirm(state: NovelState) -> str:
    """confirm 后分支：
    - 若走 back_to_chat（brainstorm_done 复位为 False，完整版气泡打上 finalize_draft 标记留在历史里）→ 回聊天
    - 否则（use 分支：字段已覆写）→ 进 extract_review
    """
    return "brainstorm_extract_review" if state.brainstorm_done else "brainstorm_chat"


def _make_confirm(field: str, label: str, itype: InterruptType) -> Callable[[NovelState], dict]:
    """轻量确认节点工厂：展示脑爆生成的内容，用户确认或编辑（不重新生成、不冲洗）。

    ⚠️ 已被 brainstorm_extract_review 合并接管，图上不再挂。保留定义仅便于快速回滚。
    """
    def _confirm(state: NovelState) -> dict:
        edited = interrupt({
            "type": itype.value,
            "title": label,  # 前端表单标题据此区分是在确认「核心主题/世界观/核心冲突」哪一项
            "message": f"确认或编辑脑爆生成的{label}（可直接修改后确认）：",
            "field": field,
            "content": getattr(state, field),
        })
        if isinstance(edited, str) and edited.strip():
            return {field: edited.strip()}
        return {}  # 直接确认 → 保留原内容
    return _confirm


confirm_brainstorm_core_theme = _make_confirm(
    "core_theme", "核心主题", InterruptType.BRAINSTORM_CORE_THEME_CONFIRM
)
confirm_brainstorm_world_building = _make_confirm(
    "world_building", "世界观", InterruptType.BRAINSTORM_WORLD_BUILDING_CONFIRM
)
confirm_brainstorm_power_system = _make_confirm(
    "power_system", "力量体系", InterruptType.BRAINSTORM_POWER_SYSTEM_CONFIRM
)
confirm_brainstorm_core_conflicts = _make_confirm(
    "core_conflicts", "核心冲突", InterruptType.BRAINSTORM_CORE_CONFLICTS_CONFIRM
)


def brainstorm_extract_review(state: NovelState) -> dict:
    """脑爆产物整合 review：把 4 个正式设定字段一次性交给用户 review + 编辑，取代原 4 个逐项 confirm。

    resume 值为 dict（前端 BrainstormExtractReview 提交）：
      - {"action": "advance", ...4 字段} → 覆写字段 + 置 brainstorm_review_advance=True → 路由到 collect_user_inputs
      - {"action": "back_to_chat"}       → 不写回字段，把 brainstorm_done 置回 False → 路由回 brainstorm_chat 继续聊天

    payload 里带 has_power_system 供前端判定是否渲染力量体系编辑区。此值来源于 state（用户在
    聊天页 switch 已经决定过），本节点不再让用户在抽屉里覆盖 flag——避免"聊天时说不要 → 抽屉里
    又勾上但没有内容可展示"的错位。
    """
    answer = interrupt({
        "type": InterruptType.BRAINSTORM_EXTRACT_REVIEW.value,
        "message": "请审阅并按需修改脑爆生成的正式设定；保存并推进将跳过逐项确认，直接进入基础参数填写。",
        "core_theme": state.core_theme,
        "world_building": state.world_building,
        "power_system": state.power_system,
        "core_conflicts": state.core_conflicts,
        "has_power_system": state.has_power_system,
        # v2 保真度改造：finalize_confirm 节点纯 python 切分完整版 markdown 后累进这个列表——
        # 未成功切到内容的字段名（core_theme/world_building/power_system/core_conflicts 之一或多个），
        # 供前端在对应 FieldBlock 头部挂黄色警告，提示用户手填或返回聊天补充。
        "missing_fields": list(state.finalize_missing_fields or []),
    })

    # 契约：前端必发 dict。非 dict 视为契约故障，回炉聊天避免坑住图；不试图猜测意图。
    if not isinstance(answer, dict):
        _logger.error("brainstorm_extract_review 收到非 dict resume：%r，回炉聊天", answer)
        return {"brainstorm_done": False, "brainstorm_review_advance": False}

    action = answer.get("action")
    if action == "back_to_chat":
        # 不写回 4 字段（丢弃抽屉里未保存编辑），复位 brainstorm_done 让 route_after_chat 重新收用户消息
        return {"brainstorm_done": False, "brainstorm_review_advance": False}

    if action == "advance":
        out: dict = {"brainstorm_review_advance": True}
        for field_name in ("core_theme", "world_building", "power_system", "core_conflicts"):
            val = answer.get(field_name)
            if isinstance(val, str) and val.strip():
                out[field_name] = val.strip()
        # 现实向作品（state.has_power_system=False）：即便前端契约漂移带回了 power_system 也丢弃，
        # 与聊天页开关关闭的语义一致。
        if not state.has_power_system:
            out.pop("power_system", None)
        return out

    # action 未识别：契约故障，回炉聊天
    _logger.error("brainstorm_extract_review 收到未知 action：%r，回炉聊天", action)
    return {"brainstorm_done": False, "brainstorm_review_advance": False}


def route_after_extract_review(state: NovelState) -> str:
    """review 节点后分支：advance → 进 collect_user_inputs；back_to_chat → 回 brainstorm_chat。"""
    return "collect_user_inputs" if state.brainstorm_review_advance else "brainstorm_chat"


def route_after_confirm_world_building(state: NovelState) -> str:
    """脑爆确认链：世界观确认后，有力量体系的作品走力量体系确认，无力量体系（state.has_power_system=False）
    跳过、直连核心冲突确认。与常规链 route_after_world_building 同一开关，双链行为一致。

    ⚠️ 已被 brainstorm_extract_review 合并接管，图上不再挂。保留定义仅便于快速回滚。
    """
    return (
        "confirm_brainstorm_power_system"
        if state.has_power_system
        else "confirm_brainstorm_core_conflicts"
    )


def route_after_collect(state: NovelState) -> str:
    """collect_user_inputs 之后：脑爆来源直连 prepare_overall_outline（4 字段已在 review 抽屉里由用户确认，
    整段跳过 Phase 1 主题/世界观/力量体系/核心冲突生成 + 4 个 confirm）；否则走原流程。"""
    return "prepare_overall_outline" if state.from_brainstorm else "prepare_core_theme"
