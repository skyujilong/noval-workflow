"""Reusable review subgraph: generate → llm_self_review → human_review."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.interrupt_types import review_type_to_interrupt_type
from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    ARC_OUTLINE_REVIEW_PROMPT,
    CHARACTER_PROFILES_REVIEW_PROMPT,
    CHARACTER_RELATIONS_REVIEW_PROMPT,
    CHARACTER_STATUS_REVIEW_PROMPT,
    CHAPTER_REVIEW_PROMPT,
    CORE_CONFLICTS_REVIEW_PROMPT,
    CORE_THEME_REVIEW_PROMPT,
    FORESHADOWING_REVIEW_PROMPT,
    FOUNDATION_REVIEW_PROMPT,
    OVERALL_OUTLINE_REVIEW_PROMPT,
    PHASE_SUMMARY_REVIEW_PROMPT,
    TITLES_REVIEW_PROMPT,
    WORLD_BUILDING_REVIEW_PROMPT,
    get_prompt_pack,
)
from noval_workflow.state import ReviewSubState

# Max review rounds kept in history, per review_type.
# foundation/titles: content is short, 5 rounds affordable.
# chapter: drafts are long (~2000 chars each), 3 rounds keeps token cost manageable.
_HISTORY_MAX_ROUNDS: dict[str, int] = {
    "foundation": 5,
    "core_theme": 5,
    "world_building": 5,
    "core_conflicts": 5,
    "overall_outline": 5,
    "character_profiles": 5,
    "titles": 5,
    "chapter": 3,
    "arc_outline": 5,
    "character_status": 3,
    "character_relations": 3,
    "foreshadowing": 3,
    "phase_summary": 3,
}
_HISTORY_MAX_ROUNDS_DEFAULT = 5

_REVIEW_PROMPTS = {
    "foundation": FOUNDATION_REVIEW_PROMPT,
    "core_theme": CORE_THEME_REVIEW_PROMPT,
    "world_building": WORLD_BUILDING_REVIEW_PROMPT,
    "core_conflicts": CORE_CONFLICTS_REVIEW_PROMPT,
    "overall_outline": OVERALL_OUTLINE_REVIEW_PROMPT,
    "character_profiles": CHARACTER_PROFILES_REVIEW_PROMPT,
    "titles": TITLES_REVIEW_PROMPT,
    "chapter": CHAPTER_REVIEW_PROMPT,
    "arc_outline": ARC_OUTLINE_REVIEW_PROMPT,
    "character_status": CHARACTER_STATUS_REVIEW_PROMPT,
    "character_relations": CHARACTER_RELATIONS_REVIEW_PROMPT,
    "foreshadowing": FORESHADOWING_REVIEW_PROMPT,
    "phase_summary": PHASE_SUMMARY_REVIEW_PROMPT,
}

PASS_SIGNALS = {"无问题", "没有问题", "无明显问题", "内容合格", "质量合格"}

# 触发「判为通过」的条件：
#   1. 整条回复就是一个 pass 信号（精确匹配，允许前后有标点/空格）
#   2. 回复较短（< 40 字）且完全被 pass 信号覆盖（避免「第二点无问题，但…」误判）
def _is_pass(feedback: str) -> bool:
    stripped = feedback.strip("。！!， ,、\n")
    # 精确匹配：整条回复就是某个 pass 信号
    if stripped in PASS_SIGNALS:
        return True
    # 短回复且只包含 pass 信号词，无否定/转折词
    NEGATIVE_HINTS = {"但", "不", "问题", "错误", "矛盾", "建议", "修改", "缺少", "缺乏", "需要"}
    if len(feedback) < 40 and any(s in feedback for s in PASS_SIGNALS):
        if not any(h in feedback for h in NEGATIVE_HINTS):
            return True
    return False


def generate(state: ReviewSubState) -> dict:
    """Generate or regenerate content based on task_prompt and any feedback."""
    # 快照台账类（character_status/relations/foreshadowing/phase_summary）是结构化数据维护，
    # 非创作正文：关闭深度思考以加速、降本；创作类（正文/设定/大纲等）保留思考以保证质量。
    # ⚠️ 若发现台账一致性变差，这里是第一个该回退（去掉 thinking）的地方。
    is_snapshot = state.review_type in _SNAPSHOT_REVIEW_TYPES
    # thinking 决策优先级：用户在人工审核打回时的显式选择 > 按 review_type 的默认策略。
    # thinking_override 仅由 human_review 写入，作用于本轮打回触发的重新生成（含其后的 AI 自审
    # 循环）；为 None 时退回默认（快照类关思考加速 / 创作类保留思考保质量）。
    if state.thinking_override is not None:
        thinking = state.thinking_override
    else:
        thinking = "disabled" if is_snapshot else None
    llm = get_llm(
        temperature=0.8,
        label=f"generate:{state.review_type}",
        thinking=thinking,
    )

    # snapshot 类型的生成：拼「数据维护员身份 + 完整基础设定（去创作身份的 system_context）」，
    # 使等级/装备/技能/资源等硬性数值与世界观、力量/等级体系保持一致；
    # system_context 由 _prepare_* 以 include_identity=False 传入（纯设定块，无创作者口吻）。
    if is_snapshot:
        system_content = "你是严谨的小说数据维护员，负责根据任务要求生成或更新各类快照台账数据。"
        if state.system_context:
            system_content += (
                "\n\n以下是本作品的核心设定（含世界观），"
                "维护台账数据时须与之保持一致：\n" + state.system_context
            )
        messages: list = [SystemMessage(content=system_content)]
    else:
        messages: list = [SystemMessage(content=state.system_context)]

    if state.review_history:
        # Replay accumulated history, then append current feedback as new user turn
        for entry in state.review_history:
            if entry["role"] == "human":
                messages.append(HumanMessage(content=entry["content"]))
            else:
                messages.append(AIMessage(content=entry["content"]))
        regen_instruction = (
            f"{state.review_feedback}\n\n"
            "【输出规范】请根据以上意见重新创作，直接输出修改后的完整正文，"
            "不得描述你做了哪些修改、不得使用「修改」「替换」「调整」等元叙述语言，"
            "从正文第一句话开始输出。"
        )
        messages.append(HumanMessage(content=regen_instruction))
        new_user_msg = state.review_feedback  # 历史只存原始 feedback，不含 instruction
    else:
        # First generation: no history yet, start with task prompt
        messages.append(HumanMessage(content=state.task_prompt))
        new_user_msg = state.task_prompt

    result = llm.invoke(messages)
    draft = result.content

    # Append this round to history and trim to per-type window
    max_rounds = _HISTORY_MAX_ROUNDS.get(state.review_type, _HISTORY_MAX_ROUNDS_DEFAULT)
    new_history = list(state.review_history) + [
        {"role": "human", "content": new_user_msg},
        {"role": "ai",    "content": draft},
    ]
    if len(new_history) > max_rounds * 2:
        new_history = new_history[-(max_rounds * 2):]

    return {
        "current_draft": draft,
        "review_feedback": "",
        "review_history": new_history,
    }


_SNAPSHOT_REVIEW_TYPES = {"character_status", "character_relations", "foreshadowing", "phase_summary"}


def llm_self_review(state: ReviewSubState) -> dict:
    """LLM reviews its own draft and returns feedback or empty string if OK."""
    llm = get_llm(temperature=0.3, label=f"self_review:{state.review_type}")

    # 章节审核的"文风合规"部分按题材注入：CHAPTER_REVIEW_PROMPT 含 {style_checklist}
    # 占位，必须提供，否则 str.format 会 KeyError。其余审核类型走共享 _REVIEW_PROMPTS。
    if state.review_type == "chapter":
        pack = get_prompt_pack(state.genre, state.novel_name)
        review_prompt = CHAPTER_REVIEW_PROMPT.format(
            draft=state.current_draft,
            style_checklist=pack.flavor.chapter_review_checklist,
        )
    else:
        review_template = _REVIEW_PROMPTS.get(state.review_type, FOUNDATION_REVIEW_PROMPT)
        review_prompt = review_template.format(draft=state.current_draft)

    # ========================================================================
    # 【重要】如果有人工审核意见，必须在 prompt 中突出强调！
    # 人工审核意见优先级高于 AI 自检，LLM 必须重点检查这些意见是否已落实
    # ========================================================================
    # 读 human_feedback（持久字段）而非 review_feedback：进入本节点前，generate 必定已把
    # review_feedback 清空为 ""（它消费人工意见重写草稿后即清零），若在此读 review_feedback
    # 会恒为空 → 下面这段强调块变成死代码、人工意见丢失。human_feedback 由 human_review 写入并
    # 贯穿整个打回→重写→自审循环，故自审能持续核对人工意见是否已落实。
    human_feedback_prefix = ""
    if state.human_feedback:
        human_feedback_prefix = (
            "═══════════════════════════════════════════════════════════════\n"
            "⚠️ 【最高优先级：人工审核意见】\n"
            "以下是人类审核员提出的修改意见，你必须重点检查草稿是否已完全落实：\n"
            f"{state.human_feedback}\n"
            "\n审核要求：\n"
            "1. 逐条核对上述人工意见，确认每一条都已在草稿中落实\n"
            "2. 如有任何一条未落实，必须明确指出并说明原因\n"
            "3. 只有全部落实后，才能给出「无问题/通过」的结论\n"
            "═══════════════════════════════════════════════════════════════\n\n"
        )

    # For snapshot-type reviews, prepend the task_prompt (which contains the previous
    # snapshot via {prev}) so the reviewer has an explicit baseline for point 5
    # ("no entries dropped vs last snapshot") rather than having to find it buried
    # in the long system_context.
    #
    # snapshot 自审同样注入完整基础设定（拼「审核员身份 + system_context」），据世界观 / 力量体系 /
    # 人物档案核对硬性数据一致性；仍前置 task_prompt 提供上次快照基线，供「不得漏条目」检查。
    # system_context 由 _prepare_* 以 include_identity=False 传入（纯设定块，无创作者口吻）。
    if state.review_type in _SNAPSHOT_REVIEW_TYPES and state.task_prompt:
        review_prompt = f"【本次更新任务（含上次快照）】\n{state.task_prompt}\n\n---\n\n{human_feedback_prefix}{review_prompt}"
        system_content = "你是严谨的小说数据审核员，负责审核各类快照数据的完整性与一致性。"
        if state.system_context:
            system_content += (
                "\n\n以下是本作品的核心设定（含世界观），"
                "请据此核对数据是否与世界观 / 力量体系 / 人物档案一致：\n" + state.system_context
            )
        system_msg = SystemMessage(content=system_content)
    else:
        review_prompt = f"{human_feedback_prefix}{review_prompt}"
        system_msg = SystemMessage(content=state.system_context)

    messages = [
        system_msg,
        HumanMessage(content=review_prompt),
    ]

    result = llm.invoke(messages)
    feedback = result.content.strip()

    if _is_pass(feedback):
        return {"review_feedback": "", "llm_review_count": state.llm_review_count + 1}
    return {"review_feedback": f"[AI审稿意见]\n{feedback}", "llm_review_count": state.llm_review_count + 1}


_APPROVE_SIGNALS = {
    "",  # 空回车 = 通过
    # English
    "approve", "approved", "ok", "okay", "yes", "y", "lgtm", "good",
    # Chinese
    "无问题", "没问题", "通过", "同意", "好", "好的", "可以", "确认", "批准",
}


def human_review(state: ReviewSubState) -> dict:
    """Pause for human review.

    Type any approval signal (e.g. '无问题', 'approve', 'ok') to pass,
    or type feedback text to send back to the LLM for revision.

    payload 自描述：带权威 type（由 review_type 反查）+ 完整富表单上下文
    （草稿/AI 自审意见/修改历史/review_type/轮次）。前端按 type 分发并直接
    渲染这些字段，无需再调用 getSubgraphState 反查嵌套子图 state——后者在
    多层子图冒泡时会选错 task，是"多子图映射不对"的根因。
    """
    feedback = interrupt({
        "type": review_type_to_interrupt_type(state.review_type).value,
        "review_type": state.review_type,
        "current_draft": state.current_draft,
        "review_feedback": state.review_feedback,
        "review_history": state.review_history,
        "llm_review_count": state.llm_review_count,
        "llm_review_max": state.llm_review_max,
        # 当前 review_type 的默认深度思考状态，供前端初始化「深度思考」开关，使其默认位置
        # 与不覆盖时的实际行为一致（创作类开、快照台账类关）。
        "default_thinking": "disabled" if state.review_type in _SNAPSHOT_REVIEW_TYPES else "enabled",
        # message 仅放操作提示；草稿正文走 current_draft 字段，前端单独渲染，避免重复存储。
        "message": "· 直接回车 → 通过\n· 输入修改意见 → 重新生成",
    })

    # resume 值规范形态为结构化 dict（human_review / foreshadowing_review 两个表单统一发送）：
    #   {"feedback": str, "thinking": "enabled"|"disabled"}
    #   - feedback 空串 = 通过；非空 = 修改意见。
    #   - thinking = 本轮重生成是否深度思考；缺失/空 → None（generate 走 review_type 默认策略）。
    # 仍兜底纯字符串（langgraph dev 手动 resume / 历史中断 / 通用兜底表单），"" = 通过。
    thinking_override: str | None = None
    if isinstance(feedback, dict):
        thinking_override = feedback.get("thinking") or None  # "" / 缺失 → None
        feedback = feedback.get("feedback", "")

    # 处理 None/falsy 值，避免 str(None) = "None" 的问题
    # 通过分支重置 human_feedback：本轮人工意见已落实，避免残留意见污染下一轮自审。
    if not feedback:
        return {"approved": True, "review_feedback": "", "llm_review_count": 0, "thinking_override": None, "human_feedback": ""}
    # 仅用小写副本比对审批信号；review_feedback 保留原始大小写，避免英文意见被压成小写后喂给 LLM。
    feedback_str = str(feedback).strip()
    if feedback_str.lower() in _APPROVE_SIGNALS:
        return {"approved": True, "review_feedback": "", "llm_review_count": 0, "thinking_override": None, "human_feedback": ""}
    # 打回：feedback_str 同时写入 review_feedback（供 generate 本轮消费）与 human_feedback
    # （持久保留，供其后 llm_self_review 核对是否已落实——generate 会清空 review_feedback）。
    return {
        "approved": False,
        "review_feedback": feedback_str,
        "llm_review_count": 0,
        "thinking_override": thinking_override,
        "human_feedback": feedback_str,
    }


def route_after_llm_review(state: ReviewSubState) -> str:
    """If LLM found issues and under max rounds, regenerate; otherwise hand off to human."""
    if state.review_feedback and state.llm_review_count < state.llm_review_max:
        return "generate"
    return "human_review"


def route_after_human(state: ReviewSubState) -> str:
    if state.approved:
        return END
    return "generate"


# Build and compile the subgraph
_builder = StateGraph(ReviewSubState)

_builder.add_node("generate", generate)
_builder.add_node("llm_self_review", llm_self_review)
_builder.add_node("human_review", human_review)

_builder.set_entry_point("generate")
_builder.add_edge("generate", "llm_self_review")
_builder.add_conditional_edges("llm_self_review", route_after_llm_review)
_builder.add_conditional_edges("human_review", route_after_human)

review_subgraph = _builder.compile()
