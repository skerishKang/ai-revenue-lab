"""Generation-run repository with full provider accounting (Issue #37 blocker I).

Each provider call (including failed calls and validation-repair calls) is
recorded as one ``generation_runs`` row grouped by ``attempt_group_id``.
Per-call metrics (latency, tokens, error category, validation result, timing)
are stored on the row; aggregate accounting (provider call count, retry count,
total latency, total tokens) is computed across the group and recorded so the
true cost of an operation is auditable.

Privacy: only ``error_category`` and a bounded, sanitized ``error_message`` are
stored — never credentials, authorization headers, or raw private input. Token
columns are nullable: ``NULL`` means the provider did not report usage, which is
distinct from ``0``.
"""

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
    attempt_group_id: str
    attempt_number: int
    request_id: str
    task_type: str
    provider: str
    advertised_model: str
    cost_class: str
    prompt_version: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    success: bool
    validation_result: str
    error_category: str
    error_message: str
    lesson_id: str
    created_at: str
    # Accounting (populated per call; totals finalized across the group).
    retry_count: int = 0
    provider_call_count: int = 1
    latency_ms_total: float = 0.0
    input_tokens_total: int | None = None
    output_tokens_total: int | None = None
    started_at: str = ""
    completed_at: str = ""


@dataclass(frozen=True)
class GenerationAccounting:
    """Aggregate accounting for one attempt group."""

    attempt_group_id: str
    provider_call_count: int
    retry_count: int
    latency_ms_total: float
    input_tokens_total: int | None
    output_tokens_total: int | None
    final_validation_result: str
    any_success: bool


_COLS = [
    "id", "attempt_group_id", "attempt_number", "request_id", "task_type",
    "provider", "advertised_model", "cost_class", "prompt_version",
    "latency_ms", "prompt_tokens", "completion_tokens", "success",
    "validation_result", "error_category", "error_message", "lesson_id",
    "created_at", "retry_count", "provider_call_count", "latency_ms_total",
    "input_tokens_total", "output_tokens_total", "started_at", "completed_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> GenerationRunRecord:
    return GenerationRunRecord(
        id=row["id"],
        attempt_group_id=row["attempt_group_id"],
        attempt_number=row["attempt_number"],
        request_id=row["request_id"] or "",
        task_type=row["task_type"],
        provider=row["provider"],
        advertised_model=row["advertised_model"] or "",
        cost_class=row["cost_class"] or "free",
        prompt_version=row["prompt_version"] or "",
        latency_ms=row["latency_ms"] or 0.0,
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        success=bool(row["success"]),
        validation_result=row["validation_result"] or "pending",
        error_category=row["error_category"] or "",
        error_message=row["error_message"] or "",
        lesson_id=row["lesson_id"] or "",
        created_at=row["created_at"],
        retry_count=row["retry_count"] or 0,
        provider_call_count=row["provider_call_count"] or 1,
        latency_ms_total=row["latency_ms_total"] or 0.0,
        input_tokens_total=row["input_tokens_total"],
        output_tokens_total=row["output_tokens_total"],
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"] or "",
    )


def create_generation_run(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    attempt_group_id: str,
    attempt_number: int = 1,
    request_id: str = "",
    provider: str = "unknown",
    advertised_model: str = "",
    cost_class: str = "free",
    prompt_version: str = "",
    latency_ms: float = 0.0,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error_category: str = "",
    error_message: str = "",
    lesson_id: str = "",
    success: bool = True,
    validation_result: str = "pending",
    started_at: str = "",
    completed_at: str = "",
    commit: bool = False,
) -> GenerationRunRecord:
    """Record a single provider call (success or failure)."""
    now = _utcnow()
    run_id = f"gr_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO generation_runs ({_SELECT}) VALUES ({','.join('?' for _ in _COLS)})",
        (
            run_id, attempt_group_id, attempt_number, request_id, task_type,
            provider, advertised_model, cost_class, prompt_version,
            latency_ms, prompt_tokens, completion_tokens, int(success),
            validation_result, error_category, error_message, lesson_id, now,
            max(0, attempt_number - 1), 1, latency_ms,
            prompt_tokens, completion_tokens, started_at or now, completed_at or now,
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


def get_generation_runs_by_group(
    conn: sqlite3.Connection, attempt_group_id: str
) -> list[GenerationRunRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM generation_runs WHERE attempt_group_id = ? "
        "ORDER BY attempt_number, created_at",
        (attempt_group_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def count_generation_runs_by_lesson(conn: sqlite3.Connection, lesson_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM generation_runs WHERE lesson_id = ?",
        (lesson_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def sum_tokens_by_lesson(conn: sqlite3.Connection, lesson_id: str) -> tuple[int, int]:
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


def compute_accounting(
    conn: sqlite3.Connection, attempt_group_id: str
) -> GenerationAccounting | None:
    """Aggregate accounting across every provider call in an attempt group.

    Retry latency is summed across all calls; token totals are ``NULL`` if no
    call reported usage (otherwise the sum of reported values); failed and
    validation-repair calls are included because every call is a row.
    """
    rows = get_generation_runs_by_group(conn, attempt_group_id)
    if not rows:
        return None

    provider_call_count = len(rows)
    retry_count = provider_call_count - 1
    latency_ms_total = sum(r.latency_ms for r in rows)

    reported_input = [r.prompt_tokens for r in rows if r.prompt_tokens is not None]
    reported_output = [r.completion_tokens for r in rows if r.completion_tokens is not None]
    input_tokens_total = sum(reported_input) if reported_input else None
    output_tokens_total = sum(reported_output) if reported_output else None

    # Final validation result = that of the last call (by attempt then time).
    final_validation_result = rows[-1].validation_result
    any_success = any(r.success for r in rows)

    return GenerationAccounting(
        attempt_group_id=attempt_group_id,
        provider_call_count=provider_call_count,
        retry_count=retry_count,
        latency_ms_total=latency_ms_total,
        input_tokens_total=input_tokens_total,
        output_tokens_total=output_tokens_total,
        final_validation_result=final_validation_result,
        any_success=any_success,
    )


def finalize_attempt_group(
    conn: sqlite3.Connection,
    attempt_group_id: str,
    *,
    validation_result: str,
    commit: bool = False,
) -> GenerationAccounting | None:
    """Record aggregate accounting onto the group's rows.

    Writes the computed totals (provider call count, retry count, total latency
    and tokens) and the final validation result onto every row of the group so
    the full request accounting is persisted and queryable from any row.
    """
    accounting = compute_accounting(conn, attempt_group_id)
    if accounting is None:
        return None
    conn.execute(
        "UPDATE generation_runs SET provider_call_count = ?, retry_count = ?, "
        "latency_ms_total = ?, input_tokens_total = ?, output_tokens_total = ?, "
        "validation_result = ? WHERE attempt_group_id = ?",
        (
            accounting.provider_call_count,
            accounting.retry_count,
            accounting.latency_ms_total,
            accounting.input_tokens_total,
            accounting.output_tokens_total,
            validation_result,
            attempt_group_id,
        ),
    )
    if commit:
        conn.commit()
    return accounting
