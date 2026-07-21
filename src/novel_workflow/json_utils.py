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
from typing import Any, Protocol, TypeVar, overload

from json_repair import repair_json
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, TypeAdapter, ValidationError

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


# ── invoke_pydantic：字段级 schema 校验 + 回喂重试（比 invoke_json 更严）─────────
#
# 与 invoke_json 的差异：invoke_json 只校验顶层 dict/list，子字段值类型完全不管；
# 这条通道用 pydantic BaseModel 做「字段级类型强校」——LLM 把 str 字段出成 dict 时
# ValidationError 会被 catch，把详细错误 + 上次 AI 输出回喂让 LLM 自修正，而不是静默
# 收敛脏数据。这是治理「LLM 出 JSON → 字段值漂移」共性问题的入口。
#
# 为什么不用 pydantic @field_validator 里做 dict→str 收敛：那会掩盖 LLM 漂移，让下游
# 一直在错的输出上做兼容。反过来让 LLM 自己修正，脏输出会随模型迭代被消灭。

_TModel = TypeVar("_TModel", bound=BaseModel)


def _format_validation_errors(exc: ValidationError) -> str:
    """把 pydantic ValidationError 展开成人类可读的中文清单——喂给 LLM 让它修正。

    输出形如：
      - 字段 `new_cards[0].ability_contract`: 期望 string，实际是 dict
      - 字段 `volumes[2].summary`: 期望 string，实际是 list
    """
    lines: list[str] = []
    for err in exc.errors():
        # loc 是元组，如 ('new_cards', 0, 'ability_contract')；拼成 dot/bracket 路径
        path_parts: list[str] = []
        for part in err["loc"]:
            if isinstance(part, int):
                path_parts.append(f"[{part}]")
            else:
                path_parts.append(f".{part}" if path_parts else str(part))
        path = "".join(path_parts) or "<root>"
        # msg 已是人类可读描述（如 "Input should be a valid string"）
        # input 可选展示（截断防止 dict 太长）
        input_val = err.get("input")
        input_repr = repr(input_val)
        if len(input_repr) > 80:
            input_repr = input_repr[:77] + "..."
        lines.append(f"  - 字段 `{path}`: {err['msg']}；实际值 = {input_repr}")
    return "\n".join(lines) if lines else "（无详细错误）"


def _pydantic_correction_message(
    exc: ValidationError, schema: type[BaseModel]
) -> HumanMessage:
    """把 pydantic 校验报错回喂给 LLM 的纠错指令：告诉它哪些字段错在哪、期望啥类型。

    包含三部分：
    1. 错误清单（loc + msg + 实际值）——精准告知问题字段
    2. 通用约束（禁止把 str 字段出成 dict/list、禁止 markdown 围栏）——覆盖最常见漂移
    3. 提示保持原任务不变——避免 LLM 认为要改需求
    """
    return HumanMessage(
        content=(
            "你上一次的输出未通过 schema 校验，无法作为审核草稿使用。\n\n"
            "具体错误：\n"
            f"{_format_validation_errors(exc)}\n\n"
            f"请严格按契约（{schema.__name__}）重新输出：\n"
            "- 所有声明为 string 的字段值必须是字符串（可为空串 \"\"），"
            "禁止把描述性字段拆成嵌套 JSON 对象（例如禁止 "
            '`"ability_contract": {"initial_anchor": ..., ...}` 这种写法）；\n'
            "- 用中文一段话描述、以 `；` 或 `+` 分隔子要素；\n"
            "- 只输出一个合法的 JSON 对象，无 markdown 围栏（```），无解释文字。\n\n"
            "**原任务不变**——只按上述约束修正字段值类型即可。"
        )
    )


@overload
def invoke_pydantic(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    schema: type[_TModel],
    label: str = ...,
    max_retries: int = ...,
) -> _TModel: ...
def invoke_pydantic(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    schema: type[BaseModel],
    label: str = "pydantic",
    max_retries: int = 2,
) -> BaseModel:
    """调用 LLM 取 JSON 并用 pydantic BaseModel 校验，失败回喂详细错误让 LLM 重生。

    与 :func:`invoke_json` 的差异：字段级类型校验，捕获 LLM 把 str 字段出成 dict/list
    的漂移，回喂 pydantic ``ValidationError`` 的具体错误清单让 LLM 自修正。

    :param llm: 已配置好的 LLM（``get_llm(...)`` 的返回值）。
    :param messages: 首轮对话消息（system + human 等）。
    :param schema: 期望的 pydantic BaseModel 类，作为字段契约。
    :param label: 日志标识，出现在告警里便于定位是哪一步（推荐传 review_type）。
    :param max_retries: 解析/校验失败后回喂 LLM 的最大重试次数（默认 2，即最多请求 3 次）。
    :raises JsonParseError: 首轮 + 全部重试均无法解析或校验通过时抛出。
    """
    convo = list(messages)
    last_error: JsonParseError | None = None
    for attempt in range(max_retries + 1):
        result = llm.invoke(convo)
        text = _content_to_text(result.content)
        # 第 1 步：修复 + 顶层 JSON 类型校验（与 invoke_json 共享逻辑）
        try:
            parsed = repair_and_parse(text, kind=dict)
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
                    _correction_message(exc, dict),
                ]
                continue
            break
        # 第 2 步：pydantic 字段级校验
        try:
            return schema.model_validate(parsed)
        except ValidationError as exc:
            last_error = JsonParseError(
                f"pydantic 校验失败（{schema.__name__}）：{exc.error_count()} 个错误"
            )
            if attempt < max_retries:
                _logger.warning(
                    "[%s] pydantic 校验失败（第 %d/%d 次），回喂 %d 个字段错误让 LLM 重生",
                    label,
                    attempt + 1,
                    max_retries + 1,
                    exc.error_count(),
                )
                convo = [
                    *convo,
                    AIMessage(content=text),
                    _pydantic_correction_message(exc, schema),
                ]
                continue
    # 重试用尽仍失败：抛到最顶层，绝不静默返回脏数据。
    assert last_error is not None
    _logger.error(
        "[%s] pydantic 校验在 %d 次尝试后仍失败", label, max_retries + 1
    )
    raise last_error


# ── invoke_pydantic_list：list 顶层版本（chapter_plan / scene_beats 用）────────
#
# 为什么单独写一个而不是给 invoke_pydantic 加反射：
# - 显式的双函数让 subgraph 里"dict 顶层 vs list 顶层"分派看一眼就懂；
# - 不引入 pydantic RootModel 概念，item_schema 直接是 BaseModel 子类，与 dict 版本
#   共享同一份错误消息格式（loc 天然带 [idx].xxx 定位）；
# - 两个函数结构 95% 相同——helper 全共享，主循环差异只在 kind=list 与逐条 model_validate。


def _pydantic_correction_message_for_list(
    exc: ValidationError, item_schema: type[BaseModel]
) -> HumanMessage:
    """list 顶层的 pydantic 纠错指令——错误清单 loc 里带 [idx] 定位到具体第几条 item。

    与 :func:`_pydantic_correction_message` 的差异只在文案：顶层是数组而非对象，且用
    item_schema.__name__ 标注单条 item 的契约名。
    """
    return HumanMessage(
        content=(
            "你上一次输出的 JSON 数组中，有条目未通过 schema 校验，无法作为审核草稿使用。\n\n"
            "具体错误（`[N]` 表示数组中的第 N 条，从 0 起）：\n"
            f"{_format_validation_errors(exc)}\n\n"
            f"请严格按契约（数组中每条为 {item_schema.__name__}）重新输出：\n"
            "- 所有声明为 string 的字段值必须是字符串（可为空串 \"\"），"
            "禁止把描述性字段拆成嵌套 JSON 对象；\n"
            "- 数值字段（如 chapter / beat_id / planted_batch）必须是数字，禁止写"
            '"第 3 章"、"批次 1" 这种字符串；\n'
            "- 只输出一个合法的 JSON 数组（以 `[` 开头、以 `]` 结束），"
            "无 markdown 围栏（```），无解释文字。\n\n"
            "**原任务不变**——只按上述约束修正字段值类型即可。"
        )
    )


def invoke_pydantic_list(
    llm: SupportsInvoke,
    messages: list[BaseMessage],
    *,
    item_schema: type[BaseModel],
    label: str = "pydantic-list",
    max_retries: int = 2,
) -> list[BaseModel]:
    """LLM 顶层出 JSON 数组、逐条按 ``item_schema`` 校验的三段式版本。

    与 :func:`invoke_pydantic` 的差异只在顶层类型：这条走 ``kind=list``，返回
    ``list[BaseModel]``；每条 item 走 ``item_schema.model_validate``。有任一条不合规，
    把所有出错 item 汇总成一份 pydantic ``ValidationError`` 回喂 LLM，让它一次性修正。

    与 invoke_json 的差异（同 invoke_pydantic）：字段级类型强校，能捕获 LLM 把 str 字段
    出成 dict / 把 int 字段出成 "第 N 章" 字符串的漂移，回喂具体错误让 LLM 自修正。

    :param llm: 已配置好的 LLM。
    :param messages: 首轮对话消息。
    :param item_schema: 数组中**每条 item** 的 pydantic BaseModel 契约。
    :param label: 日志标识（推荐传 review_type）。
    :param max_retries: 失败回喂 LLM 的最大重试次数（默认 2，即最多请求 3 次）。
    :raises JsonParseError: 首轮 + 全部重试均无法解析或校验通过时抛出。
    """
    convo = list(messages)
    last_error: JsonParseError | None = None
    for attempt in range(max_retries + 1):
        result = llm.invoke(convo)
        text = _content_to_text(result.content)
        # 第 1 步：修复 + 顶层 list 类型校验
        try:
            parsed = repair_and_parse(text, kind=list)
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
                    _correction_message(exc, list),
                ]
                continue
            break
        # 第 2 步：逐条 item pydantic 校验——用 TypeAdapter 一次性聚合所有 item 错误
        # （比逐条 try/except 干净：pydantic 自动把 loc 拼成 (idx, 字段…) 供
        # _format_validation_errors 展开成 [N].xxx 路径给 LLM 看，能一次纠所有错的 item）。
        try:
            validated = TypeAdapter(list[item_schema]).validate_python(parsed)
            return validated
        except ValidationError as exc:
            last_error = JsonParseError(
                f"pydantic 校验失败（list[{item_schema.__name__}]）："
                f"{exc.error_count()} 个错误"
            )
            if attempt < max_retries:
                _logger.warning(
                    "[%s] pydantic 校验失败（第 %d/%d 次），回喂 %d 个字段错误让 LLM 重生",
                    label,
                    attempt + 1,
                    max_retries + 1,
                    exc.error_count(),
                )
                convo = [
                    *convo,
                    AIMessage(content=text),
                    _pydantic_correction_message_for_list(exc, item_schema),
                ]
                continue
    # 重试用尽仍失败：抛到最顶层，绝不静默返回脏数据。
    assert last_error is not None
    _logger.error(
        "[%s] pydantic 校验在 %d 次尝试后仍失败", label, max_retries + 1
    )
    raise last_error
