"""nodes/volumes.py 单元测试（滚动生成卷 + 前瞻队列架构）：

prepare_volumes 双模（首次规划前 1+N 卷 / 滚动重规划未开始的 1+N 卷）、save_volumes 多卷解析 +
权威赋值（激活卷 in_progress + 草稿卷 planning；滚动收口上一卷 + 丢旧草稿 + 冻结 closed）、
route_after_save_volumes。契约：current_draft 是对象 {"volumes":[激活卷, 草稿1, ...]}，激活卷
4 字段（含 chapters）、草稿卷 3 字段（无 chapters）。
"""

from __future__ import annotations

import json

import pytest

from noval_workflow.config import VOLUME_MAX_CHAPTERS, VOLUME_MIN_CHAPTERS
from noval_workflow.nodes.volumes import (
    prepare_volumes,
    route_after_save_volumes,
    save_volumes,
)
from noval_workflow.state import NovelState, Volume


# ── 契约构造 helper ──────────────────────────────────────────────────────────


def _active(title="卷1", summary="s", setup="钩", chapters=28) -> dict:
    return {"title": title, "summary": summary, "setup_for_next": setup, "chapters": chapters}


def _draft(title="草稿卷", summary="ds", setup="d钩") -> dict:
    return {"title": title, "summary": summary, "setup_for_next": setup}


def _payload(active: dict, drafts=(), human_confirmed=None) -> str:
    obj: dict = {"volumes": [active, *drafts]}
    if human_confirmed is not None:
        obj["human_confirmed"] = human_confirmed
    return json.dumps(obj, ensure_ascii=False)


# ── prepare_volumes 双模 ─────────────────────────────────────────────────────


def test_prepare_volumes_first_mode_plans_lookahead_queue():
    """首次（无 volumes）：task_prompt 是「激活卷 + 前瞻草稿」的多卷 volumes 契约。"""
    state = NovelState(
        novel_name="星河剑主", genre="玄幻",
        overall_outline="起：少年出山……承：卷入纷争……转：高潮……合：收束……",
    )
    result = prepare_volumes(state)

    assert result["review_type"] == "volumes"
    tp = result["task_prompt"]
    assert "激活卷" in tp
    assert "前瞻草稿" in tp
    assert "volumes" in tp             # 多卷数组契约
    assert "少年出山" in tp            # 大纲被注入
    assert result["current_draft"] == ""
    assert result["approved"] is False


def test_prepare_volumes_rolling_mode_carries_activated_only():
    """滚动：承接「已激活卷」，next_index/start 由激活卷推；旧草稿卷不作为已冻结卷喂入。"""
    state = NovelState(
        novel_name="星河剑主", genre="玄幻",
        overall_outline="全书战略骨架……", total_chapters_written=25,
        volumes=[
            Volume(index=1, title="第一卷 · 少年入宗", chapter_start=1, planned_end=30,
                   summary="卷1主线", setup_for_next="血月教盯上主角", status="in_progress"),
            Volume(index=2, title="旧草稿卷", chapter_start=0, planned_end=0,
                   summary="旧草稿摘要待重生成", status="planning"),
        ],
    )
    result = prepare_volumes(state)

    assert result["review_type"] == "volumes"
    tp = result["task_prompt"]
    assert "第 2 卷" in tp                       # 下一卷 index（承接激活卷1）
    assert "第一卷 · 少年入宗" in tp             # 已激活卷节选
    assert "已写完 25 章" in tp                  # 当前进度
    assert "血月教盯上主角" in tp                # 上一卷卷尾钩
    assert "第 31 章开始" in tp                  # start = 激活卷 planned_end + 1
    assert "旧草稿摘要待重生成" not in tp        # 旧草稿本轮重生成、不喂入


# ── save_volumes 首次 ────────────────────────────────────────────────────────


def test_save_volumes_first_active_plus_drafts():
    """首次：激活卷 index=1 [1,chapters] in_progress + 草稿卷 planning（章号 0）。"""
    draft = _payload(_active("第一卷", "卷1主线", "埋卷2钩", 28),
                     [_draft("第二卷", "卷2向"), _draft("第三卷", "卷3向")])
    volumes = save_volumes(NovelState(current_draft=draft))["volumes"]

    assert [v.index for v in volumes] == [1, 2, 3]
    a = volumes[0]
    assert a.title == "第一卷" and a.chapter_start == 1 and a.planned_end == 28
    assert a.status == "in_progress" and a.actual_end is None
    for d in volumes[1:]:
        assert d.status == "planning" and d.chapter_start == 0 and d.planned_end == 0


def test_save_volumes_first_no_lookahead_single_volume():
    """LLM 只给激活卷（无草稿）：落库单卷 in_progress，等价旧单卷行为。"""
    volumes = save_volumes(NovelState(current_draft=_payload(_active(chapters=20))))["volumes"]
    assert len(volumes) == 1
    assert volumes[0].status == "in_progress" and volumes[0].planned_end == 20


def test_save_volumes_clamps_llm_overshoot():
    """LLM 激活卷章数超上限（无 human_confirmed）→ 夹到 VOLUME_MAX。"""
    v = save_volumes(NovelState(current_draft=_payload(_active(chapters=200))))["volumes"][0]
    assert v.planned_end == VOLUME_MAX_CHAPTERS   # 1 + 50 - 1


def test_save_volumes_clamps_llm_undershoot():
    v = save_volumes(NovelState(current_draft=_payload(_active(chapters=3))))["volumes"][0]
    assert v.planned_end == VOLUME_MIN_CHAPTERS


def test_save_volumes_human_override_bypasses_clamp():
    """human_confirmed=true（人工终裁）→ 尊重激活卷章数，不夹。"""
    draft = _payload(_active(chapters=80), human_confirmed=True)
    v = save_volumes(NovelState(current_draft=draft))["volumes"][0]
    assert v.planned_end == 80 and v.planned_end > VOLUME_MAX_CHAPTERS


# ── save_volumes 滚动：收口 + 丢旧草稿 + 冻结 ─────────────────────────────────


def test_save_volumes_rolling_closes_prev_and_activates_next():
    """滚动：上一激活卷收口 closed + 新激活卷承接章号 + 新草稿 planning。"""
    state = NovelState(
        total_chapters_written=28,
        volumes=[Volume(index=1, title="卷1", chapter_start=1, planned_end=30,
                        summary="s", setup_for_next="钩", status="in_progress")],
        current_draft=_payload(_active("第二卷", "卷2主线", "埋卷3钩", 25),
                               [_draft("第三卷", "卷3向")]),
    )
    volumes = save_volumes(state)["volumes"]

    assert [v.index for v in volumes] == [1, 2, 3]
    assert volumes[0].status == "closed" and volumes[0].actual_end == 30           # 收口
    assert volumes[1].status == "in_progress"
    assert volumes[1].chapter_start == 31 and volumes[1].planned_end == 55         # 31 + 25 - 1
    assert volumes[2].status == "planning" and volumes[2].planned_end == 0


def test_save_volumes_rolling_drops_stale_drafts_and_freezes_closed():
    """滚动丢弃旧 planning 草稿；已 closed 卷冻结不动、内容不被覆盖。"""
    state = NovelState(
        total_chapters_written=58,
        volumes=[
            Volume(index=1, title="卷1原", chapter_start=1, planned_end=30,
                   actual_end=30, status="closed"),
            Volume(index=2, title="卷2原", chapter_start=31, planned_end=60,
                   summary="s2", setup_for_next="钩2", status="in_progress"),
            Volume(index=3, title="卷3旧草稿", chapter_start=0, planned_end=0, status="planning"),
            Volume(index=4, title="卷4旧草稿", chapter_start=0, planned_end=0, status="planning"),
        ],
        current_draft=_payload(_active("卷3新", "n3", "钩3", 20),
                               [_draft("卷4新", "n4"), _draft("卷5新", "n5")]),
    )
    volumes = save_volumes(state)["volumes"]

    # 已激活卷 1(closed)/2(收口closed) 保留；旧草稿 3/4 丢弃；新激活卷3 + 新草稿4/5
    assert [v.index for v in volumes] == [1, 2, 3, 4, 5]
    assert volumes[0].title == "卷1原" and volumes[0].status == "closed"           # 冻结不动
    assert volumes[1].title == "卷2原" and volumes[1].status == "closed"           # 刚收口
    assert volumes[1].actual_end == 60
    assert volumes[2].title == "卷3新" and volumes[2].status == "in_progress"
    assert volumes[2].chapter_start == 61 and volumes[2].planned_end == 80         # 61 + 20 - 1
    assert [v.title for v in volumes[3:]] == ["卷4新", "卷5新"]
    assert all(v.status == "planning" and v.planned_end == 0 for v in volumes[3:])


def test_save_volumes_rolling_coerces_dict_volumes():
    """state.volumes 被 checkpoint 落成 dict → 归一后正常滚动。"""
    state = NovelState(
        total_chapters_written=28,
        volumes=[{"index": 1, "title": "卷1", "chapter_start": 1, "planned_end": 30,
                  "summary": "s", "setup_for_next": "钩", "status": "in_progress", "actual_end": None}],
        current_draft=_payload(_active("卷2", chapters=20)),
    )
    volumes = save_volumes(state)["volumes"]
    assert len(volumes) == 2 and volumes[1].chapter_start == 31


# ── save_volumes 兼容/容错 ───────────────────────────────────────────────────


def test_save_volumes_handles_code_fence():
    """```json 围栏 → repair_and_parse 剥掉，正常解析。"""
    inner = _payload(_active(chapters=25), [_draft()])
    volumes = save_volumes(NovelState(current_draft="```json\n" + inner + "\n```"))["volumes"]
    assert len(volumes) == 2


def test_save_volumes_accepts_bare_array():
    """LLM 偶尔直接吐裸数组（未包 volumes 键）→ 兼容解析。"""
    draft = json.dumps([_active(chapters=22), _draft()], ensure_ascii=False)
    volumes = save_volumes(NovelState(current_draft=draft))["volumes"]
    assert len(volumes) == 2 and volumes[0].planned_end == 22


def test_save_volumes_resets_review_fields():
    result = save_volumes(NovelState(current_draft=_payload(_active(chapters=25)), approved=True))
    assert result["current_draft"] == "" and result["approved"] is False


def test_save_volumes_rejects_invalid_json():
    with pytest.raises(ValueError, match="JSON 解析失败"):
        save_volumes(NovelState(current_draft="this is not json at all"))


def test_save_volumes_rejects_empty_volumes():
    with pytest.raises(ValueError, match="非空 volumes 数组"):
        save_volumes(NovelState(current_draft=json.dumps({"volumes": []})))


def test_save_volumes_rejects_active_missing_title():
    draft = _payload({"summary": "s", "setup_for_next": "钩", "chapters": 25})
    with pytest.raises(ValueError, match="激活卷缺 title"):
        save_volumes(NovelState(current_draft=draft))


def test_save_volumes_rejects_active_non_positive_chapters():
    with pytest.raises(ValueError, match="必须是正整数"):
        save_volumes(NovelState(current_draft=_payload(_active(chapters=0))))


def test_save_volumes_rejects_active_bool_chapters():
    """chapters=true（bool 是 int 子类，需显式排除）→ ValueError。"""
    draft = json.dumps(
        {"volumes": [{"title": "卷1", "summary": "s", "setup_for_next": "钩", "chapters": True}]},
        ensure_ascii=False,
    )
    with pytest.raises(ValueError, match="必须是正整数"):
        save_volumes(NovelState(current_draft=draft))


def test_save_volumes_rejects_draft_missing_title():
    """草稿卷缺 title → ValueError（指明第几项）。"""
    draft = _payload(_active(), [{"summary": "s", "setup_for_next": "钩"}])
    with pytest.raises(ValueError, match="草稿卷.*缺 title"):
        save_volumes(NovelState(current_draft=draft))


# ── route_after_save_volumes ─────────────────────────────────────────────────


def test_route_after_save_volumes_first_time_goes_to_character_cards():
    """首次分卷（尚未开写，written==0）→ 继续设定链 prepare_character_cards。"""
    assert route_after_save_volumes(NovelState(total_chapters_written=0)) == "prepare_character_cards"


def test_route_after_save_volumes_rolling_goes_to_chapter_plan():
    """滚动分卷（写作中，written>0）→ 展开新激活卷 prepare_chapter_plan。"""
    assert route_after_save_volumes(NovelState(total_chapters_written=30)) == "prepare_chapter_plan"
