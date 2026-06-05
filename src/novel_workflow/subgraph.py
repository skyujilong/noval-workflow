"""Reusable review subgraph: generate → llm_self_review → human_review."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from noval_workflow.llm import get_llm
from noval_workflow.prompts import (
    ARC_OUTLINE_REVIEW_PROMPT,
    CHARACTER_RELATIONS_REVIEW_PROMPT,
    CHARACTER_STATUS_REVIEW_PROMPT,
    CHAPTER_REVIEW_PROMPT,
    FORESHADOWING_REVIEW_PROMPT,
    FOUNDATION_REVIEW_PROMPT,
    PHASE_SUMMARY_REVIEW_PROMPT,
    TITLES_REVIEW_PROMPT,
)
from noval_workflow.state import ReviewSubState

# Max review rounds kept in history, per review_type.
# foundation/titles: content is short, 5 rounds affordable.
# chapter: drafts are long (~2000 chars each), 3 rounds keeps token cost manageable.
_HISTORY_MAX_ROUNDS: dict[str, int] = {
    "foundation": 5,
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
    llm = get_llm(temperature=0.8)

    messages: list = [SystemMessage(content=state.system_context)]

    if state.review_history:
        # Replay accumulated history, then append current feedback as new user turn
        for entry in state.review_history:
            if entry["role"] == "human":
                messages.append(HumanMessage(content=entry["content"]))
            else:
                messages.append(AIMessage(content=entry["content"]))
        messages.append(HumanMessage(content=state.review_feedback))
        new_user_msg = state.review_feedback
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


def llm_self_review(state: ReviewSubState) -> dict:
    """LLM reviews its own draft and returns feedback or empty string if OK."""
    llm = get_llm(temperature=0.3)

    review_template = _REVIEW_PROMPTS.get(state.review_type, FOUNDATION_REVIEW_PROMPT)
    review_prompt = review_template.format(draft=state.current_draft)

    messages = [
        SystemMessage(content=state.system_context),
        HumanMessage(content=review_prompt),
    ]

    result = llm.invoke(messages)
    feedback = result.content.strip()

    if _is_pass(feedback):
        return {"review_feedback": ""}
    return {"review_feedback": f"[AI审稿意见]\n{feedback}"}


_APPROVE_SIGNALS = {
    # English
    "approve", "approved", "ok", "okay", "yes", "y", "lgtm", "good",
    # Chinese
    "无问题", "没问题", "通过", "同意", "好", "好的", "可以", "确认", "批准",
}


def human_review(state: ReviewSubState) -> dict:
    """Pause for human review.

    Type any approval signal (e.g. '无问题', 'approve', 'ok') to pass,
    or type feedback text to send back to the LLM for revision.
    """
    display = {
        "draft": state.current_draft,
        "hint": "输入 '无问题' / 'approve' / 'ok' 通过，或输入修改意见重新生成",
    }
    if state.review_feedback:
        display["llm_critique"] = state.review_feedback

    feedback = interrupt(display)

    if str(feedback).strip().lower() in _APPROVE_SIGNALS:
        return {"approved": True, "review_feedback": ""}
    else:
        return {"approved": False, "review_feedback": str(feedback).strip()}


def route_after_llm_review(state: ReviewSubState) -> str:
    """If LLM found issues, regenerate directly; otherwise hand off to human."""
    if state.review_feedback:
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
