"""设定一致性总审闸门（nodes/consistency.py）的单元桩测。

覆盖 plan 验证项②：
- audit「无问题」→ consistency_pass=True；
- audit 发现问题 + gate「重新审查」→ 路由回 audit_consistency；
- consistency_audit_count 达上限 → 强制 save_config；
- LLM 抛异常 → 兜底判过、不阻断冻结。
纯桩测：patch get_llm 与 interrupt，不触真实模型。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from noval_workflow.nodes import consistency as C
from noval_workflow.state import NovelState


def _state(**kw) -> NovelState:
    base = NovelState(
        core_theme="主角追寻真相的成长与代价。",
        world_building="灵气复苏的现代都市，修行者隐于市。",
        core_conflicts="主角与隐秘组织的多层对抗。",
        overall_outline="四卷起承转合……",
        character_profiles="主角：初始锚点弱、四卷成长天花板明确。",
    )
    return replace(base, **kw)


class _FakeLLM:
    """按 reply 返回 .content；raise=True 时 invoke 抛异常。"""

    def __init__(self, reply: str = "无问题", raise_exc: bool = False) -> None:
        self.reply = reply
        self.raise_exc = raise_exc

    def invoke(self, messages):  # noqa: ANN001
        if self.raise_exc:
            raise RuntimeError("boom")

        class _R:
            content = self.reply

        return _R()


def _patch_llm(monkeypatch, **llm_kw) -> None:
    monkeypatch.setattr(C, "get_llm", lambda *a, **k: _FakeLLM(**llm_kw))


# ── _is_clean ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "report,expected",
    [
        ("", True),
        ("无问题", True),
        ("无问题。", True),          # 极短且含「无问题」→ 宽松判过
        ("【问题1】世界观 → 与人物能力冲突 → 建议修订", False),
        ("无问题；但整体大纲第三卷存在一处因果断裂需注意……", False),  # 含「无问题」但很长 → 不判过
    ],
)
def test_is_clean(report: str, expected: bool) -> None:
    assert C._is_clean(report) is expected


# ── audit_consistency ────────────────────────────────────────────────────────
def test_audit_clean_pass(monkeypatch) -> None:
    _patch_llm(monkeypatch, reply="无问题")
    out = C.audit_consistency(_state())
    assert out["consistency_pass"] is True
    assert out["consistency_report"] == "无问题"
    assert out["consistency_audit_count"] == 1


def test_audit_problems_not_pass(monkeypatch) -> None:
    _patch_llm(monkeypatch, reply="【问题1】世界观 → 人物能力越出体系 → 建议收敛能力")
    out = C.audit_consistency(_state(consistency_audit_count=1))
    assert out["consistency_pass"] is False
    assert "问题1" in out["consistency_report"]
    assert out["consistency_audit_count"] == 2  # 累加


def test_audit_llm_exception_fallback_pass(monkeypatch) -> None:
    _patch_llm(monkeypatch, raise_exc=True)
    out = C.audit_consistency(_state())
    assert out["consistency_pass"] is True          # 兜底判过、绝不阻断
    assert "未能完成" in out["consistency_report"]
    assert out["consistency_audit_count"] == 1


def test_audit_empty_foundation_skips(monkeypatch) -> None:
    # 无任何设定字段（异常兜底）→ 直接判过，不调 LLM
    monkeypatch.setattr(C, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用 LLM")))
    empty = NovelState()
    out = C.audit_consistency(empty)
    assert out["consistency_pass"] is True
    assert out["consistency_audit_count"] == 1


# ── consistency_gate（resume 解析）────────────────────────────────────────────
def test_gate_skip_means_freeze_pass(monkeypatch) -> None:
    # 跳过（SKIP_VALUE=""）= 通过冻结 → consistency_pass=True
    monkeypatch.setattr(C, "interrupt", lambda payload: "")
    out = C.consistency_gate(_state(consistency_report="无问题", consistency_pass=True))
    assert out["consistency_pass"] is True


def test_gate_execute_means_redo_not_pass(monkeypatch) -> None:
    # 执行（EXECUTE_VALUE="yes"）= 重新审查 → consistency_pass=False
    monkeypatch.setattr(C, "interrupt", lambda payload: "yes")
    out = C.consistency_gate(_state(consistency_report="【问题1】…", consistency_pass=False))
    assert out["consistency_pass"] is False


# ── route_after_consistency_gate ─────────────────────────────────────────────
def test_route_pass_to_save_config() -> None:
    assert C.route_after_consistency_gate(_state(consistency_pass=True, consistency_audit_count=1)) == "save_config"


def test_route_redo_under_cap_reaudits() -> None:
    assert (
        C.route_after_consistency_gate(_state(consistency_pass=False, consistency_audit_count=1))
        == "audit_consistency"
    )


def test_route_redo_at_cap_forced_save() -> None:
    assert (
        C.route_after_consistency_gate(
            _state(consistency_pass=False, consistency_audit_count=C._MAX_AUDIT_ROUNDS)
        )
        == "save_config"
    )
