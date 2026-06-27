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
    llm = get_llm(temperature=0.8, label=f"generate:{state.review_type}")

    # snapshot 类型的生成只依赖 task_prompt（已包含上次快照 + 当前章节内容），无需完整 system_context
    if state.review_type in _SNAPSHOT_REVIEW_TYPES:
        messages: list = [SystemMessage(content="你是严谨的小说数据维护员，负责根据任务要求生成或更新各类快照台账数据。")]
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

    review_template = _REVIEW_PROMPTS.get(state.review_type, FOUNDATION_REVIEW_PROMPT)
    review_prompt = review_template.format(draft=state.current_draft)

    # For snapshot-type reviews, prepend the task_prompt (which contains the previous
    # snapshot via {prev}) so the reviewer has an explicit baseline for point 5
    # ("no entries dropped vs last snapshot") rather than having to find it buried
    # in the long system_context.
    #
    # 注意：snapshot review 不依赖完整 system_context，避免 token 爆炸
    # system_context 只传给非 snapshot 类型（如章节正文、整体大纲等需要上下文连贯的内容）
    if state.review_type in _SNAPSHOT_REVIEW_TYPES and state.task_prompt:
        review_prompt = f"【本次更新任务（含上次快照）】\n{state.task_prompt}\n\n---\n\n{review_prompt}"
        # snapshot review 只用极简系统提示，不塞完整 system_context
        system_msg = SystemMessage(content="你是严谨的小说数据审核员，负责审核各类快照数据的完整性与一致性。")
    else:
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
        # message 仅放操作提示；草稿正文走 current_draft 字段，前端单独渲染，避免重复存储。
        "message": "· 直接回车 → 通过\n· 输入修改意见 → 重新生成",
    })

    # 处理 None/falsy 值，避免 str(None) = "None" 的问题
    if not feedback:
        return {"approved": True, "review_feedback": "", "llm_review_count": 0}
    feedback_str = str(feedback).strip().lower()
    if feedback_str in _APPROVE_SIGNALS:
        return {"approved": True, "review_feedback": "", "llm_review_count": 0}
    else:
        return {"approved": False, "review_feedback": feedback_str, "llm_review_count": 0}


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
