import json
import re
import sqlite3
import uuid
from dataclasses import dataclass

from app.participant_repository import RepositoryTransactionError, _now_utc_iso

_UTC_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def _validate_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _UTC_ISO_RE.match(value):
        raise GenerationRunValidationError(
            f"{field_name} must be UTC ISO-8601 "
            "(YYYY-MM-DDTHH:MM:SS.mmmZ)"
        )


@dataclass(frozen=True)
class GenerationRunRecord:
    id: str
    task_type: str
    provider: str
    advertised_model: str
    verified_upstream_status: str | None
    cost_class: str
    prompt_version: str | None
    started_at: str
    completed_at: str | None
    latency_seconds: float | None
    success: int
    validation_status: str | None
    input_tokens: int | None
    output_tokens: int | None
    retry_count: int
    error_category: str | None
    error_message: str | None
    human_correction_minutes: float | None


class GenerationRunValidationError(ValueError):
    pass


class GenerationRunNotFoundError(RuntimeError):
    pass


_GENERATION_RUN_COLS = [
    "id",
    "task_type",
    "provider",
    "advertised_model",
    "verified_upstream_status",
    "cost_class",
    "prompt_version",
    "started_at",
    "completed_at",
    "latency_seconds",
    "success",
    "validation_status",
    "input_tokens",
    "output_tokens",
    "retry_count",
    "error_category",
    "error_message",
    "human_correction_minutes",
]
_GENERATION_RUN_SELECT = ", ".join(_GENERATION_RUN_COLS)


def _validate_generation_run(
    task_type: str,
    provider: str,
    advertised_model: str,
) -> None:
    if not isinstance(task_type, str) or not task_type.strip():
        raise GenerationRunValidationError(
            "task_type must be a non-empty string"
        )
    if not isinstance(provider, str) or not provider.strip():
        raise GenerationRunValidationError(
            "provider must be a non-empty string"
        )
    if not isinstance(advertised_model, str) or not advertised_model.strip():
        raise GenerationRunValidationError(
            "advertised_model must be a non-empty string"
        )


def _row_to_record(row: sqlite3.Row) -> GenerationRunRecord:
    return GenerationRunRecord(
        id=row["id"],
        task_type=row["task_type"],
        provider=row["provider"],
        advertised_model=row["advertised_model"],
        verified_upstream_status=row["verified_upstream_status"],
        cost_class=row["cost_class"],
        prompt_version=row["prompt_version"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        latency_seconds=row["latency_seconds"],
        success=row["success"],
        validation_status=row["validation_status"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        retry_count=row["retry_count"],
        error_category=row["error_category"],
        error_message=row["error_message"],
        human_correction_minutes=row["human_correction_minutes"],
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
    _validate_generation_run(task_type, provider, advertised_model)

    if started_at is not None:
        _validate_timestamp(started_at, "started_at")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    task_type = task_type.strip()
    provider = provider.strip()
    advertised_model = advertised_model.strip()
    now = started_at or _now_utc_iso()
    run_id = str(uuid.uuid4())

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO generation_runs "
            "(id, task_type, provider, advertised_model, cost_class, "
            "prompt_version, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, task_type, provider, advertised_model, cost_class,
             prompt_version, now),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("failed to insert generation run record")

        conn.commit()
        return GenerationRunRecord(
            id=run_id,
            task_type=task_type,
            provider=provider,
            advertised_model=advertised_model,
            verified_upstream_status=None,
            cost_class=cost_class,
            prompt_version=prompt_version,
            started_at=now,
            completed_at=None,
            latency_seconds=None,
            success=0,
            validation_status=None,
            input_tokens=None,
            output_tokens=None,
            retry_count=0,
            error_category=None,
            error_message=None,
            human_correction_minutes=None,
        )
    except (GenerationRunValidationError, RepositoryTransactionError):
        raise
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
    success: int | None = None,
    validation_status: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retry_count: int | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
    verified_upstream_status: str | None = None,
    human_correction_minutes: float | None = None,
) -> GenerationRunRecord | None:
    if completed_at is not None:
        _validate_timestamp(completed_at, "completed_at")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT id FROM generation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if existing is None:
            conn.rollback()
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
        if retry_count is not None:
            updates.append("retry_count = ?")
            params.append(retry_count)
        if error_category is not None:
            updates.append("error_category = ?")
            params.append(error_category)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if verified_upstream_status is not None:
            updates.append("verified_upstream_status = ?")
            params.append(verified_upstream_status)
        if human_correction_minutes is not None:
            updates.append("human_correction_minutes = ?")
            params.append(human_correction_minutes)

        if not updates:
            conn.rollback()
            return get_generation_run_by_id(conn, run_id)

        params.append(run_id)
        conn.execute(
            f"UPDATE generation_runs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return get_generation_run_by_id(conn, run_id)
    except (GenerationRunValidationError, RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_generation_run_by_id(
    conn: sqlite3.Connection, run_id: str
) -> GenerationRunRecord | None:
    row = conn.execute(
        f"SELECT {_GENERATION_RUN_SELECT} FROM generation_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_generation_runs_by_task_type(
    conn: sqlite3.Connection, task_type: str
) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_GENERATION_RUN_SELECT} FROM generation_runs "
        "WHERE task_type = ? ORDER BY started_at",
        (task_type,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
