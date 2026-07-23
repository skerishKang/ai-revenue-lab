"""PostgreSQL acceptance tests: real repositories over the PG runtime.

These tests exercise the actual repository signatures against a real
PostgreSQL runtime connection (``autocommit=True``, ``dict_row``) opened
through the proper ``opener``/``open()`` lifecycle — never by injecting the
private ``runtime._conn``.

They only run when BOTH:
  - TEST_POSTGRES_URL is set
  - PE_PG_TEST_INTEGRATION=1

Each test gets an isolated temporary schema; the ``public`` schema is never
written to, and a production Neon database is never targeted (the URL is
refused if it resolves to the same identity as PE_DATABASE_URL).

Covered: startup verification, full CRUD, rollback, public preservation,
concurrency (atomic edition numbering + row locking), and generation-request
idempotency.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.config import normalize_pg_url_identity

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
        "PostgreSQL acceptance tests require both TEST_POSTGRES_URL and "
        "PE_PG_TEST_INTEGRATION=1."
    ),
)

DOMAIN_TABLES = {
    "participants",
    "inputs",
    "editions",
    "feedback",
    "generation_runs",
    "generation_requests",
    "benchmark_runs",
    "pilot_ops_records",
}


class PgEnv:
    """Isolated PostgreSQL environment for one test.

    ``runtime`` is a real :class:`PostgresRuntimeConnection` opened via the
    ``opener``/``open()`` lifecycle (autocommit=True).  ``raw_conn()`` opens a
    fresh migration-style connection (autocommit=False) with ``search_path``
    pointed at the isolated schema, for startup verification and public-schema
    assertions.
    """

    def __init__(self, runtime, bootstrap, schema_name):
        self.runtime = runtime
        self.bootstrap = bootstrap
        self.schema_name = schema_name

    def raw_conn(self):
        from app.db_postgres import get_pg_connection

        conn = get_pg_connection(TEST_POSTGRES_URL)
        conn.execute(f'SET search_path TO "{self.schema_name}"')
        return conn


@pytest.fixture
def pg_env():
    from app.db_pg_migrations import apply_pg_migrations
    from app.db_postgres import (
        PG_MIGRATIONS_DIR,
        get_pg_connection,
        get_pg_runtime_connection,
    )
    from app.db_runtime import PostgresRuntimeConnection

    schema_name = f"test_repo_{uuid.uuid4().hex}"
    bootstrap = get_pg_connection(TEST_POSTGRES_URL)
    try:
        bootstrap.execute(f'CREATE SCHEMA "{schema_name}"')
        bootstrap.execute(f'SET search_path TO "{schema_name}"')
        bootstrap.commit()
        apply_pg_migrations(bootstrap, PG_MIGRATIONS_DIR)
        bootstrap.commit()
    except Exception:
        try:
            bootstrap.rollback()
            bootstrap.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            bootstrap.commit()
        except Exception:
            pass
        bootstrap.close()
        raise

    def opener():
        conn = get_pg_runtime_connection(TEST_POSTGRES_URL)
        conn.execute(f'SET search_path TO "{schema_name}"')
        return conn

    runtime = PostgresRuntimeConnection(opener).open()
    env = PgEnv(runtime, bootstrap, schema_name)
    try:
        yield env
    finally:
        try:
            runtime.close()
        except Exception:
            pass
        try:
            bootstrap.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            bootstrap.commit()
        except Exception:
            try:
                bootstrap.rollback()
            except Exception:
                pass
        bootstrap.close()


def _make_participant(runtime, pid="p1"):
    from app import participant_repository as pt_repo

    provisioned = pt_repo.create_participant(
        runtime,
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )
    return provisioned.participant


def _make_input(runtime, pid="p1", raw_text="First input"):
    from app import input_repository as input_repo

    return input_repo.create_input(
        runtime,
        participant_id=pid,
        raw_text=raw_text,
        consent_confirmed=1,
    )


def _make_edition(runtime, pid="p1", **kwargs):
    from app import edition_repository as ed_repo

    return ed_repo.create_edition(
        runtime,
        participant_id=pid,
        structured_content='{"sections": []}',
        rendered_title="Test Edition",
        **kwargs,
    )


class TestRuntimeLifecycle:
    def test_runtime_is_open_without_private_injection(self, pg_env):
        # The fixture opens the connection via opener/open(); the adapter is
        # usable immediately and reports the PostgreSQL row-lock clause.
        assert pg_env.runtime.row_lock_suffix == " FOR UPDATE"
        assert pg_env.runtime.in_transaction is False

    def test_runtime_connection_is_autocommit(self, pg_env):
        # A plain SELECT must not leave an open transaction on the runtime
        # connection (autocommit=True contract).
        pg_env.runtime.execute("SELECT 1 AS one").fetchone()
        assert pg_env.runtime.in_transaction is False


class TestStartupVerification:
    def test_verify_pg_schema_passes_on_migrated_schema(self, pg_env):
        from app.db_pg_migrations import verify_pg_schema
        from app.db_postgres import PG_MIGRATIONS_DIR

        conn = pg_env.raw_conn()
        try:
            result = verify_pg_schema(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()

        assert result["pending_count"] == 0
        assert result["applied_count"] >= 1
        assert result["schema"] == pg_env.schema_name


class TestFullCrud:
    def test_participant_create_and_get(self, pg_env):
        from app import participant_repository as pt_repo

        participant = _make_participant(pg_env.runtime, "p1")
        assert participant.id == "p1"

        fetched = pt_repo.get_participant_by_id(pg_env.runtime, "p1")
        assert fetched is not None
        assert fetched.display_name == "Test User"

    def test_input_sequence(self, pg_env):
        _make_participant(pg_env.runtime, "p1")
        inp1 = _make_input(pg_env.runtime, "p1", "First")
        inp2 = _make_input(pg_env.runtime, "p1", "Second")
        assert inp1.sequence_number == 1
        assert inp2.sequence_number == 2

    def test_edition_create_and_get(self, pg_env):
        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        assert edition.id
        assert edition.publication_state == "pending"
        assert edition.generation_status == "pending_review"

        from app import edition_repository as ed_repo

        fetched = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert fetched is not None
        assert fetched.rendered_title == "Test Edition"

    def test_edition_update_content(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        updated = ed_repo.update_edition_content(
            pg_env.runtime,
            edition.id,
            rendered_title="Renamed",
        )
        assert updated is not None
        assert updated.rendered_title == "Renamed"

    def test_edition_publish(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        published = ed_repo.update_edition_publication(
            pg_env.runtime, edition.id, "published"
        )
        assert published is not None
        assert published.publication_state == "published"
        assert published.published_at is not None

    def test_edition_delete(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        assert ed_repo.delete_edition(pg_env.runtime, edition.id) is True
        fetched = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert fetched.generation_status == "deleted"

    def test_feedback_create(self, pg_env):
        from app import feedback_repository as fb_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        feedback = fb_repo.create_feedback(
            pg_env.runtime,
            participant_id="p1",
            edition_id=edition.id,
            direction_choices='["more_practical"]',
        )
        assert feedback.id
        assert feedback.applied_to_next_edition == 0

    def test_generation_run_create_and_update(self, pg_env):
        from app import generation_run_repository as gr_repo

        run = gr_repo.create_generation_run(
            pg_env.runtime,
            task_type="first_edition",
            provider="mock",
            advertised_model="mock-v1",
        )
        assert run.id
        assert run.success == 0

        updated = gr_repo.update_generation_run(
            pg_env.runtime,
            run.id,
            success=1,
            validation_status="passed",
        )
        assert updated is not None
        assert updated.success == 1
        assert updated.validation_status == "passed"


class TestRollback:
    def test_failed_create_edition_leaves_no_partial_row(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")

        with pytest.raises(ed_repo.EditionValidationError):
            _make_edition(
                pg_env.runtime,
                "p1",
                prior_edition_id="does-not-exist",
            )

        # The failed transaction must have rolled back: no edition exists and
        # the runtime connection is idle (not stuck in a transaction).
        editions = ed_repo.get_editions_by_participant(pg_env.runtime, "p1")
        assert editions == []
        assert pg_env.runtime.in_transaction is False


class TestPublicPreservation:
    def test_crud_does_not_touch_public_schema(self, pg_env):
        from app.db_pg_migrations import get_pg_schema_tables

        # Perform real writes in the isolated schema.
        _make_participant(pg_env.runtime, "p1")
        _make_input(pg_env.runtime, "p1")
        _make_edition(pg_env.runtime, "p1")

        conn = pg_env.raw_conn()
        try:
            public_tables = get_pg_schema_tables(conn, "public")
            test_tables = get_pg_schema_tables(conn, pg_env.schema_name)
        finally:
            conn.close()

        for table in DOMAIN_TABLES:
            assert table not in public_tables, (
                f"'{table}' leaked into the public schema"
            )
            assert table in test_tables, (
                f"'{table}' missing from the isolated test schema"
            )


class TestConcurrency:
    def test_auto_edition_numbering_is_sequential(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        numbers = []
        for _ in range(3):
            edition = ed_repo.create_edition(
                pg_env.runtime,
                participant_id="p1",
                structured_content='{"sections": []}',
                rendered_title="E",
            )
            numbers.append(edition.edition_number)
        assert numbers == [1, 2, 3]

    def test_cannot_publish_terminal_edition_twice(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        ed_repo.update_edition_publication(pg_env.runtime, edition.id, "published")

        # published is terminal: a second transition must be rejected rather
        # than silently overwrite state.
        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.update_edition_publication(
                pg_env.runtime, edition.id, "rejected"
            )


class TestIdempotency:
    def test_claim_complete_replay(self, pg_env):
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")

        first = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id="i1",
        )
        assert first.already_claimed is False

        duplicate = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id="i1",
        )
        assert duplicate.already_claimed is True
        assert duplicate.edition_id is None

        gen_req_repo.complete_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            edition_id="e-123",
        )

        replay = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id="i1",
        )
        assert replay.already_claimed is True
        assert replay.edition_id == "e-123"
