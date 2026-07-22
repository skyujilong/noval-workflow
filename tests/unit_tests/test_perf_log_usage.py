"""LLM 性能日志的 token usage 提取回归测试。"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from noval_workflow.llm import _PerfLogHandler, get_llm


def _result_with_message(message: AIMessage) -> LLMResult:
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_extract_usage_from_streamed_message_metadata() -> None:
    """流式调用结束后，LangChain 将 Ark usage 聚合到 AIMessage。"""
    response = _result_with_message(
        AIMessage(
            content="完成",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
            },
        )
    )

    assert _PerfLogHandler._extract_usage(response) == {
        "in": 120,
        "out": 30,
        "total": 150,
    }


def test_extract_usage_from_non_streaming_llm_output() -> None:
    """非流式 OpenAI-compatible 响应仍兼容原始 token_usage 命名。"""
    response = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content="完成"))]],
        llm_output={
            "token_usage": {
                "prompt_tokens": 80,
                "completion_tokens": 20,
                "total_tokens": 100,
            }
        },
    )

    assert _PerfLogHandler._extract_usage(response) == {
        "in": 80,
        "out": 20,
        "total": 100,
    }


def test_extract_usage_rejects_incomplete_metadata() -> None:
    """字段不完整时不伪造总量，避免日志显示看似成功的错误数据。"""
    message = AIMessage(
        content="完成",
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
        },
    )
    response = _result_with_message(message)
    message.usage_metadata = {
        "input_tokens": 120,
        "output_tokens": 30,
    }

    assert _PerfLogHandler._extract_usage(response) is None


def test_get_llm_requests_usage_for_streaming(monkeypatch) -> None:
    """生产工厂必须显式请求流式 usage，否则 Ark 结束 chunk 不返回 token。"""
    monkeypatch.setenv("ARK_API_KEY", "test-key")

    llm = get_llm()

    assert llm.stream_usage is True
