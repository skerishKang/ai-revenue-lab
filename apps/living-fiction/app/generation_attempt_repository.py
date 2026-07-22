"""Generation-attempt repository — one durable row per actual provider attempt.

Distinguished from the aggregate generation_runs row. Each attempt records
the actual provider, model, cost class, latency, tokens, request ID, task,
prompt version, attempt number, retry classification, success, validation
result, and privacy-safe error category.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class GenerationAttemptRecord:
    id: str
    generation_run_id: str
    attempt_number: int
    provider: str
    advertised_model: str
    cost_class: str
    request_id: str | None
    task_type: str
    prompt_version: str | None
    latency_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    success: bool
    retryable: bool
    error_category: str | None
    error_message: str | None
    created_at: str


_COLS = [
    "id", "generation_run_id", "attempt_number", "provider",
    "advertised_model", "cost_class", "request_id", "task_type",
    "prompt_version", "latency_seconds", "input_tokens", "output_tokens",
    "total_tokens", "success", "retryable", "error_category",
    "error_message", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> GenerationAttemptRecord:
    return GenerationAttemptRecord(
        id=row["id"],
        generation_run_id=row["generation_run_id"],
        attempt_number=row["attempt_number"],
        provider=row["provider"],
        advertised_model=row["advertised_model"],
        cost_class=row["cost_class"],
        request_id=row["request_id"],
        task_type=row["task_type"],
        prompt_version=row["prompt_version"],
        latency_seconds=row["latency_seconds"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        total_tokens=row["total_tokens"],
        success=bool(row["success"]),
        retryable=bool(row["retryable"]),
        error_category=row["error_category"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def create_generation_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    generation_run_id: str,
    attempt_number: int,
    provider: str,
    advertised_model: str,
    cost_class: str,
    task_type: str,
    request_id: str | None = None,
    prompt_version: str | None = None,
    latency_seconds: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    success: bool = False,
    retryable: bool = False,
    error_category: str | None = None,
    error_message: str | None = None,
) -> GenerationAttemptRecord:
    """Create an attempt record.

    Manages its own transaction when the connection is idle.
    If called within a service-owned transaction, inserts without committing.
    """
    now = now_utc_iso()

    if conn.in_transaction:
        # Within a service-owned transaction — just insert, don't commit
        conn.execute(
            f"INSERT INTO generation_attempts ({_SELECT}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt_id, generation_run_id, attempt_number,
                provider, advertised_model, cost_class, request_id, task_type,
                prompt_version, latency_seconds, input_tokens, output_tokens,
                total_tokens, 1 if success else 0, 1 if retryable else 0,
                error_category, error_message, now,
            ),
        )
    else:
        # Idle connection — manage own transaction
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"INSERT INTO generation_attempts ({_SELECT}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id, generation_run_id, attempt_number,
                    provider, advertised_model, cost_class, request_id, task_type,
                    prompt_version, latency_seconds, input_tokens, output_tokens,
                    total_tokens, 1 if success else 0, 1 if retryable else 0,
                    error_category, error_message, now,
                ),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    row = conn.execute(
        f"SELECT {_SELECT} FROM generation_attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    return _row_to_record(row)


def get_attempts_by_run(
    conn: sqlite3.Connection, generation_run_id: str
) -> list[GenerationAttemptRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_attempts "
        "WHERE generation_run_id = ? ORDER BY attempt_number",
        (generation_run_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_all_attempts(conn: sqlite3.Connection) -> list[GenerationAttemptRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_attempts ORDER BY created_at"
    ).fetchall()
    return [_row_to_record(r) for r in rows]
