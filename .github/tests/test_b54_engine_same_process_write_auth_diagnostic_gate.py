#!/usr/bin/env python3
"""Static contract tests for the P0 ACT-1 same-process write->auth diagnostic.

Run: python .github/tests/test_b54_engine_same_process_write_auth_diagnostic_gate.py

ACT-1 is SOURCE ONLY: these tests never dispatch, never touch the network, and
never mutate any secret. They prove:

1. GITHUB_SECRET_IN_PATH=NO — the gate never reads, writes, or references the
   GitHub repository secret B62_P01_ENGINE_CREDENTIAL in executable content,
   uses no admin PAT, and issues no `gh secret` / `gh workflow run` command;
2. SAME_PROCESS_CREDENTIAL=YES — generation, overlay PUT, served readback, and
   the auth probe all live in ONE bash step (one shell process), and the
   credential reaches the payload builder ONLY through the environment
   (`--credential-env`), never argv;
3. closed budgets: ONE_GENERATION_MAX, ONE_OVERLAY_PUT_MAX (single PUT, body
   file removed immediately), ONE_AUTH_PROBE_MAX (exactly one transport call in
   the probe), NO_AUTOMATIC_RETRY, no artifacts, no secret-derived output;
4. fail-closed stops D1..D5 exist, run BEFORE the probe budget is consumed
   where applicable, and the terminal verdict contract is exactly
   DIRECT_WRITE_AND_DIRECT_PROBE=PASS|FAIL + STOP_AND_REPORT=YES;
5. reuse without duplication: the existing overlay payload builder
   (plan/classify/failure-evidence), the canonical GET-only served-version
   guard (resolve-active/verify), and the existing oracle module semantics
   (build_request/classify_response/_transport_post) are invoked, not
   re-implemented;
6. execution gating: only workflow_dispatch + environment: production + exact
   confirmation phrase + double exact-main guard can reach the mutating step;
   the PR trigger runs only these static tests and echoes DIAGNOSTIC_EXECUTED=NO.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-same-process-write-auth-diagnostic-gate.yml"

DIAG_PHRASE = "RUN_B54_ENGINE_SAME_PROCESS_WRITE_AUTH_DIAGNOSTIC"
TARGET_SECRET_NAME = "B62_P01_ENGINE_CREDENTIAL"
ADMIN_SECRET_NAME = "B62_GITHUB_SECRET_ADMIN_TOKEN"
ROTATION_SCRIPT = ".github/scripts/b54_engine_caller_registry_overlay_rotation.py"
GUARD_SCRIPT = ".github/scripts/b54_engine_served_version_guard.py"
ORACLE_SCRIPT = ".github/scripts/b54_engine_credential_equivalence_diagnostic.py"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def _code(text: str) -> str:
    # executable workflow content only: header/prose comments legitimately name
    # forbidden mechanisms (the GitHub secret reference, the F4 backstory) and
    # must not be counted as capability usage.
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    rest = text[start + 1:]
    match = re.search(r"\n  [a-z][a-z0-9-]*:\n", rest[len(f"  {name}:\n"):])
    return rest[: len(f"  {name}:\n") + match.start()] if match else rest


def _trigger_block(text: str) -> str:
    return text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]


def _pipeline_step() -> str:
    """The single generate->PUT->readback->probe bash step body."""
    job = _job(_text(), "diagnose")
    candidates = [
        block for block in re.findall(r"run: \|\n((?:.*\n)*?) *(?=if:|uses:|- name:|$)", job + " ")
        if "NEW_CREDENTIAL" in block
    ]
    assert len(candidates) == 1, "the credential pipeline must live in exactly ONE bash step"
    return candidates[0]


def test_workflow_structure_and_triggers() -> None:
    text = _text()
    assert text.startswith("name: B54 Engine Same-Process")
    trigger = _trigger_block(text)
    assert trigger.startswith("  pull_request:\n")
    assert "\n  workflow_dispatch:\n" in trigger
    assert "\n  push:\n" not in trigger
    assert "deploy" not in trigger


def test_dispatch_inputs_and_phrase() -> None:
    text = _text()
    trigger = _trigger_block(text)
    inputs = trigger.split("workflow_dispatch:", 1)[1]
    assert inputs.count("required: true") == 3
    for name in ("target_sha:", "expected_served_version:", "confirmation:"):
        assert f"\n      {name}\n" in inputs
    assert DIAG_PHRASE in text
    assert 'test "${CONFIRMATION}" = ' in _code(text)


def test_pr_trigger_paths_are_scoped() -> None:
    trigger = _trigger_block(_text())
    paths = trigger.split("pull_request:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert sorted(re.findall(r'-\s+"([^"]+)"', paths)) == [
        ".github/tests/test_b54_engine_same_process_write_auth_diagnostic_gate.py",
        ".github/workflows/b54-engine-same-process-write-auth-diagnostic-gate.yml",
    ]


def test_read_only_permissions_and_no_orchestration_token() -> None:
    code = _code(_text())
    text = _text()
    permissions = text.split("\npermissions:\n", 1)[1].split("\nconcurrency:\n", 1)[0]
    assert permissions.strip() == "contents: read"
    assert _job(text, "diagnose").count("permissions:\n      contents: read") == 1
    assert "actions: write" not in code
    assert "contents: write" not in code
    assert "secrets.GITHUB_TOKEN" not in code
    assert "github.token" not in code


def test_github_secret_fully_out_of_path() -> None:
    code = _code(_text())
    assert TARGET_SECRET_NAME not in code, "the GitHub repository secret must not appear in executable content"
    assert ADMIN_SECRET_NAME not in code
    assert "gh secret" not in code
    assert "ADMIN_TOKEN" not in code
    assert "GITHUB_SECRET_IN_PATH=NO" in code


def test_no_downstream_dispatch_and_no_artifacts() -> None:
    code = _code(_text())
    assert "gh workflow run" not in code
    assert "gh run watch" not in code
    assert "upload-artifact" not in code
    assert "GITHUB_ENV" not in code
    assert "GITHUB_OUTPUT" not in code


def test_same_process_single_step_pipeline() -> None:
    step = _pipeline_step()
    for stage in (
        "secrets.token_urlsafe(48)",
        "plan --credential-env NEW_CREDENTIAL",
        "-X PUT",
        "resolve-active",
        "verify --version-settings",
        "AUTH_PROBE_REQUESTS_ISSUED=1",
        "unset NEW_CREDENTIAL",
    ):
        assert stage in step, f"pipeline stage missing from the single step: {stage}"
    job = _job(_text(), "diagnose")
    assert job.count("token_urlsafe") == 1, "exactly one generation site"
    assert job.count("-X PUT") == 1, "exactly one overlay PUT site"


def test_credential_never_crosses_process_boundaries() -> None:
    step = _pipeline_step()
    # never argv: no shell expansion of the credential in any command line
    assert "$NEW_CREDENTIAL" not in step.replace('os.environ["NEW_CREDENTIAL"]', "")
    assert "--credential" not in re.sub(r"--credential-env", "", step)
    assert 'credential = os.environ["NEW_CREDENTIAL"]' in step
    assert "token_urlsafe(48)" in step
    assert "[A-Za-z0-9_-]{64}" in step
    assert "D2=STOP_GENERATION_FORMAT_DISCARDED" in step


def test_put_body_file_is_short_lived_and_target_guarded() -> None:
    step = _pipeline_step()
    assert 'rm -f "${body}"' in step
    assert ".name == $name and .type == \"secret_text\"" in step
    assert "B54_ENGINE_OVERLAY_TARGET_GUARD=PASS" in step
    assert "b54-same-process-put-body.json" in step
    assert "rm -f \"${body}\" \"${response}\"" in step


def test_closed_mutation_and_probe_budgets() -> None:
    code = _code(_text())
    step = _pipeline_step()
    assert "ONE_GENERATION_MAX=YES" in step
    assert "ONE_OVERLAY_PUT_MAX=YES" in step
    assert "ONE_AUTH_PROBE_MAX=YES" in code
    assert step.count("_transport_post") == 1, "the probe must issue exactly one request"
    assert "AUTH_PROBE_REQUESTS_ISSUED=1" in step
    assert "NO_AUTOMATIC_RETRY=YES" in code
    step_no_marker = step.replace("NO_AUTOMATIC_RETRY=YES", "")
    assert "for attempt" not in step_no_marker and "until " not in step_no_marker
    assert "retry" not in step_no_marker.lower() and "sleep" not in step_no_marker


def test_fail_closed_stops_before_probe_budget() -> None:
    step = _pipeline_step()
    for marker in (
        "D2=STOP_GENERATION_FORMAT_DISCARDED",
        "D3=STOP_PRECONDITION_SERVED_VERSION",
        "D4=STOP_OVERLAY_PUT_FAILED",
        "D5=STOP_NEW_SERVED_VERSION_UNCONFIRMED",
    ):
        assert marker in step
    # the probe budget is untouched on every post-generation stop
    assert step.count("AUTH_PROBE_REQUESTS_ISSUED=0") == 2
    for stop in ("D4=STOP_OVERLAY_PUT_FAILED", "D5=STOP_NEW_SERVED_VERSION_UNCONFIRMED"):
        at = step.index(stop)
        window = step[max(0, at - 120):at + 260]
        assert "exit 1" in window and "unset NEW_CREDENTIAL" in window
    assert "D1=STOP_MAIN_DRIFT" in _code(_text())


def test_terminal_verdict_contract() -> None:
    code = _code(_text())
    step = _pipeline_step()
    assert "DIRECT_WRITE_AND_DIRECT_PROBE=PASS" in step
    assert "DIRECT_WRITE_AND_DIRECT_PROBE=FAIL" in step
    assert "VERDICT=WRITE_AND_READ_HEALTHY_GITHUB_SECRET_PATH_IS_DEFECT" in step
    assert "VERDICT=CLOUDFLARE_WRITE_OR_ENGINE_READ_PATH_DEFECT" in step
    assert "SAME_PROCESS_CREDENTIAL=YES" in step
    assert "STOP_AND_REPORT=YES" in step
    assert "PROBE_CREDENTIAL_UNSET=YES" in step


def test_no_secret_derived_output() -> None:
    code = _code(_text())
    assert "${NEW_CREDENTIAL:0" not in code
    assert "sha256" not in code and "hashlib" not in code
    for marker in ("SECRET_VALUE_OUTPUT=0", "SECRET_HASH_OUTPUT=0", "SECRET_LENGTH_OUTPUT=0",
                   "SECRET_PREFIX_SUFFIX_OUTPUT=0", "SECRET_DERIVED_OUTPUT=0", "RAW_REGISTRY_OUTPUT=0"):
        assert marker in code


def test_reuse_without_duplication() -> None:
    code = _code(_text())
    assert '"${ROTATION_SCRIPT}" plan --credential-env' in code
    assert '"${ROTATION_SCRIPT}" classify' in code
    assert '"${ROTATION_SCRIPT}" failure-evidence' in code
    assert '"${GUARD_SCRIPT}" resolve-active' in code
    assert '"${GUARD_SCRIPT}" verify --version-settings' in code
    text = _text()
    assert f"ROTATION_SCRIPT: {ROTATION_SCRIPT}" in text
    assert f"GUARD_SCRIPT: {GUARD_SCRIPT}" in text
    assert f"ORACLE_SCRIPT: {ORACLE_SCRIPT}" in text
    for script in (ROTATION_SCRIPT, GUARD_SCRIPT, ORACLE_SCRIPT):
        assert (ROOT / script).exists(), f"reused component missing: {script}"
    assert "b54_engine_credential_equivalence_diagnostic.py" in code
    assert "mod.build_request" in code and "mod.classify_response" in code
    # GET-only: no deploy/versions POST endpoints
    assert "/versions\"" not in code and "strategy=percentage" not in code
    assert "ENGINE_DEPLOY=0" in code


def test_execution_gating_is_production_and_exact_main() -> None:
    text = _text()
    code = _code(text)
    diagnose = _job(text, "diagnose")
    assert "environment: production" in diagnose
    assert "needs: [source-contract]" in diagnose
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in diagnose
    assert "checkout@v4" in code
    assert "ref: ${{ env.TARGET_SHA }}" in code
    assert "git rev-parse origin/main" in code
    assert code.count("EXACT_MAIN_GUARD=PASS") + code.count("DIAG_EXACT_MAIN_SHA=PASS") == 2
    assert "cancel-in-progress: false" in text


def test_source_contract_job_is_inert() -> None:
    source_job = _job(_text(), "source-contract")
    for lock in (
        "DIAGNOSTIC_EXECUTED=NO",
        "LIVE_DISPATCH=0",
        "NEW_CREDENTIAL_GENERATION_LIVE=0",
        "GITHUB_SECRET_MUTATION=0",
        "CLOUDFLARE_SECRET_MUTATION=0",
        "GITHUB_SECRET_READ=0",
        "PRODUCTION_MUTATION=0",
        "ENGINE_DEPLOY=0",
        "PHASE_A=0",
        "PROVIDER_CALL=0",
    ):
        assert lock in source_job
    assert "token_urlsafe" not in source_job
    assert "curl" not in source_job


def test_cloudflare_credentials_are_the_only_new_env() -> None:
    text = _text()
    diagnose = _job(text, "diagnose")
    job_env = diagnose.split("    env:\n", 1)[1].split("    steps:\n", 1)[0]
    assert sorted(re.findall(r"^      ([A-Z_]+):", job_env, re.M)) == [
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
    ]
    assert "secrets.CLOUDFLARE_API_TOKEN" in job_env
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in job_env
    assert "    env:" not in _job(text, "source-contract")
    code = _code(text)
    assert 'test -n "${CLOUDFLARE_API_TOKEN}"' in code
    assert 'test -n "${CLOUDFLARE_ACCOUNT_ID}"' in code


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"B54_SAME_PROCESS_WRITE_AUTH_DIAGNOSTIC_GATE_TESTS=PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
