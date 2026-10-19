from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "b54-engine-a7-cp-admission-production-activation.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    data = yaml.safe_load(_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_activation_is_dispatch_only_for_mutation_and_pull_request_is_source_only() -> None:
    wf = _workflow()
    assert "pull_request" in wf["triggers"]
    assert "workflow_dispatch" in wf["triggers"]
    text = _text()
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "activate_cp_engine_admission_worker" in text
    assert "ACTIVATE_PADIEM_CONTROL_PLANE_ENGINE_ADMISSION_FROM_EXACT_MAIN" in text
    assert "environment: production" in text


def test_source_contract_dry_runs_exact_private_worker() -> None:
    text = _text()
    assert "wrangler.engine-admission-authority.jsonc" in text
    assert "pywrangler deploy" in text
    assert "--dry-run" in text
    assert "A7_CP_ADMISSION_PACKAGE_DRY_RUN=PASS" in text
    assert "PRODUCTION_MUTATION=0" in text


def test_first_activation_requires_fresh_engine_detachment_immediately_before_mutation() -> None:
    text = _text()
    assert 'test "${ENGINE_BINDING_STATE}" = "ABSENT"' in text
    assert "PREMUTATION_ENGINE_ADMISSION_BINDING=ABSENT" in text
    assert "PREMUTATION_CP_ENGINE_ADMISSION_WORKER=ABSENT" in text
    assert "PREMUTATION_CP_STATE_DRIFT=STOP" in text
    assert "ENGINE_REMAINS_DETACHED_DURING_CP_ACTIVATION=YES" in text
    assert "ENGINE_BINDING_MUTATION=0" in text
    assert "ENGINE_MUTATION=0" in text


def test_activation_workflow_step_structure_is_not_duplicated_or_spliced() -> None:
    wf = _workflow()
    steps = wf["jobs"]["activate-cp-engine-admission-worker"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.count("Reconfirm exact main and live sequence state immediately before the only mutation") == 1
    assert names.count("Deploy only the private CP Engine-admission Worker when absent") == 1
    assert names.count("Record exact-present no-op") == 1
    assert names.count("Post-activation private Worker readback") == 1
    text = _text()
    assert text.count("      - name: Deploy only the private CP Engine-admission Worker when absent") == 1
    assert text.count("      - name: Post-activation private Worker readback") == 1

def test_readonly_classifies_absent_or_private_present_without_secret_values() -> None:
    text = _text()
    assert "CP_ENGINE_ADMISSION_WORKER=ABSENT" in text
    assert "CP_ENGINE_ADMISSION_WORKER=PRESENT" in text
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING" in text
    assert "--inspect-engine-admission-binding" in text
    assert "SECRET_VALUES_READ=0" in text
    assert "REAL_USER_DATA=0" in text


def test_activation_mutates_only_cp_admission_worker_and_has_no_provider_or_manifest_action() -> None:
    text = _text()
    activation = text.split("activate-cp-engine-admission-worker:", 1)[1]
    assert "packages/padiem-control-plane" in activation
    assert "CP_ENGINE_ADMISSION_DEPLOY=SUCCESS" in activation
    for forbidden in (
        "apps/padiem-ai-engine",
        "wrangler rollback",
        "d1 migrations apply",
        "MANIFEST_E7=AVAILABLE",
        "/internal/v1/orchestrate",
        "PADIEM_KILO_API_KEY",
    ):
        assert forbidden not in activation


def test_post_readback_requires_private_ingress_identity_binding_and_canonical_served_version() -> None:
    text = _text()
    assert '.result.enabled == false and .result.previews_enabled == false' in text
    assert '"CONTROL_PLANE_IDENTITY"' in text
    assert '"padiem-control-plane-identity"' in text
    assert text.count("cloudflare_served_version_cli.py resolve-active") == 2
    assert ".result.deployments[0].versions[0].version_id" not in text
    assert ".result.deployments[0].versions[0].percentage" not in text
    assert "ROLLBACK_POSTURE=ENGINE_STILL_DETACHED_CP_WORKER_MAY_REMAIN_INERT" in text


def test_readonly_present_state_and_post_activation_readback_both_use_canonical_cli() -> None:
    wf = _workflow()
    readonly = "\n".join(
        step.get("run", "")
        for step in wf["jobs"]["cloudflare-readonly"]["steps"]
        if "run" in step
    )
    activation = "\n".join(
        step.get("run", "")
        for step in wf["jobs"]["activate-cp-engine-admission-worker"]["steps"]
        if "run" in step
    )

    assert readonly.count("cloudflare_served_version_cli.py resolve-active") == 1
    assert activation.count("cloudflare_served_version_cli.py resolve-active") == 1
    assert "CP_ENGINE_ADMISSION_WORKER=ABSENT" in readonly
    assert "CP_ENGINE_ADMISSION_WORKER=PRESENT" in readonly
    assert "CP_ENGINE_ADMISSION_WORKER=PRESENT" in activation
    assert "ENGINE_BINDING_MUTATION=0" in activation


def test_workflow_retriggers_when_generic_served_version_cli_changes() -> None:
    text = _text()
    trigger_paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in trigger_paths


# #3748 / #3885: real CLI argv parity for both A7 CP Engine-version checks.
# All subprocess input is synthetic. No Cloudflare, Engine or live activation.


def _assert_3748_a7_cp_argv_source(source: str) -> None:
    good = '--active-version="${active_engine}"'
    bad = '--active-version "${active_engine}"'
    assert source.count(good) == 2
    assert bad not in source
    assert source.count("--inspect-engine-admission-binding") == 2
    assert "PREMUTATION_ENGINE_ADMISSION_BINDING=ABSENT" in source
    assert "cloudflare-readonly:" in source
    assert "activate-cp-engine-admission-worker:" in source
    assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_cp_engine_admission_worker' }}" in source


def _run_3748_a7_cp_guard(*version_args: str, detail_id: str = "-safe-a7-cp-v1",
                          binding: str = "absent"):
    import json
    import subprocess
    import sys
    import tempfile

    bindings = [
        {
            "name": "PADIEM_ENGINE_CALLER_REGISTRY_V1",
            "type": "secret_text",
            "text": "SYNTHETIC_A7_CP_SECRET_MUST_NOT_APPEAR",
        },
    ]
    if binding != "absent":
        bindings.append({
            "name": "CONTROL_PLANE_ENGINE_ADMISSION",
            "type": "service" if binding != "wrong-type" else "kv_namespace",
            "service": ("padiem-control-plane-engine-admission"
                        if binding != "wrong-target" else "synthetic-invalid-target"),
        })
    payload = {
        "success": True,
        "result": {"id": detail_id, "resources": {"bindings": bindings}},
    }
    script = ROOT / ".github/scripts/b54_engine_served_version_guard.py"
    with tempfile.TemporaryDirectory(prefix="a7-cp-3748-") as tmp:
        fixture = Path(tmp) / "synthetic-version.json"
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script), "verify",
             "--version-settings", str(fixture), *version_args,
             "--inspect-engine-admission-binding"],
            text=True, capture_output=True, check=False, timeout=15,
        )


def test_3748_a7_cp_argv_both_sites_equals_form() -> None:
    _assert_3748_a7_cp_argv_source(_text())


def test_3748_a7_cp_argv_existing_pr_ci_executes_tests_offline() -> None:
    ci_path = ROOT / ".github/workflows/b54-engine-deploy-gate-contract-tests.yml"
    ci = ci_path.read_text(encoding="utf-8")
    assert "  pull_request:" in ci
    assert '".github/workflows/b54-engine-a7-cp-admission-production-activation.yml"' in ci
    assert '".github/tests/test_b54_engine_a7_cp_admission_activation.py"' in ci
    assert " .github/tests/test_b54_engine_a7_cp_admission_activation.py " in ci
    wf = _workflow()
    assert "pull_request" in wf["triggers"]
    assert "workflow_dispatch" in wf["triggers"]
    assert "workflow_dispatch" in wf["jobs"]["cloudflare-readonly"]["if"]
    assert "workflow_dispatch" in wf["jobs"]["activate-cp-engine-admission-worker"]["if"]


def test_3748_a7_cp_argv_real_guard_accepts_safe_leading_hyphen_absent_and_present() -> None:
    import re
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", "-safe-a7-cp-v1")
    for binding, marker in (
        ("absent", "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=ABSENT"),
        ("present", "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service"),
    ):
        result = _run_3748_a7_cp_guard("--active-version=-safe-a7-cp-v1", binding=binding)
        assert result.returncode == 0, result.stderr
        assert "B54_ENGINE_SERVED_VERSION_GUARD=PASS" in result.stdout
        assert marker in result.stdout
        assert "SYNTHETIC_A7_CP_SECRET_MUST_NOT_APPEAR" not in (result.stdout + result.stderr)


def test_3748_a7_cp_argv_real_guard_rejects_old_split_form() -> None:
    result = _run_3748_a7_cp_guard("--active-version", "-safe-a7-cp-v1")
    assert result.returncode == 2, result.stderr
    assert "expected one argument" in result.stderr
    assert "B54_ENGINE_SERVED_VERSION_GUARD=PASS" not in result.stdout


def test_3748_a7_cp_argv_real_guard_fails_closed_on_identity_or_binding_drift() -> None:
    for kwargs, flag in (
        ({}, "--active-version=-different-version"),
        ({"binding": "wrong-type"}, "--active-version=-safe-a7-cp-v1"),
        ({"binding": "wrong-target"}, "--active-version=-safe-a7-cp-v1"),
    ):
        result = _run_3748_a7_cp_guard(flag, **kwargs)
        assert result.returncode == 1, result.stderr
        assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in result.stderr
        assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" not in result.stdout
        assert "SYNTHETIC_A7_CP_SECRET_MUST_NOT_APPEAR" not in (result.stdout + result.stderr)


def test_3748_a7_cp_argv_each_old_form_mutation_red_and_original_bytes_unchanged() -> None:
    original = WORKFLOW.read_bytes()
    source = original.decode("utf-8")
    _assert_3748_a7_cp_argv_source(source)
    good = '--active-version="${active_engine}"'
    bad = '--active-version "${active_engine}"'
    for target_occurrence in (1, 2):
        pieces = source.split(good)
        assert len(pieces) == 3
        mutated = (good.join(pieces[:target_occurrence])
                   + bad + good.join(pieces[target_occurrence:]))
        assert mutated != source
        try:
            _assert_3748_a7_cp_argv_source(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("spaced argv mutation was not detected")
    assert WORKFLOW.read_bytes() == original
