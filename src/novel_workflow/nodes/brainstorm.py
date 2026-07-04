"""Phase -1：灵感脑爆（可选，入口分叉）。

入口分叉：新建小说时先问「进脑爆」还是「直接填表」。选脑爆 → 与 LLM 多轮流式对话
（brainstorm_chat ⇄ brainstorm_respond 自循环），共同脑爆出基础信息 + 核心主题 + 世界观；
经轻量确认后汇合到 prepare_core_conflicts，**整段跳过** Phase 1 的 core_theme / world_building
生成审稿（否则再走 prepare 会把脑爆已生成的内容冲掉）。

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
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from noval_workflow.interrupt_types import InterruptType
from noval_workflow.json_utils import invoke_json
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

# ── prompts ──────────────────────────────────────────────────────────────────
_BRAINSTORM_SYSTEM_PROMPT = """你是一位资深的小说策划与灵感教练。你的任务是通过轻松的多轮对话，
和用户一起脑爆出一部小说的雏形：基础设定（题材、写作风格、目标读者、核心基调、篇幅）、
核心主题立意，以及世界观框架。

对话原则：
1. 一次只聚焦一两个问题，循序渐进，不要一口气抛出一堆问题。
2. 主动提出有启发性的可选方向供用户挑选，而不是干巴巴地索取信息。
3. 适时小结已经达成的共识，帮助用户看清雏形逐渐成形。
4. 当用户表示满意、或基础信息与主题/世界观已较完整时，主动提示用户可以「结束脑爆」进入正式创作。
5. 用自然、口语化的中文，简洁有重点。"""

_COMPRESS_SYSTEM_PROMPT = "你是严谨的对话纪要员，擅长把长对话压缩成不丢关键信息的要点概要。"

_COMPRESS_PROMPT = """以下是一段小说灵感脑爆对话的早期内容（可能已包含一份更早的概要）。
请把它压缩成一份简明的要点概要，保留所有已经确定或倾向的设定、主题、世界观线索与关键决定，
丢弃寒暄和重复内容。直接输出概要正文，不超过 400 字，不要任何前后缀说明。

{material}"""

_EXTRACT_SYSTEM_PROMPT = "你是小说设定结构化助手，严格按要求只输出 JSON。"

_EXTRACT_PROMPT = """以下是一段小说灵感脑爆对话（含早期概要与最近对话）。请基于全部内容，
提炼并补全这部小说的成型设定，输出**严格的 JSON 对象**（仅一个 JSON，不要额外解释文字）。

JSON 字段：
- novel_name: 小说名称（简短有辨识度）
- genre: 小说类型（如 通用/末日求生/玄幻/都市/科幻/两性情感 中贴近的一个）
- writing_style: 写作风格
- target_audience: 目标读者
- core_tone: 核心基调
- chapter_word_count: 每章字数目标（如 "3000字"）
- total_word_count: 总字数目标（如 "100万字"）
- core_theme: 核心主题与立意（完整成段，可直接作为正式设定使用）
- world_building: 世界观设定（完整成段，可直接作为正式设定使用）

对话信息不足的字段，请基于已有方向合理补全，不要留空。

输出示例：
```json
{{"novel_name": "...", "genre": "...", "writing_style": "...", "target_audience": "...", "core_tone": "...", "chapter_word_count": "...", "total_word_count": "...", "core_theme": "...", "world_building": "..."}}
```

【脑爆对话内容】
{material}"""


# ── 工具函数 ─────────────────────────────────────────────────────────────────
def _history_to_messages(history: list[dict]) -> list:
    """把对话历史映射成 langchain 消息序列。"""
    messages: list = []
    for entry in history:
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
    """把旧概要 + 滑出保留窗口的对话轮次压缩成新的简要概要。压缩失败不阻断脑爆。"""
    parts = []
    if prev_summary:
        parts.append(f"【已有概要】\n{prev_summary}")
    parts.append("【需要并入概要的更早对话】")
    parts.append(_entries_to_text(overflow))
    material = "\n".join(parts)
    try:
        # 压缩是每轮聊天的隐藏开销，必须快——关闭思考避免给对话回合再叠加十几秒延迟。
        llm = get_llm(temperature=0.3, label="brainstorm_compress", thinking="disabled")
        result = llm.invoke([
            SystemMessage(content=_COMPRESS_SYSTEM_PROMPT),
            HumanMessage(content=_COMPRESS_PROMPT.format(material=material)),
        ])
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
    """多轮聊天：只 interrupt 拿用户这一条消息（无 LLM，resume 重放无副作用）。"""
    msg = interrupt({
        "type": InterruptType.BRAINSTORM_CHAT.value,
        "message": "和 AI 一起脑爆吧——说说你的想法，或让 AI 给你些方向。聊得差不多了点「结束脑爆」。",
        "brainstorm_summary": state.brainstorm_summary,
        "brainstorm_history": state.brainstorm_history,
    })
    text = str(msg or "").strip()
    if text in _END_SIGNALS:
        return {"brainstorm_done": True}
    # 基于「提交前」的 history 重算完整新 list（覆盖语义 → resume 重放幂等，不重复 append）
    return {"brainstorm_history": state.brainstorm_history + [{"role": "human", "content": text}]}


def route_after_chat(state: NovelState) -> str:
    return "brainstorm_extract" if state.brainstorm_done else "brainstorm_respond"


def brainstorm_respond(state: NovelState) -> dict:
    """生成 AI 回复（流式由 LangGraph 自动捕获）+ 追加历史 + 必要时压缩。无 interrupt，不会被重放。"""
    history = state.brainstorm_history
    # 对话上下文：系统提示 + 早期概要（若有）+ 完整近期历史（末条即当前用户提问）
    messages: list = [SystemMessage(content=_BRAINSTORM_SYSTEM_PROMPT)]
    if state.brainstorm_summary:
        messages.append(SystemMessage(content=f"【早期对话概要】\n{state.brainstorm_summary}"))
    messages.extend(_history_to_messages(history))

    # 关闭深度思考：脑爆是交互式多轮聊天，每轮必须秒回 + 流式打字机；开启思考会先空等
    # 十几秒的 reasoning_content（前端只收到空 content chunk），体验等同「不流式」。
    llm = get_llm(temperature=0.8, label="brainstorm_respond", thinking="disabled")
    reply = llm.invoke(messages).content

    new_history = history + [{"role": "ai", "content": reply}]
    new_summary = state.brainstorm_summary

    # 记忆压缩：超过保留窗口时，把滑出的最老轮次 + 旧概要压成新概要，history 截断到保留窗口
    if len(new_history) > _KEEP_MESSAGES:
        overflow = new_history[:-_KEEP_MESSAGES]
        new_summary = _compress(state.brainstorm_summary, overflow)
        new_history = new_history[-_KEEP_MESSAGES:]

    return {"brainstorm_history": new_history, "brainstorm_summary": new_summary}


def brainstorm_extract(state: NovelState) -> dict:
    """脑爆结束：从对话抽取结构化产物（7 基础字段 + 完整 core_theme + world_building）写入 state。

    JSON 解析失败兜底返回空——7 字段空则 collect 表单让用户手填，core_theme/world_building 空则
    后续轻量确认步可手输；绝不阻断流程。
    """
    material = "\n".join([
        f"【早期对话概要】\n{state.brainstorm_summary}" if state.brainstorm_summary else "",
        _entries_to_text(state.brainstorm_history),
    ]).strip()
    try:
        # 抽取是「结束脑爆」后的一次性重格式化（对话里已有内容），不需深度思考；关闭避免
        # 切到表单前再空等一截。质量由后续表单 + 轻量确认步强制复核兜底。
        llm = get_llm(temperature=0.4, label="brainstorm_extract", thinking="disabled")
        # invoke_json：先修复脏 JSON，失败则回喂报错重试一次；仍失败抛错 → 下方兜底捕获。
        data = invoke_json(
            llm,
            [
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=_EXTRACT_PROMPT.format(material=material)),
            ],
            kind=dict,
            label="brainstorm_extract",
        )
    except Exception as e:  # noqa: BLE001 — 抽取失败兜底，表单/确认步手填
        _logger.error("脑爆产物抽取失败：%s", e)
        data = {}

    out: dict = {}
    for field_name in (*_BASIC_FIELDS, "core_theme", "world_building"):
        val = data.get(field_name)
        if isinstance(val, str) and val.strip():
            out[field_name] = val.strip()
    return out


def _make_confirm(field: str, label: str, itype: InterruptType) -> Callable[[NovelState], dict]:
    """轻量确认节点工厂：展示脑爆生成的内容，用户确认或编辑（不重新生成、不冲洗）。"""
    def _confirm(state: NovelState) -> dict:
        edited = interrupt({
            "type": itype.value,
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


def route_after_collect(state: NovelState) -> str:
    """collect_user_inputs 之后：脑爆来源走轻量确认（跳过 Phase 1 主题/世界观生成），否则走原流程。"""
    return "confirm_brainstorm_core_theme" if state.from_brainstorm else "prepare_core_theme"
