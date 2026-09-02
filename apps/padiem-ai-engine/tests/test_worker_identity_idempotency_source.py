"""Lock #1235 idempotency injection at the canonical identity-bound Worker."""

from __future__ import annotations

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_identity_worker_injects_existing_optional_idempotency_adapter() -> None:
    source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

    assert "idempotency_adapter = legacy_worker._idempotency_adapter_for_env(env)" in source
    assert "idempotency_adapter=idempotency_adapter" in source
    assert "IdentityBoundOrchestrationEngineService(" in source


def test_source_wiring_does_not_activate_production_binding() -> None:
    wrangler_source = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")

    assert 'main = "worker_identity.py"' in wrangler_source
    assert 'binding = "ENGINE_IDEMPOTENCY"' not in wrangler_source
    assert "[[d1_databases]]" not in wrangler_source
