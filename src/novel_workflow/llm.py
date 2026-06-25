"""Shared LLM factory for the novel workflow."""

from __future__ import annotations

import os
import sys
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI


class _PerfLogHandler(BaseCallbackHandler):
    """打印 LLM 调用的开始事件与耗时/token 性能日志。

    职责：
    - on_chat_model_start：在 LLM 真正发起请求时立即输出一行，让用户知道「正在跑哪个节点」。
    - on_llm_end：请求返回后输出耗时与 token 用量，便于定位慢调用。
    - on_llm_error：请求失败时输出错误与已耗时，避免静默卡住。

    每次调用以 run_id 为键记录起始时间，支持并发场景下多个调用同时计时。
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._starts: dict[UUID, float] = {}

    def _log(self, msg: str) -> None:
        # 统一走 stderr，避免与正常产出内容混在 stdout 里；flush 保证实时可见
        print(f"[LLM] {msg}", file=sys.stderr, flush=True)

    def on_chat_model_start(
        self, serialized: dict, messages: list, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._starts[run_id] = time.monotonic()
        # 估算输入规模（字符数），帮助判断慢是否由超长上下文导致
        chars = sum(len(getattr(m, "content", "") or "") for batch in messages for m in batch)
        self._log(f"→ 开始调用 [{self._label}]，输入约 {chars} 字符 …")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = time.monotonic() - self._starts.pop(run_id, time.monotonic())
        usage = self._extract_usage(response)
        usage_str = f"，token {usage}" if usage else ""
        self._log(f"✓ 完成 [{self._label}]，耗时 {elapsed:.1f}s{usage_str}")

    def on_llm_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        elapsed = time.monotonic() - self._starts.pop(run_id, time.monotonic())
        self._log(f"✗ 失败 [{self._label}]，已耗时 {elapsed:.1f}s：{error!r}")

    @staticmethod
    def _extract_usage(response: LLMResult) -> str:
        """从返回结果里提取 token 用量，兼容不同字段命名；取不到则返回空串。"""
        meta = (response.llm_output or {}).get("token_usage") if response.llm_output else None
        if not meta:
            # 部分实现把用量放在 generation 的 message.usage_metadata 上
            try:
                gen = response.generations[0][0]
                meta = getattr(gen.message, "usage_metadata", None)
            except (IndexError, AttributeError):
                meta = None
        if not meta:
            return ""
        prompt = meta.get("prompt_tokens") or meta.get("input_tokens")
        completion = meta.get("completion_tokens") or meta.get("output_tokens")
        total = meta.get("total_tokens") or meta.get("total")
        return f"(in={prompt} out={completion} total={total})"


def get_llm(temperature: float = 0.8, label: str = "llm") -> ChatOpenAI:
    """Create a ChatOpenAI instance from environment configuration.

    ChatOpenAI has built-in retry logic (max_retries=2 by default via tenacity),
    so transient network errors and rate limits are already handled internally.

    ``label`` 标识调用方（节点名），会出现在性能日志里，便于区分是哪个步骤在跑。
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
        callbacks=[_PerfLogHandler(label)],
    )
