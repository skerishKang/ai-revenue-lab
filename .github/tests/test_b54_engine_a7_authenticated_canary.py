"""Static contracts for the owner-gated A7 authenticated USER canary."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-a7-authenticated-user-canary.yml"
SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a7_authenticated_user_production_canary.py"
CP_WORKER = ROOT / "packages" / "padiem-control-plane" / "engine_admission_authority_worker.py"
PRODUCER = ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane" / "engine_entitlement_producer.py"
ENGINE_SERVICE = ROOT / "apps" / "padiem-ai-engine" / "app" / "execution_admission_service.py"


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trigger = data.get("on", data.get(True))
    return {"trigger": trigger, "jobs": data["jobs"]}


def _live_job() -> dict:
    return _workflow()["jobs"]["live-authenticated-user-canary"]


def _live_runs() -> str:
    return "\n".join(str(step.get("run", "")) for step in _live_job()["steps"])


def test_canary_source_uses_canonical_primary_and_protected_subject_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from padiem_ai_core.model_primary import TEXT_PRIMARY_MODEL_ID" in source
    assert '"subject_id": subject_id' in source
    assert '"max_tokens": 8' in source
    assert "PADIEM_A7_CANARY_SUBJECT_ID" in source
    assert "REAL_PROVIDER_CALL_MAX=1" in source
    assert "RAW_SUBJECT_OUTPUT=0" in source
    assert "print(CANARY_SUBJECT_ID" not in source
    assert "CUSTOM_PAYLOAD_JSON" not in source
    assert not re.search(r"(space-bunny|sensenova|openai|anthropic)", source, re.I)


def test_a7_subject_guard_matches_real_control_plane_mint_contract() -> None:
    """Do not approve a canary that rejects all CP-minted subject IDs."""
    import ast

    cp_source = (
        ROOT / "packages" / "padiem-control-plane" / "identity_authority_durable.py"
    ).read_text(encoding="utf-8")
    # This exact 16-byte subject mint is the existing canonical CP contract.
    assert 'self._new_ref("sub_", 16)' in cp_source

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    compiled = [
        node.value.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_SUBJECT_RE" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "compile"
        and node.value.args
        and isinstance(node.value.args[0], ast.Constant)
        and isinstance(node.value.args[0].value, str)
    ]
    assert len(compiled) == 1
    guard = re.compile(compiled[0])
    canonical = "sub_" + "0123456789abcdef" * 2
    assert guard.fullmatch(canonical)
    for invalid in (
        "usr_" + "0123456789abcdef" * 2,  # product user, not CP subject
        "sub_" + "a" * 31,                 # truncated CP ref
        "sub_" + "g" * 32,                 # not hex
        "sub_" + "A" * 32,                 # CP mint is lowercase
        canonical + " ",                  # untrusted suffix
        canonical + "\\n",               # no newline bypass
        "someone@example.com",             # provider identity is not subject
    ):
        assert not guard.fullmatch(invalid)


def test_cp_worker_auto_ensures_entitlement_from_identity_without_engine_install() -> None:
    worker = CP_WORKER.read_text(encoding="utf-8")
    producer = PRODUCER.read_text(encoding="utf-8")
    assert "ensure_authenticated_user_engine_entitlement" in worker
    assert "await self._ensure_current_entitlement(" in worker
    assert "async def fetch_entitlement_snapshot" in worker
    assert "async def reserve_usage" in worker
    assert "ENGINE_GATEWAY_CAN_INSTALL_ENTITLEMENTS = False" in worker
    assert "CONTROL_PLANE_IDENTITY_REQUIRED_FOR_ENTITLEMENT = True" in worker
    assert "resolve_current_auth_session" in producer
    assert "SubjectType.USER" in producer
    assert 'ENGINE_ORCHESTRATION_GRANT = "orchestration.run"' in producer


def test_engine_success_path_is_fail_closed_on_terminal_usage_receipt() -> None:
    source = ENGINE_SERVICE.read_text(encoding="utf-8")
    assert "await self._record_terminal_usage(" in source
    assert 'outcome="succeeded"' in source
    assert "return self._receipt_error(exc)" in source
    assert "record_usage_receipt" in source


def test_workflow_pr_path_is_source_only_and_live_mode_is_explicit() -> None:
    wf = _workflow()
    assert "pull_request" in wf["trigger"]
    assert "workflow_dispatch" in wf["trigger"]
    job = _live_job()
    assert job["environment"] == "production"
    assert "live_authenticated_user_canary" in str(job["if"])
    assert "RUN_A7_AUTHENTICATED_USER_CANARY_FROM_EXACT_MAIN" in str(job["if"])


def test_live_job_requires_exact_main_and_exact_served_version() -> None:
    runs = _live_runs()
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in runs
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in runs
    assert "EXPECTED_SERVED_VERSION_UNSAFE" in runs
    assert "resolve-active" in runs
    assert "SERVED_VERSION_MISMATCH" in runs
    assert "--inspect-engine-admission-binding" in runs
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" in runs
    assert "ENGINE_ADMISSION_BINDING_TARGET_VALIDATED=YES" in runs


def test_subject_and_caller_secrets_are_consumed_but_never_echoed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    runs = _live_runs()
    env = _live_job()["env"]
    assert env["PADIEM_A7_CANARY_SUBJECT_ID"] == "${{ secrets.PADIEM_A7_CANARY_SUBJECT_ID }}"
    assert env["CALLER_SECRET"] == "${{ secrets.B62_P01_ENGINE_CREDENTIAL }}"
    assert "add-mask::${PADIEM_A7_CANARY_SUBJECT_ID}" in runs
    assert "echo \"${PADIEM_A7_CANARY_SUBJECT_ID}" not in runs
    assert "secrets." not in runs
    assert "PADIEM_A7_CANARY_SUBJECT_ID" in text


def test_live_gate_records_bounded_mutation_surface_and_never_flips_manifest() -> None:
    runs = _live_runs()
    assert "LIVE_PROVIDER_CALL_MAX=1" in runs
    assert "CP_USAGE_MUTATION=BOUNDED" in runs
    assert "ENGINE_IDEMPOTENCY_MUTATION=BOUNDED" in runs
    assert "MANIFEST_FLIP=0" in runs
    for forbidden in (
        "pywrangler deploy",
        "wrangler deploy",
        "wrangler secret",
        "secret put",
        "d1 migrations",
        "install_entitlement_snapshot",
    ):
        assert forbidden not in runs


# #3748 / #3876: real guard subprocess tests run in existing PR source-contract.
# All fixtures are synthetic; there are no credentials or network requests.
def _assert_a7_argv_contract(source: str) -> None:
    assert source.count('--active-version="${active}"') == 1
    assert '--active-version "${active}"' not in source
    assert "GET-only exact served-version A7 binding preflight" in source
    assert "--inspect-engine-admission-binding" in source
    assert "SERVED_VERSION_MISMATCH" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert "RUN_A7_AUTHENTICATED_USER_CANARY_FROM_EXACT_MAIN" in source


def _run_a7_guard(*version_args: str, admission: str = "good"):
    import json
    import subprocess
    import sys
    import tempfile

    bindings = [
        {
            "name": "PADIEM_ENGINE_CALLER_REGISTRY_V1",
            "type": "secret_text",
            "text": "SYNTHETIC_A7_SECRET_NEVER_ECHO",
        },
    ]
    if admission != "absent":
        bindings.append(
            {
                "name": "CONTROL_PLANE_ENGINE_ADMISSION",
                "type": "service",
                "service": (
                    "padiem-control-plane-engine-admission"
                    if admission == "good"
                    else "synthetic-wrong-service"
                ),
            }
        )
    fixture = {
        "success": True,
        "result": {
            "id": "-canonical-a7-v1",
            "resources": {"bindings": bindings},
        },
    }
    script = ROOT / ".github/scripts/b54_engine_served_version_guard.py"
    with tempfile.TemporaryDirectory(prefix="a7-cli-argv-") as temp:
        detail = Path(temp) / "synthetic-version-detail.json"
        detail.write_text(json.dumps(fixture), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "verify",
                "--version-settings",
                str(detail),
                *version_args,
                "--inspect-engine-admission-binding",
            ],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


def test_a7_version_cli_equals_form_source_contract() -> None:
    _assert_a7_argv_contract(WORKFLOW.read_text(encoding="utf-8"))


def test_a7_version_cli_real_subprocess_accepts_safe_leading_hyphen() -> None:
    result = _run_a7_guard("--active-version=-canonical-a7-v1")
    assert result.returncode == 0, result.stderr
    assert "B54_ENGINE_SERVED_VERSION_GUARD=PASS" in result.stdout
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" in result.stdout
    assert "ENGINE_ADMISSION_BINDING_TARGET_VALIDATED=YES" in result.stdout
    assert "SYNTHETIC_A7_SECRET_NEVER_ECHO" not in (result.stdout + result.stderr)


def test_a7_version_cli_rejects_ambiguous_spaced_argv() -> None:
    result = _run_a7_guard("--active-version", "-canonical-a7-v1")
    assert result.returncode == 2
    assert "expected one argument" in result.stderr
    assert "B54_ENGINE_SERVED_VERSION_GUARD=PASS" not in result.stdout


def test_a7_version_cli_fails_closed_for_identity_and_service_drift() -> None:
    mismatch = _run_a7_guard("--active-version=-canonical-a7-other")
    assert mismatch.returncode == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in mismatch.stderr
    wrong_target = _run_a7_guard("--active-version=-canonical-a7-v1", admission="wrong")
    assert wrong_target.returncode == 1
    assert "B54_ENGINE_SERVED_VERSION_GUARD=FAIL" in wrong_target.stderr
    absent = _run_a7_guard("--active-version=-canonical-a7-v1", admission="absent")
    assert absent.returncode == 0
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=ABSENT" in absent.stdout
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" not in absent.stdout
    for result in (mismatch, wrong_target, absent):
        assert "SYNTHETIC_A7_SECRET_NEVER_ECHO" not in (result.stdout + result.stderr)


def test_a7_version_cli_old_form_mutation_red_original_byte_identical() -> None:
    # Negative mutation happens in memory, leaving the actual workflow intact.
    original = WORKFLOW.read_bytes()
    source = original.decode("utf-8")
    _assert_a7_argv_contract(source)
    mutated = source.replace('--active-version="${active}"', '--active-version "${active}"', 1)
    assert mutated != source
    try:
        _assert_a7_argv_contract(mutated)
    except AssertionError:
        pass  # mutation RED
    else:
        raise AssertionError("old spaced argv unexpectedly passed source contract")
    assert WORKFLOW.read_bytes() == original  # byte-identical restoration
