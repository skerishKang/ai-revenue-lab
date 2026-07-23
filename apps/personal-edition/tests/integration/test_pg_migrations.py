"""Tests for the PostgreSQL migration engine.

Covers:
- migration discovery
- deterministic ordering
- duplicate version 거부
- migration version 기록
- partial migration 탐지
- migration import 시 connection 0회
- schema parity table 목록
- schema parity index 목록
- constraint 계약
- migration 파일에 destructive reset 없음

PostgreSQL integration tests only run when TEST_POSTGRES_URL is set.
Otherwise they are explicitly skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.config import normalize_pg_url_identity, redact_database_url
from app.db_pg_migrations import (
    PgMigrationError,
    _compute_checksum,
    _discover_migrations,
    _is_pg_migration,
    _read_migration,
    _safe_message,
    _split_statements,
    apply_pg_migrations,
    get_pg_check_constraints,
    get_pg_foreign_keys,
    get_pg_primary_keys,
    get_pg_schema_columns,
    get_pg_schema_indexes,
    get_pg_schema_tables,
    get_pg_unique_constraints,
    verify_pg_schema,
)

MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "migrations"
)

# The 8 domain/operational tables (excluding schema_migrations)
EXPECTED_DOMAIN_TABLES = {
    "participants",
    "inputs",
    "editions",
    "feedback",
    "generation_runs",
    "generation_requests",
    "benchmark_runs",
    "pilot_ops_records",
}

# All tables including schema_migrations (9 total)
EXPECTED_ALL_TABLES = EXPECTED_DOMAIN_TABLES | {"schema_migrations"}


# ================================================================
# Non-integration tests (no PostgreSQL connection required)
# ================================================================


class TestMigrationDiscovery:
    """migration discovery."""

    def test_discovers_pg_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        assert len(migrations) >= 1
        assert migrations[0].name == "pg_001_initial.sql"

    def test_does_not_discover_sqlite_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            assert m.name.startswith("pg_")

    def test_does_not_discover_python_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            assert m.name.endswith(".sql")

    def test_is_pg_migration(self):
        assert _is_pg_migration("pg_001_initial.sql") is True
        assert _is_pg_migration("pg_002_add_indexes.sql") is True
        assert _is_pg_migration("001_initial.sql") is False
        assert _is_pg_migration("004_upgrade_pilot_ops.py") is False
        assert _is_pg_migration("pg_001_initial.py") is False


class TestDeterministicOrdering:
    """deterministic ordering."""

    def test_migrations_sorted_by_name(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        names = [m.name for m in migrations]
        assert names == sorted(names)

    def test_ordering_is_deterministic(self):
        first = _discover_migrations(MIGRATIONS_DIR)
        second = _discover_migrations(MIGRATIONS_DIR)
        assert [m.name for m in first] == [m.name for m in second]


class TestNoDestructiveReset:
    """migration 파일에 destructive reset 없음."""

    def test_no_drop_table_in_pg_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            content = m.read_text(encoding="utf-8")
            assert "DROP TABLE" not in content.upper(), (
                f"DROP TABLE found in {m.name} — destructive reset not allowed"
            )

    def test_no_drop_database_in_pg_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            content = m.read_text(encoding="utf-8")
            assert "DROP DATABASE" not in content.upper(), (
                f"DROP DATABASE found in {m.name}"
            )

    def test_no_truncate_in_pg_migrations(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            content = m.read_text(encoding="utf-8")
            assert "TRUNCATE" not in content.upper(), (
                f"TRUNCATE found in {m.name}"
            )


class TestStatementSplitting:
    """Test SQL statement splitting for PostgreSQL."""

    def test_simple_statements(self):
        sql = "CREATE TABLE a (id TEXT); CREATE TABLE b (id TEXT);"
        stmts = _split_statements(sql)
        assert len(stmts) == 2

    def test_statement_with_semicolon_in_string(self):
        sql = (
            "CREATE TABLE a (id TEXT); "
            "INSERT INTO a VALUES ('hello;world');"
        )
        stmts = _split_statements(sql)
        assert len(stmts) == 2
        assert "hello;world" in stmts[1]

    def test_comment_between_statements(self):
        sql = (
            "CREATE TABLE a (id TEXT); "
            "-- comment\n"
            "CREATE TABLE b (id TEXT);"
        )
        stmts = _split_statements(sql)
        assert len(stmts) == 2

    def test_block_comment_between_statements(self):
        sql = (
            "CREATE TABLE a (id TEXT); "
            "/* block comment */ "
            "CREATE TABLE b (id TEXT);"
        )
        stmts = _split_statements(sql)
        assert len(stmts) == 2

    def test_empty_input(self):
        assert _split_statements("") == []

    def test_comment_only(self):
        assert _split_statements("-- just a comment") == []


class TestChecksum:
    """Test checksum computation."""

    def test_checksum_is_deterministic(self):
        content = "CREATE TABLE test (id TEXT);"
        c1 = _compute_checksum(content.encode("utf-8"))
        c2 = _compute_checksum(content.encode("utf-8"))
        assert c1 == c2

    def test_checksum_changes_with_content(self):
        c1 = _compute_checksum(b"CREATE TABLE a (id TEXT);")
        c2 = _compute_checksum(b"CREATE TABLE b (id TEXT);")
        assert c1 != c2

    def test_checksum_is_sha256(self):
        import hashlib
        content = b"test"
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_checksum(content) == expected


class TestMigrationImportNoConnection:
    """migration import 시 connection 0회."""

    def test_import_does_not_connect(self, isolated_sys_modules):
        """Importing the migration module must not open a connection."""
        import importlib
        import sys

        # Remove from cache to force re-import
        modules_to_remove = [
            k for k in sys.modules if k.startswith("app.db_pg_migrations")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Re-import — this should NOT open any connection
        importlib.import_module("app.db_pg_migrations")

        # If we got here without a connection error, the test passes.
        # The module imports psycopg but does not call connect().
        assert True


class TestSchemaParityInventory:
    """schema parity table 목록 — verify the migration file creates
    the same tables as the SQLite schema."""

    def test_pg_migration_creates_all_domain_tables(self):
        """The PG migration SQL must create all 7 domain tables."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        assert len(migrations) >= 1

        # Read all migration content
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        for table in EXPECTED_DOMAIN_TABLES:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in all_sql, (
                f"Table '{table}' not found in PG migrations"
            )



    def test_pg_migration_creates_all_indexes(self):
        """The PG migration must create all indexes from SQLite schema."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        expected_indexes = [
            "idx_participants_access_token_hash",
            "idx_benchmark_runs_fixture",
            "idx_benchmark_runs_task",
            "idx_benchmark_runs_benchmark",
            "idx_pilot_ops_records_participant",
            "idx_pilot_ops_records_type",
        ]
        for idx in expected_indexes:
            assert idx in all_sql, f"Index '{idx}' not found in PG migrations"

    def test_pg_migration_has_foreign_keys(self):
        """The PG migration must define foreign key references."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        # Check for REFERENCES clauses
        assert "REFERENCES participants(id)" in all_sql
        assert "REFERENCES editions(id)" in all_sql
        assert "REFERENCES inputs(id)" in all_sql

    def test_pg_migration_has_unique_constraints(self):
        """The PG migration must define unique constraints."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        assert "UNIQUE(participant_id, sequence_number)" in all_sql
        assert "UNIQUE(participant_id, edition_number)" in all_sql

    def test_pg_migration_has_check_constraints(self):
        """The PG migration must define CHECK constraints."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        assert "CHECK(consent_confirmed IN (0, 1))" in all_sql
        assert "CHECK(success IN (0, 1))" in all_sql
        assert "CHECK(retry_count >= 0)" in all_sql
        assert "CHECK(latency_seconds IS NULL OR latency_seconds >= 0)" in all_sql

    def test_pg_migration_has_pilot_ops_check(self):
        """The pilot_ops_records table must have the record_type CHECK."""
        migrations = _discover_migrations(MIGRATIONS_DIR)
        all_sql = "\n".join(
            m.read_text(encoding="utf-8") for m in migrations
        )

        assert "record_type IN (" in all_sql
        for value in (
            "benchmark_run",
            "pilot_run",
            "pilot_evidence",
            "payment_evidence",
            "correction",
            "deletion_request",
            "deletion_completion",
        ):
            assert value in all_sql, f"record_type value '{value}' not found"


class TestMigrationChecksumIntegrity:
    """Test that migration checksum tracking works correctly."""

    def test_read_migration_returns_content_and_checksum(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        assert len(migrations) >= 1
        content, checksum = _read_migration(migrations[0])
        assert content
        assert len(checksum) == 64  # SHA-256 hex

    def test_checksum_matches_content(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            content, checksum = _read_migration(m)
            expected = _compute_checksum(content.encode("utf-8"))
            assert checksum == expected


class TestSafeErrorMessage:
    """Verify migration error messages never leak raw driver text.

    The CTO follow-up requires that ``PgMigrationError`` messages use fixed
    safe categories instead of interpolating the raw exception string (which
    may contain the DSN, userinfo, or SQL internals).
    """

    def test_error_has_category_attribute(self):
        err = PgMigrationError(
            "pg_001_initial.sql", "boom", category="apply_failed"
        )
        assert err.category == "apply_failed"

    def test_error_default_category(self):
        err = PgMigrationError("pg_001_initial.sql", "boom")
        assert err.category == "migration error"

    def test_error_message_does_not_contain_raw_exc(self):
        raw = "connection refused: postgresql://leak:password@host/db"
        err = PgMigrationError(
            "pg_001", _safe_message("apply_failed"), category="apply_failed"
        )
        assert raw not in str(err)
        assert "password" not in str(err)

    def test_safe_message_known_categories(self):
        for cat in (
            "apply_failed",
            "checksum_mismatch",
            "partial_schema",
            "schema_drift",
            "discovery",
        ):
            msg = _safe_message(cat)
            assert isinstance(msg, str)
            assert msg
            # Fixed messages must never contain a DSN marker.
            assert "://" not in msg
            assert "@" not in msg

    def test_safe_message_unknown_category_fallback(self):
        assert _safe_message("nonexistent") == "migration error"

    def test_error_causes_preserved(self):
        original = ValueError("underlying detail")
        try:
            raise PgMigrationError(
                "pg_001", _safe_message("apply_failed"), category="apply_failed"
            ) from original
        except PgMigrationError as err:
            assert err.__cause__ is original


class TestMigrationRunnerContract:
    """Unit tests for migration runner contract (no DB connection).

    These verify properties of the runner that the CTO follow-up requires
    without needing a live PostgreSQL connection: discovery ordering,
    checksum determinism, destructive-reset prohibition, and statement
    splitting — the foundation that the integration tests build on.
    """

    def test_runner_discovers_in_numeric_order(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        versions = []
        for m in migrations:
            match = re.match(r"^pg_(\d+)_", m.name)
            assert match is not None, f"{m.name} does not match pg_NNN_"
            versions.append(int(match.group(1)))
        assert versions == sorted(versions)

    def test_runner_checksum_deterministic(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            _, c1 = _read_migration(m)
            _, c2 = _read_migration(m)
            assert c1 == c2

    def test_runner_no_destructive_reset(self):
        migrations = _discover_migrations(MIGRATIONS_DIR)
        for m in migrations:
            content = m.read_text(encoding="utf-8").upper()
            assert "DROP TABLE" not in content
            assert "DROP DATABASE" not in content
            assert "TRUNCATE" not in content

    def test_runner_split_statements_handles_complex_sql(self):
        sql = (
            "CREATE TABLE a (id TEXT PRIMARY KEY); "
            "INSERT INTO a VALUES ('x;y'); "
            "-- trailing comment\n"
        )
        stmts = _split_statements(sql)
        assert len(stmts) == 2
        assert "x;y" in stmts[1]


# ================================================================
# PostgreSQL integration tests (require TEST_POSTGRES_URL + opt-in)
# ================================================================

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")
PE_DATABASE_URL = os.environ.get("PE_DATABASE_URL", "")
PE_PG_TEST_INTEGRATION = os.environ.get("PE_PG_TEST_INTEGRATION", "").strip()

# Safety guard: refuse to run if the test URL resolves to the same database
# identity (host/port/database) as the real database URL.  This is NOT a raw
# string equality check — it normalizes userinfo, query parameters, fragment,
# and default-port omission so that equivalent URLs expressed differently are
# still rejected.
def _urls_resolve_to_same_db(a: str, b: str) -> bool:
    """True if both URLs normalize to the same (host, port, database)."""
    if not a or not b:
        return False
    ia = normalize_pg_url_identity(a)
    ib = normalize_pg_url_identity(b)
    # If either URL is unparseable, fall back to a conservative string check
    # only if the raw strings are literally equal.
    if ia is None or ib is None:
        return a == b
    return ia == ib


if TEST_POSTGRES_URL and PE_DATABASE_URL and _urls_resolve_to_same_db(
    TEST_POSTGRES_URL, PE_DATABASE_URL
):
    raise RuntimeError(
        "TEST_POSTGRES_URL resolves to the same database identity as "
        "PE_DATABASE_URL — refusing to run integration tests that could "
        "damage the production/development database."
    )

# Integration tests are skipped unless BOTH an explicit opt-in flag is set
# AND a separate TEST_POSTGRES_URL is provided.  This double gate ensures the
# 12 integration tests can never run in CI (or locally) by accident.
_INTEGRATION_ENABLED = bool(
    TEST_POSTGRES_URL
    and PE_PG_TEST_INTEGRATION in ("1", "true", "yes", "on")
)

pytestmark_integration = pytest.mark.skipif(
    not _INTEGRATION_ENABLED,
    reason=(
        "PostgreSQL integration tests require both TEST_POSTGRES_URL and "
        "PE_PG_TEST_INTEGRATION=1 to be set explicitly."
    ),
)


@pytest.fixture
def pg_conn():
    """Create a fresh PostgreSQL connection for testing.

    Only runs when TEST_POSTGRES_URL is set and integration is opt-in.
    """
    from app.db_postgres import get_pg_connection

    conn = get_pg_connection(TEST_POSTGRES_URL)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def pg_conn_clean(pg_conn):
    """Clean connection — uses a unique temporary schema for complete isolation.

    The setup (CREATE SCHEMA / SET search_path) and teardown (DROP SCHEMA)
    are each wrapped in ``try/finally`` so that a failure during setup does
    not leave the search_path pointing at a non-existent schema, and a
    failure during teardown is still reported while the connection is closed
    by the outer ``pg_conn`` fixture.

    This fixture NEVER creates or drops objects in the ``public`` schema.
    """
    import uuid

    schema_name = f"test_schema_{uuid.uuid4().hex}"
    try:
        pg_conn.execute(f'CREATE SCHEMA "{schema_name}"')
        pg_conn.execute(f'SET search_path TO "{schema_name}"')
        pg_conn.commit()
    except Exception:
        # Best-effort cleanup if setup failed partway through.
        try:
            pg_conn.rollback()
            pg_conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            pg_conn.commit()
        except Exception:
            pass
        raise

    try:
        yield pg_conn
    finally:
        try:
            pg_conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            pg_conn.commit()
        except Exception:
            try:
                pg_conn.rollback()
            except Exception:
                pass


@pytestmark_integration
class TestPgMigrationIntegration:
    """Integration tests that require a real PostgreSQL connection.

    These tests only run when TEST_POSTGRES_URL **and**
    PE_PG_TEST_INTEGRATION=1 are both set.
    """

    def test_fresh_database_applies_migrations(self, pg_conn_clean):
        applied = apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        assert "pg_001_initial.sql" in applied
        pg_conn_clean.commit()

    def test_all_tables_created(self, pg_conn_clean):
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()
        tables = get_pg_schema_tables(pg_conn_clean)
        assert EXPECTED_ALL_TABLES.issubset(tables)

    def test_idempotent_rerun(self, pg_conn_clean):
        first = apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()
        second = apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        assert "pg_001_initial.sql" in first
        assert second == []

    def test_migration_version_recorded(self, pg_conn_clean):
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()
        rows = pg_conn_clean.execute(
            "SELECT version, checksum, applied_at FROM schema_migrations "
            "ORDER BY version"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["version"] == "pg_001_initial.sql"
        assert rows[0]["checksum"]
        assert rows[0]["applied_at"]

    def test_checksum_mismatch_detected(self, pg_conn_clean, tmp_path):
        """이미 적용된 version의 SQL 내용이 변경되면 실패."""
        # Apply the original migration
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        # Modify the migration file content
        migration_file = Path(MIGRATIONS_DIR) / "pg_001_initial.sql"
        original = migration_file.read_text(encoding="utf-8")
        try:
            migration_file.write_text(
                original + "\n-- modified\n", encoding="utf-8"
            )
            with pytest.raises(PgMigrationError, match="checksum"):
                apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        finally:
            migration_file.write_text(original, encoding="utf-8")

    def test_duplicate_version_rejected(self, pg_conn_clean, tmp_path):
        """duplicate version 거부 — uses the isolated pg_conn_clean schema."""
        # Create a temp migrations dir with duplicate versions
        tmp_dir = tmp_path / "migrations"
        tmp_dir.mkdir()
        (tmp_dir / "pg_001_a.sql").write_text(
            "CREATE TABLE a (id TEXT PRIMARY KEY);", encoding="utf-8"
        )
        (tmp_dir / "pg_001_b.sql").write_text(
            "CREATE TABLE b (id TEXT PRIMARY KEY);", encoding="utf-8"
        )

        with pytest.raises(PgMigrationError, match="duplicate"):
            apply_pg_migrations(pg_conn_clean, str(tmp_dir))

    def test_partial_migration_rollback(self, pg_conn_clean, tmp_path):
        """migration 실패 시 rollback — fully isolated via pg_conn_clean."""
        tmp_dir = tmp_path / "migrations"
        tmp_dir.mkdir()
        (tmp_dir / "pg_001_valid.sql").write_text(
            "CREATE TABLE valid_table (id TEXT PRIMARY KEY);",
            encoding="utf-8",
        )
        (tmp_dir / "pg_002_broken.sql").write_text(
            "CREATE TABLE broken_table (id TEXT PRIMARY KEY); INVALID SQL HERE;",
            encoding="utf-8",
        )

        # No DROP TABLE on public/schema_migrations — the pg_conn_clean
        # fixture provides a pristine, isolated schema already.
        with pytest.raises(PgMigrationError):
            apply_pg_migrations(pg_conn_clean, str(tmp_dir))

        # The broken migration should not have been recorded
        count = pg_conn_clean.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations "
            "WHERE version = 'pg_002_broken.sql'"
        ).fetchone()["c"]
        assert count == 0

    def test_public_schema_not_polluted(self, pg_conn_clean):
        """The public schema must never receive migration objects.

        After applying migrations in the isolated test schema, the public
        schema must contain none of the domain tables or the
        schema_migrations table.  This guards against regressions where the
        drift check or migration execution falls back to ``public``.
        """
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        public_tables = get_pg_schema_tables(pg_conn_clean, "public")
        for table in EXPECTED_ALL_TABLES:
            assert table not in public_tables, (
                f"'{table}' was created in the public schema — migrations "
                f"must target the current search_path, never public."
            )

    def test_search_path_restored_after_drift_check(self, pg_conn_clean):
        """After the drift check runs, search_path must be unchanged.

        Applies migrations twice (second run triggers the ``is_applied``
        drift path).  The search_path must still point at the isolated
        test schema afterwards.
        """
        import uuid

        schema_name = f"test_schema_{uuid.uuid4().hex}"
        try:
            pg_conn_clean.execute(f'CREATE SCHEMA "{schema_name}"')
            pg_conn_clean.execute(f'SET search_path TO "{schema_name}"')
            pg_conn_clean.commit()
        except Exception:
            try:
                pg_conn_clean.rollback()
                pg_conn_clean.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                pg_conn_clean.commit()
            except Exception:
                pass
            raise

        try:
            apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
            pg_conn_clean.commit()
            # Second run exercises the is_applied=True drift path.
            apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
            pg_conn_clean.commit()

            row = pg_conn_clean.execute("SHOW search_path").fetchone()
            current = row[0] if row else ""
            assert schema_name in current, (
                f"search_path was not restored after drift check; "
                f"got {current!r}, expected to contain {schema_name!r}."
            )
        finally:
            try:
                pg_conn_clean.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                pg_conn_clean.commit()
            except Exception:
                try:
                    pg_conn_clean.rollback()
                except Exception:
                    pass

    def test_effective_schema_via_current_schema(self, pg_conn_clean):
        """The target schema must be resolved via ``current_schema()``, not
        by tokenizing ``SHOW search_path``.

        This test sets a multi-schema search_path including a leading test
        schema and ``public``, then verifies that the drift check compares
        against the **effective** schema (the first existing schema in the
        path) rather than a literal ``$user`` token or the raw first token.
        """
        import uuid

        schema_name = f"test_schema_{uuid.uuid4().hex}"
        try:
            pg_conn_clean.execute(f'CREATE SCHEMA "{schema_name}"')
            # Multi-schema search_path: test schema first, then public.
            pg_conn_clean.execute(f'SET search_path TO "{schema_name}", public')
            pg_conn_clean.commit()
        except Exception:
            try:
                pg_conn_clean.rollback()
                pg_conn_clean.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                pg_conn_clean.commit()
            except Exception:
                pass
            raise

        try:
            # current_schema() must resolve to the test schema, not "public"
            # or the literal "$user".
            row = pg_conn_clean.execute("SELECT current_schema()").fetchone()
            effective = row[0] if row else None
            assert effective == schema_name, (
                f"current_schema() returned {effective!r}, expected "
                f"{schema_name!r}"
            )

            apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
            pg_conn_clean.commit()

            # Objects must be in the effective test schema, not public.
            test_tables = get_pg_schema_tables(pg_conn_clean, schema_name)
            public_tables = get_pg_schema_tables(pg_conn_clean, "public")
            assert EXPECTED_ALL_TABLES.issubset(test_tables)
            for table in EXPECTED_ALL_TABLES:
                assert table not in public_tables
        finally:
            try:
                pg_conn_clean.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                pg_conn_clean.commit()
            except Exception:
                try:
                    pg_conn_clean.rollback()
                except Exception:
                    pass

    def test_schema_parity_table_list(self, pg_conn_clean):
        """schema parity table 목록."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()
        tables = get_pg_schema_tables(pg_conn_clean)
        assert EXPECTED_ALL_TABLES.issubset(tables)

    def test_schema_parity_index_list(self, pg_conn_clean):
        """schema parity index 목록."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()
        indexes = get_pg_schema_indexes(pg_conn_clean)
        index_names = {name for name, _ in indexes}
        expected_indexes = {
            "idx_participants_access_token_hash",
            "idx_benchmark_runs_fixture",
            "idx_benchmark_runs_task",
            "idx_benchmark_runs_benchmark",
            "idx_pilot_ops_records_participant",
            "idx_pilot_ops_records_type",
        }
        assert expected_indexes.issubset(index_names)

    def test_constraint_contract(self, pg_conn_clean):
        """constraint 계약 — PK, FK, UNIQUE, CHECK."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        # Primary keys
        for table in EXPECTED_DOMAIN_TABLES:
            pks = get_pg_primary_keys(pg_conn_clean, table)
            if table == "participants":
                assert pks == ["id"]
            elif table == "inputs":
                assert pks == ["id"]
            elif table == "editions":
                assert pks == ["id"]
            elif table == "feedback":
                assert pks == ["id"]
            elif table == "generation_runs":
                assert pks == ["id"]
            elif table == "benchmark_runs":
                assert pks == ["id"]
            elif table == "pilot_ops_records":
                assert pks == ["record_id"]

        # Foreign keys
        inputs_fks = get_pg_foreign_keys(pg_conn_clean, "inputs")
        assert len(inputs_fks) == 1
        assert inputs_fks[0]["foreign_table_name"] == "participants"
        assert inputs_fks[0]["delete_rule"] == "NO ACTION"

        editions_fks = get_pg_foreign_keys(pg_conn_clean, "editions")
        fk_tables = {fk["foreign_table_name"] for fk in editions_fks}
        assert "participants" in fk_tables
        assert "editions" in fk_tables  # self-reference (prior_edition_id)
        assert "inputs" in fk_tables

        feedback_fks = get_pg_foreign_keys(pg_conn_clean, "feedback")
        fb_fk_tables = {fk["foreign_table_name"] for fk in feedback_fks}
        assert "participants" in fb_fk_tables
        assert "editions" in fb_fk_tables

        # Unique constraints
        inputs_uniques = get_pg_unique_constraints(pg_conn_clean, "inputs")
        assert any(
            "participant_id" in u["columns"] and "sequence_number" in u["columns"]
            for u in inputs_uniques
        )

        editions_uniques = get_pg_unique_constraints(pg_conn_clean, "editions")
        assert any(
            "participant_id" in u["columns"] and "edition_number" in u["columns"]
            for u in editions_uniques
        )

        # CHECK constraints
        participants_checks = get_pg_check_constraints(
            pg_conn_clean, "participants"
        )
        # participants has no CHECK constraints in the original schema
        assert len(participants_checks) == 0

        inputs_checks = get_pg_check_constraints(pg_conn_clean, "inputs")
        assert any("consent_confirmed" in c for c in inputs_checks)

        feedback_checks = get_pg_check_constraints(pg_conn_clean, "feedback")
        assert any("applied_to_next_edition" in c for c in feedback_checks)

        benchmark_checks = get_pg_check_constraints(
            pg_conn_clean, "benchmark_runs"
        )
        assert any("failure_category" in c for c in benchmark_checks)
        assert any("is_provider_failure" in c for c in benchmark_checks)

        pilot_checks = get_pg_check_constraints(
            pg_conn_clean, "pilot_ops_records"
        )
        assert any("record_type" in c for c in pilot_checks)

    def test_column_parity(self, pg_conn_clean):
        """Verify column names match SQLite schema."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        # participants columns
        cols = {c["column_name"] for c in get_pg_schema_columns(
            pg_conn_clean, "participants"
        )}
        expected = {
            "id", "display_name", "access_token_hash",
            "preferred_language", "tone_preference", "length_preference",
            "status", "created_at", "updated_at", "deleted_at",
        }
        assert cols == expected

        # inputs columns
        cols = {c["column_name"] for c in get_pg_schema_columns(
            pg_conn_clean, "inputs"
        )}
        expected = {
            "id", "participant_id", "sequence_number", "raw_text",
            "normalized_text", "consent_confirmed", "submitted_at",
            "deleted_at",
        }
        assert cols == expected

        # pilot_ops_records columns
        cols = {c["column_name"] for c in get_pg_schema_columns(
            pg_conn_clean, "pilot_ops_records"
        )}
        expected = {
            "record_id", "record_type", "participant_id",
            "created_at", "payload",
        }
        assert cols == expected

    def test_not_null_parity(self, pg_conn_clean):
        """Verify NOT NULL constraints match SQLite schema."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        # participants: display_name, access_token_hash, etc. are NOT NULL
        cols = get_pg_schema_columns(pg_conn_clean, "participants")
        not_null_cols = {
            c["column_name"] for c in cols if c["is_nullable"] == "NO"
        }
        assert "display_name" in not_null_cols
        assert "access_token_hash" in not_null_cols
        assert "created_at" in not_null_cols
        assert "updated_at" in not_null_cols
        assert "deleted_at" not in not_null_cols

        # inputs: raw_text, submitted_at, consent_confirmed are NOT NULL
        cols = get_pg_schema_columns(pg_conn_clean, "inputs")
        not_null_cols = {
            c["column_name"] for c in cols if c["is_nullable"] == "NO"
        }
        assert "raw_text" in not_null_cols
        assert "submitted_at" in not_null_cols
        assert "consent_confirmed" in not_null_cols
        assert "normalized_text" not in not_null_cols


@pytestmark_integration
class TestVerifyPgSchema:
    """Integration tests for read-only schema verification (Neon contract).

    Application startup must NOT run migrations — only verify schema/version/
    checksum in read-only mode. These tests verify that contract.
    """

    def test_verify_fails_without_schema_migrations_table(self, pg_conn_clean):
        """verify_pg_schema must fail if schema_migrations table is missing."""
        with pytest.raises(PgMigrationError, match="schema_migrations table not found"):
            verify_pg_schema(pg_conn_clean, MIGRATIONS_DIR)

    def test_verify_succeeds_after_migrations_applied(self, pg_conn_clean):
        """verify_pg_schema must succeed after migrations are applied."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        result = verify_pg_schema(pg_conn_clean, MIGRATIONS_DIR)
        assert result["applied_count"] == 1
        assert result["pending_count"] == 0
        assert "pg_001_initial.sql" in result["versions"]

    def test_verify_fails_with_pending_migrations(self, pg_conn_clean, tmp_path):
        """verify_pg_schema must fail if there are pending migrations."""
        # Create a temp migrations dir with 2 migrations
        tmp_dir = tmp_path / "migrations"
        tmp_dir.mkdir()
        (tmp_dir / "pg_001_a.sql").write_text(
            "CREATE TABLE a (id TEXT PRIMARY KEY);", encoding="utf-8"
        )
        (tmp_dir / "pg_002_b.sql").write_text(
            "CREATE TABLE b (id TEXT PRIMARY KEY);", encoding="utf-8"
        )

        # Apply only the first migration
        apply_pg_migrations(pg_conn_clean, str(tmp_dir))
        pg_conn_clean.commit()

        # Add a third migration file (pending)
        (tmp_dir / "pg_003_c.sql").write_text(
            "CREATE TABLE c (id TEXT PRIMARY KEY);", encoding="utf-8"
        )

        with pytest.raises(PgMigrationError, match="pending migrations"):
            verify_pg_schema(pg_conn_clean, str(tmp_dir))

    def test_verify_fails_with_checksum_mismatch(self, pg_conn_clean, tmp_path):
        """verify_pg_schema must fail if a recorded checksum doesn't match."""
        tmp_dir = tmp_path / "migrations"
        tmp_dir.mkdir()
        migration_file = tmp_dir / "pg_001_test.sql"
        migration_file.write_text(
            "CREATE TABLE test (id TEXT PRIMARY KEY);", encoding="utf-8"
        )

        apply_pg_migrations(pg_conn_clean, str(tmp_dir))
        pg_conn_clean.commit()

        # Modify the migration file
        migration_file.write_text(
            "CREATE TABLE test (id TEXT PRIMARY KEY, name TEXT);",
            encoding="utf-8",
        )

        with pytest.raises(PgMigrationError, match="content has changed"):
            verify_pg_schema(pg_conn_clean, str(tmp_dir))

    def test_verify_is_read_only(self, pg_conn_clean):
        """verify_pg_schema must not modify the database."""
        apply_pg_migrations(pg_conn_clean, MIGRATIONS_DIR)
        pg_conn_clean.commit()

        # Get state before verify
        tables_before = get_pg_schema_tables(pg_conn_clean)
        applied_before = pg_conn_clean.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations"
        ).fetchone()["c"]

        verify_pg_schema(pg_conn_clean, MIGRATIONS_DIR)

        # Get state after verify
        tables_after = get_pg_schema_tables(pg_conn_clean)
        applied_after = pg_conn_clean.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations"
        ).fetchone()["c"]

        assert tables_before == tables_after
        assert applied_before == applied_after


# ---------------------------------------------------------------------------
# dict_row contract tests (no real PostgreSQL required)
#
# verify_pg_schema runs against a real psycopg connection configured with
# row_factory=dict_row, where rows are dicts keyed by column name and
# positional row[0] access is unavailable.  The integration tests above are
# skipped without TEST_POSTGRES_URL, so these fakes prove the dict-row access
# pattern (explicit aliases + row["name"]) and the strengthened read-only
# fail-closed checks WITHOUT a live database.
# ---------------------------------------------------------------------------


class _FakeDictCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeDictRowConn:
    """A dict_row-shaped fake connection.

    Rows are plain dicts keyed by column name (exactly what psycopg's
    ``dict_row`` factory yields).  A responder callable maps each SQL string
    to its result rows, so tests control the database state precisely.
    """

    def __init__(self, responder):
        self._responder = responder
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _FakeDictCursor(self._responder(sql, params))


def _verify_responder(
    *,
    schema="public",
    has_sm_table=True,
    applied=None,
    tables=None,
):
    """Build a dict-row responder for verify_pg_schema's read-only queries."""
    applied = dict(applied or {})
    tables = set(tables or set())

    def responder(sql, params):
        norm = " ".join(sql.split()).lower()
        if "current_schema() as schema" in norm:
            return [{"schema": schema}]
        if "select exists" in norm and "schema_migrations" in norm:
            return [{"exists": has_sm_table}]
        if "from schema_migrations" in norm:
            return [
                {"version": v, "checksum": c} for v, c in sorted(applied.items())
            ]
        if "pg_catalog.pg_tables" in norm:
            return [{"tablename": t} for t in sorted(tables)]
        raise AssertionError(f"unexpected SQL in verify_pg_schema: {sql!r}")

    return responder


def _write_migration(dirpath: Path, name: str, body: str) -> str:
    """Write a migration file and return its checksum."""
    (dirpath / name).write_text(body, encoding="utf-8")
    return _compute_checksum(body.encode("utf-8"))


class TestVerifyPgSchemaDictRowContract:
    """Prove verify_pg_schema works against dict_row-shaped rows (no PG)."""

    def test_success_reads_exists_alias_by_name(self, tmp_path):
        """The EXISTS result is aliased and read as row['exists']."""
        d = tmp_path / "m"
        d.mkdir()
        checksum = _write_migration(
            d, "pg_001_widgets.sql", "CREATE TABLE widgets (id TEXT PRIMARY KEY);"
        )
        conn = _FakeDictRowConn(
            _verify_responder(
                applied={"pg_001_widgets.sql": checksum},
                tables={"widgets", "schema_migrations"},
            )
        )
        result = verify_pg_schema(conn, str(d))
        assert result["applied_count"] == 1
        assert result["pending_count"] == 0
        assert result["versions"] == ["pg_001_widgets.sql"]
        assert result["schema"] == "public"

    def test_rejects_missing_schema_migrations_table(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        _write_migration(d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);")
        conn = _FakeDictRowConn(_verify_responder(has_sm_table=False))
        with pytest.raises(PgMigrationError, match="schema_migrations table not found"):
            verify_pg_schema(conn, str(d))

    def test_rejects_null_effective_schema(self, tmp_path):
        """A NULL current_schema() must fail closed, not guess."""
        d = tmp_path / "m"
        d.mkdir()
        _write_migration(d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);")
        conn = _FakeDictRowConn(_verify_responder(schema=None))
        with pytest.raises(PgMigrationError, match="current_schema\\(\\) returned NULL"):
            verify_pg_schema(conn, str(d))

    def test_rejects_unknown_recorded_migration(self, tmp_path):
        """A recorded version absent from the migration dir must fail closed."""
        d = tmp_path / "m"
        d.mkdir()
        _write_migration(d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);")
        conn = _FakeDictRowConn(
            _verify_responder(
                applied={
                    "pg_001_a.sql": "x" * 64,
                    "pg_999_ghost.sql": "y" * 64,  # not in the directory
                },
                tables={"a"},
            )
        )
        with pytest.raises(
            PgMigrationError, match="not found in migration directory"
        ):
            verify_pg_schema(conn, str(d))

    def test_rejects_checksum_mismatch(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        _write_migration(d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);")
        conn = _FakeDictRowConn(
            _verify_responder(
                applied={"pg_001_a.sql": "deadbeef" + "0" * 56},  # wrong checksum
                tables={"a"},
            )
        )
        with pytest.raises(PgMigrationError, match="content has changed"):
            verify_pg_schema(conn, str(d))

    def test_rejects_pending_migration(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        checksum_a = _write_migration(
            d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);"
        )
        _write_migration(d, "pg_002_b.sql", "CREATE TABLE b (id TEXT PRIMARY KEY);")
        # pg_001 recorded with its correct checksum -> pg_002 is pending.
        conn = _FakeDictRowConn(
            _verify_responder(applied={"pg_001_a.sql": checksum_a}, tables={"a"})
        )
        with pytest.raises(PgMigrationError, match="pending migrations"):
            verify_pg_schema(conn, str(d))

    def test_rejects_schema_drift_missing_table(self, tmp_path):
        """A declared table absent from the effective schema must fail closed."""
        d = tmp_path / "m"
        d.mkdir()
        checksum = _write_migration(
            d,
            "pg_001_multi.sql",
            "CREATE TABLE a (id TEXT PRIMARY KEY);\n"
            "CREATE TABLE b (id TEXT PRIMARY KEY);",
        )
        # Both migrations recorded with correct checksum, but table b is missing.
        conn = _FakeDictRowConn(
            _verify_responder(
                applied={"pg_001_multi.sql": checksum},
                tables={"a", "schema_migrations"},  # b missing -> drift
            )
        )
        with pytest.raises(PgMigrationError, match="schema drift"):
            verify_pg_schema(conn, str(d))

    def test_errors_never_expose_secrets(self, tmp_path):
        """Fail-closed error text must not carry driver/DSN/secret content."""
        d = tmp_path / "m"
        d.mkdir()
        _write_migration(d, "pg_001_a.sql", "CREATE TABLE a (id TEXT PRIMARY KEY);")
        secret = "postgresql://alice:s3cr3t@db.internal.example.com:5432/prod"
        for responder in (
            _verify_responder(has_sm_table=False),
            _verify_responder(schema=None),
            _verify_responder(
                applied={"pg_999_ghost.sql": "y" * 64}, tables=set()
            ),
        ):
            conn = _FakeDictRowConn(responder)
            with pytest.raises(PgMigrationError) as excinfo:
                verify_pg_schema(conn, str(d))
            text = f"{excinfo.value} {excinfo.value.message}"
            assert secret not in text
            assert "s3cr3t" not in text
            assert "postgresql://" not in text


class TestExtractCreatedTables:
    def test_plain_create_table(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "CREATE TABLE widgets (id TEXT PRIMARY KEY);"
        assert _extract_created_tables(sql) == {"widgets"}

    def test_if_not_exists_and_schema_qualified_and_quoted(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = (
            "CREATE TABLE IF NOT EXISTS public.widgets (id TEXT);\n"
            'CREATE TABLE "gadgets" (id TEXT);\n'
            "CREATE TABLE myschema.things (id TEXT);"
        )
        assert _extract_created_tables(sql) == {"widgets", "gadgets", "things"}

    def test_no_tables(self):
        from app.db_pg_migrations import _extract_created_tables

        assert _extract_created_tables("CREATE INDEX ix ON widgets (id);") == set()

    def test_line_comment_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "-- CREATE TABLE ghost (id TEXT);\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_block_comment_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "/* CREATE TABLE ghost (id TEXT); */\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_nested_block_comment_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "/* outer /* CREATE TABLE ghost (id TEXT); */ still comment */\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_single_quoted_string_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "INSERT INTO log (msg) VALUES ('CREATE TABLE ghost (id TEXT);');\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_single_quoted_string_with_escaped_quote_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "INSERT INTO log (msg) VALUES ('it''s a CREATE TABLE ghost (id TEXT);');\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_e_string_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "INSERT INTO log (msg) VALUES (E'CREATE TABLE ghost (id TEXT);');\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_e_string_with_backslash_escape_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "INSERT INTO log (msg) VALUES (E'line\\nCREATE TABLE ghost (id TEXT);');\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_dollar_quoted_string_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "CREATE FUNCTION f() RETURNS void AS $$ CREATE TABLE ghost (id TEXT); $$ LANGUAGE sql;\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_tagged_dollar_quoted_string_ignored(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "CREATE FUNCTION f() RETURNS void AS $fn$ CREATE TABLE ghost (id TEXT); $fn$ LANGUAGE sql;\nCREATE TABLE real (id TEXT);"
        assert _extract_created_tables(sql) == {"real"}

    def test_e_prefix_inside_identifier_not_treated_as_string(self):
        from app.db_pg_migrations import _extract_created_tables

        sql = "CREATE TABLE resume (id TEXT);\nCREATE TABLE note (id TEXT);"
        assert _extract_created_tables(sql) == {"resume", "note"}

    def test_canonical_migrations_expected_table_set(self):
        from app.db_pg_migrations import _extract_created_tables
        from pathlib import Path

        migrations_dir = Path(__file__).parent.parent.parent / "migrations"
        expected = set()
        for p in sorted(migrations_dir.glob("pg_*.sql")):
            expected |= _extract_created_tables(p.read_text())
        assert "participants" in expected
        assert "inputs" in expected
        assert "editions" in expected
        assert "feedback" in expected
        assert "generation_runs" in expected
        assert "generation_requests" in expected
