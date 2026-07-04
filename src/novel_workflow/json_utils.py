"""LLM 输出 JSON 的健壮解析：先修复，再重试，最后抛错。

LLM 直接吐 JSON 时几乎必然出现脏输出：markdown 围栏、尾逗号、单引号、缺引号、
被截断、正文前后夹带说明文字。历史上各处 `json.loads(content)` 各写一份容错，
既重复又不彻底，一处解析失败就把整条链路带崩。本模块统一三段式策略：

1. **先修复**：用 ``json_repair`` 尽力把脏文本修成合法 JSON 再解析（挡掉绝大多数问题）；
2. **再重试**：仍解析失败时，把「你上次的 JSON 有误 + 具体报错」反馈回 LLM 重来，
   默认最多重试 1 次；
3. **仍不行就抛**：重试用尽仍失败，抛 :class:`JsonParseError` 到最顶层，绝不静默返回脏数据。

无 LLM 可回喂的场景（解析一段已生成好的 JSON 文本，如 current_draft 台账）用
:func:`repair_and_parse`——只做第 1 步「修复 + 解析 + 类型校验」，失败即抛。
需要「调用 LLM 拿 JSON」的场景用 :func:`invoke_json`——三段式全套。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, overload

from json_repair import repair_json
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

_logger = logging.getLogger(__name__)

# JSON 顶层只允许对象或数组（沿用 evolution._extract_json 的 dict/list 约定）。
JsonObj = dict[str, Any]
JsonArr = list[Any]
JsonKind = type[JsonObj] | type[JsonArr]


class JsonParseError(ValueError):
    """LLM 输出经修复 + 重试仍无法解析为期望的 JSON 类型。"""


class SupportsInvoke(Protocol):
    """能被 ``invoke(messages) -> 带 .content 的结果`` 调用的对象（ChatOpenAI 及测试替身）。"""

    def invoke(self, messages: Any) -> Any: ...


def _content_to_text(content: object) -> str:
    """把 LLM 返回内容归一为纯文本（兼容 str 与内容块列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts)
    return str(content)


def _kind_label(kind: JsonKind) -> str:
    """给 LLM 看的中文类型名。"""
    return "数组（array，以 [ 开头）" if kind is list else "对象（object，以 { 开头）"


@overload
def repair_and_parse(text: str) -> JsonObj: ...
@overload
def repair_and_parse(text: str, *, kind: type[JsonObj]) -> JsonObj: ...
@overload
def repair_and_parse(text: str, *, kind: type[JsonArr]) -> JsonArr: ...
def repair_and_parse(text: str, *, kind: JsonKind = dict) -> JsonObj | JsonArr:
    """先用 json_repair 修复脏 JSON 文本，再解析为 ``kind``（dict 或 list）。

    修复能吞掉 markdown 围栏、尾逗号、单引号、缺引号、截断、前后夹带的说明文字等常见脏输出。
    修复后仍非期望的顶层类型（如要 dict 却得到 list / 标量 / 空串）视为失败，抛
    :class:`JsonParseError`。
    """
    try:
        # return_objects=True：直接返回修复并解析后的 Python 对象；找不到任何 JSON 时返回 ""。
        data = repair_json(text, return_objects=True)
    except (ValueError, RecursionError) as exc:  # json_repair 极端输入的兜底
        raise JsonParseError(f"JSON 修复失败：{exc}；原文：{text[:200]!r}") from exc
    if not isinstance(data, kind):
        got = type(data).__name__
        raise JsonParseError(
            f"修复后顶层不是 {kind.__name__}（得到 {got}）；原文：{text[:200]!r}"
        )
    return data


def _correction_message(error: JsonParseError, kind: JsonKind) -> HumanMessage:
    """把解析报错回喂给 LLM 的纠错指令：要求只输出合法 JSON、无围栏、无多余文字。"""
    return HumanMessage(
        content=(
            "你上一次的输出无法被解析为合法 JSON。\n"
            f"解析错误：{error}\n\n"
            f"请严格重新输出：只输出一个合法的 JSON {_kind_label(kind)}，"
            "不要包含任何解释文字，不要使用 markdown 代码围栏（```），"
            "不要在 JSON 前后添加多余内容。"
        )
    )


@overload
def invoke_json(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    label: str = ...,
    max_retries: int = ...,
) -> JsonObj: ...
@overload
def invoke_json(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    kind: type[JsonObj],
    label: str = ...,
    max_retries: int = ...,
) -> JsonObj: ...
@overload
def invoke_json(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    kind: type[JsonArr],
    label: str = ...,
    max_retries: int = ...,
) -> JsonArr: ...
def invoke_json(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    kind: JsonKind = dict,
    label: str = "json",
    max_retries: int = 1,
) -> JsonObj | JsonArr:
    """调用 LLM 取 JSON，先修复解析；失败则回喂报错重试，重试用尽仍失败抛错。

    :param llm: 已配置好的 LLM（``get_llm(...)`` 的返回值）。
    :param messages: 首轮对话消息（system + human 等）。
    :param kind: 期望的 JSON 顶层类型，``dict`` 或 ``list``。
    :param label: 日志标识，出现在告警里便于定位是哪一步。
    :param max_retries: 解析失败后回喂 LLM 的最大重试次数（默认 1，即最多请求 2 次）。
    :raises JsonParseError: 首轮 + 全部重试均无法解析为 ``kind`` 时抛出。
    """
    convo = list(messages)
    last_error: JsonParseError | None = None
    for attempt in range(max_retries + 1):
        result = llm.invoke(convo)
        text = _content_to_text(result.content)
        try:
            return repair_and_parse(text, kind=kind)
        except JsonParseError as exc:
            last_error = exc
            if attempt < max_retries:
                _logger.warning(
                    "[%s] JSON 解析失败（第 %d/%d 次），回喂报错重试：%s",
                    label,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                convo = [
                    *convo,
                    AIMessage(content=text),
                    _correction_message(exc, kind),
                ]
    # 重试用尽仍失败：抛到最顶层，绝不静默返回脏数据。
    assert last_error is not None  # 循环至少执行一次，失败路径必已赋值
    _logger.error("[%s] JSON 解析在 %d 次尝试后仍失败", label, max_retries + 1)
    raise last_error
