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


def test_transient_manifest_renders_all_six_from_immutable_served_values_only():
    import tomllib
    values = ["true", "false", 'a"b\\c', "운영설정", "0", "enable"]
    live = flags()
    for item, value in zip(live, values):
        item["text"] = value
    config = GOOD_TOML + '\n[vars]\nPADIEM_ENGINE_AGENT_DURABLE_ENABLED = "true"\n[env.preview]\nname = "preview"\n'
    rendered = guard.render_exact_served_flags(config, served(live), "good-version")
    parsed = tomllib.loads(rendered)
    assert parsed["vars"] == {
        "PADIEM_ENGINE_AGENT_DURABLE_ENABLED": "true",
        **{entry["name"]: entry["text"] for entry in live},
    }
    assert parsed["env"]["preview"]["name"] == "preview"
    assert "[env.preview]" in rendered
    assert all(name not in config for name in guard.REQUIRED)


def test_missing_plaintext_value_refuses_instead_of_guessing():
    live = flags()
    del live[0]["text"]
    config = GOOD_TOML + '\n[vars]\nPADIEM_ENGINE_AGENT_DURABLE_ENABLED = "true"\n'
    with pytest.raises(guard.PreserveError, match="value unavailable"):
        guard.render_exact_served_flags(config, served(live), "good-version")


def test_checked_in_protected_var_and_malformed_table_refuse_staging():
    name = sorted(guard.REQUIRED)[0]
    config = GOOD_TOML + f'\n[vars]\n{name} = "false"\n'
    with pytest.raises(guard.PreserveError, match="must not be checked"):
        guard.render_exact_served_flags(config, served(flags()), "good-version")
    with pytest.raises(guard.PreserveError, match="canonical \\[vars\\]"):
        guard.render_exact_served_flags(GOOD_TOML, served(flags()), "good-version")


def test_staging_changes_only_runner_local_file_and_reuses_canonical_values(tmp_path):
    import tomllib
    config_path = tmp_path / "wrangler.toml"
    config_path.write_text(GOOD_TOML + '\n[vars]\nPADIEM_ENGINE_AGENT_DURABLE_ENABLED = "true"\n', encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")
    guard.stage_exact_served_vars(config_path, served(flags()), "good-version")
    assert before != config_path.read_text(encoding="utf-8")
    after = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert all(after["vars"][name] == "operator-controlled-not-to-log" for name in guard.REQUIRED)
    assert not (tmp_path / "wrangler.toml.b54-staged").exists()


def test_deploy_gate_stages_immutable_vars_before_published_rollback_anchor():
    workflow = (ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml").read_text("utf-8")
    guard_step = workflow.index("Verify six live XLSX flags will be retained before deploy")
    stage_step = workflow.index("Stage exact served XLSX flags into transient Engine deploy config")
    anchor_step = workflow.index("Pre-deploy canonical served-version rollback anchor")
    deploy_step = workflow.index("Deploy engine to production")
    assert guard_step < stage_step < anchor_step < deploy_step
    assert "--stage-served-vars" in workflow
    assert "ENGINE_PRODUCTION_MUTATION_BEFORE_ANCHOR=0" in workflow
    assert "B54_ENGINE_FULL_BINDING_SET_PRESERVED=PASS" in workflow
