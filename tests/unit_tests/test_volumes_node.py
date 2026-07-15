"""nodes/volumes.py 单元测试：prepare_volumes / save_volumes 快乐路径 + 校验失败路径。"""

from __future__ import annotations

import json

import pytest

from noval_workflow.nodes.volumes import prepare_volumes, save_volumes
from noval_workflow.state import NovelState


# ── prepare_volumes ─────────────────────────────────────────────────────────


def test_prepare_volumes_assembles_task_prompt_and_review_type():
    """prepare 节点必须写 review_type='volumes'，task_prompt 含硬约束和示例。"""
    state = NovelState(
        novel_name="星河剑主",
        genre="玄幻",
        overall_outline="# 第一卷 少年入宗\n主角出山……\n# 第二卷 内门风云\n宗门斗争……",
    )
    result = prepare_volumes(state)

    assert result["review_type"] == "volumes"
    assert "system_context" in result
    assert "task_prompt" in result
    # 提示词含硬约束段 + JSON 数组示例（校验 volumes_prompt 挂进来了）
    tp = result["task_prompt"]
    assert "硬约束" in tp
    assert "JSON 数组" in tp
    assert "chapter_start" in tp
    assert "target_min" in tp
    assert "target_max" in tp
    # 输入大纲应被注入
    assert "少年入宗" in tp
    # reset_review_fields 应清桥接字段
    assert result["current_draft"] == ""
    assert result["approved"] is False


# ── save_volumes 快乐路径 ────────────────────────────────────────────────────


def _valid_four_volumes_json() -> str:
    """典型 4 卷合规 JSON——章号顺次拼接 1 → 29 → 74 → 124。"""
    return json.dumps([
        {"index": 1, "title": "第一卷 · 少年入宗", "summary": "卷1主线", "setup_for_next": "埋卷2钩",
         "chapter_start": 1, "target_min": 22, "target_max": 28},
        {"index": 2, "title": "第二卷 · 内门风云", "summary": "卷2主线", "setup_for_next": "埋卷3钩",
         "chapter_start": 29, "target_min": 35, "target_max": 45},
        {"index": 3, "title": "第三卷 · 远征异域", "summary": "卷3主线", "setup_for_next": "埋卷4钩",
         "chapter_start": 74, "target_min": 40, "target_max": 50},
        {"index": 4, "title": "第四卷 · 剑指九霄", "summary": "卷4主线", "setup_for_next": "",
         "chapter_start": 124, "target_min": 42, "target_max": 52},
    ], ensure_ascii=False)


def test_save_volumes_happy_path_four_volumes():
    """4 卷合规 JSON → 4 个 Volume 实例 + 第一卷 in_progress 其余 planning。"""
    state = NovelState(current_draft=_valid_four_volumes_json())
    result = save_volumes(state)

    volumes = result["volumes"]
    assert len(volumes) == 4
    assert volumes[0].index == 1
    assert volumes[0].title == "第一卷 · 少年入宗"
    assert volumes[0].chapter_start == 1
    assert volumes[0].target_min == 22
    assert volumes[0].target_max == 28
    assert volumes[0].actual_end is None
    # 第一卷 in_progress，其余 planning
    assert volumes[0].status == "in_progress"
    assert all(v.status == "planning" for v in volumes[1:])
    # 拼接约束通过
    assert volumes[1].chapter_start == 29
    assert volumes[2].chapter_start == 74
    assert volumes[3].chapter_start == 124


def test_save_volumes_handles_dirty_json_with_code_fence():
    """LLM 有时会加 ```json 围栏——repair_and_parse 会剥掉，节点应正常处理。"""
    dirty = "```json\n" + _valid_four_volumes_json() + "\n```"
    state = NovelState(current_draft=dirty)
    result = save_volumes(state)
    assert len(result["volumes"]) == 4


def test_save_volumes_resets_review_fields():
    """save 后应清空桥接字段（与 chapter_plan / entity 一致）。"""
    state = NovelState(current_draft=_valid_four_volumes_json(), approved=True)
    result = save_volumes(state)
    assert result["current_draft"] == ""
    assert result["approved"] is False


# ── save_volumes 校验失败路径 ────────────────────────────────────────────────


def test_save_volumes_rejects_empty_array():
    """空数组 → ValueError（至少 1 卷）。"""
    state = NovelState(current_draft="[]")
    with pytest.raises(ValueError, match="至少需要 1 卷"):
        save_volumes(state)


def test_save_volumes_rejects_missing_required_field():
    """字段缺失（漏 index/title 这些无默认字段）→ ValueError（Volume(**item) 抛 TypeError → 转 ValueError）。"""
    bad = json.dumps([{"title": "卷1", "summary": "s", "setup_for_next": "",
                       "chapter_start": 1, "target_min": 20, "target_max": 25}], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="字段不符"):
        save_volumes(state)


def test_save_volumes_rejects_extra_field():
    """LLM 多输出未知字段（如 status/actual_end）→ Volume(**item) 抛 TypeError → 转 ValueError。

    严格 dataclass 约束：LLM 只能输出 7 个约定字段，status/actual_end 由后端管理。
    """
    bad = json.dumps([{"index": 1, "title": "卷1", "summary": "s", "setup_for_next": "",
                       "chapter_start": 1, "target_min": 20, "target_max": 25,
                       "unknown_field": "x"}], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="字段不符"):
        save_volumes(state)


def test_save_volumes_rejects_min_greater_than_max():
    """target_min > target_max → ValueError。"""
    bad = json.dumps([{"index": 1, "title": "卷1", "summary": "s", "setup_for_next": "",
                       "chapter_start": 1, "target_min": 30, "target_max": 20}], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="target_min=30 > target_max=20"):
        save_volumes(state)


def test_save_volumes_rejects_non_positive_target():
    """target 非正数 → ValueError。"""
    bad = json.dumps([{"index": 1, "title": "卷1", "summary": "s", "setup_for_next": "",
                       "chapter_start": 1, "target_min": 0, "target_max": 20}], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="必须 > 0"):
        save_volumes(state)


def test_save_volumes_rejects_broken_chapter_start_chain():
    """chapter_start 不接续（卷 2 应该是 29，但填了 30）→ ValueError。"""
    bad = json.dumps([
        {"index": 1, "title": "卷1", "summary": "s", "setup_for_next": "钩",
         "chapter_start": 1, "target_min": 22, "target_max": 28},
        {"index": 2, "title": "卷2", "summary": "s", "setup_for_next": "",
         "chapter_start": 30, "target_min": 35, "target_max": 40},  # 应 29 不是 30
    ], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="chapter_start=30 与期望 29 不符"):
        save_volumes(state)


def test_save_volumes_rejects_non_sequential_index():
    """index 不 1-based 顺次（第 2 项 index=3）→ ValueError。"""
    bad = json.dumps([
        {"index": 1, "title": "卷1", "summary": "s", "setup_for_next": "钩",
         "chapter_start": 1, "target_min": 22, "target_max": 28},
        {"index": 3, "title": "卷2", "summary": "s", "setup_for_next": "",
         "chapter_start": 29, "target_min": 35, "target_max": 40},
    ], ensure_ascii=False)
    state = NovelState(current_draft=bad)
    with pytest.raises(ValueError, match="index=3.*期望 2"):
        save_volumes(state)


def test_save_volumes_rejects_invalid_json():
    """LLM 输出根本不是数组 → ValueError（走 JsonParseError 转 ValueError）。"""
    state = NovelState(current_draft="this is not json at all really")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        save_volumes(state)


def test_save_volumes_single_volume_ok():
    """1 卷合规也应通过（边界 case）。"""
    single = json.dumps([{"index": 1, "title": "唯一卷", "summary": "全书就一卷",
                          "setup_for_next": "", "chapter_start": 1,
                          "target_min": 30, "target_max": 40}], ensure_ascii=False)
    state = NovelState(current_draft=single)
    result = save_volumes(state)
    assert len(result["volumes"]) == 1
    assert result["volumes"][0].status == "in_progress"
