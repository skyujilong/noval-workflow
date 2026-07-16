"""次要角色「提升为重要角色」sidecar 端点测试（Part 2）。

mock 掉 lg client（get_state/update_state）与 get_llm，用 Starlette TestClient 打两个端点，
验证：draft 生成补丁、apply 落库、以及各 fail-loud 分支（卡不存在/非次要角色/role 非法）。
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import http_app


class _FakeThreads:
    """假 threads 端：get_state 回固定 values，update_state 捕获写入供断言。"""

    def __init__(self, values: dict):
        self._values = values
        self.updated: dict | None = None

    async def get_state(self, thread_id: str):
        return {"values": self._values}

    async def update_state(self, thread_id: str, values: dict | None = None):
        self.updated = values
        return {"ok": True}


class _FakeClient:
    def __init__(self, values: dict):
        self.threads = _FakeThreads(values)


class _FakeMsg:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _prompt):
        return _FakeMsg(self._content)


def _base_values() -> dict:
    """一份含全书 canon + 一张次要角色卡的最小 values。"""
    return {
        "world_building": "近未来废土都市",
        "power_system": "能级 E→S 五阶",
        "has_power_system": True,
        "core_conflicts": "幸存者 vs 议会",
        "overall_outline": "四卷：入城→揭秘→反抗→终局",
        "volumes": [{"index": 1, "title": "入城", "summary": "初入废土"}],
        "entity_cards": [
            {
                "name": "周衡",
                "type": "人物",
                "aliases": [],
                "summary": "议会文职",
                "first_appear_chapter": 3,
                "role": "次要角色",
                "appearance": "中年清瘦",
                "speech_style": "",
                "personality": "圆滑",
                "abilities": "",
                "hidden_persona": "",
                "arc_trajectory": "",
                "ability_contract": "",
                "motivation": "自保",
                "current_state": "",
                "relations": "主角旧识",
            },
            {"name": "灵剑", "type": "装备", "aliases": [], "summary": "上古凶兵"},
        ],
    }


@pytest.fixture
def patched(monkeypatch):
    """装好假 client + 假 llm，返回 (TestClient, fake_client) 供断言 update 写入。"""
    fake_client = _FakeClient(_base_values())
    monkeypatch.setattr(http_app, "_get_lg_client", lambda: fake_client)

    draft_json = json.dumps(
        {
            "role": "功能性反派",
            "appearance": "四十岁上下，清瘦，惯穿灰呢西装，右手戴旧铜戒",
            "hidden_persona": "暗中记录议会克扣账目，握有把柄",
            "arc_trajectory": "卷一伏低→卷四反噬议会",
            "ability_contract": "初始 D 级文书权限；隐藏杀手锏：调动档案封锁令，反噬为暴露即除名",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr("noval_workflow.llm.get_llm", lambda **kw: _FakeLLM(draft_json))
    return TestClient(http_app.Starlette(routes=http_app.routes)), fake_client


def test_draft_ok(patched):
    client, _ = patched
    resp = client.post(
        "/character/promote/draft",
        json={"thread_id": "t1", "name": "周衡", "target_role": "功能性反派"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 只含 5 键、role 强制目标值、深层字段来自 LLM
    assert set(data["patch"]) == {"role", "appearance", "hidden_persona", "arc_trajectory", "ability_contract"}
    assert data["patch"]["role"] == "功能性反派"
    assert "把柄" in data["patch"]["hidden_persona"]
    assert data["current"]["name"] == "周衡"


def test_draft_reject_non_minor(patched):
    client, fake = patched
    fake.threads._values["entity_cards"][0]["role"] = "主角"  # 主角不可提升
    resp = client.post(
        "/character/promote/draft",
        json={"thread_id": "t1", "name": "周衡", "target_role": "功能性反派"},
    )
    assert resp.status_code == 400
    assert "次要角色" in resp.json()["error"]


def test_draft_reject_bad_role(patched):
    client, _ = patched
    resp = client.post(
        "/character/promote/draft",
        json={"thread_id": "t1", "name": "周衡", "target_role": "主角"},
    )
    assert resp.status_code == 400  # 主角不在 PROMOTABLE_ROLES


def test_draft_card_not_found(patched):
    client, _ = patched
    resp = client.post(
        "/character/promote/draft",
        json={"thread_id": "t1", "name": "查无此人", "target_role": "功能性反派"},
    )
    assert resp.status_code == 404


def test_apply_ok_writes_card(patched):
    client, fake = patched
    patch = {
        "role": "功能性反派",
        "appearance": "四十岁清瘦，灰呢西装",
        "hidden_persona": "握有议会把柄",
        "arc_trajectory": "卷一伏低→卷四反噬",
        "ability_contract": "初始 D 级；杀手锏：档案封锁令",
    }
    resp = client.post(
        "/character/promote/apply",
        json={"thread_id": "t1", "name": "周衡", "patch": patch},
    )
    assert resp.status_code == 200, resp.text
    # update_state 收到全量 entity_cards，目标卡已升级、其余卡不动、非提升字段保留
    written = fake.threads.updated["entity_cards"]
    zhou = next(c for c in written if c["name"] == "周衡")
    assert zhou["role"] == "功能性反派"
    assert zhou["hidden_persona"] == "握有议会把柄"
    assert zhou["personality"] == "圆滑"  # 非提升字段原样保留
    assert zhou["motivation"] == "自保"
    assert any(c["name"] == "灵剑" for c in written)  # 其余卡还在


def test_apply_reject_bad_role(patched):
    client, fake = patched
    resp = client.post(
        "/character/promote/apply",
        json={"thread_id": "t1", "name": "周衡", "patch": {"role": "次要角色"}},
    )
    assert resp.status_code == 400  # 目标 role 必须是可提升角色之一
    assert fake.threads.updated is None  # 未落库
