"""nodes/volumes.py 单元测试（滚动生成卷架构）：

prepare_volumes 双模（首次仅规划卷1 / 滚动规划下一卷）、save_volumes 单卷解析 + 权威赋值
（planned_end 换算 / 章数松护栏 clamp / 滚动 append+上一卷收口）、route_after_save_volumes。
契约：current_draft 是**单个 JSON 对象**（不是数组），LLM 只出 title/summary/setup_for_next/chapters。
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


# ── prepare_volumes 双模 ─────────────────────────────────────────────────────


def test_prepare_volumes_first_mode_plans_volume_one():
    """首次（无 volumes）：task_prompt 是「只规划第一卷」的单卷对象契约。"""
    state = NovelState(
        novel_name="星河剑主",
        genre="玄幻",
        overall_outline="起：少年出山……承：卷入纷争……转：高潮……合：收束……",
    )
    result = prepare_volumes(state)

    assert result["review_type"] == "volumes"
    tp = result["task_prompt"]
    assert "第一卷" in tp
    assert "JSON 对象" in tp          # 单卷对象契约
    assert "chapters" in tp
    assert "只规划第一卷" in tp        # 单卷（不是整书一次抽完）
    assert "少年出山" in tp           # 大纲被注入
    assert result["current_draft"] == ""
    assert result["approved"] is False


def test_prepare_volumes_rolling_mode_plans_next_volume():
    """滚动（已有卷）：task_prompt 是「规划下一卷」，含已有卷节选 + 进度 + 上一卷卷尾钩 + 下一卷起始章号。"""
    state = NovelState(
        novel_name="星河剑主",
        genre="玄幻",
        overall_outline="全书战略骨架……",
        total_chapters_written=25,
        volumes=[
            Volume(index=1, title="第一卷 · 少年入宗", chapter_start=1, planned_end=30,
                   summary="卷1主线", setup_for_next="血月教盯上主角", status="in_progress"),
        ],
    )
    result = prepare_volumes(state)

    assert result["review_type"] == "volumes"
    tp = result["task_prompt"]
    assert "第 2 卷" in tp                    # 规划下一卷
    assert "第一卷 · 少年入宗" in tp          # 已有卷节选
    assert "已写完 25 章" in tp               # 当前进度
    assert "血月教盯上主角" in tp             # 上一卷卷尾钩
    assert "第 31 章开始" in tp               # 下一卷起始章号（prev.planned_end + 1）


# ── save_volumes 首次 ────────────────────────────────────────────────────────


def _obj(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def test_save_volumes_first_volume_authoritative_fields():
    """首次单卷对象 → 卷1：index=1 / chapter_start=1 / planned_end=chapters / in_progress。"""
    draft = _obj(title="第一卷 · 少年入宗", summary="卷1主线", setup_for_next="埋卷2钩", chapters=28)
    result = save_volumes(NovelState(current_draft=draft))

    volumes = result["volumes"]
    assert len(volumes) == 1
    v = volumes[0]
    assert v.index == 1
    assert v.title == "第一卷 · 少年入宗"
    assert v.chapter_start == 1
    assert v.planned_end == 28          # chapter_start(1) + chapters(28) - 1
    assert v.status == "in_progress"
    assert v.actual_end is None


def test_save_volumes_clamps_llm_overshoot():
    """LLM 自主输出章数超上限（无 planned_end 标记）→ 夹到 VOLUME_MAX。"""
    draft = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=200)
    result = save_volumes(NovelState(current_draft=draft))
    v = result["volumes"][0]
    assert v.planned_end == VOLUME_MAX_CHAPTERS   # 1 + 50 - 1 = 50


def test_save_volumes_clamps_llm_undershoot():
    """LLM 自主输出章数低于下限 → 夹到 VOLUME_MIN。"""
    draft = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=3)
    result = save_volumes(NovelState(current_draft=draft))
    v = result["volumes"][0]
    assert v.planned_end == VOLUME_MIN_CHAPTERS   # 1 + 15 - 1 = 15


def test_save_volumes_human_override_bypasses_clamp():
    """人工在表单突破护栏（草稿带 human_confirmed 标记）→ 尊重其章数，不夹。"""
    # human_confirmed=true 即视为人工终裁；章数 80 超过 MAX 也予以尊重
    draft = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=80, human_confirmed=True)
    result = save_volumes(NovelState(current_draft=draft))
    v = result["volumes"][0]
    assert v.planned_end == 80          # 未夹（chapter_start=1 + 80 - 1）
    assert v.planned_end > VOLUME_MAX_CHAPTERS


# ── save_volumes 滚动 append + 上一卷收口 ─────────────────────────────────────


def test_save_volumes_rolling_appends_and_closes_prev():
    """滚动：上一卷收口（actual_end=planned_end, closed）+ append 新卷（承接章号）。"""
    state = NovelState(
        total_chapters_written=28,
        volumes=[
            Volume(index=1, title="卷1", chapter_start=1, planned_end=30,
                   summary="卷1主线", setup_for_next="钩", status="in_progress"),
        ],
        current_draft=_obj(title="第二卷", summary="卷2主线", setup_for_next="埋卷3钩", chapters=25),
    )
    result = save_volumes(state)
    volumes = result["volumes"]

    assert len(volumes) == 2
    prev, new = volumes[0], volumes[1]
    # 上一卷收口
    assert prev.index == 1
    assert prev.actual_end == 30
    assert prev.status == "closed"
    # 新卷承接
    assert new.index == 2
    assert new.chapter_start == 31          # 上一卷 planned_end + 1
    assert new.planned_end == 55            # 31 + 25 - 1
    assert new.status == "in_progress"
    assert new.actual_end is None


def test_save_volumes_rolling_coerces_dict_volumes():
    """state.volumes 若被 checkpoint 落成 dict（缺 planned_end 走默认 0 会报错，这里给全）→ 归一后正常滚动。"""
    state = NovelState(
        total_chapters_written=28,
        volumes=[
            {"index": 1, "title": "卷1", "chapter_start": 1, "planned_end": 30,
             "summary": "s", "setup_for_next": "钩", "status": "in_progress", "actual_end": None},
        ],
        current_draft=_obj(title="卷2", summary="s2", setup_for_next="", chapters=20),
    )
    result = save_volumes(state)
    assert len(result["volumes"]) == 2
    assert result["volumes"][1].chapter_start == 31


# ── save_volumes 兜底/容错 ───────────────────────────────────────────────────


def test_save_volumes_handles_code_fence():
    """LLM 加 ```json 围栏 → repair_and_parse 剥掉，正常解析单卷对象。"""
    inner = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=25)
    state = NovelState(current_draft="```json\n" + inner + "\n```")
    result = save_volumes(state)
    assert len(result["volumes"]) == 1


def test_save_volumes_resets_review_fields():
    """save 后清空桥接字段。"""
    draft = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=25)
    result = save_volumes(NovelState(current_draft=draft, approved=True))
    assert result["current_draft"] == ""
    assert result["approved"] is False


def test_save_volumes_rejects_invalid_json():
    """根本不是 JSON → ValueError。"""
    with pytest.raises(ValueError, match="JSON 解析失败"):
        save_volumes(NovelState(current_draft="this is not json at all"))


def test_save_volumes_rejects_missing_title():
    """缺 title → ValueError。"""
    draft = _obj(summary="s", setup_for_next="钩", chapters=25)
    with pytest.raises(ValueError, match="缺 title"):
        save_volumes(NovelState(current_draft=draft))


def test_save_volumes_rejects_non_positive_chapters():
    """chapters 非正整数 → ValueError。"""
    draft = _obj(title="卷1", summary="s", setup_for_next="钩", chapters=0)
    with pytest.raises(ValueError, match="必须是正整数"):
        save_volumes(NovelState(current_draft=draft))


def test_save_volumes_rejects_bool_chapters():
    """chapters=true（bool 是 int 子类，需显式排除）→ ValueError。"""
    # json.dumps(True) → "true"，构造带 bool 的对象
    draft = json.dumps({"title": "卷1", "summary": "s", "setup_for_next": "钩", "chapters": True},
                       ensure_ascii=False)
    with pytest.raises(ValueError, match="必须是正整数"):
        save_volumes(NovelState(current_draft=draft))


# ── route_after_save_volumes ─────────────────────────────────────────────────


def test_route_after_save_volumes_first_time_goes_to_character_cards():
    """首次分卷（尚未开写，written==0）→ 继续设定链 prepare_character_cards。"""
    state = NovelState(total_chapters_written=0)
    assert route_after_save_volumes(state) == "prepare_character_cards"


def test_route_after_save_volumes_rolling_goes_to_chapter_plan():
    """滚动分卷（写作中，written>0）→ 展开新卷 prepare_chapter_plan。"""
    state = NovelState(total_chapters_written=30)
    assert route_after_save_volumes(state) == "prepare_chapter_plan"
