"""Regression: an accepted code rollout must not inherit unaccepted SSE flag drift."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_sse_served_config_drift_guard.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
import sys
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("b62_sse_guard", SCRIPT)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
FLAG = "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"


def s(flag):
    binds = [{"name": "ASSETS", "type": "assets"}]
    if flag is not None:
        binds.append({"name": FLAG, "type": "plain_text", "text": flag})
    return {"success": True, "result": {"bindings": binds}}


def v(flag):
    binds = [{"name": "ASSETS", "type": "assets"}]
    if flag is not None:
        binds.append({"name": FLAG, "type": "plain_text", "text": flag})
    return {"result": {"id": "00000000-0000-0000-0000-000000000001", "resources": {
        "script": {"etag": "sha-test"}, "script_runtime": {},
        "bindings": binds,
    }}}


def test_same_state_can_continue():
    for state in (None, "false", "true"):
        assert guard.verify(s(state), v(state)) == (state or "absent")


def test_unaccepted_patch_redeploy_refused():
    # Actual 2026-10-14: server restored pre-activation version, latest has SSE=true.
    for a, b in (("true", None), ("true", "false"), (None, "true"), ("false", "true")):
        try:
            guard.verify(s(a), v(b))
        except guard.ServedSSEStateDrift as exc:
            assert str(exc) == "SSE_FLAG_LATEST_VS_ACTIVE_DRIFT"
        else:
            raise AssertionError(f"Unsafe B62 redeploy: {a!r} vs {b!r}")


def test_invalid_and_duplicated_binding_fails_closed():
    bad = s("true")
    bad["result"]["bindings"].append({"name": FLAG, "type": "plain_text", "text": "true"})
    cases = [(bad, v("true")), (s("enabled"), v("true")),
             (s("true"), v("enabled")), ({"success": True}, v("true"))]
    for settings, version in cases:
        try:
            guard.verify(settings, version)
        except guard.ServedSSEStateDrift:
            continue
        raise AssertionError("Malformed SSE metadata accepted")


def test_b62_preflight_and_premutation_both_block_before_upload():
    w = WORKFLOW.read_text(encoding="utf-8")
    readonly = w.split("\n  cloudflare-readonly:", 1)[1].split("\n  deploy-production-code:", 1)[0]
    deploy = w.split("\n  deploy-production-code:", 1)[1].split("\n  rollback-production-code:", 1)[0]
    helper = "b62_sse_served_config_drift_guard.py"
    assert helper in readonly
    assert readonly.index(helper) < readonly.index("B62_CODE_DEPLOY_READONLY=PASS")
    assert helper in deploy
    assert deploy.index(helper) < deploy.index("Deploy production code preserving the full binding set")
    assert "test_b62_sse_served_config_drift_guard.py" in w
    assert '.github/scripts/b62_sse_served_config_drift_guard.py' in w


if __name__ == "__main__":
    for k, f in sorted(globals().copy().items()):
        if k.startswith("test_") and callable(f):
            f()
            print(k+"=PASS")
