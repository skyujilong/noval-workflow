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
        total_chars = 0
        system_chars = 0
        user_chars = 0
        breakdown = []

        for batch in messages:
            for m in batch:
                content = getattr(m, "content", "") or ""
                chars = len(content)
                total_chars += chars

                # 按消息类型统计
                msg_type = getattr(m, "type", "unknown")
                if msg_type == "system":
                    system_chars += chars
                elif msg_type == "human":
                    user_chars += chars

                # 解析 system context 的组成结构（只统计第一个 system message）
                if msg_type == "system" and not breakdown:
                    text = content
                    # 提取各 section 的长度
                    sections = []
                    import re
                    for match in re.finditer(r"【(.+?)】", text):
                        section_name = match.group(1)
                        start = match.start()
                        # 找下一个 section 或结尾
                        next_match = re.search(r"\n【", text[start + 1:])
                        end = start + 1 + (next_match.start() if next_match else len(text) - start - 1)
                        section_len = end - start
                        sections.append(f"{section_name}: ~{section_len} 字")
                    if sections:
                        breakdown = sections

        # 打印详细组成
        self._log(f"→ 开始调用 [{self._label}]")
        self._log(f"  总计: {total_chars} 字符 (system: {system_chars}, user: {user_chars})")
        if breakdown:
            self._log(f"  System Context 组成: {', '.join(breakdown)}")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = time.monotonic() - self._starts.pop(run_id, time.monotonic())
        usage = self._extract_usage(response)
        finish = self._extract_finish_reason(response)
        parts = [f"耗时 {elapsed:.1f}s"]
        if usage:
            parts.append(f"入 {usage['in']} tok")
            parts.append(f"出 {usage['out']} tok")
            parts.append(f"总 {usage['total']} tok")
        if finish:
            parts.append(f"结束原因={finish}")
        self._log(f"✓ 完成 [{self._label}]，{', '.join(parts)}")

    def on_llm_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        elapsed = time.monotonic() - self._starts.pop(run_id, time.monotonic())
        self._log(f"✗ 失败 [{self._label}]，已耗时 {elapsed:.1f}s：{error!r}")

    @staticmethod
    def _extract_usage(response: LLMResult) -> dict[str, int] | None:
        """从返回结果里提取 token 用量，兼容不同字段命名。"""
        meta = (response.llm_output or {}).get("token_usage") if response.llm_output else None
        if not meta:
            # 部分实现把用量放在 generation 的 message.usage_metadata 上
            try:
                gen = response.generations[0][0]
                meta = getattr(gen.message, "usage_metadata", None)
            except (IndexError, AttributeError):
                meta = None
        if not meta:
            return None
        prompt = meta.get("prompt_tokens") or meta.get("input_tokens")
        completion = meta.get("completion_tokens") or meta.get("output_tokens")
        total = meta.get("total_tokens") or meta.get("total")
        return {"in": prompt, "out": completion, "total": total}

    @staticmethod
    def _extract_finish_reason(response: LLMResult) -> str | None:
        """提取结束原因：stop / length / content_filter / tool_calls 等。"""
        try:
            gen = response.generations[0][0]
            # 优先从 generation_info 取
            if gen.generation_info:
                reason = gen.generation_info.get("finish_reason")
                if reason:
                    return reason
            # 其次从 message 取
            if hasattr(gen.message, "response_metadata"):
                meta = gen.message.response_metadata
                if meta:
                    reason = meta.get("finish_reason")
                    if reason:
                        return reason
            # 兜底从 llm_output 取
            if response.llm_output:
                choices = response.llm_output.get("choices", [])
                if choices:
                    reason = choices[0].get("finish_reason")
                    if reason:
                        return reason
        except (IndexError, AttributeError):
            pass
        return None


def get_llm(
    temperature: float = 0.8,
    label: str = "llm",
    max_tokens: int | None = None,
    thinking: str | None = None,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance from environment configuration.

    ChatOpenAI has built-in retry logic (max_retries=2 by default via tenacity),
    so transient network errors and rate limits are already handled internally.

    ``label`` 标识调用方（节点名），会出现在性能日志里，便于区分是哪个步骤在跑。
    ``max_tokens`` 显式设置最大输出 token 数，避免长文本生成被截断。
    ``thinking`` 控制豆包推理模型的「深度思考」：
        - None（默认）：保持模型默认（Doubao-Seed-2.0-pro 默认会先输出 ~10-20s 的
          reasoning_content 再给正文，长文生成可接受、质量更好）。
        - "disabled"：关闭思考，模型立即输出正文 token（实测首 token <1s）。交互式场景
          （如灵感脑爆聊天）必须关，否则每轮要空等十几秒、流式打字机迟迟不出。
        - "enabled"：显式开启。
      经 Ark 透传 extra_body={"thinking": {"type": ...}}；该模型不支持 "auto"。
    """
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        raise ValueError("ARK_API_KEY environment variable is required")
    if max_tokens is None:
        max_tokens = int(os.environ.get("ARK_MAX_TOKENS", "16384"))
    # extra_body 直接合并进请求体根部，把豆包专有的 thinking 开关透传给 Ark；None 时不影响默认行为。
    extra_body = {"thinking": {"type": thinking}} if thinking is not None else None
    return ChatOpenAI(
        model=os.environ.get("ARK_MODEL", "doubao-seed-2.0-lite"),
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=os.environ.get(
            "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"
        ),
        timeout=900,  # 超时 15 分钟，适应长文本生成避免中途截断
        max_retries=2,  # 减少重试次数，平衡总等待时长
        extra_body=extra_body,
        callbacks=[_PerfLogHandler(label)],
    )
