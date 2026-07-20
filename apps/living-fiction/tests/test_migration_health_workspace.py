"""Tests: migration, /health smoke, workspace independence."""

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_new_database_migration(temp_db_path):
    """New database gets all migration tables."""
    from app.db import apply_migrations, get_connection
    conn = get_connection(temp_db_path)
    applied = apply_migrations(conn, str(
        Path(__file__).resolve().parent.parent / "migrations"
    ))
    assert "001_initial.sql" in applied

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {t["name"] for t in tables}
    expected = {
        "readers", "worlds", "characters", "locations", "clues",
        "canon_snapshots", "canon_checkpoints", "episodes",
        "reader_choices", "branches", "generation_runs",
        "pilot_evidence", "rejoin_requests", "schema_migrations",
    }
    assert expected.issubset(table_names)
    conn.close()


def test_existing_database_migration_idempotent(temp_db_path):
    """Re-running migrations on an existing DB is a no-op."""
    from app.db import apply_migrations, get_connection
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        Path(__file__).resolve().parent.parent / "migrations"
    )
    apply_migrations(conn, migrations_dir)
    applied = apply_migrations(conn, migrations_dir)
    assert applied == []
    conn.close()


def test_health_smoke(temp_db_path):
    """Application starts and /health responds."""
    from app.factory import create_app
    app = create_app(db_path=temp_db_path)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ai_provider"] == "mock"


def test_workspace_independence():
    """Living Fiction does not import from sibling apps."""
    # Check that app modules don't import personal_edition or living_travel
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "personal_edition" not in content, \
            f"{py_file} imports from personal_edition"
        assert "living_travel" not in content, \
            f"{py_file} imports from living_travel"
        assert "world_feed" not in content, \
            f"{py_file} imports from world_feed"


def test_no_shared_package():
    """No shared package was created."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    # Ensure there's no shared/ or common/ directory
    for d in app_dir.iterdir():
        if d.is_dir():
            assert d.name not in ("shared", "common"), \
                f"shared package detected: {d.name}"
