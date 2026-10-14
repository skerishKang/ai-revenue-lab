"""#4469: explicit one-variable search activation in existing protected B62 deploy."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from test_b62_production_deploy_config import (
    _load_module, _settings_payload, _production_bindings,
    _write_repo_config, PUBLIC_URL,
)

ROOT = Path(__file__).resolve().parents[3]


def _binding_guard():
    path = ROOT / ".github/scripts/b62_binding_state_guard.py"
    spec = importlib.util.spec_from_file_location("b62_binding_state_guard_test_4469", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_search(*, value="true"):
    return _settings_payload(_production_bindings() + [{
        "type": "plain_text", "name": "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED",
        "text": value,
    }])


def test_claw_search_exact_missing_to_on_builder_and_guard(tmp_path):
    module = _load_module()
    before = _settings_payload(_production_bindings())
    live = module.parse_live_bindings(before)
    config = module.build_production_config(
        live, _write_repo_config(tmp_path), PUBLIC_URL,
        activate_claw_public_search=True,
    )
    assert 'PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED = "true"' in config
    module.verify_mutation_zero(config, live, allow_claw_public_search=True)
    with pytest.raises(module.ProductionConfigError, match="mutates live"):
        module.verify_mutation_zero(config, live)
    guard = _binding_guard()
    guard.assert_claw_public_search_added_only(before, _with_search())


def test_on_is_idempotent_and_off_cannot_be_overwritten(tmp_path):
    mod = _load_module()
    exact = _with_search()
    live = mod.parse_live_bindings(exact)
    output = mod.build_production_config(
        live, _write_repo_config(tmp_path), PUBLIC_URL,
        activate_claw_public_search=True,
    )
    mod.verify_mutation_zero(output, live, allow_claw_public_search=True)
    _binding_guard().assert_claw_public_search_added_only(exact, exact)
    drift = mod.parse_live_bindings(_with_search(value="false"))
    with pytest.raises(mod.ProductionConfigError, match="conflicts"):
        mod.build_production_config(
            drift, _write_repo_config(tmp_path), PUBLIC_URL,
            activate_claw_public_search=True,
        )


def test_no_unrelated_binding_change_allowed():
    guard = _binding_guard()
    before = _settings_payload(_production_bindings())
    correct = _with_search()
    guard.assert_claw_public_search_added_only(before, correct)
    with pytest.raises(guard.BindingStateError):
        guard.assert_claw_public_search_added_only(before, before)
    with pytest.raises(guard.BindingStateError):
        guard.assert_claw_public_search_added_only(before, _with_search(value="false"))
    plus = _settings_payload(correct["result"]["bindings"] + [{
        "type": "plain_text", "name": "UNRELATED_ENABLED", "text": "true",
    }])
    with pytest.raises(guard.BindingStateError):
        guard.assert_claw_public_search_added_only(before, plus)


def test_existing_production_workflow_requires_explicit_single_mode():
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    assert "ACTIVATE_CLAW_PUBLIC_SEARCH" in text
    assert "DEPLOY_B62_CLAW_PUBLIC_WEB_SEARCH_FROM_EXACT_MAIN" in text
    assert "--activate-claw-public-search" in text
    assert "--expected-add-claw-public-search" in text
    assert "ACTIVATE_CLAW_PUBLIC_SEARCH" in text.split("Read back exact post-deploy binding and variable state")[1]
