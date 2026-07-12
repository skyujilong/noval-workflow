"""提示词自进化的中央存储边界（SQLite）。

两张表：
- evolution_events：每本小说的进化事件台账（提炼→应用→还原），用于全量挖掘、
  历史视图与「应用前快照」还原。
- directive_library：按条的可复用整改条目（打题材标签、记来源），供跨小说宽范围
  挑选导入。

与 prompts/overrides.py（每本小说 prompt_overrides.json）职责分离：overrides.json 是
图节点实际读取的「当前有效覆盖」；本库只被 http_app 侧信道与离线脚本读写，图节点不碰，
故 hot path 零改动。DB 路径默认 ./data/prompt_evolution.db（相对 langgraph dev 启动
cwd），可用环境变量 PROMPT_EVOLUTION_DB 覆盖。

这是唯一的存储边界：将来若改用 Postgres / 向量库，只需替换本文件实现。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Sequence

# ── 领域模型 ─────────────────────────────────────────────────────────────────


class EventTrigger(str, Enum):
    """进化事件的触发来源。"""

    MANUAL = "manual"  # 用户在抽屉里手动提炼
    REJECT = "reject"  # 由人工打回自动捕获（预留）
    IMPORT = "import"  # 从整改库导入条目
    RECONCILE = "reconcile"  # 整理消解：把累积整改全量 reconcile 成自洽版本（REPLACE）


class EventStatus(str, Enum):
    """进化事件的生命周期状态。"""

    PROPOSED = "proposed"  # 已提炼出候选，尚未应用
    APPLIED = "applied"  # 已写入该小说 overrides
    REVERTED = "reverted"  # 已还原到应用前快照


class ProposalOp(str, Enum):
    """单条整改提案对目标字段的操作方式。"""

    APPEND = "append"  # 追加到字段末尾
    REPLACE = "replace"  # 整体替换字段


@dataclass(frozen=True)
class Proposal:
    """LLM 提炼出的单条整改提案。field 为 GenreFlavor 字段名。

    applies_to:整改分发目标——除了 field 主字段外,还想把这条整改同步写到哪些桶。
    典型场景:用户在 chapter review 里提炼出「打脸四拍必须齐全」,这条对 scene_beats 也适用,
    apply 时显式勾选 also_apply_to=[scene_beats],让一条整改一次分发到多桶。
    空 tuple = 只写主 field(默认,严格隔离)。取值必须是 evolved_directives_{chapter|arc_outline|scene_beats}。
    """

    field: str
    text: str
    op: ProposalOp = ProposalOp.APPEND
    rationale: str = ""
    conflicts_with: str = ""  # 非空＝与既有规则冲突，text 已措辞成显式覆盖
    applies_to: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvolutionEvent:
    """一次进化事件的完整台账记录。id/created_at 为空时由 add_event 落库时补齐。"""

    novel_name: str
    genre: str
    trigger: EventTrigger
    review_type: str = "chapter"
    chapter_index: int | None = None
    source_feedback: str = ""
    rejected_excerpt: str = ""
    proposals: tuple[Proposal, ...] = ()
    status: EventStatus = EventStatus.PROPOSED
    applied: dict[str, str] = field(default_factory=dict)
    prompt_before: dict[str, str] = field(default_factory=dict)
    applied_at: str | None = None
    reverted_at: str | None = None
    id: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class DirectiveItem:
    """整改库里的一条可复用原子条目。id/created_at 为空时由 add_directives 落库时补齐。"""

    genre: str
    title: str
    text: str
    tags: tuple[str, ...] = ()
    source_novel: str = ""
    source_event_id: str = ""
    source_feedback: str = ""
    active: bool = True
    usage_count: int = 0
    id: str = ""
    created_at: str = ""


class EvolutionEventNotFound(LookupError):
    """按 id 找不到进化事件。"""


# ── 连接与建表 ───────────────────────────────────────────────────────────────

_DEFAULT_DB = "./data/prompt_evolution.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_events (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    novel_name      TEXT NOT NULL,
    genre           TEXT NOT NULL DEFAULT '',
    trigger         TEXT NOT NULL,
    review_type     TEXT NOT NULL DEFAULT 'chapter',
    chapter_index   INTEGER,
    source_feedback TEXT NOT NULL DEFAULT '',
    rejected_excerpt TEXT NOT NULL DEFAULT '',
    proposals       TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'proposed',
    applied         TEXT NOT NULL DEFAULT '{}',
    prompt_before   TEXT NOT NULL DEFAULT '{}',
    applied_at      TEXT,
    reverted_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_novel ON evolution_events(novel_name);
CREATE INDEX IF NOT EXISTS idx_events_genre ON evolution_events(genre);

CREATE TABLE IF NOT EXISTS directive_library (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    genre           TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    source_novel    TEXT NOT NULL DEFAULT '',
    source_event_id TEXT NOT NULL DEFAULT '',
    source_feedback TEXT NOT NULL DEFAULT '',
    active          INTEGER NOT NULL DEFAULT 1,
    usage_count     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dir_genre ON directive_library(genre);
CREATE INDEX IF NOT EXISTS idx_dir_active ON directive_library(active);
"""


def _db_path() -> Path:
    return Path(os.environ.get("PROMPT_EVOLUTION_DB", _DEFAULT_DB))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """短生命周期连接：建目录、开 WAL、设 busy_timeout、幂等建表。

    每次调用新开连接（配合 asyncio.to_thread 的一线程一调用），故 check_same_thread
    默认值即安全。
    """
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """显式建库/建表（幂等）。正常路径由 _connect 自动完成，此函数供启动/测试预热。"""
    with _connect():
        pass


# ── 行 ↔ 领域模型 ────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proposals_to_json(proposals: Sequence[Proposal]) -> str:
    return json.dumps(
        [
            {
                "field": p.field,
                "text": p.text,
                "op": p.op.value,
                "rationale": p.rationale,
                "conflicts_with": p.conflicts_with,
                "applies_to": list(p.applies_to),
            }
            for p in proposals
        ],
        ensure_ascii=False,
    )


def _event_to_row(ev: EvolutionEvent) -> dict[str, object]:
    return {
        "id": ev.id,
        "created_at": ev.created_at,
        "novel_name": ev.novel_name,
        "genre": ev.genre,
        "trigger": ev.trigger.value,
        "review_type": ev.review_type,
        "chapter_index": ev.chapter_index,
        "source_feedback": ev.source_feedback,
        "rejected_excerpt": ev.rejected_excerpt,
        "proposals": _proposals_to_json(ev.proposals),
        "status": ev.status.value,
        "applied": json.dumps(ev.applied, ensure_ascii=False),
        "prompt_before": json.dumps(ev.prompt_before, ensure_ascii=False),
        "applied_at": ev.applied_at,
        "reverted_at": ev.reverted_at,
    }


def _row_to_event(row: sqlite3.Row) -> EvolutionEvent:
    proposals = tuple(
        Proposal(
            field=p.get("field", ""),
            text=p.get("text", ""),
            op=ProposalOp(p.get("op", "append")),
            rationale=p.get("rationale", ""),
            conflicts_with=p.get("conflicts_with", ""),
            applies_to=tuple(p.get("applies_to", []) or []),
        )
        for p in json.loads(row["proposals"] or "[]")
    )
    return EvolutionEvent(
        id=row["id"],
        created_at=row["created_at"],
        novel_name=row["novel_name"],
        genre=row["genre"],
        trigger=EventTrigger(row["trigger"]),
        review_type=row["review_type"],
        chapter_index=row["chapter_index"],
        source_feedback=row["source_feedback"],
        rejected_excerpt=row["rejected_excerpt"],
        proposals=proposals,
        status=EventStatus(row["status"]),
        applied=json.loads(row["applied"] or "{}"),
        prompt_before=json.loads(row["prompt_before"] or "{}"),
        applied_at=row["applied_at"],
        reverted_at=row["reverted_at"],
    )


def _directive_to_row(d: DirectiveItem) -> dict[str, object]:
    return {
        "id": d.id,
        "created_at": d.created_at,
        "genre": d.genre,
        "title": d.title,
        "text": d.text,
        "tags": json.dumps(list(d.tags), ensure_ascii=False),
        "source_novel": d.source_novel,
        "source_event_id": d.source_event_id,
        "source_feedback": d.source_feedback,
        "active": 1 if d.active else 0,
        "usage_count": d.usage_count,
    }


def _row_to_directive(row: sqlite3.Row) -> DirectiveItem:
    return DirectiveItem(
        id=row["id"],
        created_at=row["created_at"],
        genre=row["genre"],
        title=row["title"],
        text=row["text"],
        tags=tuple(json.loads(row["tags"] or "[]")),
        source_novel=row["source_novel"],
        source_event_id=row["source_event_id"],
        source_feedback=row["source_feedback"],
        active=bool(row["active"]),
        usage_count=row["usage_count"],
    )


# ── 事件 CRUD ────────────────────────────────────────────────────────────────


def add_event(event: EvolutionEvent) -> EvolutionEvent:
    """落库一条进化事件；id/created_at 为空时自动补齐，返回已落库记录。"""
    stamped = replace(
        event,
        id=event.id or f"ev_{uuid.uuid4().hex}",
        created_at=event.created_at or _now(),
    )
    row = _event_to_row(stamped)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row)
    with _connect() as conn, conn:
        conn.execute(
            f"INSERT INTO evolution_events ({cols}) VALUES ({placeholders})", row
        )
    return stamped


def get_events(novel_name: str) -> list[EvolutionEvent]:
    """按小说列出进化事件，最新在前。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evolution_events WHERE novel_name = ? ORDER BY created_at DESC",
            (novel_name,),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def get_event(event_id: str) -> EvolutionEvent:
    """按 id 取事件；不存在则抛 EvolutionEventNotFound。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM evolution_events WHERE id = ?", (event_id,)
        ).fetchone()
    if row is None:
        raise EvolutionEventNotFound(event_id)
    return _row_to_event(row)


def update_event(event_id: str, **patch: object) -> EvolutionEvent:
    """更新事件的部分列（枚举/JSON 字段自动序列化），返回更新后的事件。

    仅接受 EvolutionEvent 的已知可变字段，未知键抛 KeyError（避免静默拼错列名）。
    """
    if not patch:
        return get_event(event_id)
    updatable = {
        "status",
        "applied",
        "prompt_before",
        "applied_at",
        "reverted_at",
        "proposals",
    }
    unknown = set(patch) - updatable
    if unknown:
        raise KeyError(f"update_event 不支持的字段: {sorted(unknown)}")

    values: dict[str, object] = {}
    for key, val in patch.items():
        if key == "proposals":
            values[key] = _proposals_to_json(val)  # type: ignore[arg-type]
        elif isinstance(val, Enum):
            values[key] = val.value
        elif key in {"applied", "prompt_before"}:
            values[key] = json.dumps(val, ensure_ascii=False)
        else:
            values[key] = val
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    values["_id"] = event_id
    with _connect() as conn, conn:
        cur = conn.execute(
            f"UPDATE evolution_events SET {assignments} WHERE id = :_id", values
        )
        if cur.rowcount == 0:
            raise EvolutionEventNotFound(event_id)
    return get_event(event_id)


# ── 整改库 CRUD / 查询 ───────────────────────────────────────────────────────


def add_directives(items: Sequence[DirectiveItem]) -> list[DirectiveItem]:
    """批量落库整改条目；每条 id/created_at 为空时自动补齐，返回已落库记录。"""
    stamped = [
        replace(
            it,
            id=it.id or f"dir_{uuid.uuid4().hex}",
            created_at=it.created_at or _now(),
        )
        for it in items
    ]
    if not stamped:
        return []
    rows = [_directive_to_row(it) for it in stamped]
    cols = ", ".join(rows[0].keys())
    placeholders = ", ".join(f":{k}" for k in rows[0])
    with _connect() as conn, conn:
        conn.executemany(
            f"INSERT INTO directive_library ({cols}) VALUES ({placeholders})", rows
        )
    return stamped


def query_directives(
    genre: str | None = None,
    q: str | None = None,
    active: bool = True,
    limit: int = 500,
) -> list[DirectiveItem]:
    """查询整改库。genre=None 表示不按题材过滤（放宽到全部）；q 对标题/正文模糊匹配。"""
    clauses: list[str] = []
    params: list[object] = []
    if active:
        clauses.append("active = 1")
    if genre:
        clauses.append("genre = ?")
        params.append(genre)
    if q:
        clauses.append("(title LIKE ? OR text LIKE ?)")
        like = f"%{q}%"
        params.extend((like, like))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM directive_library {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_directive(r) for r in rows]


def get_directives(ids: Sequence[str]) -> list[DirectiveItem]:
    """按 id 批量取条目（保持输入顺序，缺失的 id 静默跳过）。"""
    id_list = list(ids)
    if not id_list:
        return []
    placeholders = ", ".join("?" for _ in id_list)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM directive_library WHERE id IN ({placeholders})", id_list
        ).fetchall()
    by_id = {r["id"]: _row_to_directive(r) for r in rows}
    return [by_id[i] for i in id_list if i in by_id]


def bump_usage(ids: Sequence[str]) -> None:
    """给一批条目的 usage_count +1（导入时调用）。"""
    id_list = list(ids)
    if not id_list:
        return
    placeholders = ", ".join("?" for _ in id_list)
    with _connect() as conn, conn:
        conn.execute(
            f"UPDATE directive_library SET usage_count = usage_count + 1 "
            f"WHERE id IN ({placeholders})",
            id_list,
        )
