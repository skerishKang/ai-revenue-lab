from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
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


def _readonly_job_block() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("cloudflare-readonly:", 1)[1].split("activate-config:", 1)[0]


def test_readonly_job_output_wires_r2_bucket_existence() -> None:
    """JOB_OUTPUT_WIRED=YES: CENTRAL must be able to retrieve the bounded R2 result."""
    readonly = _readonly_job_block()
    outputs_block = readonly.split("steps:", 1)[0]
    assert "outputs:" in outputs_block
    assert "disposition: ${{ steps.classify.outputs.disposition }}" in outputs_block
    assert (
        "r2_bucket_existence: ${{ steps.r2_bucket.outputs.r2_bucket_existence }}"
        in outputs_block
    )
    assert "id: r2_bucket" in readonly


def test_readonly_r2_bucket_existence_uses_stable_output_key() -> None:
    readonly = _readonly_job_block()
    for state in ("EXISTS", "ABSENT", "ERROR_OR_DRIFT"):
        assert f'r2_bucket_existence={state}" >> "${{GITHUB_OUTPUT}}"' in readonly, state


def test_readonly_r2_bucket_existence_emits_bounded_log_evidence() -> None:
    readonly = _readonly_job_block()
    evidence_lines = [
        line.strip() for line in readonly.splitlines() if "R2_BUCKET_EXISTENCE=" in line
    ]
    assert evidence_lines, "expected bounded ordinary R2 bucket existence evidence"
    allowed = {
        "echo 'R2_BUCKET_EXISTENCE=EXISTS'",
        "echo 'R2_BUCKET_EXISTENCE=ABSENT'",
        "echo 'R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT'",
    }
    for line in evidence_lines:
        assert line in allowed, line


def test_readonly_r2_evidence_never_emits_credentials_or_account_id() -> None:
    readonly = _readonly_job_block()
    for line in readonly.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert "CLOUDFLARE_ACCOUNT_ID" not in stripped, stripped
            assert "CLOUDFLARE_API_TOKEN" not in stripped, stripped
            assert "secret_text" not in stripped.lower(), stripped
            assert "secrets." not in stripped.lower(), stripped
            assert "object_key" not in stripped, stripped
            assert "r2:///" not in stripped, stripped


def test_readonly_r2_check_stays_get_only_with_no_mutation_verbs() -> None:
    readonly = _readonly_job_block()
    assert "/r2/buckets/${R2_BUCKET_NAME}" in readonly
    assert readonly.count("/r2/buckets/") == 1
    assert "/objects" not in readonly
    for verb in ("-X PUT", "-X POST", "-X PATCH", "-X DELETE", "--data", "-F ", "wrangler"):
        assert verb not in readonly, verb


def test_readonly_worker_settings_classification_unchanged() -> None:
    readonly = _readonly_job_block()
    assert "id: classify" in readonly
    assert "B62_CLAW_LIVE_CONFIG_DISPOSITION=" in readonly
    assert "ALREADY_EXACT|ACTIVATION_REQUIRED" in readonly
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in readonly
    assert "SECRET_VALUES_READ=0" in readonly
    assert "workers/scripts/${B62_WORKER}/settings" in readonly


def _r2_step_block() -> str:
    return _readonly_job_block().split(
        "- name: Read-only R2 bucket existence check", 1
    )[1]


def _activate_job_block() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("activate-config:", 1)[1].split("rollback-config:", 1)[0]


def _activation_r2_confirm_block() -> str:
    """The activation-time bucket confirmation step body."""
    activate = _activate_job_block()
    return activate.split(
        "- name: Confirm the private R2 bucket already exists", 1
    )[1].split("- name: ", 1)[0]


def _activation_plan_step_block() -> str:
    activate = _activate_job_block()
    return activate.split(
        "- name: Rebuild the activation patch against the pre-mutation snapshot", 1
    )[1].split("- name: Confirm the private R2 bucket already exists", 1)[0]


def _activation_patch_step_block() -> str:
    activate = _activate_job_block()
    return activate.split(
        "- name: Apply the activation patch through the settings API", 1
    )[1].split("- name: ", 1)[0]


def _classify_step_block() -> str:
    return _readonly_job_block().split(
        "- name: Read live Worker settings and classify activation targets", 1
    )[1].split("- name: Read-only R2 bucket existence check", 1)[0]


def _readonly_job_env_block() -> str:
    """The job-level env block, i.e. everything before the first step."""
    return _readonly_job_block().split("steps:", 1)[0]


DEDICATED_R2_SECRET = "B62_R2_READONLY_API_TOKEN"
DEDICATED_R2_ENV = "R2_READONLY_API_TOKEN"
DEDICATED_R2_ENV_LINE = (
    "R2_READONLY_API_TOKEN: ${{ secrets.B62_R2_READONLY_API_TOKEN }}"
)
SHARED_TOKEN_ENV_LINE = "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}"


def _expected_block(text: str, base_indent: int) -> str:
    """Dedent a literal, then re-indent it to the workflow's real base column."""
    prefix = " " * base_indent
    return "\n".join(
        prefix + line if line else line
        for line in textwrap.dedent(text).splitlines()
    )


def test_readonly_r2_bucket_http_status_is_bounded() -> None:
    readonly = _readonly_job_block()
    emitted = {
        line.strip()
        for line in readonly.splitlines()
        if line.strip().startswith("echo 'R2_BUCKET_HTTP_STATUS=")
    }
    assert emitted == {
        "echo 'R2_BUCKET_HTTP_STATUS=200'",
        "echo 'R2_BUCKET_HTTP_STATUS=404'",
        "echo 'R2_BUCKET_HTTP_STATUS=401'",
        "echo 'R2_BUCKET_HTTP_STATUS=403'",
        "echo 'R2_BUCKET_HTTP_STATUS=OTHER'",
    }
    for unbounded in (
        "R2_BUCKET_HTTP_STATUS=500",
        "R2_BUCKET_HTTP_STATUS=502",
        "R2_BUCKET_HTTP_STATUS=503",
        "R2_BUCKET_HTTP_STATUS=${http_status}",
        'R2_BUCKET_HTTP_STATUS="${http_status}"',
    ):
        assert unbounded not in readonly, unbounded


def test_readonly_r2_bucket_response_shape_is_bounded() -> None:
    readonly = _readonly_job_block()
    emitted = {
        line.strip()
        for line in readonly.splitlines()
        if line.strip().startswith("echo 'R2_BUCKET_RESPONSE_SHAPE=")
    }
    assert emitted == {
        "echo 'R2_BUCKET_RESPONSE_SHAPE=EXACT'",
        "echo 'R2_BUCKET_RESPONSE_SHAPE=DRIFT'",
        "echo 'R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE'",
    }


def test_readonly_r2_bucket_http_status_uses_stable_output_keys() -> None:
    readonly = _readonly_job_block()
    for key, value in (
        ("r2_bucket_http_status", "200"),
        ("r2_bucket_http_status", "404"),
        ("r2_bucket_http_status", "401"),
        ("r2_bucket_http_status", "403"),
        ("r2_bucket_http_status", "OTHER"),
        ("r2_bucket_response_shape", "EXACT"),
        ("r2_bucket_response_shape", "DRIFT"),
        ("r2_bucket_response_shape", "NOT_APPLICABLE"),
    ):
        assert f'{key}={value}" >> "${{GITHUB_OUTPUT}}"' in readonly, (key, value)


def test_readonly_job_output_wires_r2_status_observability() -> None:
    readonly = _readonly_job_block()
    outputs_block = readonly.split("steps:", 1)[0]
    assert "disposition: ${{ steps.classify.outputs.disposition }}" in outputs_block
    assert (
        "r2_bucket_existence: ${{ steps.r2_bucket.outputs.r2_bucket_existence }}"
        in outputs_block
    )
    assert (
        "r2_bucket_http_status: ${{ steps.r2_bucket.outputs.r2_bucket_http_status }}"
        in outputs_block
    )
    assert (
        "r2_bucket_response_shape: ${{ steps.r2_bucket.outputs.r2_bucket_response_shape }}"
        in outputs_block
    )


def test_readonly_r2_status_mapping_is_exact_per_case_arm() -> None:
    """Every case arm must bind status -> existence -> response shape atomically."""
    readonly = _readonly_job_block()

    arm_200_exact = _expected_block(
        """\
            200)
              if jq -e --arg name "${R2_BUCKET_NAME}" '.success == true and .result.name == $name' "${bucket}" >/dev/null; then
                echo "r2_bucket_existence=EXISTS" >> "${GITHUB_OUTPUT}"
                echo "r2_bucket_http_status=200" >> "${GITHUB_OUTPUT}"
                echo "r2_bucket_response_shape=EXACT" >> "${GITHUB_OUTPUT}"
                echo 'R2_BUCKET_EXISTENCE=EXISTS'
                echo 'R2_BUCKET_HTTP_STATUS=200'
                echo 'R2_BUCKET_RESPONSE_SHAPE=EXACT'""",
        12,
    )
    arm_200_drift = _expected_block(
        """\
            else
              echo "r2_bucket_existence=ERROR_OR_DRIFT" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_http_status=200" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_response_shape=DRIFT" >> "${GITHUB_OUTPUT}"
              echo 'R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT'
              echo 'R2_BUCKET_HTTP_STATUS=200'
              echo 'R2_BUCKET_RESPONSE_SHAPE=DRIFT'
            fi
            ;;""",
        14,
    )
    arm_404 = _expected_block(
        """\
            404)
              echo "r2_bucket_existence=ABSENT" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_http_status=404" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_response_shape=NOT_APPLICABLE" >> "${GITHUB_OUTPUT}"
              echo 'R2_BUCKET_EXISTENCE=ABSENT'
              echo 'R2_BUCKET_HTTP_STATUS=404'
              echo 'R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE'
              ;;""",
        12,
    )
    arm_401 = _expected_block(
        """\
            401)
              echo "r2_bucket_existence=ERROR_OR_DRIFT" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_http_status=401" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_response_shape=NOT_APPLICABLE" >> "${GITHUB_OUTPUT}"
              echo 'R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT'
              echo 'R2_BUCKET_HTTP_STATUS=401'
              echo 'R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE'
              ;;""",
        12,
    )
    arm_403 = _expected_block(
        """\
            403)
              echo "r2_bucket_existence=ERROR_OR_DRIFT" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_http_status=403" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_response_shape=NOT_APPLICABLE" >> "${GITHUB_OUTPUT}"
              echo 'R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT'
              echo 'R2_BUCKET_HTTP_STATUS=403'
              echo 'R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE'
              ;;""",
        12,
    )
    arm_other = _expected_block(
        """\
            *)
              echo "r2_bucket_existence=ERROR_OR_DRIFT" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_http_status=OTHER" >> "${GITHUB_OUTPUT}"
              echo "r2_bucket_response_shape=NOT_APPLICABLE" >> "${GITHUB_OUTPUT}"
              echo 'R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT'
              echo 'R2_BUCKET_HTTP_STATUS=OTHER'
              echo 'R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE'
              ;;""",
        12,
    )

    for arm in (arm_200_exact, arm_200_drift, arm_404, arm_401, arm_403, arm_other):
        assert arm in readonly, arm

    # 200 must be the only arm that can report a response shape other than NOT_APPLICABLE.
    assert readonly.count('R2_BUCKET_RESPONSE_SHAPE=EXACT') == 1
    assert readonly.count('R2_BUCKET_RESPONSE_SHAPE=DRIFT') == 1
    assert readonly.count('R2_BUCKET_RESPONSE_SHAPE=NOT_APPLICABLE') == 4


def test_readonly_r2_status_evidence_emits_no_raw_response_or_secrets() -> None:
    r2 = _r2_step_block()
    for line in r2.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert "${bucket}" not in stripped, stripped
            assert "CLOUDFLARE_ACCOUNT_ID" not in stripped, stripped
            assert "CLOUDFLARE_API_TOKEN" not in stripped, stripped
            assert "Authorization" not in stripped, stripped
            assert "object_key" not in stripped, stripped
    for token in ("-i ", "--include", "-D ", "cat ", "jq -c .", "jq . "):
        assert token not in r2, token


def test_readonly_r2_single_get_preserved_after_status_observability() -> None:
    r2 = _r2_step_block()
    assert r2.count("curl ") == 1
    assert "/r2/buckets/${R2_BUCKET_NAME}" in r2
    assert "-w '%{http_code}'" in r2
    for verb in ("-X PUT", "-X POST", "-X PATCH", "-X DELETE", "--data", "-F ", "wrangler"):
        assert verb not in r2, verb


def test_readonly_r2_step_uses_only_the_dedicated_secret() -> None:
    """R2 bucket metadata GET must authenticate with the dedicated secret only."""
    r2 = _r2_step_block()
    assert DEDICATED_R2_ENV_LINE in r2
    assert f"secrets.{DEDICATED_R2_SECRET}" in r2
    assert f"Bearer ${{{DEDICATED_R2_ENV}}}" in r2
    assert "CLOUDFLARE_API_TOKEN" not in r2


def test_readonly_r2_dedicated_secret_reference_is_canonical_and_single() -> None:
    r2 = _r2_step_block()
    assert r2.count(f"secrets.{DEDICATED_R2_SECRET}") == 1
    assert f"${{{{ secrets.{DEDICATED_R2_SECRET} }}}}" in r2


def test_readonly_worker_settings_step_keeps_shared_token() -> None:
    """Worker settings classification must keep using the shared deployment token."""
    classify = _classify_step_block()
    assert SHARED_TOKEN_ENV_LINE in classify
    assert "Bearer ${CLOUDFLARE_API_TOKEN}" in classify
    assert "workers/scripts/${B62_WORKER}/settings" in classify
    assert DEDICATED_R2_SECRET not in classify
    assert DEDICATED_R2_ENV not in classify


def test_readonly_job_env_does_not_expose_shared_token_to_r2_step() -> None:
    job_env = _readonly_job_env_block()
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in job_env
    assert "CLOUDFLARE_API_TOKEN" not in job_env
    assert DEDICATED_R2_SECRET not in job_env
    assert DEDICATED_R2_ENV not in job_env


def test_readonly_r2_missing_dedicated_token_fails_closed_before_curl() -> None:
    r2 = _r2_step_block()
    # empty-default expansion only; never a shared-token default
    guard = 'if [ -z "${R2_READONLY_API_TOKEN:-}" ]; then'
    assert guard in r2
    assert "exit 1" in r2
    # the guard must run before any network request
    assert r2.index(guard) < r2.index("curl ")

    guard_block = r2.split(guard, 1)[1].split("\n          fi\n", 1)[0]
    assert "B62_R2_READONLY_CREDENTIAL=MISSING" in guard_block
    assert "R2_BUCKET_PROBE=NOT_ATTEMPTED" in guard_block
    assert "SECRET_VALUE_EMITTED=0" in guard_block
    assert "PRODUCTION_MUTATION=0" in guard_block
    # fail-closed must not fabricate bounded R2 evidence
    assert "R2_BUCKET_EXISTENCE=" not in guard_block
    assert "R2_BUCKET_HTTP_STATUS=" not in guard_block
    assert "R2_BUCKET_RESPONSE_SHAPE=" not in guard_block


def test_readonly_r2_step_has_no_shared_token_fallback() -> None:
    r2 = _r2_step_block()
    assert "CLOUDFLARE_API_TOKEN" not in r2
    for fallback in (
        "${CLOUDFLARE_API_TOKEN:-",
        ":-${CLOUDFLARE_API_TOKEN}",
        ":-$CLOUDFLARE_API_TOKEN",
        "${R2_READONLY_API_TOKEN:-${CLOUDFLARE_API_TOKEN}}",
        "|| ${CLOUDFLARE_API_TOKEN}",
        "|| $CLOUDFLARE_API_TOKEN",
    ):
        assert fallback not in r2, fallback


def test_readonly_r2_dedicated_token_value_is_never_emitted() -> None:
    r2 = _r2_step_block()
    for line in r2.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert DEDICATED_R2_ENV not in stripped, stripped
            assert DEDICATED_R2_SECRET not in stripped, stripped
            assert "Bearer" not in stripped, stripped


def test_readonly_r2_evidence_keys_unchanged_after_credential_split() -> None:
    """The credential split must not alter the bounded evidence contract."""
    readonly = _readonly_job_block()
    assert "R2_BUCKET_EXISTENCE=EXISTS" in readonly
    assert "R2_BUCKET_EXISTENCE=ABSENT" in readonly
    assert "R2_BUCKET_EXISTENCE=ERROR_OR_DRIFT" in readonly
    assert "R2_OBJECT_READ=0" in readonly
    assert "R2_OBJECT_WRITE=0" in readonly
    assert "PRODUCTION_MUTATION=0" in readonly
    outputs_block = readonly.split("steps:", 1)[0]
    assert "r2_bucket_existence: ${{ steps.r2_bucket.outputs.r2_bucket_existence }}" in outputs_block
    assert "r2_bucket_http_status: ${{ steps.r2_bucket.outputs.r2_bucket_http_status }}" in outputs_block
    assert (
        "r2_bucket_response_shape: ${{ steps.r2_bucket.outputs.r2_bucket_response_shape }}"
        in outputs_block
    )


def test_activation_r2_confirm_uses_only_the_dedicated_secret() -> None:
    """Activation-time R2 metadata GET must authenticate with the dedicated secret only."""
    confirm = _activation_r2_confirm_block()
    assert DEDICATED_R2_ENV_LINE in confirm
    assert f"secrets.{DEDICATED_R2_SECRET}" in confirm
    assert f"Bearer ${{{DEDICATED_R2_ENV}}}" in confirm
    assert "CLOUDFLARE_API_TOKEN" not in confirm


def test_activation_r2_confirm_dedicated_reference_is_canonical_and_single() -> None:
    confirm = _activation_r2_confirm_block()
    assert confirm.count(f"secrets.{DEDICATED_R2_SECRET}") == 1
    assert f"${{{{ secrets.{DEDICATED_R2_SECRET} }}}}" in confirm


def test_activation_r2_confirm_has_no_shared_token_fallback() -> None:
    confirm = _activation_r2_confirm_block()
    assert "CLOUDFLARE_API_TOKEN" not in confirm
    for fallback in (
        "${CLOUDFLARE_API_TOKEN:-",
        ":-${CLOUDFLARE_API_TOKEN}",
        ":-$CLOUDFLARE_API_TOKEN",
        "${R2_READONLY_API_TOKEN:-${CLOUDFLARE_API_TOKEN}}",
        "|| ${CLOUDFLARE_API_TOKEN}",
        "|| $CLOUDFLARE_API_TOKEN",
    ):
        assert fallback not in confirm, fallback


def test_activation_r2_confirm_missing_dedicated_token_fails_closed_before_curl() -> None:
    confirm = _activation_r2_confirm_block()
    guard = 'if [ -z "${R2_READONLY_API_TOKEN:-}" ]; then'
    assert guard in confirm
    assert "exit 1" in confirm
    assert confirm.index(guard) < confirm.index("curl ")

    guard_block = confirm.split(guard, 1)[1].split("\n          fi\n", 1)[0]
    assert "B62_R2_READONLY_CREDENTIAL=MISSING" in guard_block
    assert "R2_BUCKET_PROBE=NOT_ATTEMPTED" in guard_block
    assert "SECRET_VALUE_EMITTED=0" in guard_block
    assert "PRODUCTION_MUTATION=0" in guard_block
    assert "R2_BUCKET_REUSE_EXISTING" not in guard_block


def test_activation_r2_confirm_remains_single_get_only() -> None:
    confirm = _activation_r2_confirm_block()
    assert confirm.count("curl ") == 1
    assert "/r2/buckets/${R2_BUCKET_NAME}" in confirm
    assert "-w '%{http_code}'" in confirm
    assert "test \"${http_status}\" = \"200\"" in confirm
    for verb in ("-X PUT", "-X POST", "-X PATCH", "-X DELETE", "--data", "-F ", "wrangler"):
        assert verb not in confirm, verb


def test_activation_r2_confirm_fails_on_success_false_or_name_mismatch() -> None:
    confirm = _activation_r2_confirm_block()
    assert (
        "jq -e --arg name \"${R2_BUCKET_NAME}\" "
        "'.success == true and .result.name == $name' \"${bucket}\" >/dev/null" in confirm
    )


def test_activation_r2_confirm_never_emits_token_account_or_raw_response() -> None:
    confirm = _activation_r2_confirm_block()
    for line in confirm.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert DEDICATED_R2_ENV not in stripped, stripped
            assert DEDICATED_R2_SECRET not in stripped, stripped
            assert "CLOUDFLARE_ACCOUNT_ID" not in stripped, stripped
            assert "CLOUDFLARE_API_TOKEN" not in stripped, stripped
            assert "Bearer" not in stripped, stripped
            assert "Authorization" not in stripped, stripped
            assert "${bucket}" not in stripped, stripped
    for token in ("-i ", "--include", "-D ", "cat ", "jq -c .", "jq . "):
        assert token not in confirm, token


def test_activation_r2_confirm_precedes_settings_patch_and_secret_put() -> None:
    """Fail-closed bucket confirmation must gate every downstream mutation."""
    activate = _activate_job_block()
    confirm_at = activate.index("- name: Confirm the private R2 bucket already exists")
    patch_at = activate.index("- name: Apply the activation patch through the settings API")
    credential_at = activate.index("- name: Create the P01 Engine credential only when it is absent")
    assert confirm_at < patch_at < credential_at


def test_activation_shared_token_remains_for_worker_config_operations() -> None:
    """Shared token stays available only for Worker settings/secret operations."""
    activate = _activate_job_block()
    assert SHARED_TOKEN_ENV_LINE in activate.split("steps:", 1)[0]
    patch = _activation_patch_step_block()
    assert "Bearer ${CLOUDFLARE_API_TOKEN}" in patch
    assert "workers/scripts/${B62_WORKER}/settings" in patch
    credential_step = activate.split(
        "- name: Create the P01 Engine credential only when it is absent", 1
    )[1].split("- name: ", 1)[0]
    assert "Bearer ${CLOUDFLARE_API_TOKEN}" in credential_step
    assert "workers/scripts/${B62_WORKER}/secrets" in credential_step
    assert DEDICATED_R2_SECRET not in patch
    assert DEDICATED_R2_ENV not in patch


def test_activation_r2_evidence_keys_unchanged_after_dedicated_wiring() -> None:
    """The dedicated wiring must not alter the activation evidence contract."""
    activate = _activate_job_block()
    assert "R2_BUCKET_REUSE_EXISTING=PASS" in activate
    assert "R2_BUCKET_CREATED=0" in activate
    assert "B62_CLAW_LIVE_CONFIG_AUTHORIZATION=PASS" in activate
    assert "B62_CLAW_CONFIG_PATCH=SUCCESS" in activate
    assert "B62_CLAW_LIVE_CONFIG_POST_READBACK=PASS" in activate
    assert "SKIPPED_ALREADY_EXACT" in activate
    assert "SECRET_VALUES_READ=0" in activate
    assert "UNRELATED_BINDINGS_PRESERVED=PASS" in activate


SOURCE_CREDENTIAL_ENV = "B62_P01_ENGINE_CREDENTIAL"
GOOD_CREDENTIAL = "x" * 40


def _run_cli(args: list[str], *, credential: str | None = None):
    env = {key: value for key, value in os.environ.items() if key != SOURCE_CREDENTIAL_ENV}
    if credential is not None:
        env[SOURCE_CREDENTIAL_ENV] = credential
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _write_settings(directory: Path, name: str, bindings) -> Path:
    path = directory / name
    path.write_text(json.dumps(_settings(bindings)), encoding="utf-8")
    return path


def _replacement_job_block() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("replace-p01-credential:", 1)[1].split("\n  rollback-config:", 1)[0]


def _post_mutation_step_block() -> str:
    step = _replacement_job_block().split(
        "- name: Record post-mutation served version evidence", 1
    )[1]
    return step.split("\n      - name:", 1)[0]


def test_source_credential_quality_byte_boundaries() -> None:
    helper = _load_helper()
    assert helper.source_credential_quality("a" * 32) is True
    assert helper.source_credential_quality("a" * 512) is True
    assert helper.source_credential_quality("a" * 31) is False
    assert helper.source_credential_quality("a" * 513) is False
    assert helper.source_credential_quality("") is False
    assert helper.source_credential_quality(None) is False
    assert helper.source_credential_quality(12345) is False


def test_source_credential_quality_counts_utf8_bytes_not_characters() -> None:
    helper = _load_helper()
    assert helper.source_credential_quality("가" * 10) is False
    assert helper.source_credential_quality("가" * 11) is True
    assert helper.source_credential_quality("가" * 171) is False


def test_helper_credential_bounds_match_worker_config() -> None:
    helper = _load_helper()
    source = WORKER_CONFIG.read_text(encoding="utf-8")
    assert f'_P01_CREDENTIAL_MIN_BYTES = {helper.P01_CREDENTIAL_MIN_BYTES}' in source
    assert f'_P01_CREDENTIAL_MAX_BYTES = {helper.P01_CREDENTIAL_MAX_BYTES}' in source


def test_replacement_precheck_requires_existing_secret_text() -> None:
    helper = _load_helper()
    result = helper.replacement_precheck(_settings(_activated_bindings()))
    assert helper.P01_CREDENTIAL_NAME in result["secret_names"]
    assert "LEGACY_SECRET" in result["secret_names"]

    for bindings, needle in (
        (_baseline_bindings() + [_binding(helper.P01_CREDENTIAL_NAME, "plain_text", text="x")],
         "refusing to overwrite"),
    ):
        try:
            helper.replacement_precheck(_settings(bindings))
        except helper.ActivationPlanError as exc:
            assert needle in str(exc)
        else:
            raise AssertionError(f"expected refusal: {needle}")

    try:
        helper.replacement_precheck(_settings(_baseline_bindings()))
    except helper.ActivationPlanError as exc:
        assert "absent" in str(exc) and "activate_config" in str(exc)
    else:
        raise AssertionError("absent credential must refuse replacement")


def test_replacement_precheck_reports_names_only() -> None:
    helper = _load_helper()
    result = helper.replacement_precheck(_settings(_activated_bindings()))
    assert list(result) == ["secret_names"]
    assert all(isinstance(name, str) for name in result["secret_names"])


def test_verify_replacement_readback_accepts_identical_or_extended_bindings() -> None:
    helper = _load_helper()
    activated = _activated_bindings()
    assert helper.verify_replacement_readback(_settings(activated), _settings(activated)) == []
    extended = activated + [_binding("QUOTA_SALT", "plain_text", text="1")]
    assert helper.verify_replacement_readback(_settings(activated), _settings(extended)) == []


def test_verify_replacement_readback_flags_credential_loss_or_retype() -> None:
    helper = _load_helper()
    activated = _activated_bindings()
    dropped = [b for b in activated if b["name"] != helper.P01_CREDENTIAL_NAME]
    failures = helper.verify_replacement_readback(_settings(activated), _settings(dropped))
    assert any(helper.P01_CREDENTIAL_NAME in f for f in failures)
    retyped = [
        _binding(helper.P01_CREDENTIAL_NAME, "plain_text", text="oops")
        if b["name"] == helper.P01_CREDENTIAL_NAME
        else b
        for b in activated
    ]
    failures = helper.verify_replacement_readback(_settings(activated), _settings(retyped))
    assert any(helper.P01_CREDENTIAL_NAME in f for f in failures)


def test_verify_replacement_readback_flags_unrelated_secret_loss() -> None:
    helper = _load_helper()
    activated = _activated_bindings()
    lost = [b for b in activated if b["name"] != "LEGACY_SECRET"]
    failures = helper.verify_replacement_readback(_settings(activated), _settings(lost))
    assert any("LEGACY_SECRET" in f for f in failures)


def test_cli_credential_quality_passes_with_valid_env_without_emitting_value() -> None:
    proc = _run_cli(["credential-quality"], credential=GOOD_CREDENTIAL)
    assert proc.returncode == 0, proc.stderr
    assert "SOURCE_CREDENTIAL_PRESENT=YES" in proc.stdout
    assert "SOURCE_CREDENTIAL_QUALITY=PASS" in proc.stdout
    for key in (
        "SECRET_VALUE_OUTPUT=0",
        "SECRET_LENGTH_OUTPUT=0",
        "SECRET_HASH_OUTPUT=0",
        "PRODUCTION_MUTATION=0",
    ):
        assert key in proc.stdout, key
    assert GOOD_CREDENTIAL not in proc.stdout + proc.stderr


def test_cli_credential_quality_fails_closed_when_env_missing() -> None:
    proc = _run_cli(["credential-quality"])
    assert proc.returncode == 1
    assert "SOURCE_CREDENTIAL_PRESENT=NO" in proc.stdout
    assert "SOURCE_CREDENTIAL_QUALITY=FAIL" in proc.stdout


def test_cli_credential_quality_fails_on_invalid_length_without_leaking() -> None:
    for value in ("a" * 31, "a" * 513, "가" * 171):
        proc = _run_cli(["credential-quality"], credential=value)
        assert proc.returncode == 1, value
        assert "SOURCE_CREDENTIAL_QUALITY=FAIL" in proc.stdout
        assert value not in proc.stdout + proc.stderr


def test_cli_replacement_precheck_requires_settings() -> None:
    proc = _run_cli(["replacement-precheck"])
    assert proc.returncode == 2
    assert "--settings" in proc.stderr


def test_cli_replacement_precheck_passes_with_existing_secret_text() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_settings(Path(tmp), "pre.json", _activated_bindings())
        proc = _run_cli(["replacement-precheck", "--settings", str(path)])
    assert proc.returncode == 0, proc.stderr
    assert "B62_P01_REPLACEMENT_PRECHECK=PASS" in proc.stdout
    assert helper.P01_CREDENTIAL_NAME in proc.stdout
    assert "OLD_SECRET_VALUE_READ=NO" in proc.stdout
    assert "SECRET_VALUES_READ=0" in proc.stdout


def test_cli_replacement_precheck_refuses_absent_and_wrong_type() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        absent = _write_settings(Path(tmp), "absent.json", _baseline_bindings())
        wrong = _write_settings(
            Path(tmp),
            "wrong.json",
            _baseline_bindings() + [_binding(helper.P01_CREDENTIAL_NAME, "plain_text", text="x")],
        )
        proc_absent = _run_cli(["replacement-precheck", "--settings", str(absent)])
        proc_wrong = _run_cli(["replacement-precheck", "--settings", str(wrong)])
    assert proc_absent.returncode == 1
    assert "B62_P01_REPLACEMENT_PRECHECK=FAIL" in proc_absent.stderr
    assert "absent" in proc_absent.stderr
    assert proc_wrong.returncode == 1
    assert "refusing to overwrite" in proc_wrong.stderr


def test_cli_replacement_verify_passes_and_denies_runtime_claim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pre = _write_settings(Path(tmp), "pre.json", _activated_bindings())
        post = _write_settings(Path(tmp), "post.json", _activated_bindings())
        proc = _run_cli(
            ["replacement-verify", "--settings", str(post), "--pre-settings", str(pre)]
        )
    assert proc.returncode == 0, proc.stderr
    assert "B62_P01_REPLACEMENT_VERIFY=PASS" in proc.stdout
    assert "P01_ENGINE_CREDENTIAL=PRESENT:secret_text" in proc.stdout
    assert "UNRELATED_SECRET_MUTATION=0" in proc.stdout
    assert "RUNTIME_SUCCESS_CLAIM=NO_UNTIL_PHASE_A_RERUN" in proc.stdout


def test_cli_replacement_verify_fails_on_dropped_binding() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as tmp:
        pre = _write_settings(Path(tmp), "pre.json", _activated_bindings())
        post = _write_settings(
            Path(tmp),
            "post.json",
            [b for b in _activated_bindings() if b["name"] != helper.P01_CREDENTIAL_NAME],
        )
        proc = _run_cli(
            ["replacement-verify", "--settings", str(post), "--pre-settings", str(pre)]
        )
    assert proc.returncode == 1
    assert "B62_P01_REPLACEMENT_VERIFY=FAIL" in proc.stderr
    assert helper.P01_CREDENTIAL_NAME in proc.stderr


def test_cli_replacement_verify_requires_both_settings_files() -> None:
    proc = _run_cli(["replacement-verify"])
    assert proc.returncode == 2
    assert "--pre-settings" in proc.stderr


def test_workflow_exposes_replacement_dispatch_mode() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "- replace_p01_engine_credential" in workflow
    assert "inputs.mode == 'replace_p01_engine_credential'" in workflow
    assert (
        "inputs.mode != 'replace_p01_engine_credential'"
        in workflow.split("cloudflare-readonly:", 1)[1].split("steps:", 1)[0]
    )


def test_replacement_job_uses_dedicated_confirmation_phrase() -> None:
    block = _replacement_job_block()
    assert "CONFIRM_REPLACE_B62_P01_ENGINE_CREDENTIAL" in block
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" not in block
    assert "ACTIVATION_CONFIRMATION_PHRASE_NOT_REUSED=YES" in block


def test_replacement_job_is_production_gated_and_needs_only_source_contract() -> None:
    block = _replacement_job_block()
    header = block.split("steps:", 1)[0]
    assert "environment: production" in header
    assert "needs: source-contract" in header
    assert "cloudflare-readonly" not in header
    assert "github.event_name == 'workflow_dispatch'" in header


def test_replacement_job_uses_only_secret_put_and_never_patches_settings() -> None:
    block = _replacement_job_block()
    assert "workers/scripts/${B62_WORKER}/secrets" in block
    assert re.findall(r"-X ([A-Z]+)", block) == ["PUT"]
    for token in ("-X PATCH", "-X POST", "-F ", "settings=<", "--keep-vars", "wrangler"):
        assert token not in block, token


def test_replacement_job_mutates_only_the_p01_credential_binding_name() -> None:
    block = _replacement_job_block()
    names = re.findall(r'"name": "([A-Za-z0-9_]+)"', block)
    assert names == ["P01_ENGINE_CREDENTIAL"]


def test_replacement_job_records_served_version_evidence() -> None:
    block = _replacement_job_block()
    assert "PREMUTATION_SERVED_VERSION_ID" in block
    assert "(.result.deployments[0].versions | length) == 1" in block
    assert ".result.deployments[0].versions[0].percentage == 100" in block
    assert "WORKER_CODE_DEPLOY_SUBMITTED=0" in block


def test_replacement_served_version_evidence_is_bounded_polling_not_single_read() -> None:
    """#2453: the YES|NO verdict must come from the bounded convergence poll.

    The workflow may not map one immediate post-PUT GET to YES or NO: a first
    read still equal to the pre-mutation version is transient lag, not stable
    evidence. The poll reuses the overlay-rotation budget (30 x 2s), resolves
    every read only through the canonical helper resolver, and finalizes the
    verdict via replacement-served-version-final over the observation log.
    """
    block = _replacement_job_block()
    step = block.split("- name: Record post-mutation served version evidence", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    assert "for attempt in $(seq 1 30)" in step
    assert "sleep 2" in step
    assert "replacement-served-version-read" in step
    assert "replacement-served-version-final" in step
    assert '--pre-version "${PREMUTATION_SERVED_VERSION_ID}"' in step
    assert "(.result.deployments | length) > 0" in step
    # the first acceptable divergent read closes YES, and NO needs the 15-observation floor
    assert '[ "${served}" != "${PREMUTATION_SERVED_VERSION_ID}" ]' in step
    assert '[ "${same}" -ge 15 ]' in step
    assert "b62-served-version-observations.tsv" in step


def test_replacement_served_version_step_never_finalizes_from_one_read() -> None:
    """Static prohibition (fixture 6): no direct shell mapping of a read to YES/NO."""
    step = _post_mutation_step_block()
    assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=YES" not in step
    assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=NO" not in step
    assert "POSTMUTATION_SERVED_VERSION_ID=" not in step
    verdict_writers = [
        line for line in step.splitlines()
        if "SERVED_VERSION_CHANGED_BY_SECRET_PUT" in line
        or "POSTMUTATION_SERVED_VERSION_ID" in line
    ]
    assert verdict_writers == [], verdict_writers


def test_replacement_job_step_order_is_authorize_gate_precheck_mutate_verify() -> None:
    block = _replacement_job_block()
    order = [
        "- name: Require explicit credential replacement authorization",
        "- name: Gate the source credential with bounded quality evidence",
        "- name: Record pre-mutation settings and served version",
        "- name: Replace the P01 Engine credential through the secrets API",
        "- name: Record post-mutation served version evidence",
        "- name: Read back the replaced credential by binding name and type only",
    ]
    positions = [block.index(step) for step in order]
    assert positions == sorted(positions)
    assert 'test "${CONFIRMATION}"' in block[: positions[1]]


def test_replacement_job_wires_helper_precheck_and_verify_commands() -> None:
    block = _replacement_job_block()
    assert "b62_claw_live_config_activation.py credential-quality" in block
    assert "b62_claw_live_config_activation.py replacement-precheck" in block
    assert "b62_claw_live_config_activation.py replacement-verify" in block
    assert "--pre-settings" in block
    assert "OLD_SECRET_VALUE_READ=NO" in block


def test_replacement_job_never_echoes_the_source_credential_value() -> None:
    block = _replacement_job_block()
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert "${B62_P01_ENGINE_CREDENTIAL}" not in stripped, stripped
    assert "test -n \"${B62_P01_ENGINE_CREDENTIAL}\"" in block


def _deployments_envelope(version_id: str) -> dict:
    """The canonical served-version envelope the poll must accept (#2427 shape)."""
    return {
        "success": True,
        "result": {"deployments": [{"id": "deployment-1", "versions": [
            {"version_id": version_id, "percentage": 100}
        ]}]},
    }


def _observations(directory: Path, name: str, entries: list[tuple[str, str | None]]) -> Path:
    path = directory / name
    lines = [
        f"{flag}\t{version or ''}"
        for flag, version in entries
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_convergence_decision_first_divergent_read_finalizes_yes() -> None:
    """Fixture 1: PRE=A, acceptable A then B -> YES on the second read."""
    helper = _load_helper()
    decision = helper.convergence_decision("A", [(True, "A"), (True, "B")])
    assert decision["finalized"] == "YES"
    assert decision["post_version_id"] == "B"
    assert decision["diverged_at"] == 2


def test_convergence_decision_transient_repeats_then_new_version_is_yes() -> None:
    """Fixture 2: several pre-version reads then the new canonical version -> YES."""
    helper = _load_helper()
    decision = helper.convergence_decision(
        "A", [(True, "A"), (True, "A"), (True, "A"), (True, "A"), (True, "B")]
    )
    assert decision["finalized"] == "YES"
    assert decision["post_version_id"] == "B"
    assert decision["same_observations"] == 4
    assert decision["diverged_at"] == 5


def test_convergence_decision_stable_window_finalizes_no_as_evidence() -> None:
    """Fixture 3: unchanged canonical state across the full window -> NO, not failure."""
    helper = _load_helper()
    decision = helper.convergence_decision("A", [(True, "A")] * 30)
    assert decision["finalized"] == "NO"
    assert decision["changed"] is False
    assert decision["post_version_id"] == "A"
    assert decision["diverged_at"] is None


def test_convergence_decision_needs_the_stable_minimum_before_no() -> None:
    """A short acceptable window proves nothing: below the floor it is FAIL, not NO."""
    helper = _load_helper()
    decision = helper.convergence_decision("A", [(True, "A")] * 14)
    assert decision["finalized"] == "FAIL"
    assert decision["changed"] is None


def test_convergence_decision_rejects_malformed_and_ambiguous_reads() -> None:
    """Fixture 4: rejected reads are skipped, never PASS or NO evidence."""
    helper = _load_helper()
    assert helper.convergence_decision("A", [(False, None)] * 20)["finalized"] == "FAIL"
    mixed = helper.convergence_decision(
        "A", [(False, None), (False, "garbage"), (True, "B")]
    )
    assert mixed["finalized"] == "YES"
    assert mixed["diverged_at"] == 1  # counted over acceptable reads only


def test_convergence_decision_requires_a_usable_pre_version() -> None:
    helper = _load_helper()
    for bad in ("", None, 123):
        try:
            helper.convergence_decision(bad, [(True, "A")])
        except helper.ActivationPlanError:
            continue
        raise AssertionError(f"pre-version {bad!r} must be refused")


def test_cli_replacement_served_version_read_accepts_canonical_envelope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "d.json"
        path.write_text(json.dumps(_deployments_envelope("version-A")), encoding="utf-8")
        proc = _run_cli(["replacement-served-version-read", "--deployments", str(path)])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "version-A"
    assert proc.stderr == ""


def test_cli_replacement_served_version_read_refuses_every_noncanonical_shape() -> None:
    """Raw list, last-entry history, result list, and bad splits are never poll evidence."""
    helper = _load_helper()
    assert helper.resolve_served_version_id(_deployments_envelope("version-A")) == "version-A"
    payloads = [
        [{"versions": [{"version_id": "A", "percentage": 100}]}],  # wrangler raw list
        {"success": True, "result": {"deployments": []}},
        {"success": False, "result": {"deployments": []}},
        _envelope_two_versions(),
        {"success": True, "result": {"deployments": [{"versions": [
            {"version_id": "A", "percentage": 50}, {"id": "B", "percentage": 50}]}]}},
        {"success": True, "result": {"deployments": [{"versions": [
            {"id": "bare-id-A", "percentage": 100}]}]}},
    ]
    for payload in payloads:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            proc = _run_cli(["replacement-served-version-read", "--deployments", str(path)])
        assert proc.returncode == 1, payload
        assert "B62_P01_SERVED_VERSION_READ=REJECTED" in proc.stderr
        assert proc.stdout.strip() == "", "a rejected read must never emit a version id"


def _envelope_two_versions() -> dict:
    return {"success": True, "result": {"deployments": [{"versions": [
        {"version_id": "A", "percentage": 100},
        {"version_id": "B", "percentage": 60},
    ]}]}}


def test_cli_replacement_served_version_final_yes_and_no_are_bounded_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        diverged = _observations(Path(tmp), "div.tsv", [("acceptable", "A"), ("acceptable", "B")])
        proc = _run_cli([
            "replacement-served-version-final",
            "--observations-file", str(diverged), "--pre-version", "A",
        ])
        assert proc.returncode == 0, proc.stderr
        assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=YES" in proc.stdout
        assert "POSTMUTATION_SERVED_VERSION_ID=B" in proc.stdout
        assert "POST_PUT_DIVERGENCE_OBSERVED_AT=2" in proc.stdout

        stable = _observations(Path(tmp), "stable.tsv", [("acceptable", "A")] * 20)
        proc = _run_cli([
            "replacement-served-version-final",
            "--observations-file", str(stable), "--pre-version", "A",
        ])
        assert proc.returncode == 0, proc.stderr
        assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT=NO" in proc.stdout
        # NO is evidence, never a mutation claim
        assert "SECRET_PUT_MUST_CHANGE_VERSION=NO" in proc.stdout
        assert "WORKER_CODE_DEPLOY_SUBMITTED=0" in proc.stdout


def test_cli_replacement_served_version_final_fails_closed_without_acceptable_state() -> None:
    """Fixture 5: window exhausted with no canonical served state -> FAIL exit 1."""
    with tempfile.TemporaryDirectory() as tmp:
        no_ok = _observations(Path(tmp), "rej.tsv", [("rejected", None)] * 5)
        proc = _run_cli([
            "replacement-served-version-final",
            "--observations-file", str(no_ok), "--pre-version", "A",
        ])
        assert proc.returncode == 1
        assert "B62_P01_SERVED_VERSION_CONVERGENCE=FAIL" in proc.stdout
        assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT" not in proc.stdout

        too_short = _observations(Path(tmp), "short.tsv", [("acceptable", "A")] * 5)
        proc = _run_cli([
            "replacement-served-version-final",
            "--observations-file", str(too_short), "--pre-version", "A",
        ])
        assert proc.returncode == 1
        assert "B62_P01_SERVED_VERSION_CONVERGENCE=FAIL" in proc.stdout
        assert "SERVED_VERSION_CHANGED_BY_SECRET_PUT" not in proc.stdout


def test_cli_replacement_served_version_final_never_emits_secret_surfaces() -> None:
    """Fixtures 9/10/11: no secret value, hash, or length on any convergence path."""
    source = HELPER.read_text(encoding="utf-8")
    read_src = source.split("def _main_replacement_served_version_read", 1)[1].split(
        "def _main_replacement_served_version_final", 1
    )[0]
    final_src = source.split("def _main_replacement_served_version_final", 1)[1].split(
        'if __name__', 1
    )[0]
    for body in (read_src, final_src):
        assert "B62_P01_ENGINE_CREDENTIAL" not in body
        assert "hashlib" not in body
        assert "SOURCE_CREDENTIAL_ENV" not in body
    # the finalizer emits the explicit zero-denials on both success and FAIL
    for denial in ("SECRET_VALUE_OUTPUT=0", "SECRET_HASH_OUTPUT=0", "SECRET_LENGTH_OUTPUT=0"):
        assert final_src.count(denial) >= 2, denial
    with tempfile.TemporaryDirectory() as tmp:
        obs = _observations(Path(tmp), "o.tsv", [("acceptable", "A")] * 20)
        proc = _run_cli([
            "replacement-served-version-final",
            "--observations-file", str(obs), "--pre-version", "A",
        ])
        combined = proc.stdout + proc.stderr
        assert "SECRET_VALUE_OUTPUT=0" in combined
        assert "SECRET_HASH_OUTPUT=0" in combined
        assert "SECRET_LENGTH_OUTPUT=0" in combined


def test_replacement_job_keeps_settings_plane_name_type_verification() -> None:
    """Fixture 12: convergence polling must not weaken the readback NAME/TYPE verify."""
    block = _replacement_job_block()
    assert "b62_claw_live_config_activation.py replacement-verify" in block
    assert "--pre-settings" in block
    assert 'test "${verified}" = yes' in block
    assert "B62_P01_REPLACEMENT_POST_READBACK=PASS" in block
    verify_step = block.split(
        "- name: Read back the replaced credential by binding name and type only", 1
    )[1]
    for line in verify_step.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or "${GITHUB_OUTPUT}" in stripped:
            assert "${B62_P01_ENGINE_CREDENTIAL}" not in stripped, stripped


def test_replacement_job_is_placed_between_activate_and_rollback() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    activate_at = workflow.index("  activate-config:")
    replace_at = workflow.index("  replace-p01-credential:")
    rollback_at = workflow.index("  rollback-config:")
    assert activate_at < replace_at < rollback_at


def test_activate_config_create_path_remains_untouched_by_replacement() -> None:
    activate = _activate_job_block()
    assert "B62_CLAW_CONFIG_CREDENTIAL_CREATE_REQUIRED == '1'" in activate
    assert "CONFIRM_ACTIVATE_B62_CLAW_LIVE_CONFIG" in activate
    block = _replacement_job_block()
    assert "CREDENTIAL_CREATE_REQUIRED" not in block
    assert "credential-quality" in block


def test_replacement_plan_and_activate_paths_never_replace_existing_credential() -> None:
    helper = _load_helper()
    plan = helper.build_activation_patch(
        _settings(_activated_bindings()),
        engine_service_name=ENGINE,
        r2_bucket_name=BUCKET,
        target_sha="0" * 40,
    )
    assert plan["no_op"] is True
    assert plan["credential_create_required"] is False
    assert helper.P01_CREDENTIAL_NAME not in [c.split("_")[0] for c in plan["changes"]]
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_settings(Path(tmp), "s.json", _activated_bindings())
        proc = _run_cli(
            ["plan", "--settings", str(path), "--engine-service", ENGINE,
             "--r2-bucket", BUCKET, "--target-sha", "0" * 40,
             "--output", str(Path(tmp) / "patch.json")]
        )
    assert proc.returncode == 0, proc.stderr
    assert "B62_CLAW_CONFIG_CREDENTIAL_CREATE_REQUIRED=0" in proc.stdout


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
    test_readonly_job_output_wires_r2_bucket_existence()
    test_readonly_r2_bucket_existence_uses_stable_output_key()
    test_readonly_r2_bucket_existence_emits_bounded_log_evidence()
    test_readonly_r2_evidence_never_emits_credentials_or_account_id()
    test_readonly_r2_check_stays_get_only_with_no_mutation_verbs()
    test_readonly_worker_settings_classification_unchanged()
    test_readonly_r2_bucket_http_status_is_bounded()
    test_readonly_r2_bucket_response_shape_is_bounded()
    test_readonly_r2_bucket_http_status_uses_stable_output_keys()
    test_readonly_job_output_wires_r2_status_observability()
    test_readonly_r2_status_mapping_is_exact_per_case_arm()
    test_readonly_r2_status_evidence_emits_no_raw_response_or_secrets()
    test_readonly_r2_single_get_preserved_after_status_observability()
    test_readonly_r2_step_uses_only_the_dedicated_secret()
    test_readonly_r2_dedicated_secret_reference_is_canonical_and_single()
    test_readonly_worker_settings_step_keeps_shared_token()
    test_readonly_job_env_does_not_expose_shared_token_to_r2_step()
    test_readonly_r2_missing_dedicated_token_fails_closed_before_curl()
    test_readonly_r2_step_has_no_shared_token_fallback()
    test_readonly_r2_dedicated_token_value_is_never_emitted()
    test_readonly_r2_evidence_keys_unchanged_after_credential_split()
    test_activation_r2_confirm_uses_only_the_dedicated_secret()
    test_activation_r2_confirm_dedicated_reference_is_canonical_and_single()
    test_activation_r2_confirm_has_no_shared_token_fallback()
    test_activation_r2_confirm_missing_dedicated_token_fails_closed_before_curl()
    test_activation_r2_confirm_remains_single_get_only()
    test_activation_r2_confirm_fails_on_success_false_or_name_mismatch()
    test_activation_r2_confirm_never_emits_token_account_or_raw_response()
    test_activation_r2_confirm_precedes_settings_patch_and_secret_put()
    test_activation_shared_token_remains_for_worker_config_operations()
    test_activation_r2_evidence_keys_unchanged_after_dedicated_wiring()
    test_source_credential_quality_byte_boundaries()
    test_source_credential_quality_counts_utf8_bytes_not_characters()
    test_helper_credential_bounds_match_worker_config()
    test_replacement_precheck_requires_existing_secret_text()
    test_replacement_precheck_reports_names_only()
    test_verify_replacement_readback_accepts_identical_or_extended_bindings()
    test_verify_replacement_readback_flags_credential_loss_or_retype()
    test_verify_replacement_readback_flags_unrelated_secret_loss()
    test_cli_credential_quality_passes_with_valid_env_without_emitting_value()
    test_cli_credential_quality_fails_closed_when_env_missing()
    test_cli_credential_quality_fails_on_invalid_length_without_leaking()
    test_cli_replacement_precheck_requires_settings()
    test_cli_replacement_precheck_passes_with_existing_secret_text()
    test_cli_replacement_precheck_refuses_absent_and_wrong_type()
    test_cli_replacement_verify_passes_and_denies_runtime_claim()
    test_cli_replacement_verify_fails_on_dropped_binding()
    test_cli_replacement_verify_requires_both_settings_files()
    test_workflow_exposes_replacement_dispatch_mode()
    test_replacement_job_uses_dedicated_confirmation_phrase()
    test_replacement_job_is_production_gated_and_needs_only_source_contract()
    test_replacement_job_uses_only_secret_put_and_never_patches_settings()
    test_replacement_job_mutates_only_the_p01_credential_binding_name()
    test_replacement_job_records_served_version_evidence()
    test_replacement_job_step_order_is_authorize_gate_precheck_mutate_verify()
    test_replacement_job_wires_helper_precheck_and_verify_commands()
    test_replacement_job_never_echoes_the_source_credential_value()
    test_replacement_job_is_placed_between_activate_and_rollback()
    test_activate_config_create_path_remains_untouched_by_replacement()
    test_replacement_plan_and_activate_paths_never_replace_existing_credential()
    test_replacement_served_version_evidence_is_bounded_polling_not_single_read()
    test_replacement_served_version_step_never_finalizes_from_one_read()
    test_convergence_decision_first_divergent_read_finalizes_yes()
    test_convergence_decision_transient_repeats_then_new_version_is_yes()
    test_convergence_decision_stable_window_finalizes_no_as_evidence()
    test_convergence_decision_needs_the_stable_minimum_before_no()
    test_convergence_decision_rejects_malformed_and_ambiguous_reads()
    test_convergence_decision_requires_a_usable_pre_version()
    test_cli_replacement_served_version_read_accepts_canonical_envelope()
    test_cli_replacement_served_version_read_refuses_every_noncanonical_shape()
    test_cli_replacement_served_version_final_yes_and_no_are_bounded_evidence()
    test_cli_replacement_served_version_final_fails_closed_without_acceptable_state()
    test_cli_replacement_served_version_final_never_emits_secret_surfaces()
    test_replacement_job_keeps_settings_plane_name_type_verification()
    print("B62_CLAW_LIVE_CONFIG_ACTIVATION_TESTS=PASS")
