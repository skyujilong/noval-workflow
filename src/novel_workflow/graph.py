"""Simple generate → human_review workflow."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from noval_workflow.nodes import generate, human_review, route_after_review
from noval_workflow.state import WorkflowState

builder = StateGraph(WorkflowState)

builder.add_node("generate", generate)
builder.add_node("human_review", human_review)

builder.set_entry_point("generate")
builder.add_edge("generate", "human_review")
builder.add_conditional_edges("human_review", route_after_review)

graph = builder.compile(name="Generate & Review")
