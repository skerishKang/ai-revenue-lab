from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "migrations" / "0001_engine_idempotency.sql"
ADAPTER = ROOT / "app" / "idempotency_binding.py"
WRANGLER = ROOT / "wrangler.toml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_idempotency_schema_matches_adapter_table_contract() -> None:
    migration = _text(MIGRATION)
    adapter = _text(ADAPTER)

    assert "padiem_engine_idempotency" in migration
    assert '_TABLE_NAME = "padiem_engine_idempotency"' in adapter

    for column in (
        "app_id TEXT NOT NULL",
        "idempotency_key TEXT NOT NULL",
        "request_fingerprint TEXT NOT NULL",
        "state TEXT NOT NULL",
        "result_json TEXT",
        "created_at TEXT NOT NULL",
        "updated_at TEXT NOT NULL",
        "expires_at TEXT NOT NULL",
        "PRIMARY KEY (app_id, idempotency_key)",
    ):
        assert column in migration


def test_idempotency_schema_records_bounded_state_and_expiry_index() -> None:
    migration = _text(MIGRATION)

    assert "CHECK (state IN ('reserved', 'completed', 'aborted'))" in migration
    assert "idx_padiem_engine_idempotency_expires_at" in migration
    assert "idx_padiem_engine_idempotency_state" in migration


def test_runtime_adapter_does_not_provision_schema() -> None:
    adapter = _text(ADAPTER).upper()

    assert "CREATE TABLE" not in adapter
    assert "CREATE INDEX" not in adapter
    assert "ALTER TABLE" not in adapter
    assert "DROP TABLE" not in adapter


def test_schema_contract_matches_production_binding_config() -> None:
    """WO-8 PR-B inversion: the provisioned D1 database must be bound in Production.

    Pre-PR-B this test asserted absence (fail-closed slice); the #1235 A9
    activation PR-B now binds the provisioned database, so this test asserts
    the exact binding + database identity instead.
    """
    wrangler = _text(WRANGLER)

    assert 'binding = "ENGINE_IDEMPOTENCY"' in wrangler
    assert "[[d1_databases]]" in wrangler
    assert 'database_id = "6b77ad02-bc27-488f-bb97-6325f6750cba"' in wrangler


def test_schema_contract_is_engine_scoped_not_b14_or_b62() -> None:
    migration = _text(MIGRATION)

    assert "padiem_engine_idempotency" in migration
    assert "apps/padiem-chat" not in migration
    assert "apps/korean-ai-platform" not in migration
    assert "b62" not in migration.lower()
    assert "b14" not in migration.lower()
