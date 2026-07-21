"""invoke_pydantic 三段式（修复 → schema 校验 → 失败回喂重试 → 用尽 fail-loud）单测。

用 mock LLM（SupportsInvoke protocol）驱动，不依赖真实 API。断言：
1. 首轮通过 → 单次调用返回实例
2. 首轮 pydantic 校验失败 → 回喂纠错消息 → 第二轮通过
3. 用尽仍失败 → 抛 JsonParseError
4. 纠错消息内容含 pydantic errors 详情（字段路径 + 类型说明）
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from noval_workflow.json_utils import JsonParseError, invoke_pydantic, invoke_pydantic_list


class _Sample(BaseModel):
    """测试用小 schema——name 是必填 str，count 是可选 int。"""

    name: str
    count: int = 0


class _ScriptedLLM:
    """按 responses 列表依次返回 AIMessage(content)。记录每次收到的 messages 供断言。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self.responses:
            raise RuntimeError("_ScriptedLLM: responses 耗尽")
        return AIMessage(content=self.responses.pop(0))


# ── 场景 1：首轮通过 ─────────────────────────────────────────────────────────

def test_invoke_pydantic_first_shot():
    llm = _ScriptedLLM(['{"name": "张三", "count": 42}'])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    model = invoke_pydantic(llm, messages, schema=_Sample, max_retries=2)
    assert isinstance(model, _Sample)
    assert model.name == "张三" and model.count == 42
    assert len(llm.calls) == 1


# ── 场景 2：首轮 pydantic 校验失败，第二轮通过 ─────────────────────────────────

def test_invoke_pydantic_retry_after_validation_error():
    llm = _ScriptedLLM([
        '{"name": {"nested": "wrong"}, "count": 1}',  # name 出成 dict → 校验失败
        '{"name": "李四", "count": 2}',  # 第二轮修正
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    model = invoke_pydantic(llm, messages, schema=_Sample, max_retries=2)
    assert model.name == "李四" and model.count == 2
    assert len(llm.calls) == 2
    # 第二轮 messages 应含原 sys + 原 task + AI 上次响应 + 纠错指令
    round2 = llm.calls[1]
    assert len(round2) >= 4
    # 纠错消息（倒数第一条 human）应含 pydantic 错误提示 + 字段路径
    correction = round2[-1]
    assert isinstance(correction, HumanMessage)
    assert "schema 校验" in correction.content
    assert "name" in correction.content  # 出错字段名


# ── 场景 3：用尽重试仍失败 → 抛 JsonParseError ────────────────────────────────

def test_invoke_pydantic_exhausts_retries_and_raises():
    llm = _ScriptedLLM([
        '{"name": {}, "count": 0}',  # 三次都出错
        '{"name": {}, "count": 0}',
        '{"name": {}, "count": 0}',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    with pytest.raises(JsonParseError) as exc_info:
        invoke_pydantic(llm, messages, schema=_Sample, max_retries=2)
    assert "pydantic 校验失败" in str(exc_info.value)
    assert "_Sample" in str(exc_info.value)
    assert len(llm.calls) == 3  # max_retries=2 = 首轮 + 2 次重试


# ── 场景 4：JSON 语法错也走回喂重试（复用 invoke_json 的顶层校验分支）─────────

def test_invoke_pydantic_json_syntax_error_also_retries():
    """JSON 语法错（顶层不是 dict）走 repair_and_parse 的错误分支，走同样的回喂逻辑。"""
    llm = _ScriptedLLM([
        "这不是 JSON, 只是散文",  # repair_and_parse 会拿到 str，抛 JsonParseError
        '{"name": "赵五", "count": 3}',  # 修正
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    model = invoke_pydantic(llm, messages, schema=_Sample, max_retries=2)
    assert model.name == "赵五"
    assert len(llm.calls) == 2


# ── 场景 5：纠错消息含字段路径详情，方便 LLM 定位 ─────────────────────────────

def test_correction_message_contains_field_path_and_actual_value():
    """确认纠错消息里能带出：字段路径 + 实际值——LLM 才知道具体是哪个字段错、错在什么值。"""
    llm = _ScriptedLLM([
        '{"name": {"initial_anchor": "x", "growth_ceiling": "y"}, "count": 5}',
        '{"name": "王六", "count": 5}',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    invoke_pydantic(llm, messages, schema=_Sample, max_retries=2)
    correction_content = llm.calls[1][-1].content
    # 字段路径带出（loc）
    assert "name" in correction_content
    # 实际值样本带出（帮 LLM 认出问题字段）
    assert "initial_anchor" in correction_content or "dict" in correction_content


# ══════════════════════════════════════════════════════════════════════════════
# invoke_pydantic_list：list 顶层版本（chapter_plan / scene_beats 用）
# ══════════════════════════════════════════════════════════════════════════════


class _Item(BaseModel):
    """测试用 item schema——模拟 ChapterPlanItemDraft / BeatDraft 的最小形态。"""

    chapter: int
    purpose: str


# ── 场景 A：首轮通过——LLM 出裸 JSON 数组、逐条 item 合规 ──────────────────────


def test_invoke_pydantic_list_first_shot():
    llm = _ScriptedLLM([
        '[{"chapter": 1, "purpose": "开场"}, {"chapter": 2, "purpose": "冲突"}]',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    items = invoke_pydantic_list(llm, messages, item_schema=_Item, max_retries=2)
    assert len(items) == 2
    assert items[0].chapter == 1 and items[1].purpose == "冲突"
    assert len(llm.calls) == 1


# ── 场景 B：一条 item 字段错 → 回喂后第二轮通过；错误清单带 [idx] 定位 ──────


def test_invoke_pydantic_list_retry_with_indexed_error():
    """LLM 出的数组中第 1 条（index=1）的 purpose 被拆成 dict → 回喂第二轮修正。"""
    llm = _ScriptedLLM([
        # 首轮：第 0 条对、第 1 条 purpose 是 dict
        '[{"chapter": 1, "purpose": "开场"}, {"chapter": 2, "purpose": {"target": "冲突"}}]',
        # 第二轮：全部合规
        '[{"chapter": 1, "purpose": "开场"}, {"chapter": 2, "purpose": "冲突"}]',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    items = invoke_pydantic_list(llm, messages, item_schema=_Item, max_retries=2)
    assert len(items) == 2
    assert len(llm.calls) == 2

    # 回喂消息应含 [1].purpose 这种 index 定位（帮 LLM 知道具体是数组第几条错）
    correction = llm.calls[1][-1]
    assert isinstance(correction, HumanMessage)
    assert "[1]" in correction.content  # index 定位
    assert "purpose" in correction.content
    assert "_Item" in correction.content  # 契约名标注


# ── 场景 C：顶层不是数组 → 走 _correction_message 通用文案回喂 ─────────────────


def test_invoke_pydantic_list_wrong_top_kind_retries():
    """LLM 出 dict 而非数组 → 顶层类型不对，走同款回喂重试。"""
    llm = _ScriptedLLM([
        '{"chapter": 1, "purpose": "错误的顶层"}',  # 是 dict，不是数组
        '[{"chapter": 1, "purpose": "开场"}]',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    items = invoke_pydantic_list(llm, messages, item_schema=_Item, max_retries=2)
    assert len(items) == 1
    assert len(llm.calls) == 2


# ── 场景 D：用尽重试仍失败 → 抛 JsonParseError ────────────────────────────────


def test_invoke_pydantic_list_exhausts_and_raises():
    llm = _ScriptedLLM([
        '[{"chapter": 1, "purpose": {}}]',
        '[{"chapter": 1, "purpose": {}}]',
        '[{"chapter": 1, "purpose": {}}]',
    ])
    messages = [SystemMessage(content="sys"), HumanMessage(content="task")]
    with pytest.raises(JsonParseError) as exc_info:
        invoke_pydantic_list(llm, messages, item_schema=_Item, max_retries=2)
    assert "pydantic 校验失败" in str(exc_info.value)
    assert "_Item" in str(exc_info.value)
    assert len(llm.calls) == 3  # max_retries=2 = 首轮 + 2 次重试
