"""设定一致性总审闸门 + AI 修订闭环（nodes/consistency.py）的单元桩测。

覆盖：
- audit「无问题」/发现问题/LLM 异常兜底 → consistency_pass 与轮数；
- gate resume 解析 → consistency_action（freeze/revise/reaudit）+ can_revise + revise_note 展示；
- route_after_consistency_gate 三分支（freeze/revise/reaudit）+ 达上限强制 save_config；
- revise_consistency：LLM 提案过滤（越界/空/无改动丢弃）、无结果/异常兜底提示；
- consistency_diff_gate：应用（回写白名单字段）/放弃 resume 解析；
- route_after_revise / route_after_diff_gate 路由。
纯桩测：patch get_llm / invoke_json / interrupt，不触真实模型。
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


# ── consistency_gate（resume 解析 → consistency_action）──────────────────────
def test_gate_freeze_action(monkeypatch) -> None:
    # 空串「跳过」/freeze = 通过冻结 → consistency_action="freeze"
    monkeypatch.setattr(C, "interrupt", lambda payload: "")
    out = C.consistency_gate(_state(consistency_report="无问题", consistency_pass=True))
    assert out["consistency_action"] == "freeze"
    assert out["consistency_revise_note"] == ""


def test_gate_revise_action(monkeypatch) -> None:
    # 让 AI 修订 → consistency_action="revise"
    monkeypatch.setattr(C, "interrupt", lambda payload: "revise")
    out = C.consistency_gate(_state(consistency_report="【问题1】…", consistency_pass=False))
    assert out["consistency_action"] == "revise"


@pytest.mark.parametrize("signal", ["yes", "reaudit", "重新审查"])
def test_gate_reaudit_action(monkeypatch, signal: str) -> None:
    monkeypatch.setattr(C, "interrupt", lambda payload: signal)
    out = C.consistency_gate(_state(consistency_report="【问题1】…", consistency_pass=False))
    assert out["consistency_action"] == "reaudit"


def test_gate_payload_can_revise_only_when_problems(monkeypatch) -> None:
    # can_revise 随 consistency_pass 取反：有问题才提供「让 AI 修订」
    seen = {}
    monkeypatch.setattr(C, "interrupt", lambda payload: seen.update(payload) or "")
    C.consistency_gate(_state(consistency_pass=False))
    assert seen["can_revise"] is True
    C.consistency_gate(_state(consistency_pass=True))
    assert seen["can_revise"] is False


def test_gate_shows_revise_note(monkeypatch) -> None:
    # revise 未产出改动时留下的提示会被闸门展示，并在返回里清空
    captured = {}
    monkeypatch.setattr(C, "interrupt", lambda payload: captured.update(payload) or "")
    out = C.consistency_gate(
        _state(consistency_pass=False, consistency_revise_note="AI 未提出可用修订")
    )
    assert "AI 未提出可用修订" in captured["message"]
    assert out["consistency_revise_note"] == ""


# ── route_after_consistency_gate（按 consistency_action 路由）────────────────
def test_route_freeze_to_save_config() -> None:
    assert (
        C.route_after_consistency_gate(_state(consistency_action="freeze", consistency_audit_count=1))
        == "save_config"
    )


def test_route_reaudit_under_cap() -> None:
    assert (
        C.route_after_consistency_gate(_state(consistency_action="reaudit", consistency_audit_count=1))
        == "audit_consistency"
    )


def test_route_revise_under_cap() -> None:
    assert (
        C.route_after_consistency_gate(_state(consistency_action="revise", consistency_audit_count=1))
        == "revise_consistency"
    )


@pytest.mark.parametrize("action", ["reaudit", "revise", "freeze"])
def test_route_at_cap_forced_save(action: str) -> None:
    # 达上限一律强制冻结，无论选什么
    assert (
        C.route_after_consistency_gate(
            _state(consistency_action=action, consistency_audit_count=C._MAX_AUDIT_ROUNDS)
        )
        == "save_config"
    )


# ── revise_consistency（AI 修订提案生成 + 过滤）──────────────────────────────
def _patch_invoke_json(monkeypatch, payload) -> None:
    monkeypatch.setattr(C, "get_llm", lambda *a, **k: object())
    monkeypatch.setattr(C, "invoke_json", lambda *a, **k: payload)


def test_revise_filters_and_builds(monkeypatch) -> None:
    _patch_invoke_json(
        monkeypatch,
        {
            "revisions": [
                {"field": "world_building", "reason": "收敛越界能力", "revised": "修订后的世界观"},
                {"field": "unknown_field", "reason": "x", "revised": "y"},          # 越界 → 丢弃
                {"field": "core_theme", "reason": "noop", "revised": "主角追寻真相的成长与代价。"},  # 与原文同 → 丢弃
                {"field": "core_conflicts", "reason": "空", "revised": "   "},        # 空 → 丢弃
            ]
        },
    )
    out = C.revise_consistency(_state(consistency_report="【问题1】世界观 → 冲突 → 收敛"))
    revs = out["consistency_revisions"]
    assert len(revs) == 1
    r = revs[0]
    assert r["field"] == "world_building"
    assert r["label"] == "世界观设定"
    assert r["before"] == "灵气复苏的现代都市，修行者隐于市。"
    assert r["after"] == "修订后的世界观"
    assert r["reason"] == "收敛越界能力"


def test_revise_clean_report_skips_llm(monkeypatch) -> None:
    monkeypatch.setattr(C, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用 LLM")))
    out = C.revise_consistency(_state(consistency_report="无问题"))
    assert out == {"consistency_revisions": []}


def test_revise_empty_result_gives_note(monkeypatch) -> None:
    _patch_invoke_json(monkeypatch, {"revisions": []})
    out = C.revise_consistency(_state(consistency_report="【问题1】…"))
    assert out["consistency_revisions"] == []
    assert out["consistency_revise_note"]  # 非空提示


def test_revise_llm_exception_fallback(monkeypatch) -> None:
    monkeypatch.setattr(C, "get_llm", lambda *a, **k: object())
    monkeypatch.setattr(C, "invoke_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = C.revise_consistency(_state(consistency_report="【问题1】…"))
    assert out["consistency_revisions"] == []
    assert out["consistency_revise_note"]  # 兜底提示、绝不阻断


def test_route_after_revise() -> None:
    assert C.route_after_revise(_state(consistency_revisions=[])) == "consistency_gate"
    assert (
        C.route_after_revise(_state(consistency_revisions=[{"field": "core_theme"}]))
        == "consistency_diff_gate"
    )


# ── consistency_diff_gate（应用/放弃 resume 解析）────────────────────────────
def test_diff_gate_apply_patches_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        C,
        "interrupt",
        lambda payload: {
            "action": "apply",
            "revisions": [
                {"field": "world_building", "after": "人工再改过的世界观"},
                {"field": "bad_field", "after": "x"},   # 越界 → 丢弃
                {"field": "core_theme", "after": "   "},  # 空白 → 丢弃
            ],
        },
    )
    out = C.consistency_diff_gate(_state(consistency_revisions=[{"field": "world_building"}]))
    assert out["world_building"] == "人工再改过的世界观"
    assert "bad_field" not in out and "core_theme" not in out
    assert out["consistency_action"] == "apply"
    assert out["consistency_revisions"] == []


def test_diff_gate_discard(monkeypatch) -> None:
    monkeypatch.setattr(C, "interrupt", lambda payload: {"action": "discard"})
    out = C.consistency_diff_gate(_state(consistency_revisions=[{"field": "world_building"}]))
    assert out == {"consistency_action": "discard", "consistency_revisions": []}


def test_route_after_diff_gate() -> None:
    assert C.route_after_diff_gate(_state(consistency_action="apply")) == "audit_consistency"
    assert C.route_after_diff_gate(_state(consistency_action="discard")) == "consistency_gate"
