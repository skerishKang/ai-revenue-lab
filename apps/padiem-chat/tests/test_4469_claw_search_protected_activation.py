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


def test_new_search_variable_uses_repo_value_and_existing_value_is_preserved(tmp_path):
    import tomllib
    module = _load_module()
    repo = _write_repo_config(tmp_path)
    with repo.open("a") as f: f.write('PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED = "true"\n')
    live = module.parse_live_bindings(_settings_payload(_production_bindings()))
    assert tomllib.loads(module.build_production_config(live, repo, PUBLIC_URL))["vars"]["PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"] == "true"
    live = module.parse_live_bindings(_with_search(value="false"))
    assert tomllib.loads(module.build_production_config(live, repo, PUBLIC_URL))["vars"]["PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"] == "false"
    assert tomllib.loads(module.build_production_config(live, repo, PUBLIC_URL, set_var={"PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED": "true"}))["vars"]["PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"] == "true"


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


def test_existing_production_workflow_uses_generic_explicit_variable_input():
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text()
    assert "ACTIVATE_CLAW_PUBLIC_SEARCH" not in text
    assert "--activate-claw-public-search" not in text
    assert "      set_var:" in text
    assert '--dispatch-event "${GITHUB_EVENT_PATH}"' in text
