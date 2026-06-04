"""Nodes for the simple generate → review workflow."""

from __future__ import annotations

import os

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from noval_workflow.state import WorkflowState


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("ARK_MODEL", "doubao-seed-2.0-lite"),
        temperature=0.8,
        api_key=os.environ["ARK_API_KEY"],
        base_url=os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
    )


def generate(state: WorkflowState) -> dict:
    """Call LLM to generate content based on user input (and optional feedback)."""
    llm = _get_llm()

    if state.human_feedback:
        prompt = (
            f"用户需求：{state.user_input}\n\n"
            f"你上一次的回答：\n{state.llm_output}\n\n"
            f"审核意见：{state.human_feedback}\n\n"
            "请根据审核意见修改后重新输出。"
        )
    else:
        prompt = state.user_input

    result = llm.invoke(prompt)
    return {"llm_output": result.content, "human_feedback": ""}


def human_review(state: WorkflowState) -> dict:
    """Pause and wait for human to review the LLM output."""
    feedback = interrupt(
        {
            "message": "请审核以下内容，输入 'approve' 通过，或输入修改意见：",
            "llm_output": state.llm_output,
        }
    )

    if feedback.strip().lower() == "approve":
        return {"human_feedback": ""}
    else:
        return {"human_feedback": feedback.strip()}


def route_after_review(state: WorkflowState) -> str:
    """Route: approved → end, rejected → regenerate."""
    if state.human_feedback:
        return "generate"
    return "__end__"
