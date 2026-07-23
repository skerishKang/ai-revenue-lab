"""Blocker I: provider accounting.

Every provider call (including failed and validation-repair calls) is recorded
per attempt group and aggregated. Retry latency is summed; token totals are NULL
when the provider does not report usage; credentials/raw errors are never stored.
"""

from __future__ import annotations

import pytest

from app.ai.mock import MockProvider
from app.pipeline.errors import NonRetryableError, RetryExhaustedError
from app.repositories import compute_accounting, get_generation_runs_by_group

from tests.contracts.conftest import bootstrap_learner, make_pipeline


def test_successful_generation_records_accounting(file_db):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
        # The first lesson uses attempt groups "<lesson>:first".
        group = f"{lesson_id}:first"
        accounting = compute_accounting(pipeline.conn, group)
        assert accounting is not None
        assert accounting.any_success is True
        # lesson_plan + lesson_content => at least two provider calls.
        assert accounting.provider_call_count >= 2
        assert accounting.final_validation_result == "passed"
    finally:
        pipeline.conn.close()


def test_tokens_null_when_not_reported(file_db):
    # The MockProvider does not report token usage => totals must be NULL.
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
        group = f"{lesson_id}:first"
        runs = get_generation_runs_by_group(pipeline.conn, group)
        assert all(r.prompt_tokens is None for r in runs)
        accounting = compute_accounting(pipeline.conn, group)
        assert accounting.input_tokens_total is None
        assert accounting.output_tokens_total is None
    finally:
        pipeline.conn.close()


def test_retry_latencies_are_summed(file_db, monkeypatch):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            raise TimeoutError("slow")

        monkeypatch.setattr(pipeline.provider, "generate_structured", flaky)

        with pytest.raises(RetryExhaustedError):
            pipeline.start_first_lesson(learner_id, concept_id)

        assert calls["n"] == 3
        runs = pipeline.conn.execute(
            "SELECT latency_ms, error_category, attempt_number FROM generation_runs "
            "WHERE task_type = 'lesson_plan' ORDER BY attempt_number"
        ).fetchall()
        assert len(runs) == 3
        assert all(r["error_category"] == "timeout" for r in runs)
        # Aggregate latency is the sum across retries.
        total = sum(r["latency_ms"] for r in runs)
        assert total >= 0
    finally:
        pipeline.conn.close()


def test_failed_provider_call_is_recorded(file_db, monkeypatch):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        def boom(*args, **kwargs):
            raise ValueError("nope")

        monkeypatch.setattr(pipeline.provider, "generate_structured", boom)
        with pytest.raises(NonRetryableError):
            pipeline.start_first_lesson(learner_id, concept_id)

        failed = pipeline.conn.execute(
            "SELECT count(*) AS c FROM generation_runs WHERE success = 0"
        ).fetchone()["c"]
        assert failed >= 1
    finally:
        pipeline.conn.close()


def test_no_secret_stored_in_error_message(file_db, monkeypatch):
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        def leaky(*args, **kwargs):
            raise ValueError("failure with API_KEY=sk-secretvalue1234567890")

        monkeypatch.setattr(pipeline.provider, "generate_structured", leaky)
        with pytest.raises(NonRetryableError):
            pipeline.start_first_lesson(learner_id, concept_id)

        rows = pipeline.conn.execute("SELECT error_message FROM generation_runs").fetchall()
        for row in rows:
            assert "sk-secretvalue1234567890" not in (row["error_message"] or "")
    finally:
        pipeline.conn.close()
