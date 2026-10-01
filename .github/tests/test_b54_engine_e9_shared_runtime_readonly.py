"""Network-free contract tests for shared E9 runtime binding attestation (#3314)."""

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
WORKFLOW = ROOT / ".github/workflows/b54-engine-e9-shared-runtime-readonly.yml"

V1 = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
CONT = "ENGINE_CONTINUATION"
IMAGE = "ENGINE_IMAGE_STORE"
B14 = "B14_SERVICE"
CPID = "CONTROL_PLANE_IDENTITY"
DB = "6b77ad02-bc27-488f-bb97-6325f6750cba"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b54_engine_served_version_guard", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(bindings):
    return {
        "success": True,
        "result": {
            "id": "ver-active",
            "resources": {"bindings": bindings},
        },
    }


def _bindings():
    return [
        {"name": V1, "type": "secret_text", "text": "never-print"},
        {"name": CONT, "type": "d1", "id": DB},
        {"name": IMAGE, "type": "d1", "id": DB},
        {
            "name": B14,
            "type": "service",
            "service": "ai-revenue-korean-ai-platform",
        },
        {
            "name": CPID,
            "type": "service",
            "service": "padiem-control-plane-identity",
        },
    ]


def _invoke(*flags: str, bindings=None):
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "payload.json"
        path.write_text(json.dumps(_payload(bindings or _bindings())), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = helper.main(
                [
                    "verify",
                    "--version-settings",
                    str(path),
                    "--active-version",
                    "ver-active",
                    *flags,
                ]
            )
    return code, out.getvalue() + err.getvalue()


def test_approval_runtime_bindings_are_exact_and_bounded() -> None:
    code, out = _invoke("--require-approval-runtime-bindings")
    assert code == 0
    assert "ENGINE_CONTINUATION_SERVED_BINDING=PRESENT:d1" in out
    assert "B14_SERVICE_SERVED_BINDING=PRESENT:service" in out
    assert "CONTROL_PLANE_IDENTITY_SERVED_BINDING=PRESENT:service" in out
    assert "APPROVAL_RUNTIME_BINDINGS_VALIDATED=YES" in out
    assert DB not in out
    assert "never-print" not in out


def test_a6_activation_runtime_bindings_are_exact_and_bounded() -> None:
    code, out = _invoke("--require-a6-activation-runtime-bindings")
    assert code == 0
    assert "ENGINE_IMAGE_STORE_SERVED_BINDING=PRESENT:d1" in out
    assert "B14_SERVICE_SERVED_BINDING=PRESENT:service" in out
    assert "CONTROL_PLANE_IDENTITY_SERVED_BINDING=PRESENT:service" in out
    assert "A6_ACTIVATION_RUNTIME_BINDINGS_VALIDATED=YES" in out
    assert DB not in out


def test_shared_service_target_drift_fails_closed() -> None:
    rows = _bindings()
    for row in rows:
        if row["name"] == CPID:
            row["service"] = "wrong-service"
    code, out = _invoke("--require-approval-runtime-bindings", bindings=rows)
    assert code == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in out
    assert "wrong-service" not in out


def test_workflow_is_get_only_and_reconciles_relevant_main_drift() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"pull_request", "push"}
    assert triggers["push"]["branches"] == ["main"]
    live = data["jobs"]["served-shared-readonly"]
    assert live["environment"] == "production"
    assert "github.event_name == 'push'" in live["if"]

    for marker in (
        "--require-approval-runtime-bindings",
        "--require-a6-activation-runtime-bindings",
        "APPROVAL_RUNTIME_BINDINGS_VALIDATED=YES",
        "A6_ACTIVATION_RUNTIME_BINDINGS_VALIDATED=YES",
        "E9_SHARED_RELEVANT_SOURCE_DRIFT=0",
        "PROVIDER_CALLS=0",
        "REAL_USER_DATA=0",
        "PRODUCTION_MUTATION=0",
    ):
        assert marker in text

    live_runs = "\n".join(step.get("run", "") for step in live["steps"])
    for forbidden in (
        "wrangler deploy",
        "pywrangler deploy",
        "secret put",
        "d1 execute",
        "curl -X POST",
        "curl -X PUT",
        "curl -X PATCH",
        "curl -X DELETE",
    ):
        assert forbidden not in live_runs


def test_canonical_composition_still_reuses_existing_authorities() -> None:
    source = (ROOT / "apps/padiem-ai-engine/worker_identity.py").read_text(encoding="utf-8")
    for marker in (
        "continuation_store=continuation_store",
        "approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier()",
        "image_byte_store=image_byte_store",
        "scope_authority=scope_authority",
    ):
        assert marker in source
