"""One-time P01 SSE recovery source/snapshot matrix; no live network or secrets."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_p01_sse_snapshot_off_recovery.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
spec = importlib.util.spec_from_file_location("p01_sse_snapshot_off", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def b(name, kind="plain_text", **attrs):
    return {"name": name, "type": kind, **attrs}


def fixtures():
    bs = [
        b("ASSETS", "assets"),
        b("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        b("PADIEM_CHAT_RUNTIME_MODE", text="b14"),
        b("PADIEM_CHAT_LIVE_ENABLED", text="true"),
        b("P01_ENGINE_SERVICE", "service", service="padiem-ai-engine"),
        b("P01_ENGINE_CREDENTIAL", "secret_text"),
        b("PADIEM_CHAT_QUOTA_SALT", "secret_text"),
        b("PADIEM_CHAT_PUBLIC_BASE_URL", text="https://chat.padiem.net"),
    ] + [b(f"EXTRA_{i:02}", text=f"safe-{i}") for i in range(35)]
    assert len(bs) == 43
    snapshot = {"success": True, "result": {"bindings": copy.deepcopy(bs)}}
    settings = copy.deepcopy(snapshot)
    settings["result"]["bindings"].append(b(gate.FLAG, text="true"))
    version = {"success": True, "result": {"id": gate.PREMUTATION_VERSION_ID, "resources": {
        "script": {"etag": "same-original-source"},
        "script_runtime": {"compatibility_date": "2026-10-01"},
        "bindings": copy.deepcopy(bs),
    }}}
    deployments = {"success": True, "result": {"deployments": [{
        "id": "deployment", "versions": [{"version_id": gate.PREMUTATION_VERSION_ID, "percentage": 100}]
    }]}}
    latest = {"success": True, "result": {"items": [{"id": gate.BAD_LATEST_VERSION_ID}]}}
    return settings, snapshot, deployments, version, latest


def test_recovery_recognizes_exact_incident():
    args = fixtures()
    gate.candidate(args[0], args[3])
    gate.validate(*args)


@pytest.mark.parametrize("change", [
    "added_binding", "changed_runtime", "changed_secret", "bad_snapshot",
    "different_active", "different_latest", "lost_served_binding", "split_traffic",
])
def test_recovery_refuses_other_changes(change):
    x = copy.deepcopy(fixtures())
    if change == "added_binding":
        x[0]["result"]["bindings"].append(b("FORGED", text="yes"))
    elif change == "changed_runtime":
        x[0]["result"]["bindings"][2]["text"] = "test"
    elif change == "changed_secret":
        x[0]["result"]["bindings"][5]["type"] = "plain_text"
    elif change == "bad_snapshot":
        x[1]["result"]["bindings"].pop()
    elif change == "different_active":
        x[3]["result"]["id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "different_latest":
        x[4]["result"]["items"][0]["id"] = "different"
    elif change == "lost_served_binding":
        x[3]["result"]["resources"]["bindings"].pop()
    else:
        x[2]["result"]["deployments"][0]["versions"][0]["percentage"] = 50
    with pytest.raises(gate.RecoveryRefused):
        gate.validate(*x)


@pytest.mark.parametrize("change", [
    "no_script_flag", "script_false", "served_true", "script_malformed", "served_malformed",
])
def test_recovery_candidate_refuses_nonincident_state(change):
    x = copy.deepcopy(fixtures())
    if change == "no_script_flag":
        x[0]["result"]["bindings"].pop()
    elif change == "script_false":
        x[0]["result"]["bindings"][-1]["text"] = "false"
    elif change == "served_true":
        x[3]["result"]["resources"]["bindings"].append(b(gate.FLAG, text="true"))
    elif change == "script_malformed":
        x[0]["result"]["bindings"][-1]["type"] = "secret_text"
    else:
        x[3]["result"]["resources"]["bindings"].append(b(gate.FLAG, "secret_text"))
    with pytest.raises(gate.RecoveryRefused):
        gate.candidate(x[0], x[3])


def test_only_protected_code_gate_with_snapshot_and_hard_recovery_scope():
    w = WORKFLOW.read_text(encoding="utf-8")
    assert "recover_p01_sse_off" in w
    assert "RECOVER_B62_P01_SSE_OFF_FROM_PINNED_SNAPSHOT" in w
    assert "b62_p01_sse_snapshot_off_recovery.py candidate" in w
    assert "b62_p01_sse_snapshot_off_recovery.py validate" in w
    block = w.split("\n  deploy-production-code:\n", 1)[1].split(
        "\n  rollback-production-code:\n", 1)[0]
    assert block.count("environment: production") == 1
    assert "actions: read" in block
    assert "38444728738" in block and "b62-claw-config-premutation-settings" in block
    assert block.index("Prove sole SSE drift, exact snapshot and pinned active/latest versions") < block.index("Deploy production code preserving the full binding set")
    assert 'config_settings="' + chr(36) + '{RECOVERY_SNAPSHOT}"' in block
    assert 'before_comparison="' + chr(36) + '{RECOVERY_SNAPSHOT}"' in block
    assert "b62_served_version_secret_guard.py verify" in block
    assert "MIGRATION_040_PREDEPLOY=EXACT" in block
    assert "MIGRATION_008_PREDEPLOY=EXACT" in block
    assert "B62_PRODUCTION_CODE_AUTO_ROLLBACK=EXECUTED" in block
    assert "SSE_RECOVERY_OFF_OWNER_AUTHORIZED=PASS" in block
    assert "RECOVERY_MUTATES_ONLY_UNACCEPTED_SSE_FLAG=REMOVE" in block
