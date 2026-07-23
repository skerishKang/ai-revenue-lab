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

import copy
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
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
from app.preview_data import BRANCH_EPISODE_CONTENT, BRANCH_EPISODE_PLAN, WORLD_STATE
from app.utils import new_id, now_utc_iso

import pg_provision

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


def _schema_objects(schema: str) -> list[tuple[str, str]]:
    """Snapshot (name, kind) of every relation in a schema, as the owner."""
    import psycopg  # noqa: PLC0415
    from psycopg.rows import dict_row  # noqa: PLC0415

    raw = psycopg.connect(_pg_url, autocommit=True, row_factory=dict_row)
    try:
        cur = raw.execute(
            "SELECT c.relname, c.relkind::text AS relkind "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s ORDER BY c.relname, c.relkind",
            (schema,),
        )
        return [(r["relname"], r["relkind"]) for r in cur.fetchall()]
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


@pytest.fixture(scope="session")
def runtime_url(migrated_url):
    """A restricted runtime-role URL for the migrated schema (DML, no DDL)."""
    pg_provision.ensure_runtime_role(_pg_url)
    pg_provision.grant_runtime_dml(_pg_url, "lf_it_main")
    pg_provision.revoke_runtime_create(_pg_url, "lf_it_main")
    return pg_provision.runtime_url(_pg_url, "lf_it_main")


# ── Migration runner ────────────────────────────────────────────────────────


def test_reapply_is_noop_and_verify_passes(pg_conn):
    assert apply_migrations(pg_conn, PG_MIGRATIONS_DIR) == []
    verify_schema_current(pg_conn, PG_MIGRATIONS_DIR)
    applied = applied_migrations(pg_conn)
    assert set(applied) == set(expected_versions(PG_MIGRATIONS_DIR))


def test_verify_absent_table_fails_closed_and_creates_nothing():
    schema = "lf_it_empty"
    _reset_schema(schema)
    try:
        before = _schema_objects(schema)
        conn = connect_postgres(_with_search_path(_pg_url, schema))
        try:
            with pytest.raises(SchemaMismatchError, match="migration table absent"):
                verify_schema_current(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()
        # A failed verification must leave the schema byte-for-byte unchanged.
        assert _schema_objects(schema) == before
    finally:
        _drop_schema(schema)


def test_verify_present_but_empty_table_reports_missing():
    schema = "lf_it_empty_tbl"
    _reset_schema(schema)
    try:
        url = _with_search_path(_pg_url, schema)
        import psycopg  # noqa: PLC0415

        raw = psycopg.connect(url, autocommit=True)
        try:
            raw.execute(
                "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, "
                "checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL "
                "DEFAULT now())"
            )
        finally:
            raw.close()
        conn = connect_postgres(url)
        try:
            with pytest.raises(SchemaMismatchError, match="missing=10"):
                verify_schema_current(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()
    finally:
        _drop_schema(schema)


def test_verify_rejects_unknown_applied_version():
    schema = "lf_it_unknown"
    _reset_schema(schema)
    try:
        conn = connect_postgres(_with_search_path(_pg_url, schema))
        try:
            apply_migrations(conn, PG_MIGRATIONS_DIR)
            conn.raw.execute(
                "INSERT INTO schema_migrations (version, checksum) "
                "VALUES ('999_bogus.sql', 'x')"
            )
            with pytest.raises(SchemaMismatchError, match="unknown=1"):
                verify_schema_current(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()
    finally:
        _drop_schema(schema)


def test_verify_rejects_stored_checksum_mismatch():
    schema = "lf_it_cksum"
    _reset_schema(schema)
    try:
        conn = connect_postgres(_with_search_path(_pg_url, schema))
        try:
            apply_migrations(conn, PG_MIGRATIONS_DIR)
            first = expected_versions(PG_MIGRATIONS_DIR)[0]
            conn.raw.execute(
                "UPDATE schema_migrations SET checksum = 'deadbeef' "
                "WHERE version = %s",
                (first,),
            )
            with pytest.raises(SchemaMismatchError, match="checksum_mismatch=1"):
                verify_schema_current(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()
    finally:
        _drop_schema(schema)


def test_runtime_role_verifies_current_schema_without_create_rights(runtime_url):
    conn = connect_postgres(runtime_url)
    try:
        verify_schema_current(conn, PG_MIGRATIONS_DIR)
    finally:
        conn.close()


def test_runtime_role_cannot_create_alter_drop(runtime_url):
    import psycopg  # noqa: PLC0415

    raw = psycopg.connect(runtime_url, autocommit=True)
    try:
        for stmt in (
            "CREATE TABLE lf_it_main.runtime_probe (id int)",
            "ALTER TABLE lf_it_main.worlds ADD COLUMN probe int",
            "DROP TABLE lf_it_main.worlds",
        ):
            with pytest.raises(psycopg.Error) as excinfo:
                raw.execute(stmt)
            assert excinfo.value.sqlstate == "42501"
    finally:
        raw.close()


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

    assert bootstrap.active_bound_invite_id(pg_conn, reader_id) is not None
    assert bootstrap.revoke_active_bound_invites(pg_conn, reader_id) >= 1
    assert auth.verify_invite_code(pg_conn, code, HMAC_KEY) is None
    assert bootstrap.active_bound_invite_id(pg_conn, reader_id) is None

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


# ── Repairable bootstrap: failure injection + concurrency (P0-2) ────────────


class _FailOnCall:
    """Wrap a callable to raise on exactly the Nth invocation, delegating
    otherwise. Lets a bootstrap step crash once at a precise point, then succeed
    on a later re-run (the call numbering shifts because already-created rows are
    skipped), proving convergent repair."""

    def __init__(self, fn, fail_on, exc):
        self.fn = fn
        self.fail_on = fail_on
        self.exc = exc
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self.fail_on:
            raise self.exc
        return self.fn(*args, **kwargs)


@pytest.fixture()
def fresh_bootstrap_conn():
    """A connection to a freshly migrated, isolated schema (per test)."""
    import uuid  # noqa: PLC0415

    schema = f"lf_it_boot_{uuid.uuid4().hex[:10]}"
    _reset_schema(schema)
    conn = connect_postgres(_with_search_path(_pg_url, schema))
    apply_migrations(conn, PG_MIGRATIONS_DIR)
    yield conn
    conn.close()
    _drop_schema(schema)


def _counts(conn):
    return {
        "worlds": conn.execute("SELECT COUNT(*) AS n FROM worlds").fetchone()["n"],
        "characters": conn.execute(
            "SELECT COUNT(*) AS n FROM characters"
        ).fetchone()["n"],
        "locations": conn.execute(
            "SELECT COUNT(*) AS n FROM locations"
        ).fetchone()["n"],
        "clues": conn.execute("SELECT COUNT(*) AS n FROM clues").fetchone()["n"],
        "snapshots": conn.execute(
            "SELECT COUNT(*) AS n FROM canon_snapshots"
        ).fetchone()["n"],
        "checkpoints": conn.execute(
            "SELECT COUNT(*) AS n FROM canon_checkpoints"
        ).fetchone()["n"],
        "canon_episodes": conn.execute(
            "SELECT COUNT(*) AS n FROM episodes WHERE episode_type = 'canon'"
        ).fetchone()["n"],
    }


def _assert_complete_world(conn):
    c = _counts(conn)
    assert c["worlds"] == 1
    assert c["characters"] == len(WORLD_STATE.characters)
    assert c["locations"] == len(WORLD_STATE.locations)
    assert c["clues"] == len(WORLD_STATE.clues)


def _assert_complete_canon(conn):
    c = _counts(conn)
    assert c["snapshots"] == 1
    assert c["checkpoints"] == 1
    assert c["canon_episodes"] == 1
    row = conn.execute(
        "SELECT review_state, canon_snapshot_id, canon_checkpoint_id "
        "FROM episodes WHERE episode_type = 'canon'"
    ).fetchone()
    assert row["review_state"] == "published"
    assert row["canon_snapshot_id"] == bootstrap.CANON_SNAPSHOT_ID
    assert row["canon_checkpoint_id"] == bootstrap.CANON_CHECKPOINT_ID


def test_failure_right_after_world_create_recovers(fresh_bootstrap_conn, monkeypatch):
    from app import world_repository as world_repo  # noqa: PLC0415

    monkeypatch.setattr(
        bootstrap.world_repo,
        "create_character",
        _FailOnCall(world_repo.create_character, 1, RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        bootstrap.ensure_world(fresh_bootstrap_conn)
    # World row exists but no children were created.
    assert _counts(fresh_bootstrap_conn)["worlds"] == 1
    assert _counts(fresh_bootstrap_conn)["characters"] == 0

    bootstrap.ensure_world(fresh_bootstrap_conn)
    _assert_complete_world(fresh_bootstrap_conn)


def test_failure_after_partial_characters_recovers(fresh_bootstrap_conn, monkeypatch):
    from app import world_repository as world_repo  # noqa: PLC0415

    monkeypatch.setattr(
        bootstrap.world_repo,
        "create_character",
        _FailOnCall(world_repo.create_character, 2, RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        bootstrap.ensure_world(fresh_bootstrap_conn)
    # Exactly one character survived the crash.
    assert _counts(fresh_bootstrap_conn)["characters"] == 1

    bootstrap.ensure_world(fresh_bootstrap_conn)
    _assert_complete_world(fresh_bootstrap_conn)


def test_failure_after_snapshot_create_recovers(fresh_bootstrap_conn, monkeypatch):
    from app import canon_repository as canon_repo  # noqa: PLC0415

    monkeypatch.setattr(
        bootstrap.canon_repo,
        "create_canon_checkpoint",
        _FailOnCall(canon_repo.create_canon_checkpoint, 1, RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        bootstrap.ensure_canon(fresh_bootstrap_conn)
    c = _counts(fresh_bootstrap_conn)
    assert c["snapshots"] == 1
    assert c["checkpoints"] == 0
    assert c["canon_episodes"] == 0

    bootstrap.ensure_canon(fresh_bootstrap_conn)
    _assert_complete_world(fresh_bootstrap_conn)
    _assert_complete_canon(fresh_bootstrap_conn)


def test_failure_after_checkpoint_create_recovers(fresh_bootstrap_conn, monkeypatch):
    orig = bootstrap._generate_first_canon_episode
    monkeypatch.setattr(
        bootstrap,
        "_generate_first_canon_episode",
        _FailOnCall(orig, 1, RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        bootstrap.ensure_canon(fresh_bootstrap_conn)
    c = _counts(fresh_bootstrap_conn)
    assert c["snapshots"] == 1
    assert c["checkpoints"] == 1
    assert c["canon_episodes"] == 0

    bootstrap.ensure_canon(fresh_bootstrap_conn)
    _assert_complete_canon(fresh_bootstrap_conn)


def test_failure_after_episode_before_publish_recovers(
    fresh_bootstrap_conn, monkeypatch
):
    from app import episode_repository as ep_repo  # noqa: PLC0415

    monkeypatch.setattr(
        bootstrap.ep_repo,
        "publish_episode",
        _FailOnCall(ep_repo.publish_episode, 1, RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        bootstrap.ensure_canon(fresh_bootstrap_conn)
    # Episode was generated but left unpublished.
    row = fresh_bootstrap_conn.execute(
        "SELECT review_state FROM episodes WHERE episode_type = 'canon'"
    ).fetchone()
    assert row["review_state"] == "pending_review"

    bootstrap.ensure_canon(fresh_bootstrap_conn)
    _assert_complete_canon(fresh_bootstrap_conn)


def test_failure_before_invite_issues_no_duplicate(fresh_bootstrap_conn, monkeypatch):
    orig = bootstrap.issue_invite
    monkeypatch.setattr(
        bootstrap, "issue_invite", _FailOnCall(orig, 1, RuntimeError("crash"))
    )
    reader_id = bootstrap.ensure_bootstrap_reader(fresh_bootstrap_conn)
    with pytest.raises(RuntimeError):
        bootstrap.ensure_active_invite(fresh_bootstrap_conn, HMAC_KEY, reader_id)
    assert bootstrap.active_bound_invite_id(fresh_bootstrap_conn, reader_id) is None

    bootstrap.ensure_active_invite(fresh_bootstrap_conn, HMAC_KEY, reader_id)
    active = fresh_bootstrap_conn.execute(
        "SELECT COUNT(*) AS n FROM invite_credentials "
        "WHERE bound_reader_id = ? AND revoked_at IS NULL",
        (reader_id,),
    ).fetchone()["n"]
    assert active == 1


def test_failure_after_invite_issues_no_duplicate(fresh_bootstrap_conn, monkeypatch):
    orig = bootstrap.issue_invite

    def create_then_crash(conn, hmac_key, reader_id):
        code = orig(conn, hmac_key, reader_id)  # invite row is committed...
        raise RuntimeError("crash right after issuing")  # ...then we "crash"

    monkeypatch.setattr(bootstrap, "issue_invite", create_then_crash)
    reader_id = bootstrap.ensure_bootstrap_reader(fresh_bootstrap_conn)
    with pytest.raises(RuntimeError):
        bootstrap.ensure_active_invite(fresh_bootstrap_conn, HMAC_KEY, reader_id)

    # Re-run sees the committed invite and must not create a second one.
    assert bootstrap.ensure_active_invite(fresh_bootstrap_conn, HMAC_KEY, reader_id) is None
    active = fresh_bootstrap_conn.execute(
        "SELECT COUNT(*) AS n FROM invite_credentials "
        "WHERE bound_reader_id = ? AND revoked_at IS NULL",
        (reader_id,),
    ).fetchone()["n"]
    assert active == 1


def test_world_conflict_fails_closed(fresh_bootstrap_conn):
    bootstrap.ensure_world(fresh_bootstrap_conn)
    fresh_bootstrap_conn.execute("BEGIN IMMEDIATE")
    fresh_bootstrap_conn.execute(
        "UPDATE worlds SET version = 'v999' WHERE id = ?", (WORLD_STATE.world_id,)
    )
    fresh_bootstrap_conn.commit()
    with pytest.raises(bootstrap.BootstrapConflictError, match="version"):
        bootstrap.ensure_world(fresh_bootstrap_conn)
    # The conflicting row was NOT overwritten.
    assert (
        fresh_bootstrap_conn.execute(
            "SELECT version FROM worlds WHERE id = ?", (WORLD_STATE.world_id,)
        ).fetchone()["version"]
        == "v999"
    )


def test_canon_duplicate_episode_fails_closed(fresh_bootstrap_conn):
    bootstrap.ensure_canon(fresh_bootstrap_conn)
    fresh_bootstrap_conn.execute("BEGIN IMMEDIATE")
    fresh_bootstrap_conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, title, "
        "synopsis, scene_list_json, character_ids_json, location_ids_json, "
        "prose_json, created_at) VALUES (?, ?, 'canon', 2, 'x', 'x', '[]', '[]', "
        "'[]', '[]', ?)",
        (new_id(), WORLD_STATE.world_id, now_utc_iso()),
    )
    fresh_bootstrap_conn.commit()
    with pytest.raises(bootstrap.BootstrapConflictError, match="canon episode"):
        bootstrap.ensure_canon(fresh_bootstrap_conn)


def test_concurrent_bootstrap_yields_single_entities():
    import threading  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    schema = f"lf_it_conc_{uuid.uuid4().hex[:10]}"
    _reset_schema(schema)
    url = _with_search_path(_pg_url, schema)
    setup = connect_postgres(url)
    try:
        apply_migrations(setup, PG_MIGRATIONS_DIR)
    finally:
        setup.close()

    results: list = []
    errors: list = []

    def worker():
        conn = connect_postgres(url)
        try:
            results.append(bootstrap.run_locked_bootstrap(conn, HMAC_KEY))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, f"concurrent bootstrap raised: {errors}"
        # Both operators converged on the same bootstrap reader.
        assert len(results) == 2
        assert results[0][0] == results[1][0]

        check = connect_postgres(url)
        try:
            c = _counts(check)
            assert c["worlds"] == 1
            assert c["canon_episodes"] == 1
            readers = check.execute(
                "SELECT COUNT(*) AS n FROM readers WHERE display_name = ?",
                (bootstrap.BOOTSTRAP_READER_NAME,),
            ).fetchone()["n"]
            assert readers == 1
            active_invites = check.execute(
                "SELECT COUNT(*) AS n FROM invite_credentials "
                "WHERE revoked_at IS NULL"
            ).fetchone()["n"]
            assert active_invites == 1
        finally:
            check.close()
    finally:
        _drop_schema(schema)


def test_multi_reader_invite_scoping_preserves_others(fresh_bootstrap_conn):
    reader_a = bootstrap.ensure_bootstrap_reader(fresh_bootstrap_conn)
    reader_b = reader_repo.create_reader(
        fresh_bootstrap_conn, display_name="다른 독서자"
    ).id

    code_b = bootstrap.issue_invite(fresh_bootstrap_conn, HMAC_KEY, reader_b)
    assert auth.verify_invite_code(fresh_bootstrap_conn, code_b, HMAC_KEY) == reader_b

    assert bootstrap.active_bound_invite_id(fresh_bootstrap_conn, reader_a) is None
    assert bootstrap.active_bound_invite_id(fresh_bootstrap_conn, reader_b) is not None

    bootstrap.issue_invite(fresh_bootstrap_conn, HMAC_KEY, reader_a)
    revoked = bootstrap.revoke_active_bound_invites(fresh_bootstrap_conn, reader_a)
    assert revoked == 1
    assert bootstrap.active_bound_invite_id(fresh_bootstrap_conn, reader_a) is None
    # Reader B's invite survives reader A's rotation.
    assert bootstrap.active_bound_invite_id(fresh_bootstrap_conn, reader_b) is not None
    assert auth.verify_invite_code(fresh_bootstrap_conn, code_b, HMAC_KEY) == reader_b


# ── P0-3: Full product flow with restricted runtime role ────────────────────

PRODUCT_ADMIN_SECRET = "pg-it-admin-secret-val"
PRODUCT_CREDENTIAL_KEY = HMAC_KEY
PRODUCT_SESSION_KEY = "pg-it-session-hmac-key-val"


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


@contextmanager
def _product_client(env):
    orig = {
        "database_backend": settings.database_backend,
        "database_url": settings.database_url,
        "admin_secret": settings.admin_secret,
        "credential_hmac_key": settings.credential_hmac_key,
        "session_hmac_key": settings.session_hmac_key,
    }
    settings.database_backend = "postgres"
    settings.database_url = env["runtime_url"]
    settings.admin_secret = PRODUCT_ADMIN_SECRET
    settings.credential_hmac_key = PRODUCT_CREDENTIAL_KEY
    settings.session_hmac_key = PRODUCT_SESSION_KEY
    app = None
    try:
        from app.factory import create_app  # noqa: PLC0415

        app = create_app()
        with TestClient(app, follow_redirects=False) as client:
            yield client
    finally:
        if app is not None:
            app.state.db_engine.close()
        for key, value in orig.items():
            setattr(settings, key, value)


def _login_reader_pg(client, invite_code):
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": invite_code, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _login_admin_pg(client):
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": PRODUCT_ADMIN_SECRET, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _fresh_reader_invite(env):
    conn = connect_postgres(env["owner_url"])
    try:
        reader = reader_repo.create_reader(
            conn, display_name=f"it-product-{new_id()}"
        )
        code = bootstrap.issue_invite(conn, HMAC_KEY, reader.id)
    finally:
        conn.close()
    return reader.id, code


@pytest.fixture(scope="session")
def product_env():
    schema = "lf_it_product"
    _reset_schema(schema)
    url = _with_search_path(_pg_url, schema)
    conn = connect_postgres(url)
    try:
        apply_migrations(conn, PG_MIGRATIONS_DIR)
    finally:
        conn.close()

    pg_provision.ensure_runtime_role(_pg_url)
    pg_provision.grant_runtime_dml(_pg_url, schema)
    pg_provision.revoke_runtime_create(_pg_url, schema)

    conn = connect_postgres(url)
    try:
        bootstrap.run_locked_bootstrap(conn, HMAC_KEY)
        reader_id = bootstrap.ensure_bootstrap_reader(conn)
        invite_code = bootstrap.issue_invite(conn, HMAC_KEY, reader_id)
    finally:
        conn.close()

    rt_url = pg_provision.runtime_url(_pg_url, schema)
    yield {
        "owner_url": url,
        "runtime_url": rt_url,
        "invite_code": invite_code,
        "reader_id": reader_id,
        "schema": schema,
    }
    _drop_schema(schema)


def test_product_invite_login_303(product_env):
    with _product_client(product_env) as client:
        _login_reader_pg(client, product_env["invite_code"])
        resp = client.get("/read", follow_redirects=False)
        assert resp.status_code == 200


def test_product_invite_code_not_stored_raw(product_env):
    conn = connect_postgres(product_env["owner_url"])
    try:
        rows = conn.execute("SELECT * FROM invite_credentials").fetchall()
        for row in rows:
            values = {str(v) for v in row.values() if v is not None}
            assert product_env["invite_code"] not in values
    finally:
        conn.close()


def test_product_session_stored_as_digest(product_env):
    with _product_client(product_env) as client:
        _login_reader_pg(client, product_env["invite_code"])
        raw_token = client.cookies.get(auth.READER_COOKIE_NAME)
        assert raw_token is not None

    conn = connect_postgres(product_env["owner_url"])
    try:
        rows = conn.execute("SELECT * FROM reader_sessions").fetchall()
        assert len(rows) > 0
        for row in rows:
            values = {str(v) for v in row.values() if v is not None}
            assert raw_token not in values
    finally:
        conn.close()


def test_product_admin_login_303(product_env):
    with _product_client(product_env) as client:
        _login_admin_pg(client)
        resp = client.get("/admin/review", follow_redirects=False)
        assert resp.status_code == 200


def test_product_reader_admin_session_separation(product_env):
    with _product_client(product_env) as client:
        _login_reader_pg(client, product_env["invite_code"])
        resp = client.get("/admin/review", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/access" in resp.headers["location"]


def test_product_canon_read_authenticated(product_env):
    with _product_client(product_env) as client:
        _login_reader_pg(client, product_env["invite_code"])
        resp = client.get("/read")
        assert resp.status_code == 200
        assert "CANON" in resp.text


def test_product_concurrent_choice_one_wins(product_env):
    import threading  # noqa: PLC0415

    from app import choice_service  # noqa: PLC0415
    from app.ai.mock import MockProvider  # noqa: PLC0415

    reader_id, code = _fresh_reader_invite(product_env)

    conn = connect_postgres(product_env["owner_url"])
    try:
        canon_episode_id = conn.execute(
            "SELECT id FROM episodes WHERE episode_type = 'canon' AND world_id = ? "
            "ORDER BY episode_number ASC LIMIT 1",
            (WORLD_STATE.world_id,),
        ).fetchone()["id"]
    finally:
        conn.close()

    def make_provider(choice_id, choice_text="", choice_comment=None):
        content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
        content["applied_reader_input"]["reader_choice_id"] = choice_id
        content["applied_reader_input"]["choice_text"] = choice_text
        return MockProvider(
            task_payloads={
                "episode_plan": BRANCH_EPISODE_PLAN,
                "episode_content": content,
            }
        )

    results = []
    barrier = threading.Barrier(2)

    def submit():
        c = connect_postgres(product_env["runtime_url"])
        try:
            barrier.wait()
            submission = choice_service.submit_reader_choice(
                c,
                world=WORLD_STATE,
                world_id=WORLD_STATE.world_id,
                reader_id=reader_id,
                canon_episode_id=canon_episode_id,
                canon_checkpoint_id=bootstrap.CANON_CHECKPOINT_ID,
                choice_text="선택지 1",
                comment=None,
                build_provider=make_provider,
            )
            results.append(submission.status)
        except Exception as exc:  # noqa: BLE001
            results.append(f"error: {exc}")
        finally:
            c.close()

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(results)
    assert statuses in (
        ["conflict", "submitted"],
        ["already_completed", "submitted"],
        ["submitted", "submitted"],
    ), f"unexpected statuses: {results}"

    conn = connect_postgres(product_env["owner_url"])
    try:
        choices = conn.execute(
            "SELECT COUNT(*) AS n FROM reader_choices WHERE reader_id = ?",
            (reader_id,),
        ).fetchone()["n"]
        branches = conn.execute(
            "SELECT COUNT(*) AS n FROM branches WHERE reader_id = ?",
            (reader_id,),
        ).fetchone()["n"]
        personal_eps = conn.execute(
            "SELECT COUNT(*) AS n FROM episodes "
            "WHERE episode_type = 'personal_branch' AND id IN "
            "(SELECT branch_episode_id FROM branches WHERE reader_id = ?)",
            (reader_id,),
        ).fetchone()["n"]
        assert choices == 1
        assert branches == 1
        assert personal_eps == 1
    finally:
        conn.close()


def test_product_duplicate_choice_idempotent(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)

        first = client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert first.status_code == 303

        second = client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert second.status_code == 303
        assert "/read/status" in second.headers["location"]

    conn = connect_postgres(product_env["owner_url"])
    try:
        branches = conn.execute(
            "SELECT COUNT(*) AS n FROM branches WHERE reader_id = ?",
            (reader_id,),
        ).fetchone()["n"]
        assert branches == 1
    finally:
        conn.close()


def test_product_retry_no_duplicate_branch(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)
        client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )

    conn = connect_postgres(product_env["owner_url"])
    try:
        choices = conn.execute(
            "SELECT COUNT(*) AS n FROM reader_choices WHERE reader_id = ?",
            (reader_id,),
        ).fetchone()["n"]
        branches = conn.execute(
            "SELECT COUNT(*) AS n FROM branches WHERE reader_id = ?",
            (reader_id,),
        ).fetchone()["n"]
        personal_eps = conn.execute(
            "SELECT COUNT(*) AS n FROM episodes "
            "WHERE episode_type = 'personal_branch' AND id IN "
            "(SELECT branch_episode_id FROM branches WHERE reader_id = ?)",
            (reader_id,),
        ).fetchone()["n"]
        assert choices == 1
        assert branches == 1
        assert personal_eps == 1
    finally:
        conn.close()


def test_product_pending_branch_404_not_403(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)
        client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )

        conn = connect_postgres(product_env["owner_url"])
        try:
            branch = conn.execute(
                "SELECT id FROM branches WHERE reader_id = ?",
                (reader_id,),
            ).fetchone()
        finally:
            conn.close()
        assert branch is not None

        resp = client.get(f"/read/branch/{branch['id']}")
        assert resp.status_code == 404


def test_product_admin_approve_publishes(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)
        client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )

        conn = connect_postgres(product_env["owner_url"])
        try:
            branch = conn.execute(
                "SELECT id FROM branches WHERE reader_id = ?",
                (reader_id,),
            ).fetchone()
        finally:
            conn.close()
        branch_id = branch["id"]

        _login_admin_pg(client)
        resp = client.get(f"/admin/review/{branch_id}")
        csrf = _extract_csrf(resp.text)
        resp = client.post(
            f"/admin/review/{branch_id}/approve",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        resp = client.get(f"/read/branch/{branch_id}")
        assert resp.status_code == 200


def test_product_approve_creates_one_audit_row(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)
        client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )

        conn = connect_postgres(product_env["owner_url"])
        try:
            branch = conn.execute(
                "SELECT id FROM branches WHERE reader_id = ?",
                (reader_id,),
            ).fetchone()
        finally:
            conn.close()
        branch_id = branch["id"]

        _login_admin_pg(client)
        resp = client.get(f"/admin/review/{branch_id}")
        csrf = _extract_csrf(resp.text)
        client.post(
            f"/admin/review/{branch_id}/approve",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )

    conn = connect_postgres(product_env["owner_url"])
    try:
        decisions = conn.execute(
            "SELECT COUNT(*) AS n FROM review_decisions WHERE branch_id = ?",
            (branch_id,),
        ).fetchone()["n"]
        assert decisions == 1
    finally:
        conn.close()


def test_product_unauthenticated_redirected(product_env):
    with _product_client(product_env) as client:
        resp = client.get("/read", follow_redirects=False)
        assert resp.status_code == 303
        assert "/access" in resp.headers["location"]


def test_product_reject_normalizes_reason(product_env):
    reader_id, code = _fresh_reader_invite(product_env)
    with _product_client(product_env) as client:
        _login_reader_pg(client, code)
        resp = client.get("/read")
        csrf = _extract_csrf(resp.text)
        client.post(
            "/read/choice",
            data={"choice": "0", "csrf_token": csrf},
            follow_redirects=False,
        )

        conn = connect_postgres(product_env["owner_url"])
        try:
            branch = conn.execute(
                "SELECT id FROM branches WHERE reader_id = ?",
                (reader_id,),
            ).fetchone()
        finally:
            conn.close()
        branch_id = branch["id"]

        _login_admin_pg(client)
        resp = client.get(f"/admin/review/{branch_id}")
        csrf = _extract_csrf(resp.text)
        resp = client.post(
            f"/admin/review/{branch_id}/reject",
            data={"csrf_token": csrf, "rejection_reason": "  padded reason  "},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    conn = connect_postgres(product_env["owner_url"])
    try:
        decision = conn.execute(
            "SELECT rejection_reason FROM review_decisions WHERE branch_id = ?",
            (branch_id,),
        ).fetchone()
        assert decision["rejection_reason"] == "padded reason"
    finally:
        conn.close()


def test_product_canon_unchanged_after_flow(product_env):
    conn = connect_postgres(product_env["owner_url"])
    try:
        canon = conn.execute(
            "SELECT review_state, episode_number FROM episodes "
            "WHERE episode_type = 'canon' AND world_id = ?",
            (WORLD_STATE.world_id,),
        ).fetchone()
        assert canon is not None
        assert canon["review_state"] == "published"
        assert canon["episode_number"] == 1
    finally:
        conn.close()


def test_product_pool_close_new_app_works(product_env):
    with _product_client(product_env) as client:
        resp = client.get("/health")
        assert resp.status_code == 200

    with _product_client(product_env) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_product_data_persists_in_postgres(product_env):
    conn = connect_postgres(product_env["owner_url"])
    try:
        worlds = conn.execute("SELECT COUNT(*) AS n FROM worlds").fetchone()["n"]
        characters = conn.execute(
            "SELECT COUNT(*) AS n FROM characters"
        ).fetchone()["n"]
        canon_eps = conn.execute(
            "SELECT COUNT(*) AS n FROM episodes WHERE episode_type = 'canon'"
        ).fetchone()["n"]
        assert worlds == 1
        assert characters == len(WORLD_STATE.characters)
        assert canon_eps == 1
    finally:
        conn.close()


def test_product_runtime_role_cannot_ddl(product_env):
    import psycopg  # noqa: PLC0415

    raw = psycopg.connect(product_env["runtime_url"], autocommit=True)
    try:
        schema = product_env["schema"]
        for stmt in (
            f'CREATE TABLE "{schema}".runtime_probe (id int)',
            f'ALTER TABLE "{schema}".worlds ADD COLUMN probe int',
            f'DROP TABLE "{schema}".worlds',
        ):
            with pytest.raises(psycopg.Error) as excinfo:
                raw.execute(stmt)
            assert excinfo.value.sqlstate == "42501"
    finally:
        raw.close()


def test_product_runtime_role_cannot_migrate(product_env):
    import psycopg  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    schema = f"lf_it_nomig_{uuid.uuid4().hex[:10]}"
    _reset_schema(schema)
    try:
        pg_provision.grant_runtime_dml(_pg_url, schema)
        pg_provision.revoke_runtime_create(_pg_url, schema)
        rt_url = pg_provision.runtime_url(_pg_url, schema)
        raw = psycopg.connect(rt_url, autocommit=True)
        try:
            with pytest.raises(psycopg.Error) as excinfo:
                raw.execute("CREATE TABLE schema_migrations (version TEXT)")
            assert excinfo.value.sqlstate == "42501"
        finally:
            raw.close()
    finally:
        _drop_schema(schema)
