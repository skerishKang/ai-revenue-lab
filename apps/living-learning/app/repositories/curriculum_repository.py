"""Curriculum repository for Living Learning."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.models import Curriculum


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class CurriculumRecord:
    id: str
    topic: str
    version: str
    description: str
    concepts: list[str]
    created_at: str


def _row_to_record(row: sqlite3.Row) -> CurriculumRecord:
    return CurriculumRecord(
        id=row["id"],
        topic=row["topic"],
        version=row["version"],
        description=row["description"],
        concepts=json.loads(row["concepts"]) if row["concepts"] else [],
        created_at=row["created_at"],
    )


_COLS = ["id", "topic", "version", "description", "concepts", "created_at"]
_SELECT = ", ".join(_COLS)


def create_curriculum(
    conn: sqlite3.Connection,
    *,
    topic: str,
    version: str = "1.0",
    description: str = "",
    concepts: list[str] | None = None,
    commit: bool = True,
) -> CurriculumRecord:
    now = _utcnow()
    import hashlib
    # topic/version을 정규화한 deterministic curriculum key
    topic_norm = topic.strip().lower()
    version_norm = version.strip().lower()
    key = f"{topic_norm}:{version_norm}".encode("utf-8")
    curriculum_id = f"curr_{hashlib.md5(key).hexdigest()}"

    concepts = concepts or []

    # Check if exists to reuse
    existing = get_curriculum_by_id(conn, curriculum_id)
    if existing:
        return existing

    conn.execute(
        f"INSERT INTO curricula ({_SELECT}) VALUES (?,?,?,?,?,?)",
        (curriculum_id, topic, version, description, json.dumps(concepts), now),
    )
    if commit:
        conn.commit()
    return get_curriculum_by_id(conn, curriculum_id)  # type: ignore[return-value]


def get_curriculum_by_id(conn: sqlite3.Connection, curriculum_id: str) -> CurriculumRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM curricula WHERE id = ?", (curriculum_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_curricula_by_topic(conn: sqlite3.Connection, topic: str) -> list[CurriculumRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM curricula WHERE topic = ?", (topic,)
    ).fetchall()
    return [_row_to_record(r) for r in rows]
