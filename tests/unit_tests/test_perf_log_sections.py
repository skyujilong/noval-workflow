"""_parse_context_sections：白名单化 section 解析，正文里的子标题不当独立节点。

回归动机：早期正则 `【(.+?)】` 会把力量体系正文里的【输出天花板】【治疗核心】、
伏笔台账里的【伏笔编号】等 LLM 生成 / 台账内部使用的子标题误报为独立 section，
且长度计算是「当前【到下一个【的距离」，导致日志层层嵌套、加起来远超实际字符数。

三层 prompt 重构后，设定资料从 system 移到 user 的【参考资料】块，_PerfLogHandler
改为对首条 human message 调用本函数（system 只剩身份+硬契约、无资料段头）。故除
纯函数行为外，另测 handler 确实从 human 解析（system 瘦身后不再产出 sections）。
"""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.llm import _PerfLogHandler, _parse_context_sections


def _names(sections: list) -> set[str]:
    """从 _Section 列表取名字集合，方便断言。"""
    return {s.name for s in sections}


def _as_map(sections: list) -> dict[str, int]:
    """名字 -> 字符数，方便断言长度。"""
    return {s.name: s.chars for s in sections}


def test_top_level_sections_only() -> None:
    """力量体系正文里带子标题，只应识别顶层【力量体系（本作已定稿，创作时必须严格遵循）】/【核心冲突】。"""
    power_body = (
        "本作力量体系分五大职业。\n"
        "【输出天花板】高爆发单体，正文很长很长很长\n"
        "【治疗核心】团队奶妈，正文更长更长更长\n"
    )
    text = (
        "你是一位资深作家……\n\n"
        "【小说名称】测试\n"
        f"\n【力量体系（本作已定稿，创作时必须严格遵循）】\n{power_body}"
        "\n【核心冲突】\n主角对抗诡异邪神\n"
    )
    result = _as_map(_parse_context_sections(text))

    ps_name = "力量体系（本作已定稿，创作时必须严格遵循）"
    assert set(result.keys()) == {"小说名称", ps_name, "核心冲突"}, (
        f"不应把正文里的子标题识别为顶层 section，实际得到：{list(result.keys())}"
    )
    # 力量体系长度应覆盖整段正文（含子标题），而不是"到下一个子标题的距离"
    assert result[ps_name] > len(power_body)


def test_foreshadowing_ledger_inner_labels_ignored() -> None:
    """伏笔台账正文每个条目都有【伏笔编号】【伏笔名称】等，都不能算顶层。"""
    ledger_body = (
        "【已埋】\n---\n"
        "【伏笔编号】F001\n【伏笔名称】神秘石碑\n【核心作用】关键转折\n"
    )
    text = f"【伏笔台账（最新）】\n{ledger_body}\n【阶段固化数据（最新）】\n阶段一收尾\n"
    result = _names(_parse_context_sections(text))

    assert result == {"伏笔台账（最新）", "阶段固化数据（最新）"}


def test_length_measured_to_next_top_section() -> None:
    """相邻两个顶层 section 的长度应等于起点差，不受正文里【】干扰。"""
    ps_name = "力量体系（本作已定稿，创作时必须严格遵循）"
    text = (
        f"【小说名称】测试\n\n【{ps_name}】\nA\n【子标题混淆】\nBBB\n【核心冲突】\n主线冲突\n"
    )
    result = _as_map(_parse_context_sections(text))

    # 力量体系起点 = "【小说名称】测试\n\n" 之后；核心冲突起点 = 力量体系块结束
    body = f"【{ps_name}】\nA\n【子标题混淆】\nBBB\n"
    assert result[ps_name] == len(body)


def test_empty_text_returns_empty_list() -> None:
    assert _parse_context_sections("") == []


def test_no_top_level_matches_returns_empty() -> None:
    """只有正文子标题、没有任何白名单顶层--不应产出误报。"""
    assert _parse_context_sections("正文里【输出天花板】和【治疗核心】不算 section\n") == []


def test_handler_parses_sections_from_human_not_system() -> None:
    """三层重构后设定在 user 的【参考资料】，handler 须从 human 解析、system 瘦身无产出。

    构造瘦 system（仅身份+硬契约，无白名单【】段头）+ 含【参考资料】设定的 human，
    断言 pending.sections 取到设定段名（证明解析自 human；system 无资料段头）。
    """
    settings_ctx = (
        "【世界观设定】\n病毒爆发三年后的废土世界\n\n"
        "【核心冲突】\n人与丧尸的生存冲突"
    )
    user = f"【参考资料】\n{settings_ctx}\n\n【本次任务】\n请输出核心主题。"
    messages = [
        [SystemMessage(content="你是创作者。【硬契约】…【任务契约】…【优先级约定】…")],
        [HumanMessage(content=user)],
    ]

    handler = _PerfLogHandler(label="test")
    run_id = uuid4()
    handler.on_chat_model_start({}, messages, run_id=run_id)

    pending = handler._pending[run_id]
    # system 瘦身无白名单段头 -> sections 全部来自 human 的【参考资料】块
    assert _names(pending.sections) == {"世界观设定", "核心冲突"}, (
        f"应从 human 解析设定段，实际：{sorted(_names(pending.sections))}"
    )
    # 【参考资料】/【本次任务】是分隔符、不在白名单，不得混入
    assert "参考资料" not in _names(pending.sections)
    assert "本次任务" not in _names(pending.sections)
