"""json_utils：先修复、失败回喂 LLM 重试、仍不行抛错 的三段式行为。"""

from __future__ import annotations

import pytest

from noval_workflow.json_utils import (
    JsonParseError,
    invoke_json,
    repair_and_parse,
)


class _R:
    def __init__(self, content: object) -> None:
        self.content = content


class _ScriptedLLM:
    """按脚本依次返回响应，并记录调用次数与最后一次收到的消息（用于断言回喂）。"""

    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.last_messages: list = []

    def invoke(self, messages: list) -> _R:
        self.last_messages = messages
        content = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return _R(content)


# ── repair_and_parse：第 1 步「修复 + 解析 + 类型校验」 ────────────────────────


def test_repair_parses_clean_object():
    assert repair_and_parse('{"a": 1}') == {"a": 1}


def test_repair_strips_code_fence():
    assert repair_and_parse('```json\n{"a": 1}\n```') == {"a": 1}


def test_repair_fixes_trailing_comma_and_unquoted_keys():
    assert repair_and_parse("{a: 1, b: 2,}") == {"a": 1, "b": 2}


def test_repair_extracts_json_from_surrounding_prose():
    assert repair_and_parse('分析如下：\n{"to_delete": ["F01"]} 以上。') == {
        "to_delete": ["F01"]
    }


def test_repair_completes_truncated_object():
    # 长文生成被截断：json_repair 尽力补全。
    assert repair_and_parse('{"a": "hello') == {"a": "hello"}


def test_repair_list_kind():
    assert repair_and_parse("[1, 2, 3,]", kind=list) == [1, 2, 3]


def test_repair_wrong_kind_raises():
    # 期望 dict 却得到数组 → 视为失败。
    with pytest.raises(JsonParseError):
        repair_and_parse("[1, 2, 3]", kind=dict)


def test_repair_garbage_raises():
    with pytest.raises(JsonParseError):
        repair_and_parse("这里没有任何 JSON，纯说明文字")


# ── invoke_json：修复 → 回喂重试 → 抛错 ───────────────────────────────────────


def test_invoke_returns_on_first_valid():
    llm = _ScriptedLLM('{"ok": true}')
    assert invoke_json(llm, [], kind=dict) == {"ok": True}
    assert llm.calls == 1  # 首轮即成功，不应重试


def test_invoke_retries_then_succeeds():
    # 首轮脏输出（无 JSON），第二轮合法 → 回喂重试后成功。
    llm = _ScriptedLLM("抱歉我先解释一下……", '{"ok": 1}')
    assert invoke_json(llm, [], kind=dict) == {"ok": 1}
    assert llm.calls == 2


def test_invoke_retry_feeds_error_back_to_llm():
    llm = _ScriptedLLM("没有 JSON", '{"ok": 1}')
    invoke_json(llm, [], kind=dict)
    # 第二次调用时，会话应追加了「AI 上次输出 + 纠错指令」两条消息。
    feedback_text = "".join(getattr(m, "content", "") for m in llm.last_messages)
    assert "无法被解析为合法 JSON" in feedback_text
    assert "没有 JSON" in feedback_text  # 把上次脏输出原样带回


def test_invoke_raises_after_retries_exhausted():
    llm = _ScriptedLLM("永远不是 JSON")
    with pytest.raises(JsonParseError):
        invoke_json(llm, [], kind=dict)
    assert llm.calls == 2  # max_retries=1 → 首轮 + 1 次重试 = 2 次


def test_invoke_no_retry_when_max_retries_zero():
    llm = _ScriptedLLM("不是 JSON")
    with pytest.raises(JsonParseError):
        invoke_json(llm, [], kind=dict, max_retries=0)
    assert llm.calls == 1


def test_invoke_normalizes_block_list_content():
    # 内容以「块列表」形式返回（部分 langchain 消息形态）。
    llm = _ScriptedLLM([{"text": '{"a":'}, {"text": " 1}"}])
    assert invoke_json(llm, [], kind=dict) == {"a": 1}
