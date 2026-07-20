import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import generation_run_repository as gr_repo
from app import participant_repository as repo
from app.db import apply_migrations, get_connection


class TestGenerationRunCreate:
    def test_create_generation_run(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )

        assert result.task_type == "editorial_plan"
        assert result.provider == "mock"
        assert result.advertised_model == "mock-v1"
        assert result.success == 0
        assert result.retry_count == 0
        assert result.id
        conn.close()

    def test_create_with_custom_fields(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = gr_repo.create_generation_run(
            conn,
            task_type="draft",
            provider="openai",
            advertised_model="gpt-4",
            cost_class="paid",
            prompt_version="v2",
        )

        assert result.cost_class == "paid"
        assert result.prompt_version == "v2"
        conn.close()

    def test_create_rejects_empty_task_type(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.create_generation_run(
                conn,
                task_type="",
                provider="mock",
                advertised_model="mock-v1",
            )
        conn.close()

    def test_create_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        conn.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            gr_repo.create_generation_run(
                conn,
                task_type="test",
                provider="mock",
                advertised_model="mock-v1",
            )
        conn.close()


class TestGenerationRunUpdate:
    def test_update_completion(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )

        updated = gr_repo.update_generation_run(
            conn,
            run.id,
            completed_at="2026-01-01T00:00:00.000Z",
            latency_seconds=1.5,
            success=1,
            input_tokens=100,
            output_tokens=200,
        )

        assert updated is not None
        assert updated.completed_at == "2026-01-01T00:00:00.000Z"
        assert updated.latency_seconds == 1.5
        assert updated.success == 1
        assert updated.input_tokens == 100
        assert updated.output_tokens == 200
        conn.close()

    def test_update_error_fields(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="draft",
            provider="mock",
            advertised_model="mock-v1",
        )

        updated = gr_repo.update_generation_run(
            conn,
            run.id,
            completed_at="2026-01-01T00:00:01.000Z",
            success=0,
            error_category="timeout",
            error_message="request timed out",
            retry_count=2,
        )

        assert updated.success == 0
        assert updated.error_category == "timeout"
        assert updated.error_message == "request timed out"
        assert updated.retry_count == 2
        conn.close()

    def test_update_returns_none_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        result = gr_repo.update_generation_run(
            conn, "nonexistent", success=1
        )
        assert result is None
        conn.close()

    def test_update_no_fields_returns_unchanged(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="test",
            provider="mock",
            advertised_model="mock-v1",
        )
        unchanged = gr_repo.update_generation_run(conn, run.id)
        assert unchanged is not None
        assert unchanged.id == run.id
        conn.close()


class TestGenerationRunLookup:
    def test_get_by_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="validation",
            provider="mock",
            advertised_model="mock-v1",
        )
        found = gr_repo.get_generation_run_by_id(conn, run.id)
        assert found is not None
        assert found.task_type == "validation"
        conn.close()

    def test_get_by_id_returns_none(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert gr_repo.get_generation_run_by_id(conn, "nope") is None
        conn.close()

    def test_get_by_task_type(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        gr_repo.create_generation_run(
            conn,
            task_type="draft",
            provider="mock",
            advertised_model="mock-v1",
        )

        plans = gr_repo.get_generation_runs_by_task_type(
            conn, "editorial_plan"
        )
        assert len(plans) == 2
        conn.close()


class TestGenerationRunFilePersistence:
    def test_run_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = get_connection(db_path)
            apply_migrations(conn, "migrations")

            run = gr_repo.create_generation_run(
                conn,
                task_type="editorial_plan",
                provider="mock",
                advertised_model="mock-v1",
            )
            gr_repo.update_generation_run(
                conn,
                run.id,
                completed_at="2026-01-01T00:00:01.000Z",
                latency_seconds=2.0,
                success=1,
                input_tokens=50,
                output_tokens=100,
            )
            conn.close()

            conn2 = get_connection(db_path)
            found = gr_repo.get_generation_run_by_id(conn2, run.id)
            assert found is not None
            assert found.success == 1
            assert found.latency_seconds == 2.0
            assert found.input_tokens == 50
            assert found.output_tokens == 100
            conn2.close()


class TestGenerationRunTimestampValidation:
    def test_valid_started_at_accepted(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
            started_at="2026-07-20T09:23:46.123Z",
        )
        assert result.started_at == "2026-07-20T09:23:46.123Z"
        conn.close()

    def test_invalid_started_at_month_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.create_generation_run(
                conn,
                task_type="editorial_plan",
                provider="mock",
                advertised_model="mock-v1",
                started_at="2026-13-20T09:23:46.123Z",
            )
        conn.close()

    def test_invalid_started_at_day_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.create_generation_run(
                conn,
                task_type="editorial_plan",
                provider="mock",
                advertised_model="mock-v1",
                started_at="2026-02-30T09:23:46.123Z",
            )
        conn.close()

    def test_invalid_started_at_hour_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.create_generation_run(
                conn,
                task_type="editorial_plan",
                provider="mock",
                advertised_model="mock-v1",
                started_at="2026-07-20T25:23:46.123Z",
            )
        conn.close()

    def test_invalid_started_at_shape_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.create_generation_run(
                conn,
                task_type="editorial_plan",
                provider="mock",
                advertised_model="mock-v1",
                started_at="not-a-timestamp",
            )
        conn.close()

    def test_invalid_completed_at_month_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.update_generation_run(
                conn,
                run.id,
                completed_at="2026-13-01T00:00:00.000Z",
            )
        conn.close()

    def test_invalid_completed_at_day_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.update_generation_run(
                conn,
                run.id,
                completed_at="2026-02-30T00:00:00.000Z",
            )
        conn.close()

    def test_invalid_completed_at_second_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.update_generation_run(
                conn,
                run.id,
                completed_at="2026-07-20T00:00:61.000Z",
            )
        conn.close()

    def test_invalid_completed_at_shape_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        run = gr_repo.create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            advertised_model="mock-v1",
        )
        with pytest.raises(gr_repo.GenerationRunValidationError):
            gr_repo.update_generation_run(
                conn,
                run.id,
                completed_at="not-a-timestamp",
            )
        conn.close()
