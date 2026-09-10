from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
HELPER = ROOT / ".github/scripts/b62_claw_live_config_activation.py"
WORKER_CONFIG = ROOT / "apps/padiem-chat/app/worker_config.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_claw_live_config_activation", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = "padiem-engine"
BUCKET = "padiem-workspace-private"


def _binding(name: str, kind: str, **extra):
    return {"name": name, "type": kind, **extra}


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _baseline_bindings():
    """A live Worker that still needs the full activation delta."""
    return [
        _binding("ASSETS", "assets"),
        _binding("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        _binding("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="production"),
        _binding("PADIEM_CHAT_LIVE_ENABLED", "plain_text", text="true"),
        _binding("LEGACY_SECRET", "secret_text"),
    ]


def _activated_bindings():
    helper = _load_helper()
    bindings = _baseline_bindings()
    bindings.extend(
        _binding(name, "plain_text", text=value)
        for name, value in sorted(helper.QUOTA_VALUES.items())
    )
    bindings.append(_binding(helper.R2_BINDING_NAME, "r2_bucket", bucket_name=BUCKET))
    bindings.append(_binding(helper.P01_SERVICE_NAME, "service", service=ENGINE))
    bindings.append(_binding(helper.P01_CALLER_NAME, "plain_text", text=helper.P01_CALLER_VALUE))
    bindings.append(_binding(helper.P01_CREDENTIAL_NAME, "secret_text"))
    return bindings


def _classify(bindings):
    helper = _load_helper()
    states = helper.classify_live_config(
        _settings(bindings), engine_service_name=ENGINE, r2_bucket_name=BUCKET
    )
    return helper, states, helper.disposition(states)


def test_classify_full_activation_required_and_exact() -> None:
    helper, states, overall = _classify(_baseline_bindings())
    assert overall == "ACTIVATION_REQUIRED"
    assert all(states[name] == "missing" for name in helper.QUOTA_VALUES)
    assert states[helper.R2_BINDING_NAME] == "missing"
    assert states[helper.P01_SERVICE_NAME] == "missing"
    assert states[helper.P01_CALLER_NAME] == "missing"
    assert states[helper.P01_CREDENTIAL_NAME] == "missing_secret"

    _, _, overall = _classify(_activated_bindings())
    assert overall == "ALREADY_EXACT"


def test_classify_quota_drift_and_wrong_type() -> None:
    helper, states, overall = _classify(
        _baseline_bindings()
        + [_binding("PADIEM_CHAT_USER_BURST_LIMIT", "plain_text", text="8")]
    )
    assert states["PADIEM_CHAT_USER_BURST_LIMIT"] == "drift"
    assert overall == "ACTIVATION_REQUIRED"

    _, states, overall = _classify(
        _baseline_bindings() + [_binding("PADIEM_CHAT_USER_BURST_LIMIT", "secret_text")]
    )
    assert states["PADIEM_CHAT_USER_BURST_LIMIT"] == "wrong_type"
    assert overall == "REFUSE_WRONG_TYPE"


def test_classify_refuses_structural_target_drift() -> None:
    helper = _load_helper()
    _, _, overall = _classify(
        _baseline_bindings()
        + [_binding(helper.R2_BINDING_NAME, "r2_bucket", bucket_name="other-bucket")]
    )
    assert overall == "REFUSE_TARGET_DRIFT"

    _, _, overall = _classify(
        _baseline_bindings()
        + [_binding(helper.P01_SERVICE_NAME, "service", service="wrong-engine")]
    )
    assert overall == "REFUSE_TARGET_DRIFT"

    _, _, overall = _classify(
        _baseline_bindings() + [_binding(helper.R2_BINDING_NAME, "d1", id="x")]
    )
    assert overall == "REFUSE_WRONG_TYPE"

    _, states, overall = _classify(
        _baseline_bindings()
        + [_binding(helper.P01_CALLER_NAME, "plain_text", text="someone-else")]
    )
    assert states[helper.P01_CALLER_NAME] == "drift"
    assert overall == "ACTIVATION_REQUIRED"


def test_classify_fails_closed_on_unsupported_and_duplicate_bindings() -> None:
    helper = _load_helper()
    for bad in (
        _baseline_bindings() + [_binding("MYSTERY", "kv_namespace", id="x")],
        _baseline_bindings() + [_binding("PADIEM_CHAT_DB", "d1", id="22222222-2222-2222-2222-222222222222")],
    ):
        try:
            helper.classify_live_config(
                _settings(bad), engine_service_name=ENGINE, r2_bucket_name=BUCKET
            )
        except helper._deploy_config.ProductionConfigError:  # type: ignore[attr-defined]
            continue
        raise AssertionError("expected fail-closed parse_live_bindings rejection")


def test_plan_preserves_unrelated_bindings_and_secrets() -> None:
    helper = _load_helper()
    plan = helper.build_activation_patch(
        _settings(_baseline_bindings()),
        engine_service_name=ENGINE,
        r2_bucket_name=BUCKET,
        target_sha="0123456789abcdef" * 4,
    )
    assert plan["credential_create_required"] is True
    assert plan["no_op"] is False
    assert "P01_CREDENTIAL_CREATE" in plan["changes"]
    inherited = {b["name"] for b in plan["payload"]["bindings"] if b["type"] == "inherit"}
    assert {"ASSETS", "PADIEM_CHAT_DB", "PADIEM_CHAT_RUNTIME_MODE", "LEGACY_SECRET"} <= inherited
    text = json.dumps(plan["payload"])
    assert "LEGACY_SECRET" in text and "secret_text" not in text
    assert helper.P01_CREDENTIAL_NAME not in text
    assert len(plan["payload"]["bindings"]) == len(_baseline_bindings()) + 8


def test_plan_quota_overwrites_and_no_op_when_exact() -> None:
    helper = _load_helper()
    drifted = [
        b for b in _activated_bindings() if b["name"] != "PADIEM_CHAT_GLOBAL_DAILY_LIMIT"
    ] + [_binding("PADIEM_CHAT_GLOBAL_DAILY_LIMIT", "plain_text", text="1000")]
    plan = helper.build_activation_patch(
        _settings(drifted),
        engine_service_name=ENGINE,
        r2_bucket_name=BUCKET,
        target_sha="f" * 40,
    )
    assert plan["changes"] == ["QUOTA_SET"]
    assert plan["credential_create_required"] is False
    exact = helper.build_activation_patch(
        _settings(_activated_bindings()),
        engine_service_name=ENGINE,
        r2_bucket_name=BUCKET,
        target_sha="f" * 40,
    )
    assert exact["no_op"] is True and exact["changes"] == []


def test_plan_refuses_on_refuse_disposition() -> None:
    helper = _load_helper()
    try:
        helper.build_activation_patch(
            _settings(
                _baseline_bindings()
                + [_binding(helper.P01_SERVICE_NAME, "plain_text", text="nope")]
            ),
            engine_service_name=ENGINE,
            r2_bucket_name=BUCKET,
            target_sha="f" * 40,
        )
    except helper.ActivationPlanError as exc:
        assert "REFUSE_WRONG_TYPE" in str(exc)
    else:
        raise AssertionError("expected ActivationPlanError")


def test_helper_names_match_worker_config_contract() -> None:
    source = WORKER_CONFIG.read_text(encoding="utf-8")
    helper = _load_helper()
    for name in helper.TARGET_NAMES:
        assert f'"{name}"' in source, name
    for name, value in helper.QUOTA_VALUES.items():
        assert f'"{name}"' in source
    assert f'{helper.P01_CREDENTIAL_NAME}_ENV' in source


def test_workflow_is_production_gated_and_secret_safe() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" in workflow
    assert "CONFIRM_ROLLBACK_B62_CLAW_LIVE_CONFIG" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_config'" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'rollback_config'" in workflow
    assert 'curl -sS -X PATCH' in workflow
    assert '-F "settings=<${RUNNER_TEMP}/b62-config-patch.json;type=application/json"' in workflow
    assert "B62_CLAW_CONFIG_PREMUTATION_VERSION_ID" in workflow
    assert "PREMUTATION_SETTINGS_SNAPSHOT=RECORDED" in workflow
    assert "B62_CLAW_LIVE_CONFIG_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_EXACT" in workflow
    assert "B62_P01_ENGINE_CREDENTIAL" in workflow
    assert "SECRET_VALUES_READ=0" in workflow
    assert "SECRET_VALUE_EMITTED=0" in workflow
    assert "UNRELATED_BINDINGS_PRESERVED=PASS" in workflow

    forbidden = (
        "wrangler deploy",
        "pywrangler deploy",
        "-F \"settings=@",
        "force=true",
        "r2/buckets/${R2_BUCKET_NAME} -X PUT",
        "DELETE",
    )
    for token in forbidden:
        assert token not in workflow, token


def test_readonly_job_contains_r2_bucket_existence_check() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "r2/buckets/${R2_BUCKET_NAME}" in workflow
    assert "R2_BUCKET_EXISTENCE=EXISTS" in workflow
    assert "R2_BUCKET_EXISTENCE=ABSENT" in workflow
    assert "R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT" in workflow
    assert "R2_OBJECT_READ=0" in workflow
    assert "R2_OBJECT_WRITE=0" in workflow


def test_readonly_r2_check_is_get_only_in_readonly_path() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("cloudflare-readonly:", 1)[1].split("activate-config:", 1)[0]
    assert "r2/buckets/${R2_BUCKET_NAME}" in readonly
    assert "curl -sS -X PATCH" not in readonly
    assert "-F \"settings=<${RUNNER_TEMP}/b62-config-patch.json;type=application/json\"" not in readonly
    assert "deploy" not in readonly.lower() or "B62_DEPLOY" not in readonly
    assert "r2/buckets/${R2_BUCKET_NAME} -X PUT" not in readonly
    assert "DELETE" not in readonly
    assert "R2_BUCKET_CREATED=0" not in readonly


def test_activate_config_behavior_unchanged() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    activate = workflow.split("activate-config:", 1)[1]
    assert "r2/buckets/${R2_BUCKET_NAME}" in activate
    assert "R2_BUCKET_REUSE_EXISTING=PASS" in activate
    assert "R2_BUCKET_CREATED=0" in activate
    assert "inputs.mode == 'activate_config'" in workflow
    assert "inputs.mode == 'rollback_config'" in workflow


def test_exact_main_lock_remains_required_in_readonly_path() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("cloudflare-readonly:", 1)[1].split("activate-config:", 1)[0]
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in readonly
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in readonly
    assert 'READONLY_EXACT_MAIN_SHA=PASS' in readonly


def test_readonly_path_never_emits_secret_values() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("cloudflare-readonly:", 1)[1].split("activate-config:", 1)[0]
    assert "SECRET_VALUES_READ=0" in readonly
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in readonly
    assert "PRODUCTION_MUTATION=0" in readonly
    assert "R2_OBJECT_READ=0" in readonly
    assert "R2_OBJECT_WRITE=0" in readonly
    assert "secret_text" not in readonly
    assert "P01_ENGINE_CREDENTIAL" not in readonly


def test_candidate_bucket_name_is_input_bounded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "r2_bucket_name:" in workflow
    assert "R2_BUCKET_NAME: ${{ inputs.r2_bucket_name }}" in workflow
    assert "test -n \"${R2_BUCKET_NAME}\"" in workflow
    assert "padiem-workspace-files" not in workflow.split("env:", 1)[0]


def test_no_public_r2_url_authority_introduced() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "r2:///" not in workflow
    assert "r2.dev" not in workflow
    assert "s3.amazonaws.com" not in workflow
    assert "public_r2_url" not in workflow


if __name__ == "__main__":
    test_classify_full_activation_required_and_exact()
    test_classify_quota_drift_and_wrong_type()
    test_classify_refuses_structural_target_drift()
    test_classify_fails_closed_on_unsupported_and_duplicate_bindings()
    test_plan_preserves_unrelated_bindings_and_secrets()
    test_plan_quota_overwrites_and_no_op_when_exact()
    test_plan_refuses_on_refuse_disposition()
    test_helper_names_match_worker_config_contract()
    test_workflow_is_production_gated_and_secret_safe()
    test_readonly_job_contains_r2_bucket_existence_check()
    test_readonly_r2_check_is_get_only_in_readonly_path()
    test_activate_config_behavior_unchanged()
    test_exact_main_lock_remains_required_in_readonly_path()
    test_readonly_path_never_emits_secret_values()
    test_candidate_bucket_name_is_input_bounded()
    test_no_public_r2_url_authority_introduced()
    print("B62_CLAW_LIVE_CONFIG_ACTIVATION_TESTS=PASS")
