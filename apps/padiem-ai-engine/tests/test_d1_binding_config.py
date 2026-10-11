"""WO-8 PR-B: Production D1 binding config conformance (#1235 A9).

The wrangler.toml must bind the provisioned D1 database (padiem-engine,
database_id below) under both required binding names, with the app entrypoint
and code surface untouched. Provision evidence: CI run 34042827563
(D1_CREATE=PASS, migrations 0001+0002, tables PASS), recorded on #1621.
"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
WRANGLER = APP_ROOT / "wrangler.toml"

EXPECTED_DATABASE_ID = "6b77ad02-bc27-488f-bb97-6325f6750cba"
EXPECTED_DATABASE_NAME = "padiem-engine"
EXPECTED_HARK_B62_DATABASE_ID = "702bb62b-36f5-41a0-973f-c4f663ee01e6"
EXPECTED_HARK_B62_DATABASE_NAME = "padiem-chat-db"


def _wrangler_text() -> str:
    return WRANGLER.read_text(encoding="utf-8")


def test_engine_idempotency_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_IDEMPOTENCY"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_engine_continuation_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_CONTINUATION"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_both_bindings_share_the_single_provisioned_database() -> None:
    """Every authority surface resolves to the SAME database — no split-brain."""
    source = _wrangler_text()

    blocks = [block for block in source.split("[[d1_databases]]")[1:] if block.strip()]
    assert len(blocks) == 7, f"expected exactly 7 d1_databases blocks, found {len(blocks)}"

    engine_ids = []
    hark_ids = []
    for block in blocks:
        fields: dict[str, str] = {}
        for line in block.strip().splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip().strip('"')
        binding = fields.get("binding", "")
        database_id = fields.get("database_id", "")
        if binding == "WEB_XLSX_PRIVATE_B62_D1":
            # Separate, exact B62 owner selection + approval authority:
            # must NOT be mistaken for another Engine-owned D1 binding.
            assert database_id == EXPECTED_HARK_B62_DATABASE_ID
            assert fields.get("database_name") == EXPECTED_HARK_B62_DATABASE_NAME
            hark_ids.append(database_id)
            continue
        assert binding in {
            "ENGINE_IDEMPOTENCY",
            "ENGINE_CONTINUATION",
            "ENGINE_CONNECTOR_GRANTS",
            "ENGINE_IMAGE_STORE",
            "ENGINE_DOCUMENT_STORE",
            "ENGINE_EVIDENCE_STORE",
        }
        assert database_id == EXPECTED_DATABASE_ID
        assert fields.get("database_name") == EXPECTED_DATABASE_NAME
        engine_ids.append(database_id)
    assert len(engine_ids) == 6 and len(set(engine_ids)) == 1
    assert hark_ids == [EXPECTED_HARK_B62_DATABASE_ID]
    assert engine_ids[0] != hark_ids[0], "never collapse independent authority into Engine D1"


def test_image_store_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_IMAGE_STORE"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_connector_grants_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_CONNECTOR_GRANTS"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_document_store_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_DOCUMENT_STORE"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_evidence_store_binding_points_at_provisioned_d1() -> None:
    source = _wrangler_text()

    assert '[[d1_databases]]' in source
    assert 'binding = "ENGINE_EVIDENCE_STORE"' in source
    assert f'database_name = "{EXPECTED_DATABASE_NAME}"' in source
    assert f'database_id = "{EXPECTED_DATABASE_ID}"' in source


def test_binding_config_does_not_change_entrypoint_or_app_surface() -> None:
    source = _wrangler_text()

    assert 'main = "worker_identity.py"' in source
    assert 'binding = "B14_SERVICE"' in source
    assert source.count("[[d1_databases]]") == 7
    assert source.count('binding = "WEB_XLSX_PRIVATE_B62_D1"') == 1
    assert "experimental" not in source.lower()
    assert "InMemory" not in source
