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
3. CENTRAL export hotfix (ACT2 run 34795118387 stopped before the PUT with
   B54_ENGINE_OVERLAY_ROTATION_PLAN=FAIL / "new Claw credential is not set
   (environment variable NEW_CREDENTIAL)"): the validated credential is
   exported BARE (`export NEW_CREDENTIAL`, never with a value) after
   successful format validation and before BOTH child python consumers
   (rotation plan and auth probe) that read os.environ["NEW_CREDENTIAL"];
   the real generation region is executed under bash in a behavioral
   subprocess regression test proving child-env visibility and effective
   unset, with a negative control that detects the missing export — the
   credential value never appears in any test output;
4. closed budgets: ONE_GENERATION_MAX, ONE_OVERLAY_PUT_MAX (single PUT gated on
   HTTP 2xx AND response JSON .success == true, boolean-only, body and response
   files removed before continuing), ONE_AUTH_PROBE_MAX (exactly one transport
   call in the probe), NO_AUTOMATIC_RETRY, no artifacts, no secret-derived
   output;
5. polling contract (CENTRAL fix 1 + final polling fix): the pre-PUT served
    read is a SINGLE guarded GET (PRE_READ_CONTRACT=SINGLE_GUARDED_GET — it
    does NOT poll); only the post-PUT confirmation polls
    (POST_PUT_POLLING=BOUNDED_30x2S_GET_ONLY: rotation gate bounded GET-only
    polling, 30 attempts x 2s, single 100-percent served version, guard
    cross-check, no mutation, no PUT retry) and the loop accepts ONLY a served
    version that differs from the pre-PUT version — an old/old/new read
    sequence keeps polling to the third read (behaviorally regression-tested
    with stubbed curl/jq), and D5 is emitted solely when the polling budget is
    exhausted without a new version;
6. CENTRAL fix 3: the auth verdict is the closed three-way contract
   PASS / FAIL / INCONCLUSIVE, regression-tested behaviorally under bash;
7. fail-closed stops D1..D5 exist, run BEFORE the probe budget is consumed
   where applicable, and the always() evidence step never claims an executed
   result when the pipeline stopped early (truthful outcome markers only);
8. reuse without duplication: the existing overlay payload builder
   (plan/classify/failure-evidence), the canonical GET-only served-version
   guard (resolve-active/verify), and the existing oracle module semantics
   (build_request/classify_response/_transport_post) are invoked, not
   re-implemented;
9. execution gating: only workflow_dispatch + environment: production + exact
   confirmation phrase + double exact-main guard can reach the mutating step;
   the PR trigger runs only these static tests and echoes DIAGNOSTIC_EXECUTED=NO.
"""

from __future__ import annotations

import re
import subprocess
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
POLL_OLD = "aaaaaaaa-0000-0000-0000-000000000000"
POLL_NEW = "bbbbbbbb-0000-0000-0000-000000000000"


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


def _verdict_block() -> str:
    step = _pipeline_step()
    start = step.index("# --- verdict-begin ---") + len("# --- verdict-begin ---")
    end = step.index("# --- verdict-end ---")
    return step[start:end]


def _run_verdict(accepted: str, status: str, error: str) -> str:
    script = (
        "set -euo pipefail\n"
        f'probe_accepted="{accepted}"\n'
        f'probe_status="{status}"\n'
        f'probe_error="{error}"\n'
    ) + _verdict_block()
    # bytes stdin/stdout: no universal-newline translation (LF stays LF on
    # Windows) and bounded decoding of any launcher noise on stderr
    proc = subprocess.run(["bash", "-s"], input=script.encode("utf-8"), capture_output=True)
    out = proc.stdout.decode("utf-8", errors="replace")
    assert proc.returncode == 0, f"verdict block failed: {out}"
    return out


# --- behavioral polling-region harness -------------------------------------
# The extracted region (new_version="" .. the D5 exhaustion block) is executed
# in bash with curl/jq/sleep stubbed as shell functions, so the real loop
# semantics are exercised without network, jq, or mutation: the stub curl
# serves one canned deployments document per call from the given sequence
# (clamped to its last element) and the stub jq only checks the bounded
# "valid" flag and echoes the version id.

POLL_HARNESS = r'''set -euo pipefail
pre_version="__PRE__"
api="https://api.invalid"
ENGINE_WORKER="padiem-ai-engine"
RUNNER_TEMP="$(mktemp -d)"
auth=()
served_guards='stubbed by the jq function below'
declare -a VERSIONS=(__VERSIONS__)
POLL_CURL_CALLS=0
curl() {
  local args=("$@") out="" i
  for ((i = 0; i < ${#args[@]} - 1; i++)); do
    if [ "${args[i]}" = "-o" ]; then out="${args[i + 1]}"; fi
  done
  POLL_CURL_CALLS=$((POLL_CURL_CALLS + 1))
  local idx=$((POLL_CURL_CALLS - 1))
  if [ "${idx}" -ge "${#VERSIONS[@]}" ]; then idx=$((${#VERSIONS[@]} - 1)); fi
  printf '{"valid":true,"version_id":"%s"}\n' "${VERSIONS[idx]}" > "${out}"
  echo "POLL_CURL_CALL_NUMBER=${POLL_CURL_CALLS}"
}
jq() {
  local args=("$@") file="${args[${#args[@]} - 1]}"
  if [ "${args[0]}" = "-e" ]; then
    grep -q '"valid":true' "${file}"
  else
    sed -n 's/.*"version_id":"\([^"]*\)".*/\1/p' "${file}"
  fi
}
sleep() { :; }
__REGION__
echo "POLL_CURL_CALLS_FINAL=${POLL_CURL_CALLS}"
echo "POLL_NEW_VERSION=${new_version}"
'''


def _extract_poll_region() -> str:
    step = _pipeline_step()
    start = step.index('new_version=""')
    end = step.index('resolve_post="', start)
    region = step[start:end]
    assert "for _ in $(seq 1 30); do" in region
    assert "D5=STOP_NEW_SERVED_VERSION_UNCONFIRMED" in region
    return region


def _extract_generation_region() -> str:
    step = _pipeline_step()
    start = step.index('NEW_CREDENTIAL="$(python3')
    end = step.index("plan_out=", start)
    region = step[start:end]
    assert "token_urlsafe(48)" in region
    assert "export NEW_CREDENTIAL" in region
    return region


def _run_export_region(with_export: bool) -> tuple[int, str]:
    region = _extract_generation_region()
    if not with_export:
        region = "\n".join(
            line for line in region.splitlines() if line.strip() != "export NEW_CREDENTIAL"
        )
    script = (
        "set -euo pipefail\n"
        + region
        + "if python3 -c 'import os,sys; sys.exit(0 if os.environ.get(\"NEW_CREDENTIAL\") else 1)'; "
        "then echo EXPORTED_ENV_VISIBLE=OK; else echo EXPORTED_ENV_VISIBLE=FAIL; fi\n"
        "unset NEW_CREDENTIAL\n"
        "if python3 -c 'import os,sys; sys.exit(0 if \"NEW_CREDENTIAL\" not in os.environ else 1)'; "
        "then echo UNSET_ENV_REMOVED=OK; else echo UNSET_ENV_REMOVED=FAIL; fi\n"
    )
    proc = subprocess.run(["bash", "-s"], input=script.encode("utf-8"), capture_output=True)
    out = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out


def _run_poll_region(versions: list[str]) -> tuple[int, str]:
    rendered = (
        POLL_HARNESS
        .replace("__PRE__", POLL_OLD)
        .replace("__VERSIONS__", " ".join(f'"{v}"' for v in versions))
        .replace("__REGION__", _extract_poll_region())
    )
    proc = subprocess.run(["bash", "-s"], input=rendered.encode("utf-8"), capture_output=True)
    out = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out


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


def test_credential_exported_before_child_consumers() -> None:
    step = _pipeline_step()
    assert step.count("export NEW_CREDENTIAL") == 1, "exactly one export site"
    for line in step.splitlines():
        if line.strip().startswith("export NEW_CREDENTIAL"):
            assert line.strip() == "export NEW_CREDENTIAL", "bare export only: never a value on the export line"
    export_at = step.index("export NEW_CREDENTIAL")
    assert export_at > step.index("CREDENTIAL_FORMAT_VALIDATED=PASS"), "export only after successful format validation"
    assert export_at < step.index("plan --credential-env NEW_CREDENTIAL"), "export before the rotation plan child"
    assert export_at < step.index('os.environ["NEW_CREDENTIAL"]'), "export before the auth probe child"
    # environment-only handoff: nothing is persisted to files or GHA scopes
    assert "GITHUB_ENV" not in step and "GITHUB_OUTPUT" not in step
    assert "tee" not in step
    # unset immediately after the single probe, and on every post-export stop
    probe_at = step.index('os.environ["NEW_CREDENTIAL"]')
    assert step.rindex("unset NEW_CREDENTIAL") > probe_at
    assert step.index("PROBE_CREDENTIAL_UNSET=YES") > step.rindex("unset NEW_CREDENTIAL")
    assert step[export_at:].count("unset NEW_CREDENTIAL") == 4, "D4 + D5 x2 + post-probe"
    d2_at = step.index("D2=STOP_GENERATION_FORMAT_DISCARDED")
    assert "unset NEW_CREDENTIAL" in step[:d2_at]


def test_export_regression_child_env_visible_and_unset_effective() -> None:
    # CENTRAL regression contract 10: run the REAL generation+export region in
    # bash and let a child python process read os.environ["NEW_CREDENTIAL"];
    # only fixed markers print, the credential value never reaches output
    rc, out = _run_export_region(True)
    assert rc == 0, out
    assert "ONE_GENERATION_MAX=YES" in out and "CREDENTIAL_FORMAT_VALIDATED=PASS" in out
    assert "EXPORTED_ENV_VISIBLE=OK" in out
    assert "UNSET_ENV_REMOVED=OK" in out
    assert not re.search(r"[A-Za-z0-9_-]{64}", out), "the generated credential value must never appear in output"


def test_export_regression_detects_missing_export() -> None:
    # negative control: the same region WITHOUT the export line reproduces the
    # ACT-2 runtime defect (child python cannot see NEW_CREDENTIAL), proving
    # the regression test has detection power
    rc, out = _run_export_region(False)
    assert rc == 0, out
    assert "EXPORTED_ENV_VISIBLE=FAIL" in out
    assert "UNSET_ENV_REMOVED=OK" in out
    assert not re.search(r"[A-Za-z0-9_-]{64}", out)


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
    assert "retry" not in step_no_marker.lower()
    # the ONLY sleep is the bounded GET-only polling interval; no PUT retry
    assert step_no_marker.count("sleep 2") == 1
    assert step_no_marker.count("-X PUT") == 1


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
    # (D4 once + D5 twice: polling budget exhausted / guard resolve mismatch;
    # the final polling fix moved the pre_version equality test INSIDE the
    # loop as a continue condition, so the old third D5 site is gone)
    assert step.count("AUTH_PROBE_REQUESTS_ISSUED=0") == 3
    assert "SERVED_VERSION_UNCHANGED" not in step
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
    assert "DIRECT_WRITE_AND_DIRECT_PROBE=INCONCLUSIVE" in step
    assert "VERDICT=WRITE_AND_READ_HEALTHY_GITHUB_SECRET_PATH_IS_DEFECT" in step
    assert "VERDICT=CLOUDFLARE_WRITE_OR_ENGINE_READ_PATH_DEFECT" in step
    assert "VERDICT=AUTH_ORACLE_NOT_REACHED_OR_UNEXPECTED" in step
    assert "SAME_PROCESS_CREDENTIAL=YES" in step
    assert "STOP_AND_REPORT=YES" in step
    assert "PROBE_CREDENTIAL_UNSET=YES" in step


def test_verdict_regression_pass() -> None:
    out = _run_verdict("YES", "200", "none")
    assert "DIRECT_WRITE_AND_DIRECT_PROBE=PASS" in out
    assert "VERDICT=WRITE_AND_READ_HEALTHY_GITHUB_SECRET_PATH_IS_DEFECT" in out
    assert "INCONCLUSIVE" not in out and "DIRECT_WRITE_AND_DIRECT_PROBE=FAIL" not in out


def test_verdict_regression_fail() -> None:
    out = _run_verdict("NO", "401", "service_authentication_failed")
    assert "DIRECT_WRITE_AND_DIRECT_PROBE=FAIL" in out
    assert "VERDICT=CLOUDFLARE_WRITE_OR_ENGINE_READ_PATH_DEFECT" in out
    assert "INCONCLUSIVE" not in out and "DIRECT_WRITE_AND_DIRECT_PROBE=PASS" not in out


def test_verdict_regression_inconclusive() -> None:
    for accepted, status, error in (
        ("NO", "0", "transport_blocked"),
        ("NO", "0", "none"),
        ("NO", "403", "unrecognized"),
        ("NO", "401", "unrecognized"),
        ("NO", "500", "unrecognized"),
        ("NO", "503", "unrecognized"),
        ("NO", "200", "unrecognized"),
    ):
        out = _run_verdict(accepted, status, error)
        assert "DIRECT_WRITE_AND_DIRECT_PROBE=INCONCLUSIVE" in out, (status, error, out)
        assert "VERDICT=AUTH_ORACLE_NOT_REACHED_OR_UNEXPECTED" in out, (status, error, out)
        assert "NO_AUTOMATIC_RETRY=YES" in out and "STOP_AND_REPORT=YES" in out
        assert "DIRECT_WRITE_AND_DIRECT_PROBE=PASS" not in out
        assert "DIRECT_WRITE_AND_DIRECT_PROBE=FAIL" not in out


def test_bounded_post_put_polling() -> None:
    step = _pipeline_step()
    assert step.count("for _ in $(seq 1 30); do") == 1
    poll_start = step.index("for _ in $(seq 1 30); do")
    poll = step[poll_start:step.index("done", poll_start)]
    # polling is GET-only: no verb override, no mutation call of any kind
    assert "-X" not in poll and "PUT" not in poll and "POST" not in poll
    assert "curl -fsS" in poll and "sleep 2" in poll
    # polling applies the shared single-100-percent served guard (one definition,
    # used by both the pre-read and the poll)
    assert 'jq -e "${served_guards}"' in poll
    assert step.count('jq -e "${served_guards}"') == 2
    assert step.count("percentage == 100") == 1
    # final polling fix: the loop breaks ONLY on a non-empty, non-null
    # candidate that DIFFERS from pre_version; candidate == pre_version
    # continues polling — there is no failure path inside the loop
    assert '[ "${candidate}" != "${pre_version}" ]' in poll
    assert poll.count("break") == 1
    assert poll.index('"${pre_version}"') < poll.index("break")
    assert "D5" not in poll and "exit" not in poll
    # the guard resolver cross-checks the polled version id before accepting it
    assert "GUARD_RESOLVE_MISMATCH=YES" in step
    assert "POLLING_MUTATION=0" in step
    assert "POST_PUT_POLLING=BOUNDED_30x2S_GET_ONLY" in step
    # polling never accepts the PUT response as proof: response file already gone
    assert step.index('rm -f "${response}"') < poll_start


def test_pre_read_is_single_guarded_get() -> None:
    step = _pipeline_step()
    poll_start = step.index("for _ in $(seq 1 30); do")
    pre_read = step[:poll_start]
    # the pre-read is exactly ONE deployments GET validated by ONE guard
    # application: only the post-PUT confirmation polls (wording contract:
    # PRE_READ_CONTRACT=SINGLE_GUARDED_GET, POST_PUT_POLLING=BOUNDED_30x2S_GET_ONLY)
    assert pre_read.count('/deployments" -o') == 1
    assert pre_read.count('jq -e "${served_guards}"') == 1
    assert step.count('/deployments" -o') == 2
    assert "PRE_READ_CONTRACT=SINGLE_GUARDED_GET" in step


def test_polling_regression_old_old_new_continues_to_third_read() -> None:
    # CENTRAL regression: served reads old, old, new must NOT break on the
    # first valid 100-percent version: the two old reads continue polling and
    # the third (new) read is accepted; D5 is not emitted.
    rc, out = _run_poll_region([POLL_OLD, POLL_OLD, POLL_NEW])
    assert rc == 0, out
    assert out.count("POLL_CURL_CALL_NUMBER=") == 3, out
    assert "POLL_CURL_CALLS_FINAL=3" in out
    assert f"POLL_NEW_VERSION={POLL_NEW}" in out
    assert "D5=STOP_NEW_SERVED_VERSION_UNCONFIRMED" not in out
    assert "POLLING_ATTEMPTS_EXHAUSTED=YES" not in out


def test_polling_regression_pre_version_only_exhausts_to_d5() -> None:
    # budget exhaustion with only pre_version reads: exactly 30 GET attempts,
    # then D5 with zero probe requests and no second PUT (the PUT site lives
    # outside this region and is capped by test_closed_mutation_and_probe_budgets)
    rc, out = _run_poll_region([POLL_OLD])
    assert rc == 1, out
    assert out.count("POLL_CURL_CALL_NUMBER=") == 30, out
    assert "D5=STOP_NEW_SERVED_VERSION_UNCONFIRMED" in out
    assert "POLLING_ATTEMPTS_EXHAUSTED=YES" in out
    assert "AUTH_PROBE_REQUESTS_ISSUED=0" in out
    assert "POLL_CURL_CALLS_FINAL" not in out


def test_put_success_contract_2xx_and_json_success() -> None:
    step = _pipeline_step()
    assert 'if [ "${http_status:0:1}" = "2" ] && jq -e \'.success == true\' "${response}" >/dev/null 2>&1; then put_ok=YES; fi' in step
    assert "OVERLAY_PUT_SUCCESS_CONTRACT=HTTP_2XX_AND_JSON_SUCCESS_TRUE" in step
    assert "PUT_RESPONSE_BODY_OUTPUT=0" in step
    # bounded boolean read only: the body is never echoed or catted
    assert "cat \"${response}\"" not in step
    assert step.count('rm -f "${response}"') == 2


def test_always_evidence_is_truthful() -> None:
    text = _text()
    job = _job(text, "diagnose")
    assert "id: diagnostic" in job
    evidence = job.split("if: always()", 1)[1]
    assert 'outcome="${{ steps.diagnostic.outcome }}"' in evidence
    assert "DIAGNOSTIC_PIPELINE_OUTCOME=" in evidence
    assert "DIAGNOSTIC_TERMINAL_STATE=VERDICT_REPORTED" in evidence
    assert "DIAGNOSTIC_TERMINAL_STATE=STOPPED_BEFORE_VERDICT" in evidence
    assert "EXECUTION_RESULT_MARKERS=NOT_CLAIMED" in evidence
    # static caps may always print, executed-result claims may not
    for cap in ("GENERATION_CAP=1", "OVERLAY_PUT_CAP=1", "AUTH_PROBE_CAP=1", "POLLING_CAP=30_ATTEMPTS_GET_ONLY"):
        assert cap in evidence
    for claim in ("ONE_GENERATION_MAX=YES", "ONE_OVERLAY_PUT_MAX=YES", "ONE_AUTH_PROBE_MAX=YES",
                  "PROBE_CREDENTIAL_UNSET=YES", "COMPLETE_STOP_AND_REPORT", "NEW_SERVED_VERSION_CREATED=YES"):
        assert claim not in evidence


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
