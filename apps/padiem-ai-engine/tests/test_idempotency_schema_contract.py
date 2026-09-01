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


def test_schema_contract_does_not_mutate_worker_binding_config() -> None:
    wrangler = _text(WRANGLER)

    assert "B14_SERVICE" in wrangler
    assert "ENGINE_IDEMPOTENCY" not in wrangler
    assert "[[d1_databases]]" not in wrangler


def test_schema_contract_is_engine_scoped_not_b14_or_b62() -> None:
    migration = _text(MIGRATION)

    assert "padiem_engine_idempotency" in migration
    assert "apps/padiem-chat" not in migration
    assert "apps/korean-ai-platform" not in migration
    assert "b62" not in migration.lower()
    assert "b14" not in migration.lower()
