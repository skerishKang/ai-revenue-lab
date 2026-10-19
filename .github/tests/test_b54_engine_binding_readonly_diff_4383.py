"""Offline, GET-only Engine binding inventory regressions (#4383)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b54_engine_binding_readonly_diff_4383.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("engine_binding_readonly", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def version(version_id, bindings):
    return {"success": True, "result": {"id": version_id, "resources": {"bindings": bindings}}}


def served(version_id):
    return {"success": True, "result": {"deployments": [
        {"versions": [{"version_id": version_id, "percentage": 100}]}
    ]}}


def cases():
    shared = [{"name": f"ENGINE_RETAINED_{i}", "type": "d1", "database_id": "not-exposed"} for i in range(12)]
    removed = [{"name": f"ENGINE_PREVIOUS_{i}", "type": "secret_text", "text": "must-not-appear"} for i in range(6)]
    return version(mod.GOOD_VERSION, shared + removed), version(mod.BAD_VERSION, shared)


def test_exact_six_binding_names_and_types_only():
    previous, failed = cases()
    removed, added = mod.compare(served(mod.GOOD_VERSION), previous, failed)
    assert removed == [f"ENGINE_PREVIOUS_{i}:secret_text" for i in range(6)]
    assert added == []
    assert all("must-not-appear" not in item for item in removed)


def test_fail_closed_if_engine_no_longer_serves_known_rollback():
    previous, failed = cases()
    with pytest.raises(mod.AuditError, match="not the recorded safe rollback"):
        mod.compare(served(mod.BAD_VERSION), previous, failed)


def test_fail_closed_for_wrong_immutable_version_identity():
    previous, failed = cases()
    previous["result"]["id"] = "different-version"
    with pytest.raises(mod.AuditError, match="identity mismatch"):
        mod.compare(served(mod.GOOD_VERSION), previous, failed)


def test_fail_closed_on_duplicate_names_or_unexpected_removed_count():
    previous, failed = cases()
    previous["result"]["resources"]["bindings"].append({"name": "ENGINE_RETAINED_0", "type": "service"})
    with pytest.raises(mod.AuditError, match="duplicate"):
        mod.compare(served(mod.GOOD_VERSION), previous, failed)
    previous, failed = cases()
    failed["result"]["resources"]["bindings"].append({"name": "ENGINE_PREVIOUS_0", "type": "secret_text"})
    with pytest.raises(mod.AuditError, match="unexpected binding diff counts"):
        mod.compare(served(mod.GOOD_VERSION), previous, failed)


def test_fail_closed_on_malformed_or_unsafe_bindings():
    previous, failed = cases()
    previous["result"]["resources"]["bindings"][0]["name"] = "../../unsafe"
    with pytest.raises(mod.AuditError, match="name syntax"):
        mod.compare(served(mod.GOOD_VERSION), previous, failed)


def test_workflow_performs_exactly_four_gets_and_no_mutation():
    workflow = (ROOT / ".github" / "workflows" / "b54-engine-binding-readonly-audit.yml").read_text()
    assert workflow.count("curl --fail --silent --show-error") == 4
    assert '"${base}/settings"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "NO_DEPLOY_NO_ROLLBACK_NO_SECRET_MUTATION=YES" in workflow
    for forbidden in ("uv run pywrangler deploy", "wrangler secret put", "PATCH ", "PUT ", "POST "):
        assert forbidden not in workflow


def test_mutable_settings_missing_six_flags_can_be_reported_without_values():
    good_bindings = [{"name": n, "type": "plain_text", "text": "NEVER_LOG_ME"}
                     for n in sorted(mod.PROTECTED_ENGINE_FLAGS)]
    good = version(mod.GOOD_VERSION, good_bindings)
    settings = {"success": True, "result": {"bindings": []}}
    missing = mod.settings_flags(settings, good)
    assert missing == sorted(mod.PROTECTED_ENGINE_FLAGS)
    assert all("NEVER_LOG_ME" not in name for name in missing)


def test_mutable_settings_six_flags_match_and_wrong_type_is_detected():
    good_bindings = [{"name": n, "type": "plain_text"}
                     for n in sorted(mod.PROTECTED_ENGINE_FLAGS)]
    good = version(mod.GOOD_VERSION, good_bindings)
    settings = {"success": True, "result": {"bindings": list(good_bindings)}}
    assert mod.settings_flags(settings, good) == []
    settings["result"]["bindings"][0] = {**good_bindings[0], "type": "secret_text"}
    assert mod.settings_flags(settings, good) == [good_bindings[0]["name"]]


def test_mutable_settings_parity_fails_closed_on_untrusted_metadata():
    good = version(mod.GOOD_VERSION, [
        {"name": n, "type": "plain_text"} for n in mod.PROTECTED_ENGINE_FLAGS
    ])
    with pytest.raises(mod.AuditError, match="settings GET"):
        mod.settings_flags({"success": False, "result": {}}, good)
    duplicate = [{"name": next(iter(mod.PROTECTED_ENGINE_FLAGS)), "type": "plain_text"}] * 2
    with pytest.raises(mod.AuditError, match="duplicate"):
        mod.settings_flags({"success": True, "result": {"bindings": duplicate}}, good)
