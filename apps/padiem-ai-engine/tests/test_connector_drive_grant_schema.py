"""Schema contract for the Engine Google Drive capability grant migration (#2222)."""

from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "migrations"


def test_connector_grant_base_schema_stays_gmail_compatible() -> None:
    source = (MIGRATIONS / "0003_engine_connector_grants.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS padiem_engine_connector_grants" in source
    assert "granted_scopes_json TEXT NOT NULL" in source
    assert "PRIMARY KEY (app_id, connector_id)" in source


def test_drive_capability_migration_adds_only_bounded_json_column() -> None:
    source = (MIGRATIONS / "0005_engine_connector_drive_capabilities.sql").read_text(encoding="utf-8")
    normalized = " ".join(source.split())
    assert "ALTER TABLE padiem_engine_connector_grants" in normalized
    assert "ADD COLUMN granted_capabilities_json TEXT NOT NULL DEFAULT '[]';" in normalized

    lowered = source.lower()
    for forbidden in ("refresh_token", "access_token", "client_secret", "client_id"):
        assert forbidden not in lowered


def test_migration_order_places_drive_capability_after_connector_grant_table() -> None:
    names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert names.index("0003_engine_connector_grants.sql") < names.index(
        "0005_engine_connector_drive_capabilities.sql"
    )
