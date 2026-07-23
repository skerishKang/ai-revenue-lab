"""Tests: migration, /health smoke, workspace independence."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_new_database_migration(temp_db_path):
    """New database gets all migration tables, including durable sequences."""
    from app.db import apply_migrations, get_connection

    conn = get_connection(temp_db_path)
    applied = apply_migrations(
        conn,
        str(Path(__file__).resolve().parent.parent / "migrations"),
    )
    assert "001_initial.sql" in applied
    assert "005_episode_number_reservations.sql" in applied

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {table["name"] for table in tables}
    expected = {
        "readers",
        "worlds",
        "characters",
        "locations",
        "clues",
        "canon_snapshots",
        "canon_checkpoints",
        "episodes",
        "episode_number_sequences",
        "reader_choices",
        "branches",
        "generation_runs",
        "pilot_evidence",
        "rejoin_requests",
        "schema_migrations",
    }
    assert expected.issubset(table_names)
    conn.close()


def test_existing_database_migration_idempotent(temp_db_path):
    """Re-running migrations on an existing DB is a no-op."""
    from app.db import apply_migrations, get_connection

    conn = get_connection(temp_db_path)
    migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
    apply_migrations(conn, migrations_dir)
    applied = apply_migrations(conn, migrations_dir)
    assert applied == []
    conn.close()


def test_health_smoke_reports_instantiated_provider_contract(temp_db_path):
    """Health reports actual runtime identity with canonical cost values."""
    from app.factory import create_app

    app = create_app(db_path=temp_db_path, enable_web=False)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "ai_provider": "mock",
            "ai_model": "mock-living-fiction-v1",
            "cost_class": "free",
            "provider_type": "MockProvider",
        }


def test_health_uses_injected_provider_identity(temp_db_path):
    """Health never substitutes settings labels for an injected provider."""
    from app.ai.mock import MockProvider
    from app.domain.enums import CostClass
    from app.factory import create_app

    provider = MockProvider(
        provider_name="contract-provider",
        model="contract-model-v2",
        cost_class=CostClass.PAID,
    )
    app = create_app(db_path=temp_db_path, provider=provider, enable_web=False)
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "ai_provider": "contract-provider",
            "ai_model": "contract-model-v2",
            "cost_class": "paid",
            "provider_type": "MockProvider",
        }


def test_workspace_independence():
    """Living Fiction does not import from sibling apps."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "personal_edition" not in content, f"{py_file} imports personal_edition"
        assert "living_travel" not in content, f"{py_file} imports living_travel"
        assert "world_feed" not in content, f"{py_file} imports world_feed"


def test_no_shared_package():
    """No shared package was created."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for directory in app_dir.iterdir():
        if directory.is_dir():
            assert directory.name not in ("shared", "common"), (
                f"shared package detected: {directory.name}"
            )
