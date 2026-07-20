"""Generation run repository for Living Learning."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class GenerationRunRecord:
    id: str
    task_type: str
    provider: str
    advertised_model: str
    cost_class: str
    prompt_version: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    error_category: str
    error_message: str
    lesson_id: str
    success: bool
    created_at: str


def _row_to_record(row: sqlite3.Row) -> GenerationRunRecord:
    return GenerationRunRecord(
        id=row["id"],
        task_type=row["task_type"],
        provider=row["provider"],
        advertised_model=row["advertised_model"],
        cost_class=row["cost_class"],
        prompt_version=row["prompt_version"],
        latency_ms=row["latency_ms"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        error_category=row["error_category"],
        error_message=row["error_message"],
        lesson_id=row["lesson_id"],
        success=bool(row["success"]),
        created_at=row["created_at"],
    )


_COLS = [
    "id", "task_type", "provider", "advertised_model", "cost_class",
    "prompt_version", "latency_ms", "prompt_tokens", "completion_tokens",
    "error_category", "error_message", "lesson_id", "success", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_generation_run(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    provider: str = "unknown",
    advertised_model: str = "",
    cost_class: str = "free",
    prompt_version: str = "",
    latency_ms: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error_category: str = "",
    error_message: str = "",
    lesson_id: str = "",
    success: bool = True,
    commit: bool = True,
) -> GenerationRunRecord:
    now = _utcnow()
    run_id = f"gr_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO generation_runs ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id, task_type, provider, advertised_model, cost_class,
            prompt_version, latency_ms, prompt_tokens, completion_tokens,
            error_category, error_message, lesson_id, int(success), now,
        ),
    )
    if commit:
        conn.commit()
    return get_generation_run_by_id(conn, run_id)  # type: ignore[return-value]


def get_generation_run_by_id(conn: sqlite3.Connection, run_id: str) -> GenerationRunRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_generation_runs_by_task_type(
    conn: sqlite3.Connection, task_type: str
) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs WHERE task_type = ? ORDER BY created_at",
        (task_type,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def count_generation_runs_by_lesson(
    conn: sqlite3.Connection, lesson_id: str
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM generation_runs WHERE lesson_id = ?",
        (lesson_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def sum_tokens_by_lesson(
    conn: sqlite3.Connection, lesson_id: str
) -> tuple[int, int]:
    row = conn.execute(
        """SELECT
            COALESCE(SUM(prompt_tokens), 0) as total_prompt,
            COALESCE(SUM(completion_tokens), 0) as total_completion
        FROM generation_runs WHERE lesson_id = ?""",
        (lesson_id,),
    ).fetchone()
    if row:
        return int(row["total_prompt"]), int(row["total_completion"])
    return 0, 0