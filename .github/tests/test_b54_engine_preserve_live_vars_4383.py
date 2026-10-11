"""Fail closed on the specific six lost B54 Engine plain-text flags (#4383)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / ".github" / "scripts" / "b54_engine_preserve_live_vars_4383.py"
spec = importlib.util.spec_from_file_location("keep_vars_guard", FILE)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

GOOD_TOML = 'name = "padiem-ai-engine"\nkeep_vars = true\nmain = "worker_identity.py"\n'


def served(bindings):
    return {"success": True, "result": {"id": "good-version", "resources": {"bindings": bindings}}}


def flags():
    return [{"name": name, "type": "plain_text", "text": "operator-controlled-not-to-log"}
            for name in sorted(guard.REQUIRED)]


def test_six_pinned_live_flags_are_accepted_without_reading_values():
    guard.verify(GOOD_TOML, served(flags()), "good-version")


@pytest.mark.parametrize("config", [
    'name = "padiem-ai-engine"\nmain = "worker_identity.py"\n',
    'name = "padiem-ai-engine"\nkeep_vars = false\n',
    'name = "other-worker"\nkeep_vars = true\n',
])
def test_non_keep_vars_config_fails_closed(config):
    with pytest.raises(guard.PreserveError, match="keep_vars"):
        guard.verify(config, served(flags()), "good-version")


def test_missing_or_wrong_type_blocks_mutation():
    with pytest.raises(guard.PreserveError, match="six protected"):
        guard.verify(GOOD_TOML, served(flags()[:-1]), "good-version")
    changes = flags()
    changes[0]["type"] = "secret_text"
    with pytest.raises(guard.PreserveError, match="six protected"):
        guard.verify(GOOD_TOML, served(changes), "good-version")


def test_version_identity_and_duplicates_fail_closed():
    with pytest.raises(guard.PreserveError, match="identity"):
        guard.verify(GOOD_TOML, served(flags()), "not-pinned")
    with pytest.raises(guard.PreserveError, match="duplicate"):
        guard.verify(GOOD_TOML, served(flags() + [flags()[0]]), "good-version")


def test_real_config_and_pre_migration_workflow_are_guarded():
    toml = (ROOT / "apps/padiem-ai-engine/wrangler.toml").read_text("utf-8")
    assert "keep_vars = true" in toml
    workflow = (ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml").read_text("utf-8")
    assert "uv run pywrangler deploy --keep-vars" in workflow
    assert "b54_engine_preserve_live_vars_4383.py" in workflow
    assert workflow.index("Verify six live XLSX flags will be retained before deploy") < workflow.index("Pre-deploy canonical served-version rollback anchor")
    assert workflow.index("Verify six live XLSX flags will be retained before deploy") < workflow.index("Deploy engine to production")
    assert "POST_DEPLOY_SERVED_VERSION_GUARD=PASS" in workflow
