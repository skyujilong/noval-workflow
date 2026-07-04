"""进化中央库（SQLite）的 CRUD / 查询往返测试。"""

from __future__ import annotations

import pytest

from noval_workflow.prompts import evolution_store as s


@pytest.fixture()
def db(monkeypatch, tmp_path):
    """每个测试用独立临时 db，避免相互污染。"""
    monkeypatch.setenv("PROMPT_EVOLUTION_DB", str(tmp_path / "evo.db"))
    s.init_db()
    return tmp_path


def _sample_event() -> s.EvolutionEvent:
    return s.EvolutionEvent(
        novel_name="测试书",
        genre="玄幻",
        trigger=s.EventTrigger.MANUAL,
        review_type="chapter",
        chapter_index=3,
        source_feedback="战斗太拖沓",
        rejected_excerpt="一段被打回正文",
        proposals=(
            s.Proposal(
                field="evolved_directives",
                text="战斗控制在300字内",
                rationale="收紧节奏",
                conflicts_with="原3000字要求",
            ),
        ),
    )


def test_event_add_get_roundtrip(db):
    ev = s.add_event(_sample_event())
    assert ev.id.startswith("ev_") and ev.created_at

    got = s.get_events("测试书")
    assert len(got) == 1
    only = got[0]
    assert only.source_feedback == "战斗太拖沓"
    assert only.chapter_index == 3
    assert only.proposals[0].conflicts_with == "原3000字要求"
    assert only.status is s.EventStatus.PROPOSED


def test_event_get_by_id_and_missing(db):
    ev = s.add_event(_sample_event())
    assert s.get_event(ev.id).id == ev.id
    with pytest.raises(s.EvolutionEventNotFound):
        s.get_event("ev_does_not_exist")


def test_update_event_marks_applied(db):
    ev = s.add_event(_sample_event())
    updated = s.update_event(
        ev.id,
        status=s.EventStatus.APPLIED,
        applied={"evolved_directives": "战斗控制在300字内"},
        prompt_before={"evolved_directives": ""},
        applied_at=s._now(),
    )
    assert updated.status is s.EventStatus.APPLIED
    assert updated.applied["evolved_directives"] == "战斗控制在300字内"
    assert updated.prompt_before == {"evolved_directives": ""}
    assert updated.applied_at


def test_update_event_rejects_unknown_field(db):
    ev = s.add_event(_sample_event())
    with pytest.raises(KeyError):
        s.update_event(ev.id, bogus_col=1)


def test_update_event_missing_id_raises(db):
    with pytest.raises(s.EvolutionEventNotFound):
        s.update_event("ev_nope", status=s.EventStatus.REVERTED)


def test_directive_add_query_filter(db):
    s.add_directives(
        [
            s.DirectiveItem(genre="玄幻", title="战斗节奏", text="战斗控制在300字内", tags=("节奏",)),
            s.DirectiveItem(genre="玄幻", title="对话占比", text="对话不超过四成", tags=("对话",)),
            s.DirectiveItem(genre="都市", title="都市味", text="多用城市意象"),
        ]
    )
    # 按题材过滤
    xianxia = s.query_directives(genre="玄幻")
    assert len(xianxia) == 2
    # 关键词过滤
    hit = s.query_directives(genre="玄幻", q="战斗")
    assert len(hit) == 1 and hit[0].title == "战斗节奏"
    # 放宽到全部题材
    everything = s.query_directives(genre=None)
    assert len(everything) == 3


def test_directive_get_and_bump_usage(db):
    saved = s.add_directives(
        [s.DirectiveItem(genre="玄幻", title="t", text="战斗控制在300字内")]
    )
    did = saved[0].id
    assert s.get_directives([did])[0].usage_count == 0
    s.bump_usage([did])
    s.bump_usage([did])
    assert s.get_directives([did])[0].usage_count == 2
    # 缺失 id 静默跳过
    assert s.get_directives(["dir_missing"]) == []


def test_inactive_directives_hidden_by_default(db):
    s.add_directives([s.DirectiveItem(genre="玄幻", title="t", text="x", active=False)])
    assert s.query_directives(genre="玄幻") == []
    assert len(s.query_directives(genre="玄幻", active=False)) == 1
