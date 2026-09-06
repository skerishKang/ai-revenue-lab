"""Lock #1235 idempotency injection at the canonical identity-bound Worker."""

from __future__ import annotations

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_identity_worker_injects_existing_optional_idempotency_adapter() -> None:
    source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

    assert "idempotency_adapter = legacy_worker._idempotency_adapter_for_env(env)" in source
    assert "idempotency_adapter=idempotency_adapter" in source
    assert "CanonicalIdempotencyOrchestrationEngineService(" in source


def test_source_wiring_activates_durable_production_binding() -> None:
    """WO-8 PR-B inversion: entrypoint unchanged, durable binding now active."""
    wrangler_source = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")

    assert 'main = "worker_identity.py"' in wrangler_source
    assert 'binding = "ENGINE_IDEMPOTENCY"' in wrangler_source
    assert "[[d1_databases]]" in wrangler_source
    assert 'database_id = "6b77ad02-bc27-488f-bb97-6325f6750cba"' in wrangler_source
