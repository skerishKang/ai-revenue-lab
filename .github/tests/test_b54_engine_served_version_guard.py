"""Network-free contract tests for the served-version caller-registry guard (#2414).

Proves that ``b54_engine_served_version_guard.py`` resolves the active version
fail-closed, validates ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` (and the overlay
when expected) only on the *served* version (never the settings plane), never
emits binding values, and that the deploy gate wires both guards GET-only.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b54_engine_served_version_guard.py"
WORKFLOW = ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml"

SENTINEL = "sentinel-secret-value-must-never-appear"
V1 = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b54_engine_served_version_guard", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(name: str, binding_type: str, **value_fields: object) -> dict[str, object]:
    row: dict[str, object] = {"name": name, "type": binding_type}
    row.update(value_fields)
    return row


def _version_settings(bindings: list[dict[str, object]], tag: str | None = "ver-active") -> dict[str, object]:
    result: dict[str, object] = {"settings": {"bindings": bindings}}
    if tag is not None:
        result["tag"] = tag
    return {"success": True, "result": result}


def _invoke(helper, argv_for: object, payload: object) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "payload.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        args = argv_for(str(path))  # type: ignore[operator]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = helper.main(args)
    return code, stdout.getvalue() + stderr.getvalue()


def _resolve(helper, payload: object) -> tuple[int, str]:
    return _invoke(helper, lambda p: ["resolve-active", "--deployments", p], payload)


def _verify(helper, payload: object, active: str = "ver-active", expect_overlay: bool = False) -> tuple[int, str]:
    args: list[str]
    def build(p: str) -> list[str]:
        args = ["verify", "--version-settings", p, "--active-version", active]
        if expect_overlay:
            args.append("--expect-overlay")
        return args
    return _invoke(helper, build, payload)


# --- resolve-active -----------------------------------------------------------

def test_resolve_active_canonical_deployments_shape() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {"deployments": [{"versions": [{"version_id": "ver-A", "percentage": 100}]}]}}
    code, out = _resolve(helper, payload)
    assert code == 0
    assert "ENGINE_ACTIVE_VERSION_IDENTIFIED=PASS" in out
    assert "ENGINE_ACTIVE_VERSION_ID=ver-A" in out
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in out


def test_resolve_active_raw_wrangler_list_uses_latest() -> None:
    helper = _load_helper()
    payload = [
        {"versions": [{"version_id": "ver-old", "percentage": 0}]},
        {"versions": [{"version_id": "ver-new", "percentage": 100}]},
    ]
    code, out = _resolve(helper, payload)
    assert code == 0
    assert "ENGINE_ACTIVE_VERSION_ID=ver-new" in out


def test_resolve_active_accepts_result_versions_with_id_key() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {"versions": [{"id": "ver-B", "percentage": 100}]}}
    code, out = _resolve(helper, payload)
    assert code == 0
    assert "ENGINE_ACTIVE_VERSION_ID=ver-B" in out


def test_resolve_active_ambiguous_versions_fail_closed() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {"deployments": [{"versions": [
        {"version_id": "ver-A", "percentage": 100},
        {"version_id": "ver-B", "percentage": 100},
    ]}]}}
    code, out = _resolve(helper, payload)
    assert code == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out
    assert "ambiguous" in out


def test_resolve_active_no_full_rollout_fails_closed() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {"deployments": [{"versions": [{"version_id": "ver-A", "percentage": 90}]}]}}
    code, out = _resolve(helper, payload)
    assert code == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out


def test_resolve_active_empty_deployments_fails_closed() -> None:
    helper = _load_helper()
    for payload in ({"success": True, "result": {"deployments": []}}, {"success": False, "result": None}):
        code, out = _resolve(helper, payload)
        assert code == 1
        assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out


def test_resolve_active_unsafe_version_id_fails_closed() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {"deployments": [{"versions": [{"version_id": "ver A; rm -rf /", "percentage": 100}]}]}}
    code, out = _resolve(helper, payload)
    assert code == 1
    assert "unsafe" in out


# --- verify: pass paths -------------------------------------------------------

def test_verify_passes_v1_on_served_version_without_overlay() -> None:
    helper = _load_helper()
    payload = _version_settings([_binding(V1, "secret_text", text=SENTINEL)])
    code, out = _verify(helper, payload)
    assert code == 0
    assert "B54_ENGINE_SERVED_VERSION_GUARD=PASS" in out
    assert "ENGINE_V1_SERVED_BINDING=PRESENT:secret_text" in out
    assert "ENGINE_OVERLAY_SERVED_BINDING=NOT_EXPECTED" in out
    assert "B54_ENGINE_OVERLAY_EXPECTED=NO" in out
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in out
    assert "PRODUCTION_MUTATION=0" in out
    assert SENTINEL not in out


def test_verify_passes_overlay_when_expected_and_present() -> None:
    helper = _load_helper()
    payload = _version_settings([
        _binding(V1, "secret_text", text=SENTINEL),
        _binding(OVERLAY, "secret_text", text=SENTINEL),
    ])
    code, out = _verify(helper, payload, expect_overlay=True)
    assert code == 0
    assert "ENGINE_OVERLAY_SERVED_BINDING=PRESENT:secret_text" in out
    assert "B54_ENGINE_OVERLAY_EXPECTED=YES" in out
    assert "SERVED_VERSION_SECRET_SET_VALIDATION=YES" in out
    assert SENTINEL not in out


def test_verify_accepts_flat_bindings_and_version_id_identity() -> None:
    helper = _load_helper()
    payload = {"success": True, "result": {
        "version_id": "ver-active",
        "bindings": [_binding(V1, "secret_text", text=SENTINEL)],
    }}
    code, out = _verify(helper, payload)
    assert code == 0
    assert "ENGINE_V1_SERVED_BINDING=PRESENT:secret_text" in out


# --- verify: fail-closed paths ------------------------------------------------

def test_verify_missing_v1_fails_closed() -> None:
    helper = _load_helper()
    payload = _version_settings([_binding("UNRELATED_KV", "kv_namespace", id=SENTINEL)])
    code, out = _verify(helper, payload)
    assert code == 1
    assert "registry binding" in out


def test_verify_missing_expected_overlay_fails_closed() -> None:
    helper = _load_helper()
    payload = _version_settings([_binding(V1, "secret_text", text=SENTINEL)])
    code, out = _verify(helper, payload, expect_overlay=True)
    assert code == 1
    assert "overlay binding is missing" in out


def test_verify_v1_type_drift_fails_closed() -> None:
    helper = _load_helper()
    payload = _version_settings([_binding(V1, "plain_text", text=SENTINEL)])
    code, out = _verify(helper, payload)
    assert code == 1
    assert "registry binding" in out


def test_verify_overlay_type_drift_fails_closed_even_when_not_expected() -> None:
    helper = _load_helper()
    payload = _version_settings([
        _binding(V1, "secret_text", text=SENTINEL),
        _binding(OVERLAY, "plain_text", text=SENTINEL),
    ])
    code, out = _verify(helper, payload, expect_overlay=False)
    assert code == 1
    assert "overlay binding" in out


def test_verify_duplicate_binding_names_fail_closed() -> None:
    helper = _load_helper()
    payload = _version_settings([
        _binding(V1, "secret_text", text=SENTINEL),
        _binding(V1, "secret_text", text=SENTINEL),
    ])
    code, out = _verify(helper, payload)
    assert code == 1
    assert "duplicate" in out


def test_verify_settings_plane_payload_without_version_tag_is_rejected() -> None:
    # The #2412 gap: the mutable settings plane must never pass as served-version
    # validation. A payload without a provable version identity fails closed.
    helper = _load_helper()
    payload = {"success": True, "result": {"bindings": [_binding(V1, "secret_text", text=SENTINEL)]}}
    code, out = _verify(helper, payload)
    assert code == 1
    assert "identity unproven" in out


def test_verify_version_tag_mismatch_fails_closed() -> None:
    helper = _load_helper()
    payload = _version_settings([_binding(V1, "secret_text", text=SENTINEL)], tag="ver-other")
    code, out = _verify(helper, payload)
    assert code == 1
    assert "does not match active version" in out


def test_verify_never_emits_binding_values() -> None:
    helper = _load_helper()
    payloads = [
        _version_settings([_binding(V1, "secret_text", text=SENTINEL), _binding(OVERLAY, "secret_text", text=SENTINEL)]),
        _version_settings([_binding(V1, "plain_text", text=SENTINEL)]),
        _version_settings([], tag=None),
        _version_settings([_binding(V1, "secret_text", text=SENTINEL), _binding(V1, "secret_text", text=SENTINEL)]),
        _version_settings([_binding(V1, "secret_text", text=SENTINEL)], tag=SENTINEL),
    ]
    for payload in payloads:
        for argv in (
            lambda p: ["verify", "--version-settings", p, "--active-version", "ver-active"],
            lambda p: ["verify", "--version-settings", p, "--active-version", "ver-active", "--expect-overlay"],
            lambda p: ["resolve-active", "--deployments", p],
        ):
            code, out = _invoke(helper, argv, payload)
            assert SENTINEL not in out, f"binding value leaked (exit={code})"


# --- deploy gate wiring (static, no network) ----------------------------------

def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _deploy_job_block() -> str:
    text = _workflow_text()
    return text.split("deploy-production-engine:", 1)[1].split("smoke-idempotency:", 1)[0]


def test_deploy_job_yaml_exposes_both_guard_steps() -> None:
    data = yaml.safe_load(_workflow_text())
    steps = [str(step.get("name", "")) for step in data["jobs"]["deploy-production-engine"]["steps"]]
    assert "Pre-deploy served-version secret guard" in steps
    assert "Post-deploy served-version secret guard" in steps
    assert steps.index("Pre-deploy served-version secret guard") < steps.index("Deploy engine to production")
    assert steps.index("Post-deploy served-version secret guard") > steps.index("Post-deploy smoke")


def test_guards_run_the_shared_script_in_both_phases() -> None:
    block = _deploy_job_block()
    assert block.count("b54_engine_served_version_guard.py resolve-active") == 2
    assert block.count("b54_engine_served_version_guard.py verify") == 2
    assert "PREMUTATION_SERVED_VERSION_GUARD=PASS" in block
    assert "POST_DEPLOY_SERVED_VERSION_GUARD=PASS" in block


def test_guards_are_get_only_and_never_touch_secrets_or_values() -> None:
    block = _deploy_job_block()
    for verb in ("-X POST", "-X PUT", "-X PATCH", "-X DELETE", "wrangler secret"):
        assert verb not in block
    # The guard consumes whole API GET bodies into RUNNER_TEMP files only.
    assert "/versions/" in block and "/deployments" in block


def test_post_deploy_guard_requires_overlay_when_predeploy_had_it() -> None:
    block = _deploy_job_block()
    assert 'B54_ENGINE_OVERLAY_EXPECTED' in block
    assert "--expect-overlay" in block
    assert "B54_ENGINE_OVERLAY_EXPECTED=${overlay_expected}" in block


def test_rollback_job_is_untouched_by_the_guard() -> None:
    text = _workflow_text()
    rollback_block = text.split("rollback-production-engine:", 1)[1]
    assert "b54_engine_served_version_guard.py" not in rollback_block
