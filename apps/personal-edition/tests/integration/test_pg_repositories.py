"""PostgreSQL repository integration tests.

Verifies that all repositories work correctly with the PostgreSQL runtime
connection.  These tests only run when BOTH:
  - TEST_POSTGRES_URL is set
  - PE_PG_TEST_INTEGRATION=1

The tests use a temporary schema for complete isolation and never touch
the public schema.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.config import normalize_pg_url_identity
from app.db_postgres import get_pg_connection
from app.db_runtime import PostgresRuntimeConnection

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")
PE_DATABASE_URL = os.environ.get("PE_DATABASE_URL", "")
PE_PG_TEST_INTEGRATION = os.environ.get("PE_PG_TEST_INTEGRATION", "").strip()


def _urls_resolve_to_same_db(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ia = normalize_pg_url_identity(a)
    ib = normalize_pg_url_identity(b)
    if ia is None or ib is None:
        return a == b
    return ia == ib


if TEST_POSTGRES_URL and PE_DATABASE_URL and _urls_resolve_to_same_db(
    TEST_POSTGRES_URL, PE_DATABASE_URL
):
    raise RuntimeError(
        "TEST_POSTGRES_URL resolves to the same database identity as "
        "PE_DATABASE_URL — refusing to run integration tests."
    )

_INTEGRATION_ENABLED = bool(
    TEST_POSTGRES_URL
    and PE_PG_TEST_INTEGRATION in ("1", "true", "yes", "on")
)

pytestmark = pytest.mark.skipif(
    not _INTEGRATION_ENABLED,
    reason=(
        "PostgreSQL repository integration tests require both "
        "TEST_POSTGRES_URL and PE_PG_TEST_INTEGRATION=1."
    ),
)


@pytest.fixture
def pg_runtime_conn():
    """Create a PostgreSQL runtime connection with isolated schema."""
    from app.db_pg_migrations import apply_pg_migrations
    from app.db_postgres import PG_MIGRATIONS_DIR

    conn = get_pg_connection(TEST_POSTGRES_URL)
    schema_name = f"test_repo_{uuid.uuid4().hex}"

    try:
        conn.execute(f'CREATE SCHEMA "{schema_name}"')
        conn.execute(f'SET search_path TO "{schema_name}"')
        conn.commit()

        apply_pg_migrations(conn, PG_MIGRATIONS_DIR)
        conn.commit()

        runtime = PostgresRuntimeConnection(lambda: conn)
        runtime._conn = conn
        yield runtime
    finally:
        try:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        conn.close()


class TestParticipantRepositoryPg:
    """Participant repository works with PostgreSQL."""

    def test_create_and_get_participant(self, pg_runtime_conn):
        from app import participant_repository as pt_repo

        record = pt_repo.create_participant(
            pg_runtime_conn,
            display_name="Test User",
            access_token_hash="hash123",
        )
        assert record.id
        assert record.display_name == "Test User"

        fetched = pt_repo.get_participant_by_id(pg_runtime_conn, record.id)
        assert fetched is not None
        assert fetched.display_name == "Test User"

    def test_duplicate_access_token_rejected(self, pg_runtime_conn):
        from app import participant_repository as pt_repo

        pt_repo.create_participant(
            pg_runtime_conn,
            display_name="User 1",
            access_token_hash="same_hash",
        )

        with pytest.raises(pt_repo.DuplicateParticipantError):
            pt_repo.create_participant(
                pg_runtime_conn,
                display_name="User 2",
                access_token_hash="same_hash",
            )


class TestInputRepositoryPg:
    """Input repository works with PostgreSQL."""

    def test_create_input_with_sequence(self, pg_runtime_conn):
        from app import input_repository as input_repo
        from app import participant_repository as pt_repo

        participant = pt_repo.create_participant(
            pg_runtime_conn,
            display_name="Test User",
            access_token_hash="hash123",
        )

        inp1 = input_repo.create_input(
            pg_runtime_conn,
            participant_id=participant.id,
            raw_text="First input",
        )
        assert inp1.sequence_number == 1

        inp2 = input_repo.create_input(
            pg_runtime_conn,
            participant_id=participant.id,
            raw_text="Second input",
        )
        assert inp2.sequence_number == 2

    def test_row_lock_suffix_applied(self, pg_runtime_conn):
        """Verify FOR UPDATE is used for participant row lock."""
        assert pg_runtime_conn.row_lock_suffix == " FOR UPDATE"


class TestEditionRepositoryPg:
    """Edition repository works with PostgreSQL."""

    def test_create_edition(self, pg_runtime_conn):
        from app import edition_repository as ed_repo
        from app import participant_repository as pt_repo

        participant = pt_repo.create_participant(
            pg_runtime_conn,
            display_name="Test User",
            access_token_hash="hash123",
        )

        edition = ed_repo.create_edition(
            pg_runtime_conn,
            participant_id=participant.id,
            edition_number=1,
            structured_content='{"sections": []}',
            rendered_title="Test Edition",
        )
        assert edition.id
        assert edition.edition_number == 1
        assert edition.publication_state == "pending"


class TestFeedbackRepositoryPg:
    """Feedback repository works with PostgreSQL."""

    def test_create_feedback(self, pg_runtime_conn):
        from app import edition_repository as ed_repo
        from app import feedback_repository as fb_repo
        from app import participant_repository as pt_repo

        participant = pt_repo.create_participant(
            pg_runtime_conn,
            display_name="Test User",
            access_token_hash="hash123",
        )

        edition = ed_repo.create_edition(
            pg_runtime_conn,
            participant_id=participant.id,
            edition_number=1,
            structured_content='{"sections": []}',
            rendered_title="Test Edition",
        )

        feedback = fb_repo.create_feedback(
            pg_runtime_conn,
            participant_id=participant.id,
            edition_id=edition.id,
            direction_choices='["more_practical"]',
        )
        assert feedback.id
        assert feedback.applied_to_next_edition == 0


class TestGenerationRunRepositoryPg:
    """Generation run repository works with PostgreSQL."""

    def test_create_and_update_generation_run(self, pg_runtime_conn):
        from app import generation_run_repository as gr_repo

        run = gr_repo.create_generation_run(
            pg_runtime_conn,
            task_type="first_edition",
            provider="mock",
            advertised_model="mock-v1",
        )
        assert run.id
        assert run.success == 0

        updated = gr_repo.update_generation_run(
            pg_runtime_conn,
            run.id,
            success=1,
            validation_status="passed",
        )
        assert updated is not None
        assert updated.success == 1
        assert updated.validation_status == "passed"
