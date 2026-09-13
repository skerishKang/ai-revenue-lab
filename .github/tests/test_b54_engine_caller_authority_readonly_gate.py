from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-authority-readonly-gate.yml"
HELPER = ROOT / ".github/scripts/b54_engine_caller_authority_readonly.py"

SENTINEL = "sentinel-raw-value-must-never-appear"

TARGET_NAMES = (
    "PADIEM_ENGINE_CALLER_REGISTRY_V1",
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("b54_engine_caller_authority_readonly", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(name: str, binding_type: str, **value_fields: object) -> dict[str, object]:
    row: dict[str, object] = {"name": name, "type": binding_type}
    row.update(value_fields)
    return row


def _settings(bindings: list[dict[str, object]]) -> dict[str, object]:
    return {"success": True, "result": {"bindings": bindings}}


def _run_main(helper, payload: object) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = helper.main([str(path)])
    return code, stdout.getvalue() + stderr.getvalue()


def test_target_names_exact_four() -> None:
    helper = _load_helper()
    assert helper.TARGET_NAMES == TARGET_NAMES
    assert len(set(helper.TARGET_NAMES)) == 4
    assert helper.ENGINE_WORKER == "padiem-ai-engine"


def test_classifier_reports_present_type_or_absent() -> None:
    helper = _load_helper()
    states = helper.classify_authority(
        _settings(
            [
                _binding("PADIEM_ENGINE_CALLER_REGISTRY_V1", "secret_text", text=SENTINEL),
                _binding("PADIEM_ENGINE_CALLER_ID", "plain_text", text=SENTINEL),
                _binding("PADIEM_CHAT_DB", "d1", id=SENTINEL),
            ]
        )
    )
    assert states["PADIEM_ENGINE_CALLER_REGISTRY_V1"] == "PRESENT:secret_text"
    assert states["PADIEM_ENGINE_CALLER_ID"] == "PRESENT:plain_text"
    assert states["PADIEM_ENGINE_CALLER_SECRET"] == "ABSENT"
    assert states["PADIEM_ENGINE_ALLOWED_APPS"] == "ABSENT"


def test_duplicate_target_fail_closed() -> None:
    helper = _load_helper()
    payload = _settings(
        [
            _binding("PADIEM_ENGINE_CALLER_ID", "plain_text"),
            _binding("PADIEM_ENGINE_CALLER_ID", "secret_text"),
        ]
    )
    try:
        helper.classify_authority(payload)
    except helper.CallerAuthorityEvidenceError:
        return
    raise AssertionError("duplicate target binding must fail closed")


def test_malformed_settings_fail_closed() -> None:
    helper = _load_helper()
    malformed = (
        {},
        {"success": False, "errors": [{"message": SENTINEL}]},
        {"success": True},
        {"success": True, "result": {}},
        {"success": True, "result": "not-an-object"},
        {"success": True, "result": {"bindings": {}}},
        {"success": True, "result": {"bindings": ["not-a-binding-object"]}},
        {"success": True, "result": {"bindings": [{"name": "PADIEM_ENGINE_CALLER_SECRET"}]}},
    )
    for payload in malformed:
        try:
            helper.classify_authority(payload)
        except helper.CallerAuthorityEvidenceError:
            continue
        raise AssertionError("malformed settings payload must fail closed")


def test_cli_success_output_is_bounded_name_type_only() -> None:
    helper = _load_helper()
    code, output = _run_main(
        helper,
        _settings(
            [
                _binding("PADIEM_ENGINE_CALLER_REGISTRY_V1", "secret_text", text=SENTINEL),
                _binding("PADIEM_ENGINE_CALLER_ID", "plain_text", text=SENTINEL),
                _binding("PADIEM_ENGINE_CALLER_SECRET", "secret_text", text=SENTINEL),
                _binding("PADIEM_ENGINE_ALLOWED_APPS", "plain_text", text=SENTINEL),
            ]
        ),
    )
    assert code == 0
    assert SENTINEL not in output
    lines = output.strip().splitlines()
    assert len(lines) == 8
    keys = tuple(line.split("=", 1)[0] for line in lines)
    assert keys == TARGET_NAMES + (
        "ENGINE_CALLER_AUTHORITY_TARGET_COUNT",
        "RAW_BINDING_VALUE_OUTPUT",
        "SECRET_VALUE_OUTPUT",
        "PRODUCTION_MUTATION",
    )
    assert "ENGINE_CALLER_AUTHORITY_TARGET_COUNT=4" in output
    assert "RAW_BINDING_VALUE_OUTPUT=0" in output
    assert "SECRET_VALUE_OUTPUT=0" in output
    assert "PRODUCTION_MUTATION=0" in output


def test_cli_failure_output_never_leaks_payload() -> None:
    helper = _load_helper()
    code, output = _run_main(
        helper,
        {"success": False, "errors": [{"message": SENTINEL}], "result": None},
    )
    assert code == 1
    assert SENTINEL not in output
    assert "B54_ENGINE_CALLER_AUTHORITY_READONLY=FAIL" in output


def test_workflow_is_get_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "curl -sS" in workflow
    assert "/workers/scripts/${ENGINE_WORKER}/settings" in workflow
    assert "padiem-ai-engine" in workflow
    assert "GET_ONLY=PASS" in workflow
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert re.search(rf"\b{verb}\b", workflow) is None, f"mutation verb forbidden: {verb}"
    assert "-X " not in workflow
    assert "--request " not in workflow


def test_workflow_has_no_secret_mutation_endpoint_or_wrangler() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # The content-blind diagnostic job may read the two registry payloads via
    # GET only (the mutation-verb guard above still forbids POST/PUT/PATCH/
    # DELETE and -X/--request anywhere in this workflow). All other jobs stay
    # NAME/TYPE-only.
    assert workflow.count("/secrets") == 1
    parts = workflow.split("content-blind-diagnostic:")
    assert len(parts) == 2
    assert "/secrets" in parts[1]
    assert "/secrets" not in parts[0]
    assert "wrangler" not in workflow
    assert "environment:" not in workflow
    assert "confirmation" not in workflow
    assert "apply" not in workflow


def test_workflow_uploads_no_raw_settings_artifact() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "upload-artifact" not in workflow
    assert "RAW_SETTINGS_ARTIFACT_UPLOADED=0" in workflow


def test_workflow_exact_main_guard() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "EXACT_MAIN_GUARD=PASS" in workflow
    assert "READONLY_EXACT_MAIN_SHA=PASS" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'cloudflare_readonly'" in workflow


def test_workflow_mode_options_are_read_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "repository_preflight" in workflow
    assert "cloudflare_readonly" in workflow
    assert "RAW_BINDING_VALUE_OUTPUT=0" in HELPER.read_text(encoding="utf-8")
    assert "SECRET_VALUE_OUTPUT=0" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "CLOUDFLARE_MUTATION=0" in workflow


if __name__ == "__main__":
    test_target_names_exact_four()
    test_classifier_reports_present_type_or_absent()
    test_duplicate_target_fail_closed()
    test_malformed_settings_fail_closed()
    test_cli_success_output_is_bounded_name_type_only()
    test_cli_failure_output_never_leaks_payload()
    test_workflow_is_get_only()
    test_workflow_has_no_secret_mutation_endpoint_or_wrangler()
    test_workflow_uploads_no_raw_settings_artifact()
    test_workflow_exact_main_guard()
    test_workflow_mode_options_are_read_only()
    print("B54_ENGINE_CALLER_AUTHORITY_READONLY_GATE_TESTS=PASS")
