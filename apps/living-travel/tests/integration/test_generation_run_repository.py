"""Integration tests for generation run repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.generation_run_repository import (
    count_generation_runs_by_edition,
    create_generation_run,
    get_generation_run_by_id,
    get_generation_runs_by_task_type,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestGenerationRunRepository:
    def test_create_and_get(self, conn):
        run = create_generation_run(
            conn,
            task_type="editorial_plan",
            provider="mock",
            edition_id="ed_test",
        )
        assert run.id.startswith("gr_")
        fetched = get_generation_run_by_id(conn, run.id)
        assert fetched is not None
        assert fetched.task_type == "editorial_plan"

    def test_list_by_task_type(self, conn):
        create_generation_run(conn, task_type="editorial_plan", provider="mock", edition_id="ed1")
        create_generation_run(conn, task_type="edition_draft", provider="mock", edition_id="ed1")
        create_generation_run(conn, task_type="editorial_plan", provider="mock", edition_id="ed2")
        plans = get_generation_runs_by_task_type(conn, "editorial_plan")
        assert len(plans) == 2

    def test_count_by_edition(self, conn):
        create_generation_run(conn, task_type="editorial_plan", provider="mock", edition_id="ed1")
        create_generation_run(conn, task_type="edition_draft", provider="mock", edition_id="ed1")
        create_generation_run(conn, task_type="editorial_plan", provider="mock", edition_id="ed2")
        assert count_generation_runs_by_edition(conn, "ed1") == 2
        assert count_generation_runs_by_edition(conn, "ed2") == 1
        assert count_generation_runs_by_edition(conn, "ed_none") == 0

    def test_error_info_stored(self, conn):
        run = create_generation_run(
            conn,
            task_type="edition_draft",
            provider="mock",
            success=False,
            error_category="provider_error",
            error_message="simulated",
            edition_id="ed_err",
        )
        fetched = get_generation_run_by_id(conn, run.id)
        assert fetched is not None
        assert fetched.success is False
        assert fetched.error_category == "provider_error"
