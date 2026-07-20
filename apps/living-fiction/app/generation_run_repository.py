"""Generation-run repository — accounting for every provider call.

Records provider, model, prompt version, task, latency, retry count,
token usage, validation result, and privacy-safe error category.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class GenerationRunRecord:
    id: str
    task_type: str
    provider: str
    advertised_model: str
    cost_class: str
    prompt_version: str | None
    started_at: str
    completed_at: str | None
    latency_seconds: float | None
    success: bool
    validation_status: str | None
    input_tokens: int | None
    output_tokens: int | None
    retry_count: int
    error_category: str | None
    error_message: str | None
    created_at: str


class GenerationRunValidationError(ValueError):
    pass


_COLS = [
    "id", "task_type", "provider", "advertised_model", "cost_class",
    "prompt_version", "started_at", "completed_at", "latency_seconds",
    "success", "validation_status", "input_tokens", "output_tokens",
    "retry_count", "error_category", "error_message", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> GenerationRunRecord:
    return GenerationRunRecord(
        id=row["id"],
        task_type=row["task_type"],
        provider=row["provider"],
        advertised_model=row["advertised_model"],
        cost_class=row["cost_class"],
        prompt_version=row["prompt_version"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        latency_seconds=row["latency_seconds"],
        success=bool(row["success"]),
        validation_status=row["validation_status"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        retry_count=row["retry_count"],
        error_category=row["error_category"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def create_generation_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_type: str,
    provider: str,
    advertised_model: str,
    cost_class: str = "free",
    prompt_version: str | None = None,
    started_at: str | None = None,
) -> GenerationRunRecord:
    if not task_type.strip() or not provider.strip() or not advertised_model.strip():
        raise GenerationRunValidationError(
            "task_type, provider, advertised_model must be non-empty"
        )

    now = started_at or now_utc_iso()

    if conn.in_transaction:
        # Within a service-owned transaction — insert without committing
        conn.execute(
            "INSERT INTO generation_runs "
            "(id, task_type, provider, advertised_model, cost_class, "
            "prompt_version, started_at, retry_count, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (run_id, task_type, provider, advertised_model, cost_class,
             prompt_version, now, now),
        )
        return GenerationRunRecord(
            id=run_id, task_type=task_type, provider=provider,
            advertised_model=advertised_model, cost_class=cost_class,
            prompt_version=prompt_version, started_at=now,
            completed_at=None, latency_seconds=None, success=False,
            validation_status=None, input_tokens=None,
            output_tokens=None, retry_count=0, error_category=None,
            error_message=None, created_at=now,
        )

    # Idle connection — manage own transaction
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO generation_runs "
            "(id, task_type, provider, advertised_model, cost_class, "
            "prompt_version, started_at, retry_count, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (run_id, task_type, provider, advertised_model, cost_class,
             prompt_version, now, now),
        )
        conn.commit()
        return GenerationRunRecord(
            id=run_id, task_type=task_type, provider=provider,
            advertised_model=advertised_model, cost_class=cost_class,
            prompt_version=prompt_version, started_at=now,
            completed_at=None, latency_seconds=None, success=False,
            validation_status=None, input_tokens=None,
            output_tokens=None, retry_count=0, error_category=None,
            error_message=None, created_at=now,
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def update_generation_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    completed_at: str | None = None,
    latency_seconds: float | None = None,
    success: bool | None = None,
    validation_status: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retry_count: int | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
) -> GenerationRunRecord | None:
    """Update a generation run.

    Works in both modes:
    - Idle connection: manages its own transaction (BEGIN/COMMIT).
    - Within service-owned transaction: updates without committing.
    """
    updates: list[str] = []
    params: list = []

    if completed_at is not None:
        updates.append("completed_at = ?")
        params.append(completed_at)
    if latency_seconds is not None:
        updates.append("latency_seconds = ?")
        params.append(latency_seconds)
    if success is not None:
        updates.append("success = ?")
        params.append(1 if success else 0)
    if validation_status is not None:
        updates.append("validation_status = ?")
        params.append(validation_status)
    if input_tokens is not None:
        updates.append("input_tokens = ?")
        params.append(input_tokens)
    if output_tokens is not None:
        updates.append("output_tokens = ?")
        params.append(output_tokens)
    if retry_count is not None:
        updates.append("retry_count = ?")
        params.append(retry_count)
    if error_category is not None:
        updates.append("error_category = ?")
        params.append(error_category)
    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)

    if conn.in_transaction:
        # Within a service-owned transaction — update without committing
        if updates:
            params.append(run_id)
            conn.execute(
                f"UPDATE generation_runs SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        row = conn.execute(
            f"SELECT {_SELECT} FROM generation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return _row_to_record(row) if row else None

    # Idle connection — manage own transaction
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT id FROM generation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if existing is None:
            conn.rollback()
            return None

        if updates:
            params.append(run_id)
            conn.execute(
                f"UPDATE generation_runs SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        conn.commit()
        row = conn.execute(
            f"SELECT {_SELECT} FROM generation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return _row_to_record(row) if row else None
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_generation_run(conn: sqlite3.Connection, run_id: str) -> GenerationRunRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_generation_runs_by_task(
    conn: sqlite3.Connection, task_type: str
) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs WHERE task_type = ? "
        "ORDER BY started_at",
        (task_type,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_all_generation_runs(conn: sqlite3.Connection) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs ORDER BY started_at"
    ).fetchall()
    return [_row_to_record(r) for r in rows]
