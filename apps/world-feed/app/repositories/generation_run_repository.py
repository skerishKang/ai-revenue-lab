import sqlite3
from dataclasses import dataclass

from app.db import transaction_scope
from app.repositories.common import now_utc_iso


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
    success: int
    validation_status: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    retry_count: int
    error_category: str | None
    error_message: str | None


_RUN_COLS = [
    "id", "task_type", "provider", "advertised_model", "cost_class",
    "prompt_version", "started_at", "completed_at", "latency_seconds",
    "success", "validation_status", "input_tokens", "output_tokens",
    "total_tokens", "retry_count", "error_category", "error_message",
]
_RUN_SELECT = ", ".join(_RUN_COLS)


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
        success=row["success"],
        validation_status=row["validation_status"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        total_tokens=row["total_tokens"],
        retry_count=row["retry_count"],
        error_category=row["error_category"],
        error_message=row["error_message"],
    )


def create_generation_run(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    provider: str,
    advertised_model: str,
    cost_class: str = "free",
    prompt_version: str | None = None,
    started_at: str | None = None,
) -> GenerationRunRecord:
    import uuid

    now = started_at or now_utc_iso()
    with transaction_scope(conn):
        run_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO generation_runs (
                id, task_type, provider, advertised_model, cost_class,
                prompt_version, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, task_type, provider, advertised_model, cost_class,
             prompt_version, now),
        )
        return get_generation_run_by_id(conn, run_id)


def update_generation_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    completed_at: str | None = None,
    latency_seconds: float | None = None,
    success: int | None = None,
    validation_status: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    retry_count: int | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
) -> GenerationRunRecord | None:
    with transaction_scope(conn):
        existing = conn.execute(
            "SELECT id FROM generation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if existing is None:
            return None
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
            params.append(success)
        if validation_status is not None:
            updates.append("validation_status = ?")
            params.append(validation_status)
        if input_tokens is not None:
            updates.append("input_tokens = ?")
            params.append(input_tokens)
        if output_tokens is not None:
            updates.append("output_tokens = ?")
            params.append(output_tokens)
        if total_tokens is not None:
            updates.append("total_tokens = ?")
            params.append(total_tokens)
        if retry_count is not None:
            updates.append("retry_count = ?")
            params.append(retry_count)
        if error_category is not None:
            updates.append("error_category = ?")
            params.append(error_category)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if not updates:
            return get_generation_run_by_id(conn, run_id)
        params.append(run_id)
        conn.execute(
            f"UPDATE generation_runs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        return get_generation_run_by_id(conn, run_id)


def get_generation_run_by_id(
    conn: sqlite3.Connection, run_id: str
) -> GenerationRunRecord | None:
    row = conn.execute(
        f"SELECT {_RUN_SELECT} FROM generation_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def list_runs_by_task_type(
    conn: sqlite3.Connection, task_type: str
) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_RUN_SELECT} FROM generation_runs "
        "WHERE task_type = ? ORDER BY started_at",
        (task_type,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
