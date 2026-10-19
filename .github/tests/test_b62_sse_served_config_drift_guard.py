"""Regression: an accepted code rollout must not inherit unaccepted SSE flag drift."""
from __future__ import annotations

import importlib.util
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

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


def _read_only_cli(settings: dict, served: dict) -> tuple[int, str]:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        (root / "served.json").write_text(json.dumps(served), encoding="utf-8")
        argv = ["sse-served-config-guard",
                "--settings", str(root / "settings.json"),
                "--served-version", str(root / "served.json")]
        output = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = argv
            with redirect_stdout(output):
                code = guard.main()
        finally:
            sys.argv = old_argv
        return code, output.getvalue()


def test_cli_reports_explicit_flag_state_only_after_valid_parity():
    # Parity alone does not prove OFF; this finite readout prevents a false
    # operational readiness conclusion from a PASS on a shared TRUE state.
    for state, expected in ((None, "ABSENT"), ("false", "FALSE"), ("true", "TRUE")):
        code, out = _read_only_cli(s(state), v(state))
        assert code == 0
        assert "B62_SSE_SERVED_CONFIG_PARITY=PASS" in out
        assert "B62_SSE_SERVED_FLAG_STATE=" + expected in out
        assert "B62_DEPLOY_MUTATION=0" in out
        assert "SECRET_" not in out


def test_cli_mismatch_never_prints_flag_state_or_secret_material():
    private = "private-sentinel-must-not-be-logged"
    settings = s("true")
    settings["result"]["bindings"].append({
        "name": "SIMULATED_AUTH", "type": "secret_text", "value": private})
    served = v("false")
    served["result"]["resources"]["bindings"].append({
        "name": "SIMULATED_AUTH", "type": "secret_text", "value": private})
    code, out = _read_only_cli(settings, served)
    assert code == 2
    assert "B62_SSE_SERVED_CONFIG_PARITY=BLOCKED" in out
    assert "B62_SSE_SERVED_FLAG_STATE=" not in out
    assert "B62_DEPLOY_MUTATION=0" in out
    assert private not in out


def test_cloudflare_readonly_mode_uses_state_guard_not_emergency_recovery_candidate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("\n  cloudflare-readonly:\n", 1)[1].split(
        "\n  deploy-production-code:\n", 1)[0]
    assert 'if [ "${{ inputs.mode }}" = "recover_p01_sse_off" ]; then' in readonly
    assert "b62_p01_sse_snapshot_off_recovery.py candidate" in readonly
    assert "b62_sse_served_config_drift_guard.py" in readonly
    assert "B62_CODE_DEPLOY_READONLY=PASS" in readonly
    assert "B62_SSE_SERVED_FLAG_STATE=" in SCRIPT.read_text(encoding="utf-8")


if __name__ == "__main__":
    for k, f in sorted(globals().copy().items()):
        if k.startswith("test_") and callable(f):
            f()
            print(k+"=PASS")
