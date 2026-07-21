"""P0 三层 prompt 架构的单测：render / PromptRequest / build_system。

不调 LLM、不需要 ARK_API_KEY。只验证结构与渲染契约。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from noval_workflow.prompts.render import (
    HARD_CONTRACTS,
    SNAPSHOT_IDENTITY_MAINTAINER,
    SNAPSHOT_IDENTITY_REVIEWER,
    ContextSection,
    PromptRequest,
    SystemRole,
    build_system,
    render,
    render_user,
)


def test_render_user_partitions_context_and_task() -> None:
    """有 L2 时 render_user 产出【参考资料】/【本次任务】分区。"""
    user = render_user("世界观正文", "写正文")
    assert "【参考资料】" in user
    assert "世界观正文" in user
    assert "【本次任务】" in user
    assert "写正文" in user


def test_render_user_empty_context_degrades_to_task() -> None:
    """L2 空时 render_user 退化为纯 task，不带分区头（重放历史轮次场景）。"""
    user = render_user("", "仅任务")
    assert user == "仅任务"
    assert "【参考资料】" not in user


def test_render_user_is_used_by_render() -> None:
    """render() 内部调 render_user，两者拼装同源（无漂移）。"""
    req = PromptRequest(
        system="sys",
        context=(ContextSection(key="k", body="ctx-body"),),
        task="task-body",
    )
    rendered_user = render(req)[1].content
    direct_user = render_user("ctx-body", "task-body")
    assert rendered_user == direct_user


def test_render_produces_one_system_one_human() -> None:
    """render 输出固定 1 SystemMessage + 1 HumanMessage。"""
    req = PromptRequest(
        system="sys",
        context=(ContextSection(key="k", body="ctx"),),
        task="do something",
    )
    msgs = render(req)
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)


def test_render_with_context_partitions_user() -> None:
    """有 L2 时 user 含【参考资料】/【本次任务】分区。"""
    req = PromptRequest(
        system="sys",
        context=(ContextSection(key="设定", body="世界观正文"),),
        task="写正文",
    )
    user = render(req)[1].content
    assert "【参考资料】" in user
    assert "世界观正文" in user
    assert "【本次任务】" in user
    assert "写正文" in user


def test_render_without_context_degrades_to_pure_task() -> None:
    """L2 为空时 user 退化为纯 task，不带【参考资料】分区头。"""
    req = PromptRequest(system="sys", context=(), task="仅任务")
    user = render(req)[1].content
    assert user == "仅任务"
    assert "【参考资料】" not in user


def test_render_skips_empty_sections() -> None:
    """空 body 的 section 被跳过，不污染 user。"""
    req = PromptRequest(
        system="sys",
        context=(
            ContextSection(key="空", body=""),
            ContextSection(key="有", body="内容"),
        ),
        task="t",
    )
    user = render(req)[1].content
    assert "内容" in user
    # 空 section 的 body 是空串，不应在输出里产生多余空分区
    assert user.count("【参考资料】") == 1


def test_build_system_genre_author_includes_all_hard_contracts() -> None:
    """build_system(GENRE_AUTHOR, ..., genre_identity=...) 产出的 L1 含全部硬契约名 + 优先级约定。"""
    system = build_system(
        SystemRole.GENRE_AUTHOR,
        "写核心主题",
        genre_identity="你是玄幻作家",
    )
    for contract in HARD_CONTRACTS:
        assert contract.name in system
    assert "优先级约定" in system
    assert "历史整改要点" in system
    assert "硬契约" in system
    assert "你是玄幻作家" in system
    assert "写核心主题" in system


def test_build_system_snapshot_maintainer_role() -> None:
    """snapshot 类走 SystemRole.SNAPSHOT_MAINTAINER，L1 出「数据维护员」身份 + 硬契约。"""
    system = build_system(SystemRole.SNAPSHOT_MAINTAINER, "更新伏笔台账")
    assert "数据维护员" in system
    # snapshot 也守硬契约
    for contract in HARD_CONTRACTS:
        assert contract.name in system
    assert "更新伏笔台账" in system


def test_build_system_no_hard_contracts_role_omits_contracts() -> None:
    """_NO_HARD_CONTRACTS_ROLES 里的 role(evolution/brainstorm)不叠硬契约,只出身份+任务契约。"""
    system = build_system(SystemRole.EVOLUTION_ENGINEER, "提炼整改规则")
    assert "进化工程师" in system
    assert "提炼整改规则" in system
    # 硬契约不注入
    assert "硬契约" not in system
    assert "优先级约定" not in system


def test_build_system_genre_author_missing_identity_fails() -> None:
    """GENRE_AUTHOR 未传 genre_identity → fail-loud(ValueError)。"""
    with pytest.raises(ValueError, match="GENRE_AUTHOR"):
        build_system(SystemRole.GENRE_AUTHOR, "任务")


def test_build_system_non_genre_role_rejects_genre_identity() -> None:
    """非 GENRE_AUTHOR 传 genre_identity → fail-loud,避免两身份并存的语义混淆。"""
    with pytest.raises(ValueError, match="SNAPSHOT_MAINTAINER"):
        build_system(
            SystemRole.SNAPSHOT_MAINTAINER,
            "任务",
            genre_identity="不该传",
        )


def test_build_system_identity_substitutions() -> None:
    """identity_substitutions 替换 _ROLE_TEXT 里的 {key} 占位符(供 brainstorm 注入题材列表)。"""
    system = build_system(
        SystemRole.BRAINSTORM_COACH,
        "力量体系分支规则",
        identity_substitutions={"genres_list": "玄幻 / 都市 / 科幻"},
    )
    # 占位符被真实值替换
    assert "玄幻 / 都市 / 科幻" in system
    assert "{genres_list}" not in system


def test_snapshot_identity_constants_distinct() -> None:
    """维护员/审核员身份文案不同，且都点明「严谨」「数据」语义(旧兼容别名保留)。"""
    assert SNAPSHOT_IDENTITY_MAINTAINER != SNAPSHOT_IDENTITY_REVIEWER
    assert "数据维护员" in SNAPSHOT_IDENTITY_MAINTAINER
    assert "数据审核员" in SNAPSHOT_IDENTITY_REVIEWER


def test_prompt_request_and_context_section_are_frozen() -> None:
    """三层类型不可变（frozen），防止运行时被篡改。"""
    req = PromptRequest(system="s", context=(), task="t")
    try:
        req.system = "x"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("PromptRequest 应为 frozen，system 不可改")
    section = ContextSection(key="k", body="b")
    try:
        section.body = "x"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("ContextSection 应为 frozen，body 不可改")
