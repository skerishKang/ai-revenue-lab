"""Database-layer tests: migrations, configuration, factory, seeding."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MigrationError, apply_migrations, get_connection
from app.factory import create_app
from app.services import SqliteTaskService
from app.store import Store

MIGRATIONS = "migrations"


# --- 18.1 migrations -----------------------------------------------------


def test_fresh_db_migration_succeeds(tmp_path):
    db = str(tmp_path / "fresh.db")
    conn = get_connection(db)
    try:
        applied = apply_migrations(conn, MIGRATIONS)
        assert "001_initial.sql" in applied
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "tasks" in tables
        assert "task_runs" in tables
        assert "security_settings" in tables
    finally:
        conn.close()


def test_rerun_migration_applies_zero(tmp_path):
    db = str(tmp_path / "rerun.db")
    conn = get_connection(db)
    try:
        apply_migrations(conn, MIGRATIONS)
        second = apply_migrations(conn, MIGRATIONS)
        assert second == []
    finally:
        conn.close()


def test_migration_version_recorded(tmp_path):
    db = str(tmp_path / "version.db")
    conn = get_connection(db)
    try:
        apply_migrations(conn, MIGRATIONS)
        versions = {
            r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
        }
        assert "001_initial.sql" in versions
    finally:
        conn.close()


def test_migration_order_deterministic(tmp_path):
    db = str(tmp_path / "order.db")
    conn = get_connection(db)
    try:
        applied = apply_migrations(conn, MIGRATIONS)
        assert applied == sorted(applied)
    finally:
        conn.close()


def test_migration_failure_rollback(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_good.sql").write_text(
        "CREATE TABLE good_table (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (mig / "002_bad.sql").write_text(
        "CREATE TABLE bad_table (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO nonexistent_table VALUES (1);",
        encoding="utf-8",
    )
    db = str(tmp_path / "fail.db")
    conn = get_connection(db)
    try:
        with pytest.raises(MigrationError) as exc_info:
            apply_migrations(conn, str(mig))
        assert exc_info.value.filename == "002_bad.sql"
        # good migration committed; bad one rolled back entirely.
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "good_table" in tables
        assert "bad_table" not in tables
        versions = {
            r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
        }
        assert "001_good.sql" in versions
        assert "002_bad.sql" not in versions
    finally:
        conn.close()


def test_failed_migration_version_not_recorded(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_bad.sql").write_text("THIS IS NOT VALID SQL;", encoding="utf-8")
    db = str(tmp_path / "failver.db")
    conn = get_connection(db)
    try:
        with pytest.raises(MigrationError):
            apply_migrations(conn, str(mig))
        versions = {
            r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
        }
        assert "001_bad.sql" not in versions
    finally:
        conn.close()


def test_incomplete_sql_rejected(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_incomplete.sql").write_text(
        "CREATE TABLE t (id INTEGER", encoding="utf-8"
    )
    db = str(tmp_path / "incomplete.db")
    conn = get_connection(db)
    try:
        with pytest.raises(MigrationError):
            apply_migrations(conn, str(mig))
    finally:
        conn.close()


def test_invalid_utf8_read_error_handled(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_binary.sql").write_bytes(b"\xff\xfe\x00CREATE TABLE x (id INTEGER);")
    db = str(tmp_path / "binary.db")
    conn = get_connection(db)
    try:
        with pytest.raises(MigrationError):
            apply_migrations(conn, str(mig))
    finally:
        conn.close()


def test_foreign_keys_enabled(tmp_path):
    db = str(tmp_path / "fk.db")
    conn = get_connection(db)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_parent_dir_created(tmp_path):
    db = str(tmp_path / "nested" / "deep" / "app.db")
    conn = get_connection(db)
    try:
        assert (tmp_path / "nested" / "deep").is_dir()
    finally:
        conn.close()


# --- 18.6 configuration & factory ---------------------------------------


def test_default_sqlite_config():
    s = Settings()
    assert s.db_backend == "sqlite"
    assert s.database_path.endswith("korean-ai-platform.db")


def test_ambient_database_url_ignored(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://other-business/db")
    s = Settings()
    # No database_url field exists; the ambient URL is never picked up.
    assert not hasattr(s, "database_url")
    assert s.db_backend == "sqlite"


def test_invalid_backend_fail_closed():
    with pytest.raises(Exception):
        Settings(db_backend="mysql")


def test_postgresql_fail_closed():
    with pytest.raises(Exception):
        Settings(db_backend="postgresql")


def test_import_creates_no_db_file(tmp_path, monkeypatch):
    # Importing the app module must not create a DB file or open a connection.
    target = tmp_path / "should_not_exist.db"
    monkeypatch.setenv("KAP_DATABASE_PATH", str(target))
    import importlib

    import app.config as config_mod

    importlib.reload(config_mod)
    import app.main as main_mod

    importlib.reload(main_mod)
    assert not target.exists()


def test_temporary_db_path_injection(tmp_path):
    db = str(tmp_path / "inject.db")
    app = create_app(db_path=db)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["database_backend"] == "sqlite"


def test_in_memory_store_injection():
    store = Store(seed=False)
    app = create_app(store=store)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.json()["database_backend"] == "memory"


def test_health_backend_only(tmp_path):
    db = str(tmp_path / "health.db")
    app = create_app(db_path=db)
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["persistence"] == "product_local"
        assert body["database_backend"] == "sqlite"


def test_health_no_path_or_secret(tmp_path):
    db = str(tmp_path / "secret.db")
    app = create_app(db_path=db)
    with TestClient(app) as client:
        raw = client.get("/health").text
        assert db not in raw
        assert "secret" not in raw.lower()
        assert "password" not in raw.lower()


# --- 18.5 seed & ID ------------------------------------------------------


def test_seed_only_on_empty_db(tmp_path):
    db = str(tmp_path / "seed.db")
    service = SqliteTaskService(db)
    service.initialize()
    tasks = service.list_tasks()
    assert len(tasks) > 0  # demo seed created


def test_no_duplicate_seed_second_startup(tmp_path):
    db = str(tmp_path / "seed2.db")
    service = SqliteTaskService(db)
    service.initialize()
    first = len(service.list_tasks())
    # Simulate a second startup against the same DB file.
    service2 = SqliteTaskService(db)
    service2.initialize()
    assert len(service2.list_tasks()) == first


def test_new_task_id_no_collision_after_restart(tmp_path):
    db = str(tmp_path / "seq.db")
    service = SqliteTaskService(db)
    service.initialize()
    existing_ids = {t.id for t in service.list_tasks()}
    form = {
        "title": "새 작업",
        "instruction": "지시",
        "project_id": "commerce-backend",
        "worker_model_id": "domestic-open",
        "validator_model_id": "domestic-open",
        "allowed_paths": "app/",
        "denied_paths": "",
        "cost_limit_krw": "1000",
        "external_policy": "allow",
        "branch_mode": "auto",
    }
    task, errors = service.create_task(form)
    assert errors == {}
    assert task.id not in existing_ids
    # Restart and create another; still no collision.
    service2 = SqliteTaskService(db)
    service2.initialize()
    task2, errors2 = service2.create_task(form)
    assert errors2 == {}
    assert task2.id not in existing_ids
    assert task2.id != task.id


def test_seed_false_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    service = SqliteTaskService(db)
    service.initialize(seed=False)
    assert service.list_tasks() == []
