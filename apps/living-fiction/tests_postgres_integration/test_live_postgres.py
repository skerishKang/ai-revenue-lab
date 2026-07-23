"""Live PostgreSQL integration tests for Living Fiction (opt-in).

These tests are NOT collected by the default suite (``testpaths = ["tests"]``
in pyproject.toml excludes this directory). They run ONLY when an operator
points them at a disposable local PostgreSQL database:

    LF_TEST_POSTGRES_URL=postgresql://user:password@localhost:5432/lf_it \
        python -m pytest tests_postgres_integration/ -q

WARNING: the tests DROP and CREATE the schemas ``lf_it_main``, ``lf_it_empty``
and ``lf_it_tamper`` inside the target database. Never point this at a database
that holds data you care about.

Covered live behaviour:

* fresh migration apply + idempotent re-apply + ``verify_schema_current``
* fail-closed verification against an empty schema
* checksum tamper detection
* ``?`` placeholder / ``INSERT OR IGNORE`` / ``BEGIN IMMEDIATE`` adaptation
* operator bootstrap seeding idempotency and digest-only invite storage
* uniqueness violations surfacing as the neutral IntegrityError
* the reader-deletion privacy trigger (anonymize once, never re-anonymize)
* bounded pool acquire/release and scale-to-zero defaults
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from app import auth
from app import reader_repository as reader_repo
from app.database.errors import IntegrityError as NeutralIntegrityError
from app.database.errors import SchemaMismatchError
from app.database.migrate_postgres import (
    PostgresMigrationError,
    applied_migrations,
    apply_migrations,
    expected_versions,
    verify_schema_current,
)
from app.database.pool import (
    DEFAULT_POOL_MAX_SIZE,
    DEFAULT_POOL_MIN_SIZE,
    PostgresPool,
)
from app.database.postgres import connect_postgres
from app.ops import bootstrap
from app.preview_data import WORLD_STATE
from app.utils import new_id, now_utc_iso

APP_ROOT = Path(__file__).resolve().parent.parent
PG_MIGRATIONS_DIR = APP_ROOT / "migrations_postgres"

TEST_URL_ENV = "LF_TEST_POSTGRES_URL"

_pg_url = os.environ.get(TEST_URL_ENV, "").strip()
if not _pg_url:
    pytest.skip(
        f"{TEST_URL_ENV} is not set — live PostgreSQL integration is opt-in "
        "and never runs in the default suite; point it at a disposable "
        "local database to run explicitly",
        allow_module_level=True,
    )

HMAC_KEY = "live-integration-hmac-key-0123456789"


def _with_search_path(url: str, schema: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options=-csearch_path%3D{schema}"


def _reset_schema(schema: str) -> None:
    import psycopg  # noqa: PLC0415

    raw = psycopg.connect(_pg_url, autocommit=True)
    try:
        raw.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        raw.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        raw.close()


def _drop_schema(schema: str) -> None:
    import psycopg  # noqa: PLC0415

    raw = psycopg.connect(_pg_url, autocommit=True)
    try:
        raw.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        raw.close()


@pytest.fixture(scope="session")
def migrated_url():
    """A fully migrated schema, reset once per session."""
    schema = "lf_it_main"
    _reset_schema(schema)
    url = _with_search_path(_pg_url, schema)
    conn = connect_postgres(url)
    try:
        newly = apply_migrations(conn, PG_MIGRATIONS_DIR)
        assert newly == expected_versions(PG_MIGRATIONS_DIR)
        verify_schema_current(conn, PG_MIGRATIONS_DIR)
    finally:
        conn.close()
    yield url
    _drop_schema(schema)


@pytest.fixture()
def pg_conn(migrated_url):
    conn = connect_postgres(migrated_url)
    yield conn
    conn.close()


# ── Migration runner ────────────────────────────────────────────────────────


def test_reapply_is_noop_and_verify_passes(pg_conn):
    assert apply_migrations(pg_conn, PG_MIGRATIONS_DIR) == []
    verify_schema_current(pg_conn, PG_MIGRATIONS_DIR)
    applied = applied_migrations(pg_conn)
    assert set(applied) == set(expected_versions(PG_MIGRATIONS_DIR))


def test_verify_fails_closed_on_empty_schema():
    schema = "lf_it_empty"
    _reset_schema(schema)
    try:
        conn = connect_postgres(_with_search_path(_pg_url, schema))
        try:
            with pytest.raises(SchemaMismatchError, match="missing=10"):
                verify_schema_current(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()
    finally:
        _drop_schema(schema)


def test_checksum_tamper_is_detected(tmp_path):
    schema = "lf_it_tamper"
    _reset_schema(schema)
    try:
        conn = connect_postgres(_with_search_path(_pg_url, schema))
        try:
            apply_migrations(conn, PG_MIGRATIONS_DIR)
            tampered_dir = tmp_path / "migrations"
            shutil.copytree(PG_MIGRATIONS_DIR, tampered_dir)
            target = tampered_dir / "010_triggers.sql"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n-- tampered\n",
                encoding="utf-8",
            )
            with pytest.raises(PostgresMigrationError, match="checksum mismatch"):
                apply_migrations(conn, tampered_dir)
        finally:
            conn.close()
    finally:
        _drop_schema(schema)


# ── Runtime adapter against a live server ───────────────────────────────────


def test_placeholder_transaction_and_insert_or_ignore_adaptation(pg_conn):
    world_id = "it-world-insert-or-ignore"
    params = (world_id, "v1", "premise", "{}", now_utc_iso())
    insert_sql = (
        "INSERT OR IGNORE INTO worlds "
        "(id, version, premise, world_rules, created_at) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    pg_conn.execute("BEGIN IMMEDIATE")
    assert pg_conn.in_transaction
    first = pg_conn.execute(insert_sql, params)
    assert first.rowcount == 1
    duplicate = pg_conn.execute(insert_sql, params)
    assert duplicate.rowcount == 0
    pg_conn.execute("COMMIT")
    assert not pg_conn.in_transaction

    row = pg_conn.execute(
        "SELECT COUNT(*) AS n FROM worlds WHERE id = ?", (world_id,)
    ).fetchone()
    assert row["n"] == 1


# ── Operator bootstrap semantics ────────────────────────────────────────────


def test_bootstrap_seeding_is_idempotent(pg_conn):
    assert bootstrap.ensure_canon(pg_conn) is True
    assert bootstrap.ensure_world(pg_conn) is False
    assert bootstrap.ensure_canon(pg_conn) is False

    canon_rows = pg_conn.execute(
        "SELECT id, review_state FROM episodes "
        "WHERE world_id = ? AND episode_type = 'canon'",
        (WORLD_STATE.world_id,),
    ).fetchall()
    assert len(canon_rows) == 1
    assert canon_rows[0]["review_state"] == "published"

    reader_a = bootstrap.ensure_bootstrap_reader(pg_conn)
    reader_b = bootstrap.ensure_bootstrap_reader(pg_conn)
    assert reader_a == reader_b


def test_invite_is_stored_as_digest_only_and_rotates(pg_conn):
    bootstrap.ensure_canon(pg_conn)
    reader_id = bootstrap.ensure_bootstrap_reader(pg_conn)

    code = bootstrap.issue_invite(pg_conn, HMAC_KEY, reader_id)
    assert auth.verify_invite_code(pg_conn, code, HMAC_KEY) == reader_id

    row = pg_conn.execute(
        "SELECT * FROM invite_credentials WHERE bound_reader_id = ? "
        "AND revoked_at IS NULL",
        (reader_id,),
    ).fetchone()
    assert row is not None
    stored_values = {str(v) for v in row.values() if v is not None}
    assert code not in stored_values

    assert bootstrap.active_bound_invite_id(pg_conn) is not None
    assert bootstrap.revoke_active_bound_invites(pg_conn) >= 1
    assert auth.verify_invite_code(pg_conn, code, HMAC_KEY) is None
    assert bootstrap.active_bound_invite_id(pg_conn) is None

    replacement = bootstrap.issue_invite(pg_conn, HMAC_KEY, reader_id)
    assert auth.verify_invite_code(pg_conn, replacement, HMAC_KEY) == reader_id


def test_duplicate_invite_code_raises_neutral_integrity_error(pg_conn):
    bootstrap.ensure_canon(pg_conn)
    reader_id = bootstrap.ensure_bootstrap_reader(pg_conn)
    code = auth.generate_invite_code()
    auth.create_invite_credential(
        pg_conn, code, HMAC_KEY, bound_reader_id=reader_id
    )
    with pytest.raises(NeutralIntegrityError) as excinfo:
        auth.create_invite_credential(
            pg_conn, code, HMAC_KEY, bound_reader_id=reader_id
        )
    assert not isinstance(excinfo.value, sqlite3.Error)
    assert _pg_url not in str(excinfo.value)


# ── Reader-deletion privacy trigger ─────────────────────────────────────────


def test_reader_deletion_trigger_anonymizes_request_keys_once(pg_conn):
    bootstrap.ensure_canon(pg_conn)
    reader_id = reader_repo.create_reader(
        pg_conn, display_name=f"it-trigger-{new_id()}"
    ).id
    canon_episode_id = pg_conn.execute(
        "SELECT id FROM episodes WHERE world_id = ? AND episode_type = 'canon' "
        "ORDER BY episode_number ASC LIMIT 1",
        (WORLD_STATE.world_id,),
    ).fetchone()["id"]
    checkpoint_id = pg_conn.execute(
        "SELECT id FROM canon_checkpoints ORDER BY episode_number ASC LIMIT 1"
    ).fetchone()["id"]
    choice_id = new_id()
    pg_conn.execute(
        "INSERT INTO reader_choices "
        "(id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (choice_id, reader_id, canon_episode_id, "trigger-test", now_utc_iso()),
    )
    request_id = new_id()
    original_key = f"original-idem-{new_id()}"
    pg_conn.execute(
        "INSERT INTO branch_generation_requests "
        "(id, idempotency_key, reader_id, reader_choice_id, prior_episode_id, "
        "canon_checkpoint_id, world_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request_id,
            original_key,
            reader_id,
            choice_id,
            canon_episode_id,
            checkpoint_id,
            WORLD_STATE.world_id,
            now_utc_iso(),
        ),
    )

    pg_conn.execute(
        "UPDATE readers SET status = 'deleted' WHERE id = ?", (reader_id,)
    )
    anonymized = pg_conn.execute(
        "SELECT idempotency_key FROM branch_generation_requests WHERE id = ?",
        (request_id,),
    ).fetchone()["idempotency_key"]
    assert anonymized.startswith("anon-idem-")
    assert anonymized != original_key
    assert request_id in anonymized

    pg_conn.execute(
        "UPDATE readers SET status = 'active' WHERE id = ?", (reader_id,)
    )
    pg_conn.execute(
        "UPDATE readers SET status = 'deleted' WHERE id = ?", (reader_id,)
    )
    again = pg_conn.execute(
        "SELECT idempotency_key FROM branch_generation_requests WHERE id = ?",
        (request_id,),
    ).fetchone()["idempotency_key"]
    assert again == anonymized


# ── Bounded pool ────────────────────────────────────────────────────────────


def test_pool_is_bounded_and_returns_connections(migrated_url):
    from psycopg_pool import PoolTimeout  # noqa: PLC0415

    assert DEFAULT_POOL_MIN_SIZE == 0
    assert DEFAULT_POOL_MAX_SIZE == 5

    pool = PostgresPool(migrated_url, min_size=0, max_size=1, timeout=1.0)
    pool.open()
    try:
        first = pool.acquire()
        assert first.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        with pytest.raises(PoolTimeout):
            pool.acquire()
        first.close()
        second = pool.acquire()
        assert second.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        second.close()
    finally:
        pool.close()
