"""P0: provider call vs retry accounting.

``provider_call_count`` is the total number of provider calls; ``retry_count`` is
the sum over tasks of ``MAX(attempt_number) - 1`` (attempts restart at 1 per
task), so it is NOT ``provider_call_count - 1`` when a group has multiple tasks.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.db import apply_migrations
from app.repositories.generation_run_repository import (
    compute_accounting,
    compute_task_breakdown,
)

GROUP = "lesson_X:first"


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    apply_migrations(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass


def _add_run(conn, task_type, attempt_number, *, latency_ms=10.0, prompt_tokens=None, completion_tokens=None, success=True, provider="mock", model="mock-fixture"):
    conn.execute(
        "INSERT INTO generation_runs (id, attempt_group_id, attempt_number, request_id, task_type, "
        "provider, advertised_model, cost_class, prompt_version, latency_ms, prompt_tokens, completion_tokens, "
        "success, validation_result, error_category, error_message, lesson_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'free', 'v1', ?, ?, ?, ?, 'passed', '', '', 'lesson_X', datetime('now'))",
        (
            f"run_{task_type}_{attempt_number}_{os.urandom(3).hex()}",
            GROUP, attempt_number, f"req_{task_type}_{attempt_number}", task_type,
            provider, model, latency_ms, prompt_tokens, completion_tokens, int(success),
        ),
    )
    conn.commit()


def test_plan1_content1_calls2_retries0(db):
    _add_run(db, "lesson_plan", 1)
    _add_run(db, "lesson_content", 1)
    acc = compute_accounting(db, GROUP)
    assert acc.provider_call_count == 2
    assert acc.retry_count == 0


def test_plan2_content1_calls3_retries1(db):
    _add_run(db, "lesson_plan", 1)
    _add_run(db, "lesson_plan", 2)
    _add_run(db, "lesson_content", 1)
    acc = compute_accounting(db, GROUP)
    assert acc.provider_call_count == 3
    assert acc.retry_count == 1


def test_plan3_content2_calls5_retries3(db):
    for a in (1, 2, 3):
        _add_run(db, "lesson_plan", a)
    for a in (1, 2):
        _add_run(db, "lesson_content", a)
    acc = compute_accounting(db, GROUP)
    assert acc.provider_call_count == 5
    assert acc.retry_count == 3  # (3-1) + (2-1)


def test_failed_call_included(db):
    _add_run(db, "lesson_plan", 1, success=False)
    _add_run(db, "lesson_plan", 2, success=True)
    _add_run(db, "lesson_content", 1, success=True)
    acc = compute_accounting(db, GROUP)
    assert acc.provider_call_count == 3
    assert acc.retry_count == 1
    assert acc.any_success is True


def test_tokens_all_unreported_is_null(db):
    _add_run(db, "lesson_plan", 1, prompt_tokens=None, completion_tokens=None)
    _add_run(db, "lesson_content", 1, prompt_tokens=None, completion_tokens=None)
    acc = compute_accounting(db, GROUP)
    assert acc.input_tokens_total is None
    assert acc.output_tokens_total is None


def test_tokens_partial_reported_sums_only_reported(db):
    _add_run(db, "lesson_plan", 1, prompt_tokens=100, completion_tokens=50)
    _add_run(db, "lesson_content", 1, prompt_tokens=None, completion_tokens=None)
    acc = compute_accounting(db, GROUP)
    assert acc.input_tokens_total == 100
    assert acc.output_tokens_total == 50


def test_latency_is_true_sum(db):
    _add_run(db, "lesson_plan", 1, latency_ms=10.0)
    _add_run(db, "lesson_plan", 2, latency_ms=15.0)
    _add_run(db, "lesson_content", 1, latency_ms=20.0)
    acc = compute_accounting(db, GROUP)
    assert acc.latency_ms_total == 45.0


def test_task_breakdown_per_task(db):
    _add_run(db, "lesson_plan", 1, latency_ms=10.0, provider="mock", model="m1")
    _add_run(db, "lesson_plan", 2, latency_ms=5.0, provider="mock", model="m1")
    _add_run(db, "lesson_content", 1, latency_ms=20.0, provider="mock", model="m2")
    breakdown = {t.task_type: t for t in compute_task_breakdown(db, GROUP)}
    assert breakdown["lesson_plan"].provider_call_count == 2
    assert breakdown["lesson_plan"].retry_count == 1
    assert breakdown["lesson_plan"].latency_ms_total == 15.0
    assert breakdown["lesson_plan"].model == "m1"
    assert breakdown["lesson_content"].provider_call_count == 1
    assert breakdown["lesson_content"].retry_count == 0
    assert breakdown["lesson_content"].model == "m2"


def test_repository_and_review_accounting_consistent(db):
    """The aggregate equals the sum of the per-task breakdown."""
    _add_run(db, "lesson_plan", 1, latency_ms=10.0)
    _add_run(db, "lesson_plan", 2, latency_ms=5.0)
    _add_run(db, "lesson_content", 1, latency_ms=20.0)
    acc = compute_accounting(db, GROUP)
    breakdown = compute_task_breakdown(db, GROUP)
    assert acc.provider_call_count == sum(t.provider_call_count for t in breakdown)
    assert acc.retry_count == sum(t.retry_count for t in breakdown)
    assert acc.latency_ms_total == sum(t.latency_ms_total for t in breakdown)
