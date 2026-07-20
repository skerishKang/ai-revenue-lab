"""Idempotency repository for Living Learning."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class IdempotencyRecord:
    key_value: str
    lesson_id: str
    result: str
    created_at: str


def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        key_value=row["key_value"],
        lesson_id=row["lesson_id"],
        result=row["result"],
        created_at=row["created_at"],
    )


def check_idempotency_key(conn: sqlite3.Connection, key_value: str) -> IdempotencyRecord | None:
    row = conn.execute(
        "SELECT * FROM idempotency_keys WHERE key_value = ?", (key_value,)
    ).fetchone()
    return _row_to_record(row) if row else None


def store_idempotency_key(
    conn: sqlite3.Connection,
    key_value: str,
    lesson_id: str,
    result: str = "",
    commit: bool = True,
) -> IdempotencyRecord:
    conn.execute(
        "INSERT OR REPLACE INTO idempotency_keys (key_value, lesson_id, result, created_at) VALUES (?, ?, ?, ?)",
        (key_value, lesson_id, result, _utcnow()),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT * FROM idempotency_keys WHERE key_value = ?", (key_value,)
    ).fetchone()
    return _row_to_record(row)  # type: ignore[return-value]