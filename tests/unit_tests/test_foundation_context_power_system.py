"""build_foundation_context 力量体系约束段测试。

回归动机：power_system 早期只是被动罗列到 system prompt，LLM 在弧线大纲/章节
正文里会编造未定义的境界或体系。改成祈使约束后：
- 力量体系非空 → 必须包含"必须严格遵循""禁止虚构"两句硬规则；
- 力量体系为空 → 不注入任何约束文本，避免误导没有独立体系的作品。
"""

from __future__ import annotations

from noval_workflow.context import build_foundation_context
from noval_workflow.state import NovelState


_POWER_SYSTEM_BODY = "境界阶梯：炼气→筑基→金丹→元婴；金丹期为本作天花板。"


def _make_state(power_system: str) -> NovelState:
    """构造一个最小可用的 NovelState——只需要力量体系相关字段。"""
    return NovelState(
        novel_name="测试作品",
        genre="玄幻",
        has_power_system=bool(power_system),
        power_system=power_system,
    )


def test_power_system_present_injects_hard_constraint() -> None:
    """有力量体系时，system context 必须带上祈使约束的完整语句。"""
    ctx = build_foundation_context(_make_state(_POWER_SYSTEM_BODY))

    # 正文原样注入
    assert _POWER_SYSTEM_BODY in ctx
    # header 已从被动罗列改成祈使
    assert "【力量体系（本作已定稿，创作时必须严格遵循）】" in ctx
    # 硬约束关键短语
    assert "必须严格落入上述框架" in ctx
    assert "禁止虚构未在其中定义的新境界" in ctx


def test_power_system_absent_no_constraint_injected() -> None:
    """力量体系为空时，绝对不能出现祈使约束——避免误导没有独立体系的作品。"""
    ctx = build_foundation_context(_make_state(""))

    assert "【力量体系" not in ctx
    assert "必须严格落入上述框架" not in ctx
    assert "禁止虚构未在其中定义的新境界" not in ctx
