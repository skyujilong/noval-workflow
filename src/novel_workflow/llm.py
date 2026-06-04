"""Shared LLM factory for the novel workflow."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.8) -> ChatOpenAI:
    """Create a ChatOpenAI instance from environment configuration.

    ChatOpenAI has built-in retry logic (max_retries=2 by default via tenacity),
    so transient network errors and rate limits are already handled internally.
    """
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        raise ValueError("ARK_API_KEY environment variable is required")
    return ChatOpenAI(
        model=os.environ.get("ARK_MODEL", "doubao-seed-2.0-lite"),
        temperature=temperature,
        api_key=api_key,
        base_url=os.environ.get(
            "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"
        ),
    )
