"""nodes/volume_cast.py 单元测试（卷级花名册 Volume Cast Roster）。

prepare_volume_cast：组装本卷花名册生成任务（review_type=volume_cast，注入激活卷主线 + 现有卡司）。
save_volume_cast：introducing 完整卡去重预注册进 entity_cards（canon）+ returning/focus 写 volume_cast
动态层 + volume_cast_index 锚定激活卷；解析/字段错 fail-loud。
"""

from __future__ import annotations

import json

import pytest

from noval_workflow.nodes.volume_cast import prepare_volume_cast, save_volume_cast
from noval_workflow.state import NovelState, Volume


def _active_volume(index=1, title="第一卷·破题", summary="林尘出山对阵陆衍", start=1, end=28) -> Volume:
    return Volume(
        index=index, title=title, summary=summary, setup_for_next="卷末钩",
        chapter_start=start, planned_end=end, status="in_progress",
    )


def _draft_volume(index=2, title="第二卷·入局", summary="牵出隐藏势力") -> Volume:
    # 前瞻草稿卷：未锁章号
    return Volume(index=index, title=title, summary=summary, setup_for_next="",
                  chapter_start=0, planned_end=0, status="planning")


def _payload(introducing=(), returning=(), focus="本卷主线") -> str:
    return json.dumps(
        {"introducing": list(introducing), "returning": list(returning), "focus": focus},
        ensure_ascii=False,
    )


# ── prepare_volume_cast ──────────────────────────────────────────────────────


def test_prepare_volume_cast_builds_task_for_active_volume():
    """prepare 注入激活卷主线 + 现有卡司 + 后续卷前瞻，review_type=volume_cast，清审核桥接字段。"""
    state = NovelState(
        novel_name="星河剑主", genre="玄幻",
        volumes=[_active_volume(), _draft_volume()],
        total_chapters_written=0,
        entity_cards=[{"name": "林尘", "type": "人物", "role": "主角", "aliases": ["小尘"]}],
    )
    result = prepare_volume_cast(state)

    assert result["review_type"] == "volume_cast"
    tp = result["task_prompt"]
    assert "第一卷·破题" in tp          # 激活卷卷名注入
    assert "林尘出山对阵陆衍" in tp      # 激活卷主线注入
    assert "林尘" in tp                  # 现有卡司清单（判新旧）
    assert "第二卷·入局" in tp          # 后续卷前瞻
    assert "introducing" in tp and "returning" in tp  # 输出契约
    assert result["current_draft"] == "" and result["approved"] is False


# ── save_volume_cast：新登场落 canon + 返场/focus 落动态层 ─────────────────────


def test_save_volume_cast_registers_new_cards_and_roster():
    """introducing 完整卡并入 entity_cards；returning/focus 落 volume_cast；index 锚定激活卷。"""
    state = NovelState(
        volumes=[_active_volume(index=1)],
        total_chapters_written=0,
        entity_cards=[{"name": "林尘", "type": "人物", "role": "主角", "aliases": ["小尘"]}],
        current_draft=_payload(
            introducing=[
                {"name": "陆衍", "type": "人物", "role": "功能性反派", "aliases": []},
                {"name": "焚天印", "type": "物品", "effect": "焚烧一切", "rank": "上品"},
            ],
            returning=[{"name": "林尘", "role_in_volume": "本卷主导反击"}],
            focus="林尘对阵陆衍，夺焚天印",
        ),
    )
    out = save_volume_cast(state)

    names = {c.name for c in out["entity_cards"]}
    assert names == {"林尘", "陆衍", "焚天印"}          # 新卡并入，原卡保留
    vc = out["volume_cast"]
    assert vc["volume_index"] == 1
    assert vc["focus"] == "林尘对阵陆衍，夺焚天印"
    assert vc["returning"] == [{"name": "林尘", "role_in_volume": "本卷主导反击"}]
    assert {"name": "陆衍", "type": "人物"} in vc["introducing"]
    assert out["volume_cast_index"] == 1
    assert out["approved"] is False                     # 审核桥接字段被清


def test_save_volume_cast_dedup_drops_existing_entity():
    """introducing 里混入已有实体（名/别名命中）→ 去重丢弃，不重复建卡（canon 优先）。"""
    state = NovelState(
        volumes=[_active_volume(index=1)],
        total_chapters_written=0,
        entity_cards=[{"name": "林尘", "type": "人物", "role": "主角", "aliases": ["小尘"]}],
        current_draft=_payload(
            introducing=[
                {"name": "小尘", "type": "人物", "role": "主角"},   # 别名命中已有 → 丢弃
                {"name": "陆衍", "type": "人物", "role": "功能性反派"},
            ],
        ),
    )
    out = save_volume_cast(state)
    names = [c.name for c in out["entity_cards"]]
    assert names.count("林尘") == 1 and "小尘" not in names       # 未重复建卡
    assert "陆衍" in names


def test_save_volume_cast_cleans_returning_without_name():
    """returning 里缺 name 的脏项被剔除。"""
    state = NovelState(
        volumes=[_active_volume(index=3, start=61, end=90)],
        total_chapters_written=60,
        current_draft=_payload(
            returning=[
                {"name": "林尘", "role_in_volume": "继续成长"},
                {"role_in_volume": "没名字应被丢"},
                {"name": "  ", "role_in_volume": "空白名应被丢"},
            ],
        ),
    )
    out = save_volume_cast(state)
    assert out["volume_cast"]["returning"] == [{"name": "林尘", "role_in_volume": "继续成长"}]
    assert out["volume_cast_index"] == 3                # 锚定当前激活卷（第 3 卷）


# ── fail-loud ────────────────────────────────────────────────────────────────


def test_save_volume_cast_empty_draft_raises():
    state = NovelState(volumes=[_active_volume()], current_draft="")
    with pytest.raises(ValueError, match="current_draft 为空"):
        save_volume_cast(state)


def test_save_volume_cast_bad_json_raises():
    state = NovelState(volumes=[_active_volume()], current_draft="这不是 JSON{{{")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        save_volume_cast(state)


def test_save_volume_cast_introducing_not_list_raises():
    state = NovelState(
        volumes=[_active_volume()],
        current_draft=json.dumps({"introducing": {"name": "x"}, "returning": []}),
    )
    with pytest.raises(ValueError, match="introducing 必须是数组"):
        save_volume_cast(state)


def test_save_volume_cast_bad_card_fails_loud():
    """introducing 里人物卡缺 role → parse_card fail-loud（交审核循环重生成）。"""
    state = NovelState(
        volumes=[_active_volume()],
        current_draft=_payload(introducing=[{"name": "陆衍", "type": "人物"}]),  # 人物缺 role
    )
    with pytest.raises(ValueError):
        save_volume_cast(state)
