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
    assert len(blocks) == 4, f"expected exactly 4 d1_databases blocks, found {len(blocks)}"

    ids = []
    for block in blocks:
        fields: dict[str, str] = {}
        for line in block.strip().splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip().strip('"')
        binding = fields.get("binding", "")
        database_id = fields.get("database_id", "")
        ids.append(database_id)
        assert binding in {
            "ENGINE_IDEMPOTENCY",
            "ENGINE_CONTINUATION",
            "ENGINE_CONNECTOR_GRANTS",
            "ENGINE_IMAGE_STORE",
        }
        assert database_id == EXPECTED_DATABASE_ID
    assert len(set(ids)) == 1, "all bindings must reference the same database_id"


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


def test_binding_config_does_not_change_entrypoint_or_app_surface() -> None:
    source = _wrangler_text()

    assert 'main = "worker_identity.py"' in source
    assert 'binding = "B14_SERVICE"' in source
    assert source.count("[[d1_databases]]") == 4
    assert "experimental" not in source.lower()
    assert "InMemory" not in source
