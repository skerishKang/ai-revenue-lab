"""Network-free contract tests for the A7 admission runtime attestation (#3308)."""

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
WORKFLOW = ROOT / ".github/workflows/b54-engine-a7-admission-readonly.yml"

V1 = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
ADMISSION = "CONTROL_PLANE_ENGINE_ADMISSION"
ADMISSION_SERVICE = "padiem-control-plane-engine-admission"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b54_engine_served_version_guard", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version_detail(bindings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "success": True,
        "result": {
            "id": "ver-active",
            "resources": {"bindings": bindings},
        },
    }


def _verify(payload: object) -> tuple[int, str]:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "version.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = helper.main(
                [
                    "verify",
                    "--version-settings",
                    str(path),
                    "--active-version",
                    "ver-active",
                    "--inspect-engine-admission-binding",
                ]
            )
    return code, stdout.getvalue() + stderr.getvalue()


def _base_bindings() -> list[dict[str, object]]:
    return [{"name": V1, "type": "secret_text", "text": "never-print-me"}]


def test_a7_binding_absence_is_reported_without_false_activation_failure() -> None:
    code, out = _verify(_version_detail(_base_bindings()))
    assert code == 0
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=ABSENT" in out
    assert "ENGINE_ADMISSION_BINDING_TARGET_VALIDATED=NOT_APPLICABLE" in out
    assert "never-print-me" not in out


def test_a7_binding_present_requires_exact_service_target() -> None:
    bindings = _base_bindings() + [
        {
            "name": ADMISSION,
            "type": "service",
            "service": ADMISSION_SERVICE,
        }
    ]
    code, out = _verify(_version_detail(bindings))
    assert code == 0
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" in out
    assert "ENGINE_ADMISSION_BINDING_TARGET_VALIDATED=YES" in out


def test_a7_binding_wrong_type_fails_closed() -> None:
    bindings = _base_bindings() + [
        {"name": ADMISSION, "type": "plain_text", "text": "forged"}
    ]
    code, out = _verify(_version_detail(bindings))
    assert code == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out
    assert "forged" not in out


def test_a7_binding_wrong_service_target_fails_closed() -> None:
    bindings = _base_bindings() + [
        {
            "name": ADMISSION,
            "type": "service",
            "service": "wrong-service",
        }
    ]
    code, out = _verify(_version_detail(bindings))
    assert code == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out
    assert "wrong-service" not in out


def test_workflow_is_read_only_and_live_job_runs_only_on_merged_main_push() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"pull_request", "push"}
    assert triggers["push"]["branches"] == ["main"]

    live = data["jobs"]["served-a7-readonly"]
    assert live["needs"] == "source-contract"
    assert live["environment"] == "production"
    assert "github.event_name == 'push'" in live["if"]
    assert "github.ref == 'refs/heads/main'" in live["if"]

    required = (
        "b54_engine_served_version_guard.py resolve-active",
        "--inspect-engine-admission-binding",
        "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=",
        "padiem-control-plane-engine-admission",
        "CP_ENGINE_ADMISSION_WORKER=",
        "ENGINE_ROLLBACK_ANCHOR=",
        "CP_ROLLBACK_ANCHOR=",
        "PROVIDER_CALLS=0",
        "REAL_USER_DATA=0",
        "PRODUCTION_MUTATION=0",
    )
    for marker in required:
        assert marker in text

    live_runs = "\n".join(step.get("run", "") for step in live["steps"])
    forbidden = (
        "wrangler deploy",
        "pywrangler deploy",
        "secret put",
        "d1 execute",
        "d1 migrations",
        "curl -X POST",
        "curl -X PUT",
        "curl -X PATCH",
        "curl -X DELETE",
        "install_entitlement_snapshot",
    )
    for shape in forbidden:
        assert shape not in live_runs


def test_workflow_never_prints_raw_cloudflare_payloads_or_sensitive_identifiers() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "RAW_SETTINGS_OUTPUT=0",
        "RAW_VERSION_DETAIL_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "ACCOUNT_ID_OUTPUT=0",
        "DATABASE_ID_OUTPUT=0",
        "TENANT_USER_IDENTIFIER_OUTPUT=0",
    )
    for marker in required:
        assert marker in text
