"""Real PostgreSQL backend integration tests.

These run against an actual PostgreSQL 16+ server. Set LT_TEST_PG_URL to a
test database URL to enable. They are skipped when the variable is absent or
the server is unreachable, so the default SQLite suite stays network-free.

Covers: fresh migration, idempotent rerun, CRUD, transaction rollback, unique
constraints, foreign keys, the full first-edition workflow, feedback binding,
and close/reconnect durability.
"""

from __future__ import annotations

import os

import pytest

PG_URL = os.environ.get("LT_TEST_PG_URL", "")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="LT_TEST_PG_URL not set; skipping real PostgreSQL tests"
)

_LT_TABLES = [
    "deactivation_requests",
    "traveler_sessions",
    "traveler_tokens",
    "operator_sessions",
    "feedback",
    "editions",
    "travel_inputs",
    "sources",
    "generation_runs",
    "pilot_evidence",
    "external_identities",
    "travelers",
    "schema_migrations",
]


def _raw_connect(url: str):
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


@pytest.fixture()
def pg_url():
    try:
        conn = _raw_connect(PG_URL)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unreachable: {exc.__class__.__name__}")
    return PG_URL


@pytest.fixture()
def pg_env(pg_url, monkeypatch):
    monkeypatch.setenv("LT_DATABASE_BACKEND", "postgresql")
    monkeypatch.setenv("LT_AUTH_MODE", "legacy")
    monkeypatch.setenv("LT_ENVIRONMENT", "testing")
    monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
    monkeypatch.setenv("LT_DATABASE_URL", pg_url)
    monkeypatch.setenv("LT_MIGRATION_DATABASE_URL", pg_url)
    from app.config import reset_settings

    reset_settings()
    yield pg_url
    reset_settings()


@pytest.fixture()
def pg_clean_schema(pg_env):
    conn = _raw_connect(pg_env)
    with conn.cursor() as cur:
        for table in _LT_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    conn.close()
    return pg_env


@pytest.fixture()
def pg_conn(pg_clean_schema):
    from app.db import apply_migrations, get_connection

    apply_migrations()
    conn = get_connection()
    yield conn
    conn.close()


class TestPostgresMigrations:
    def test_fresh_migration_creates_tables(self, pg_clean_schema):
        from app.db import apply_migrations

        apply_migrations()
        conn = _raw_connect(pg_clean_schema)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            tables = {row["table_name"] for row in cur.fetchall()}
        conn.close()
        assert {
            "travelers",
            "sources",
            "travel_inputs",
            "editions",
            "feedback",
            "generation_runs",
            "pilot_evidence",
            "operator_sessions",
            "traveler_tokens",
            "traveler_sessions",
            "deactivation_requests",
            "schema_migrations",
        }.issubset(tables)

    def test_migration_rerun_is_idempotent(self, pg_clean_schema):
        from app.db import apply_migrations

        apply_migrations()
        apply_migrations()
        conn = _raw_connect(pg_clean_schema)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM schema_migrations")
            count = cur.fetchone()["n"]
        conn.close()
        assert count == 5

    def test_schema_migrations_records_filenames(self, pg_clean_schema):
        from app.db import apply_migrations

        apply_migrations()
        conn = _raw_connect(pg_clean_schema)
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
            names = [row["filename"] for row in cur.fetchall()]
        conn.close()
        assert names[0] == "001_initial.sql"
        assert names[-1] == "005_deactivation_request_constraints.sql"


class TestPostgresConnection:
    def test_get_connection_returns_pg_backend(self, pg_conn):
        assert getattr(pg_conn, "backend", "sqlite") == "postgresql"

    def test_reconnect_durability(self, pg_conn):
        from app.db import get_connection
        from app.traveler_repository import create_traveler, get_traveler_by_id

        rec = create_traveler(pg_conn, display_name="Durable", destination="Busan")
        pg_conn.close()

        conn2 = get_connection()
        try:
            fetched = get_traveler_by_id(conn2, rec.id)
        finally:
            conn2.close()
        assert fetched is not None
        assert fetched.display_name == "Durable"


class TestPostgresRepositoryParity:
    def test_traveler_crud(self, pg_conn):
        from app.traveler_repository import (
            create_traveler,
            get_traveler_by_id,
            update_traveler_preferences,
            delete_traveler,
            get_traveler_by_id_admin,
        )

        rec = create_traveler(
            pg_conn,
            display_name="Alice",
            destination="Seoul",
            trip_duration_nights=3,
            interests=["food", "history"],
        )
        assert rec.id.startswith("trav_")
        assert rec.interests == ["food", "history"]

        fetched = get_traveler_by_id(pg_conn, rec.id)
        assert fetched is not None
        assert fetched.destination == "Seoul"

        assert update_traveler_preferences(
            pg_conn, rec.id, destination="Jeju", trip_duration_nights=5
        )
        updated = get_traveler_by_id(pg_conn, rec.id)
        assert updated.destination == "Jeju"
        assert updated.trip_duration_nights == 5

        assert delete_traveler(pg_conn, rec.id)
        assert get_traveler_by_id(pg_conn, rec.id) is None
        assert get_traveler_by_id_admin(pg_conn, rec.id) is not None

    def test_unique_edition_number_constraint(self, pg_conn):
        import psycopg
        from app.traveler_repository import create_traveler
        from app.edition_repository import create_edition

        rec = create_traveler(pg_conn, display_name="Bob", destination="Osaka")
        create_edition(pg_conn, traveler_id=rec.id, edition_number=1)
        with pytest.raises(Exception):
            create_edition(pg_conn, traveler_id=rec.id, edition_number=1)
        pg_conn.rollback()

    def test_foreign_key_enforced(self, pg_conn):
        import psycopg

        with pytest.raises(Exception):
            pg_conn.execute(
                "INSERT INTO travel_inputs "
                "(id, traveler_id, sequence_number, raw_text, destination) "
                "VALUES (?, ?, ?, ?, ?)",
                ("in_x", "nonexistent_traveler", 1, "text", "Seoul"),
            )
        pg_conn.rollback()

    def test_transaction_rollback(self, pg_conn):
        from app.traveler_repository import create_traveler, get_traveler_by_id

        rec = create_traveler(pg_conn, display_name="Carol", destination="Hanoi")
        try:
            pg_conn.execute(
                "UPDATE travelers SET destination = ? WHERE id = ?",
                ("Rolled Back", rec.id),
            )
            raise RuntimeError("force rollback")
        except RuntimeError:
            pg_conn.rollback()
        fetched = get_traveler_by_id(pg_conn, rec.id)
        assert fetched.destination == "Hanoi"

    def test_deactivation_request_idempotent(self, pg_conn):
        from app.traveler_repository import create_traveler
        from app.deactivation_repository import create_deactivation_request

        rec = create_traveler(pg_conn, display_name="Dan", destination="Lisbon")
        with pg_conn:
            create_deactivation_request(pg_conn, rec.id)
        with pg_conn:
            create_deactivation_request(pg_conn, rec.id)
        rows = pg_conn.execute(
            "SELECT COUNT(*) AS n FROM deactivation_requests "
            "WHERE traveler_id = ? AND status = 'pending'",
            (rec.id,),
        ).fetchone()
        assert rows["n"] == 1


class TestPostgresFullWorkflow:
    def test_first_edition_publish_feedback_second(self, pg_conn):
        from app.traveler_repository import create_traveler
        from app.edition_repository import (
            create_edition,
            get_editions_by_traveler,
            get_edition_by_id,
            update_edition_publication,
        )
        from app.feedback_repository import create_feedback, get_feedback_by_edition

        traveler = create_traveler(
            pg_conn, display_name="Edith", destination="Kyoto", trip_duration_nights=4
        )

        first = create_edition(pg_conn, traveler_id=traveler.id, edition_number=1)
        assert first.publication_state == "pending"

        update_edition_publication(pg_conn, first.id, "published")
        published = get_edition_by_id(pg_conn, first.id)
        assert published.publication_state == "published"

        create_feedback(
            pg_conn,
            traveler_id=traveler.id,
            edition_id=first.id,
            direction_choices=["more food"],
            free_text="loved it",
        )
        fb = get_feedback_by_edition(pg_conn, first.id)
        assert len(fb) == 1
        assert fb[0].traveler_id == traveler.id

        second = create_edition(
            pg_conn,
            traveler_id=traveler.id,
            edition_number=2,
            prior_edition_id=first.id,
        )
        assert second.edition_number == 2

        editions = get_editions_by_traveler(pg_conn, traveler.id)
        assert len(editions) == 2
