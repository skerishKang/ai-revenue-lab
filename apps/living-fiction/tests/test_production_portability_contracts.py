"""Production portability contracts for Living Fiction.

These tests run entirely on SQLite / offline: they pin the backend-selection
and fail-closed rules, URL/secret non-leakage, SQL adaptation, the PostgreSQL
migration manifest, bootstrap idempotency and invite privacy, and the static
contracts of the Modal and Cloudflare deployment skeletons. Live PostgreSQL
behaviour is covered separately by tests_postgres_integration/ (explicit run
only).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app import auth
from app.config import settings
from app.database.engine import build_engine
from app.database.errors import ConfigurationError, SchemaMismatchError
from app.database.migrate_postgres import (
    expected_versions,
    file_checksum,
    list_migrations,
    split_statements,
    verify_schema_current,
)
from app.database.postgres import connect_postgres
from app.database.sql import (
    adapt_sql_for_postgres,
    translate_insert_or_ignore,
    translate_placeholders,
)
from app.database.url import is_postgres_url, redact_url
from app.db import apply_migrations, get_connection
from app.ops import bootstrap

APP_ROOT = Path(__file__).resolve().parent.parent
PG_MIGRATIONS_DIR = APP_ROOT / "migrations_postgres"
SQLITE_MIGRATIONS_DIR = APP_ROOT / "migrations"
DEPLOY_DIR = APP_ROOT / "deploy"

SECRET_URL = "postgresql://appuser:supersecretpw@db.internal.example:5432/lf"


@pytest.fixture()
def migrated_conn(tmp_path):
    conn = get_connection(str(tmp_path / "lf-contract.db"))
    apply_migrations(conn, str(SQLITE_MIGRATIONS_DIR))
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def modal_entry():
    path = DEPLOY_DIR / "modal" / "app_entry.py"
    spec = importlib.util.spec_from_file_location("lf_modal_app_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Backend selection: explicit, fail closed ───────────────────────────────


def test_unknown_backend_rejected(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "mysql")
    with pytest.raises(ValueError, match="must be 'sqlite' or 'postgres'"):
        settings.validate_database()


def test_production_sqlite_rejected(monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "database_backend", "sqlite")
    with pytest.raises(ValueError, match="production requires the postgres"):
        settings.validate_database()


def test_postgres_requires_runtime_url(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "postgres")
    monkeypatch.setattr(settings, "database_url", "")
    with pytest.raises(ValueError, match="LF_DATABASE_URL"):
        settings.validate_database()


def test_postgres_url_must_be_postgres_url(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "postgres")
    monkeypatch.setattr(settings, "database_url", "mysql://u:p@h/db")
    with pytest.raises(ValueError, match="not a valid PostgreSQL"):
        settings.validate_database()


def test_backend_is_normalized_not_inferred(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "  Postgres ")
    monkeypatch.setattr(settings, "database_url", SECRET_URL)
    settings.validate_database()
    assert settings.database_backend == "postgres"


def test_validation_errors_never_include_url_or_password(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "postgres")
    monkeypatch.setattr(settings, "database_url", "mysql://u:leakme@h/db")
    with pytest.raises(ValueError) as excinfo:
        settings.validate_database()
    message = str(excinfo.value)
    assert "leakme" not in message
    assert "mysql://u" not in message


def test_factory_production_sqlite_fails_closed(monkeypatch, tmp_path):
    from app.factory import create_app

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "database_backend", "sqlite")
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "x.db"))
    with pytest.raises(ValueError, match="production requires the postgres"):
        create_app(enable_web=False)


def test_factory_postgres_without_url_fails_closed(monkeypatch, tmp_path):
    from app.factory import create_app

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "database_backend", "postgres")
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "x.db"))
    with pytest.raises(ValueError, match="LF_DATABASE_URL"):
        create_app(enable_web=False)


def test_build_engine_rejects_unknown_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_backend", "oracle")
    with pytest.raises(ConfigurationError):
        build_engine(settings, str(tmp_path / "x.db"))


def test_build_engine_postgres_without_url_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_backend", "postgres")
    monkeypatch.setattr(settings, "database_url", "")
    with pytest.raises(ConfigurationError, match="LF_DATABASE_URL"):
        build_engine(settings, str(tmp_path / "x.db"))


def test_sqlite_engine_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_backend", "sqlite")
    engine = build_engine(settings, str(tmp_path / "x.db"))
    assert engine.backend == "sqlite"
    conn = engine.acquire()
    try:
        assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
    finally:
        engine.release(conn)


# ── URL / secret non-leakage ───────────────────────────────────────────────


def test_redact_url_strips_password():
    redacted = redact_url(SECRET_URL)
    assert "supersecretpw" not in redacted
    assert "***@" in redacted


def test_redact_url_unparseable_is_fully_redacted():
    assert redact_url("postgresql://user:pw@[bad") == "<redacted>"


def test_is_postgres_url_recognizes_schemes():
    assert is_postgres_url("postgresql://u:p@h/db")
    assert is_postgres_url("postgres://u:p@h/db")
    assert is_postgres_url("postgresql+psycopg://u:p@h/db")
    assert not is_postgres_url("mysql://u:p@h/db")
    assert not is_postgres_url("sqlite:///x.db")
    assert not is_postgres_url("")


def test_connect_postgres_error_is_generic():
    with pytest.raises(ConfigurationError) as excinfo:
        connect_postgres(
            "postgresql://u:leakme@127.0.0.1:1/db", connect_timeout=1
        ) if _connect_accepts_timeout() else connect_postgres(
            "postgresql://u:leakme@127.0.0.1:1/db"
        )
    message = str(excinfo.value)
    assert "leakme" not in message
    assert "127.0.0.1" not in message


def _connect_accepts_timeout() -> bool:
    return False


# ── SQL adaptation ─────────────────────────────────────────────────────────


def test_translate_placeholders_is_quote_aware():
    sql = "SELECT * FROM t WHERE a = ? AND b = 'lit?eral' AND c = \"id?ent\""
    out = translate_placeholders(sql)
    assert out.count("%s") == 1
    assert "'lit?eral'" in out
    assert '"id?ent"' in out


def test_insert_or_ignore_rewrite():
    out = translate_insert_or_ignore(
        "INSERT OR IGNORE INTO readers (id) VALUES (?)"
    )
    assert out == "INSERT INTO readers (id) VALUES (?) ON CONFLICT DO NOTHING"


def test_non_insert_or_ignore_unchanged():
    sql = "INSERT INTO readers (id) VALUES (?)"
    assert translate_insert_or_ignore(sql) == sql


def test_adapt_sql_combines_rewrites():
    out = adapt_sql_for_postgres(
        "INSERT OR IGNORE INTO readers (id, note) VALUES (?, 'q?')"
    )
    assert out == (
        "INSERT INTO readers (id, note) VALUES (%s, 'q?') "
        "ON CONFLICT DO NOTHING"
    )


# ── PostgreSQL migration manifest ──────────────────────────────────────────


def test_migration_manifest_matches_disk_order():
    versions = expected_versions(PG_MIGRATIONS_DIR)
    files = [p.name for p in sorted(PG_MIGRATIONS_DIR.glob("*.sql"))]
    assert versions == files
    assert len(versions) == 10
    assert versions[0] == "001_worlds_readers.sql"
    assert versions[-1] == "010_triggers.sql"
    assert versions == sorted(versions)


def test_migration_checksums_are_stable_and_unique():
    checksums = [
        file_checksum(p) for p in list_migrations(PG_MIGRATIONS_DIR)
    ]
    assert len(checksums) == len(set(checksums))
    first = list_migrations(PG_MIGRATIONS_DIR)[0]
    assert file_checksum(first) == checksums[0]


def test_every_migration_splits_into_statements():
    for path in list_migrations(PG_MIGRATIONS_DIR):
        statements = split_statements(path.read_text(encoding="utf-8"))
        assert statements, f"{path.name} split into zero statements"
        for stmt in statements:
            assert stmt.strip()


def _first_sql_line(stmt):
    for line in stmt.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return stripped
    return ""


def test_split_statements_keeps_dollar_quoted_trigger_body():
    sql = (PG_MIGRATIONS_DIR / "010_triggers.sql").read_text(encoding="utf-8")
    statements = split_statements(sql)
    assert len(statements) == 3
    fn = statements[0]
    assert _first_sql_line(fn).upper().startswith("CREATE OR REPLACE FUNCTION")
    assert "UPDATE branch_generation_requests" in fn
    assert fn.count("$$") == 2
    assert _first_sql_line(statements[1]).upper().startswith("DROP TRIGGER")
    assert _first_sql_line(statements[2]).upper().startswith("CREATE TRIGGER")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeRaw:
    def __init__(self, applied_rows):
        self.executed = []
        self._applied = applied_rows

    def execute(self, sql, params=()):
        self.executed.append(sql)
        if sql.lstrip().upper().startswith("SELECT"):
            return _FakeCursor(self._applied)
        return _FakeCursor([])


def test_verify_schema_current_fails_closed_on_empty_database():
    raw = _FakeRaw([])
    with pytest.raises(SchemaMismatchError, match="missing=10"):
        verify_schema_current(raw, PG_MIGRATIONS_DIR)


def test_verify_schema_current_accepts_complete_manifest():
    rows = [
        {"version": v, "checksum": "x"} for v in expected_versions(PG_MIGRATIONS_DIR)
    ]
    verify_schema_current(_FakeRaw(rows), PG_MIGRATIONS_DIR)


def test_verify_schema_current_rejects_unknown_version():
    rows = [
        {"version": v, "checksum": "x"} for v in expected_versions(PG_MIGRATIONS_DIR)
    ]
    rows.append({"version": "999_unexpected.sql", "checksum": "x"})
    with pytest.raises(SchemaMismatchError, match="unknown=1"):
        verify_schema_current(_FakeRaw(rows), PG_MIGRATIONS_DIR)


# ── Operator bootstrap: idempotency + invite privacy ───────────────────────

HMAC_KEY = "contract-test-hmac-key-0123456789"


def test_bootstrap_world_is_idempotent(migrated_conn):
    assert bootstrap.ensure_world(migrated_conn) is True
    assert bootstrap.ensure_world(migrated_conn) is False
    count = migrated_conn.execute("SELECT COUNT(*) AS n FROM worlds").fetchone()["n"]
    assert count == 1


def test_bootstrap_canon_is_idempotent(migrated_conn):
    assert bootstrap.ensure_canon(migrated_conn) is True
    assert bootstrap.ensure_canon(migrated_conn) is False
    canon_episodes = migrated_conn.execute(
        "SELECT COUNT(*) AS n FROM episodes WHERE episode_type = 'canon'"
    ).fetchone()["n"]
    assert canon_episodes == 1
    published = migrated_conn.execute(
        "SELECT review_state FROM episodes WHERE episode_type = 'canon'"
    ).fetchone()["review_state"]
    assert published == "published"
    assert migrated_conn.execute(
        "SELECT COUNT(*) AS n FROM canon_snapshots"
    ).fetchone()["n"] == 1
    assert migrated_conn.execute(
        "SELECT COUNT(*) AS n FROM canon_checkpoints"
    ).fetchone()["n"] == 1


def test_bootstrap_reader_is_idempotent(migrated_conn):
    first = bootstrap.ensure_bootstrap_reader(migrated_conn)
    second = bootstrap.ensure_bootstrap_reader(migrated_conn)
    assert first == second
    assert migrated_conn.execute(
        "SELECT COUNT(*) AS n FROM readers"
    ).fetchone()["n"] == 1


def test_bootstrap_invite_never_duplicates_active(migrated_conn):
    reader_id = bootstrap.ensure_bootstrap_reader(migrated_conn)
    assert bootstrap.active_bound_invite_id(migrated_conn) is None
    bootstrap.issue_invite(migrated_conn, HMAC_KEY, reader_id)
    active = bootstrap.active_bound_invite_id(migrated_conn)
    assert active is not None
    count = migrated_conn.execute(
        "SELECT COUNT(*) AS n FROM invite_credentials"
    ).fetchone()["n"]
    assert count == 1


def test_bootstrap_rotate_revokes_then_reissues(migrated_conn):
    reader_id = bootstrap.ensure_bootstrap_reader(migrated_conn)
    old_code = bootstrap.issue_invite(migrated_conn, HMAC_KEY, reader_id)
    assert auth.verify_invite_code(migrated_conn, old_code, HMAC_KEY) == reader_id

    revoked = bootstrap.revoke_active_bound_invites(migrated_conn)
    assert revoked == 1
    assert auth.verify_invite_code(migrated_conn, old_code, HMAC_KEY) is None
    assert bootstrap.active_bound_invite_id(migrated_conn) is None

    new_code = bootstrap.issue_invite(migrated_conn, HMAC_KEY, reader_id)
    assert new_code != old_code
    assert auth.verify_invite_code(migrated_conn, new_code, HMAC_KEY) == reader_id


def test_invite_code_is_stored_as_digest_only(migrated_conn):
    reader_id = bootstrap.ensure_bootstrap_reader(migrated_conn)
    code = bootstrap.issue_invite(migrated_conn, HMAC_KEY, reader_id)
    rows = migrated_conn.execute("SELECT * FROM invite_credentials").fetchall()
    assert rows
    for row in rows:
        blob = "|".join("" if v is None else str(v) for v in tuple(row))
        assert code not in blob
    digest = auth.hash_invite_code(code, HMAC_KEY)
    stored = migrated_conn.execute(
        "SELECT code_digest FROM invite_credentials"
    ).fetchone()["code_digest"]
    assert stored == digest


def test_bootstrap_cli_fails_closed_without_migration_url(monkeypatch, capsys):
    monkeypatch.setattr(settings, "migration_database_url", "")
    assert bootstrap.main(["migrate"]) == 1
    err = capsys.readouterr().err
    assert "LF_MIGRATION_DATABASE_URL" in err


def test_bootstrap_cli_rejects_non_postgres_url_without_leak(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        settings, "migration_database_url", "mysql://u:leakme@h/db"
    )
    assert bootstrap.main(["migrate"]) == 1
    err = capsys.readouterr().err
    assert "leakme" not in err
    assert "mysql://u" not in err


def test_bootstrap_invite_fails_closed_without_hmac_key(monkeypatch, capsys):
    monkeypatch.setattr(
        settings, "migration_database_url", "postgresql://u@h/db"
    )
    monkeypatch.setattr(settings, "credential_hmac_key", "")
    assert bootstrap.main(["invite"]) == 1
    err = capsys.readouterr().err
    assert "LF_CREDENTIAL_HMAC_KEY" in err


# ── Modal deployment skeleton ──────────────────────────────────────────────


def test_modal_entry_app_name_and_free_tier_constants(modal_entry):
    assert modal_entry.APP_NAME == "ai-revenue-living-fiction"
    assert modal_entry.MAX_CONTAINERS <= 2
    assert modal_entry.SCALEDOWN_WINDOW_SECONDS <= 120
    assert modal_entry.MEMORY_MB <= 1024


def test_modal_entry_source_pins_free_tier_caps(modal_entry):
    source = Path(modal_entry.__file__).read_text(encoding="utf-8")
    assert "min_containers=0" in source
    assert "buffer_containers=0" in source
    assert "max_containers=MAX_CONTAINERS" in source
    assert "gpu=" not in source
    assert "volumes=" not in source
    assert "custom_domains" not in source
    assert "@modal.concurrent" not in source
    assert "keep_warm" not in source
    assert "modal.Volume" not in source


def test_modal_entry_builds_asgi_app_with_health(monkeypatch, tmp_path, modal_entry):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "database_backend", "sqlite")
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "modal.db"))
    monkeypatch.setattr(settings, "admin_secret", "contract-admin-secret-value-0123456789")
    monkeypatch.setattr(
        settings, "credential_hmac_key", "contract-credential-hmac-0123456789"
    )
    monkeypatch.setattr(
        settings, "session_hmac_key", "contract-session-hmac-0123456789"
    )
    monkeypatch.setattr(settings, "allowed_origins", "")

    asgi = modal_entry.build_asgi_app()
    client = TestClient(asgi)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["cost_class"] == "free"


# ── Cloudflare proxy skeleton ──────────────────────────────────────────────


def test_cloudflare_worker_static_contracts():
    source = (DEPLOY_DIR / "cloudflare" / "src" / "index.js").read_text(
        encoding="utf-8"
    )
    assert "env.UPSTREAM_ORIGIN" in source
    assert "modal.run" not in source
    assert "AbortSignal.timeout" in source
    assert "no-store" in source
    assert "504" in source
    assert "502" in source
    assert "cacheEverything: false" in source
    assert 'Access-Control-Allow-Origin": "*"' not in source
    assert "Access-Control-Allow-Origin', '*'" not in source
    assert "X-Forwarded-Host" in source


def test_cloudflare_wrangler_example_has_no_real_origin():
    source = (DEPLOY_DIR / "cloudflare" / "wrangler.toml.example").read_text(
        encoding="utf-8"
    )
    assert 'UPSTREAM_ORIGIN = ""' in source
    assert "modal.run" not in source
    assert "workers.dev" not in source
