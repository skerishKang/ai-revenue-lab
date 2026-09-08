from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0004_engine_attachment_images.sql"
ADAPTER = ROOT / "app" / "attachment_byte_store.py"
WRANGLER = ROOT / "wrangler.toml"
GATE = ROOT.parents[1] / ".github" / "workflows" / "b54-engine-d1-provision-gate.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_attachment_schema_matches_adapter_table_contract() -> None:
    migration = _text(MIGRATION)
    adapter = _text(ADAPTER)

    assert "padiem_engine_attachment_images" in migration
    assert '_TABLE_NAME = "padiem_engine_attachment_images"' in adapter

    for column in (
        "attachment_ref TEXT NOT NULL",
        "app_id TEXT NOT NULL",
        "tenant_id TEXT NOT NULL",
        "subject_id TEXT NOT NULL",
        "media_type TEXT NOT NULL",
        "byte_size INTEGER NOT NULL",
        "created_at TEXT NOT NULL",
        "expires_at TEXT",
        "terminal INTEGER NOT NULL DEFAULT 0",
        "payload_base64 TEXT NOT NULL",
        "PRIMARY KEY (attachment_ref)",
    ):
        assert column in migration


def test_adapter_insert_columns_are_all_declared_in_migration() -> None:
    migration = _text(MIGRATION)
    adapter = _text(ADAPTER)

    marker = "INSERT INTO {_TABLE_NAME} "
    assert marker in adapter
    segment = adapter.split(marker, 1)[1].split(") VALUES", 1)[0]
    columns = re.findall(r"[a-z_][a-z0-9_]*", segment)
    assert columns == [
        "attachment_ref",
        "app_id",
        "tenant_id",
        "subject_id",
        "media_type",
        "byte_size",
        "created_at",
        "expires_at",
        "terminal",
        "payload_base64",
    ]
    for column in columns:
        assert f"{column} " in migration


def test_attachment_schema_records_media_bytes_and_terminal_bounds() -> None:
    migration = _text(MIGRATION)

    assert "CHECK (media_type IN ('image/jpeg', 'image/png', 'image/webp'))" in migration
    assert "byte_size > 0 AND byte_size <= 4194304" in migration
    assert "length(payload_base64) <= 5592412" in migration
    assert "CHECK (terminal IN (0, 1))" in migration
    assert "idx_padiem_engine_attachment_images_expires_at" in migration
    assert "idx_padiem_engine_attachment_images_scope" in migration


def test_runtime_adapter_does_not_provision_schema() -> None:
    adapter = _text(ADAPTER).upper()

    assert "CREATE TABLE" not in adapter
    assert "CREATE INDEX" not in adapter
    assert "ALTER TABLE" not in adapter
    assert "DROP TABLE" not in adapter


def test_provision_gate_applies_0004_in_sequence() -> None:
    gate = _text(GATE)

    assert "0004_engine_attachment_images.sql" in gate
    assert "D1_MIGRATIONS=0001,0002,0003,0004" in gate
    assert "'padiem_engine_attachment_images'" in gate


def test_schema_slice_adds_no_worker_binding_or_wiring() -> None:
    wrangler = _text(WRANGLER)

    assert "ATTACHMENT" not in wrangler.upper()
    migration = _text(MIGRATION).lower()
    assert "insert" not in migration
    assert "select" not in migration
