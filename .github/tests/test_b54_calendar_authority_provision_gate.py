"""Static contract tests for the B54 Calendar authority provision gate.

These tests never call Cloudflare, Google, or D1. They pin the safety
invariants of the Calendar allowlist provision gate so a future edit cannot
silently widen the mutation scope, provision an Engine-owned Google OAuth
credential, overwrite an existing Production allowlist, leak the allowlist
value, or drop the exact-main and single-use confirmation guards.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(".github/workflows/b54-calendar-authority-provision-gate.yml")

CONFIRMATION_PHRASE = "CONFIRM_PROVISION_CALENDAR_ALLOWLIST"
MUTATION_MODE = "provision_calendar_allowlist"
ALLOWLIST_BINDING = "ENGINE_CALENDAR_ALLOWED_CALENDARS"
ALLOWLIST_SECRET = "B54_CALENDAR_ALLOWED_CALENDARS"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow_document() -> dict:
    return yaml.safe_load(workflow_text())


def input_default(inputs: dict, name: str) -> str:
    return str(inputs[name].get("default", ""))


def provision_job() -> dict:
    jobs = workflow_document()["jobs"]
    assert "provision-authority" in jobs
    return jobs["provision-authority"]


def provision_job_text() -> str:
    marker = "  provision-authority:"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "provision job not found"
    return marker + tail


ROLLBACK_STEP_NAME = "Roll back a confirmed Calendar allowlist PUT after downstream failure"
PUSH_STEP_NAME = "Push the Calendar Engine allowlist secret"


def step_by_name(name: str) -> dict:
    for step in provision_job()["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step not found: {name}")


def rollback_step_run() -> str:
    """The rollback step's own shell block (region-scoped assertions).

    Assertions about the rollback behavior must be scoped to this region: the
    push step contains the same Cloudflare success-envelope literal, so a
    whole-job text search would let the push step satisfy a rollback check that
    was silently removed.
    """

    script = step_by_name(ROLLBACK_STEP_NAME).get("run")
    assert isinstance(script, str) and script.strip(), "rollback step has no run block"
    return script


def push_step_run() -> str:
    script = step_by_name(PUSH_STEP_NAME).get("run")
    assert isinstance(script, str) and script.strip(), "push step has no run block"
    return script


def test_workflow_parses_and_default_dispatch_is_preflight() -> None:
    document = workflow_document()
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert input_default(inputs, "mode") == "repository_preflight"
    assert input_default(inputs, "target_sha") == ""
    assert input_default(inputs, "confirmation") == ""


def test_permissions_are_read_only() -> None:
    assert workflow_document()["permissions"] == {"contents": "read"}


def test_pull_request_trigger_covers_gate_test_and_grammar_source() -> None:
    triggers = workflow_document().get("on", workflow_document().get(True))
    paths = triggers["pull_request"]["paths"]
    assert ".github/workflows/b54-calendar-authority-provision-gate.yml" in paths
    assert ".github/tests/test_b54_calendar_authority_provision_gate.py" in paths
    assert "apps/padiem-ai-engine/app/calendar_port_cp_lease.py" in paths


def test_mutation_job_requires_mode_confirmation_and_production_environment() -> None:
    job = provision_job()
    guard = " ".join(str(job["if"]).split())
    assert f"github.event.inputs.mode == '{MUTATION_MODE}'" in guard
    assert f"github.event.inputs.confirmation == '{CONFIRMATION_PHRASE}'" in guard
    assert "github.event_name == 'workflow_dispatch'" in guard
    assert job["environment"] == "production"
    assert job["needs"] == "source-contract"


def test_mutation_job_is_unreachable_from_pull_request_and_push() -> None:
    guard = " ".join(str(provision_job()["if"]).split())
    assert "push" not in guard
    assert "pull_request" not in guard


def test_mutation_job_requires_exact_current_main() -> None:
    text = provision_job_text()
    assert 'expected="${{ github.event.inputs.target_sha }}"' in text
    assert 'test "$(git rev-parse HEAD)" = "${expected}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${expected}"' in text
    assert "fetch-depth: 1" in text
    assert "persist-credentials: false" in text
    assert "PROVISION_EXACT_MAIN_SHA=PASS" in text


def test_secret_source_is_referenced_once() -> None:
    text = provision_job_text()
    assert f"CALENDAR_ALLOWLIST_SOURCE: ${{{{ secrets.{ALLOWLIST_SECRET} }}}}" in text
    assert text.count(f"secrets.{ALLOWLIST_SECRET}") == 1


def test_bound_binding_name_is_canonical() -> None:
    env = workflow_document()["env"]
    assert env["CALENDAR_ALLOWLIST_BINDING"] == ALLOWLIST_BINDING
    assert env["ENGINE_WORKER"] == "padiem-ai-engine"
    assert env["CALENDAR_ALLOWLIST_BINDING_TYPE"] == "secret_text"


def test_allowlist_shape_reuses_the_canonical_engine_grammar() -> None:
    text = provision_job_text()
    assert "from app.calendar_port_cp_lease import parse_calendar_ids" in text
    assert "parse_calendar_ids(raw)" in text
    # No second grammar authority: the charset literal from
    # padiem_ai_core.calendar_capability must not be re-implemented here.
    assert r"[A-Za-z0-9][A-Za-z0-9._%+@\-]{0,511}" not in text
    assert "CALENDAR_ALLOWLIST_NONEMPTY=YES" in text
    assert "CALENDAR_ALLOWLIST_INVALID_ID_REJECT=YES" in text
    assert "CALENDAR_ALLOWLIST_MAX_ENTRIES_BOUND=PASS" in text


@pytest.mark.parametrize(
    "pattern",
    [
        r'echo\s+"?\$\{?CALENDAR_ALLOWLIST_SOURCE',
        r'print\(\s*os\.environ\[\s*"CALENDAR_ALLOWLIST_SOURCE',
        r"\bset -x\b",
        r"ACTIONS_RUNNER_DEBUG",
        r"ACTIONS_STEP_DEBUG",
    ],
)
def test_allowlist_value_is_never_emitted(pattern: str) -> None:
    assert re.search(pattern, workflow_text()) is None


def test_allowlist_source_variable_only_appears_in_reviewed_safe_forms() -> None:
    """Any echo/print of the allowlist source variable would leak the value."""

    offenders = [
        line
        for line in workflow_text().splitlines()
        if "CALENDAR_ALLOWLIST_SOURCE" in line and ("echo" in line or "print(" in line)
    ]
    assert offenders == []


def test_only_bounded_counts_and_flags_are_emitted() -> None:
    text = provision_job_text()
    assert "RAW_CALENDAR_ID_OUTPUT=0" in text
    assert "SECRET_VALUE_OUTPUT=0" in text
    assert "SECRET_VALUES_READBACK=0" in text
    assert "RAW_BINDING_VALUE_OUTPUT=0" in text
    assert "CALENDAR_ALLOWLIST_ENTRY_COUNT_BOUNDED=YES:" in text


@pytest.mark.parametrize(
    "forbidden",
    [
        "googleapis.com",
        "oauth2.googleapis.com",
        "www.googleapis.com/calendar",
        "calendar/v3",
        "events.insert",
        "d1/database",
        "wrangler d1",
        "wrangler deploy",
        "/content",
        "git push",
    ],
)
def test_forbidden_effect_surfaces_are_absent(forbidden: str) -> None:
    assert forbidden not in workflow_text()


def test_no_engine_owned_google_oauth_credential_is_provisioned() -> None:
    text = workflow_text()
    for forbidden in (
        "ENGINE_GOOGLE_OAUTH_CLIENT_ID",
        "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET",
        "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN",
        "calendar.readonly\"",
    ):
        assert forbidden not in text
    assert "CONTROL_PLANE_GOOGLE_OAUTH_LONG_LIVED_CREDENTIAL_OWNER=CONTROL_PLANE" in text
    assert "ENGINE_DIRECT_GOOGLE_CREDENTIAL_PROVISIONED=0" in text
    assert "GOOGLE_OAUTH_MUTATION=0" in text


def test_create_only_precheck_runs_immediately_before_push() -> None:
    text = provision_job_text()
    precheck = text.index("Require create-only Calendar target state immediately before mutation")
    push = text.index("Push the Calendar Engine allowlist secret")
    assert precheck < push
    assert "CALENDAR_PREMUTATION_TARGET_ABSENT=PASS" in text
    assert "CALENDAR_PROVISION_MODE=CREATE_ONLY_REFUSE_EXISTING" in text
    assert 'if state != "ABSENT":' in text
    assert "OVERWRITE_EXISTING=NO" in text


def test_secret_put_requires_cloudflare_success_body() -> None:
    text = provision_job_text()
    guard = """if ! jq -e '.success == true' "${response}" >/dev/null; then"""
    assert guard in text
    guard_index = text.index(guard)
    pass_index = text.index("echo 'CALENDAR_ALLOWLIST_PUT=PASS'", guard_index)
    assert guard_index < pass_index
    assert "CLOUDFLARE_API_SUCCESS=FAIL" in text[guard_index:pass_index]


def test_cloudflare_error_body_is_never_emitted() -> None:
    text = provision_job_text()
    assert "CLOUDFLARE_ERROR_BODY_OUTPUT=0" in text
    assert "errors: [(.errors // [])[] | {code, message}]" not in text


def test_readback_is_name_type_only() -> None:
    text = provision_job_text()
    assert "CALENDAR_ALLOWLIST_SERVED_BINDING=" in text
    assert "CALENDAR_AUTHORITY_SETTINGS_READBACK=PASS" in text
    assert 'hits[0].get("type") != expected_type' in text
    assert "SECRET_VALUES_READBACK=0" in text


def test_scope_truth_is_not_claimed_by_the_provision() -> None:
    text = provision_job_text()
    assert "SECRET_PRESENT != CALENDAR_SCOPE_GRANTED" in text
    assert "CALENDAR_OAUTH_SCOPE_STATUS=UNVERIFIED_WITHOUT_PROVIDER" in text


def test_served_version_check_uses_bounded_convergence_poll() -> None:
    text = provision_job_text()
    assert "for _ in $(seq 1 30)" in text
    assert "sleep 2" in text
    assert "CALENDAR_SERVED_VERSION_CONVERGENCE_MAX_ATTEMPTS=30" in text
    assert "CALENDAR_ACTIVE_VERSION_OWNS_AUTHORITY=PASS" in text


def test_downstream_failure_is_not_reported_as_success() -> None:
    text = provision_job_text()
    marker = "CALENDAR_RUNTIME_AUTHORITY=NOT_PROVISIONED_DOWNSTREAM_VERIFICATION_FAILED"
    assert marker in text
    tail = text.partition(marker)[2]
    assert "CALENDAR_ACTIVE_VERSION_OWNS_AUTHORITY=FAIL" in tail
    assert "exit 1" in tail
    # The rolled-back state must never be reported as a provisioned authority.
    assert "CALENDAR_RUNTIME_AUTHORITY=PROVISIONED_PENDING_VERSION_ACTIVATION" not in text


def test_rollback_runs_only_after_a_confirmed_successful_put() -> None:
    """Confirmed PUT + downstream failure -> rollback; failed PUT -> no DELETE."""

    text = provision_job_text()
    assert "if: ${{ failure() && steps.push.outcome == 'success' }}" in text
    # The failed-push condition must never authorize a rollback DELETE.
    assert "steps.push.outcome == 'failure'" not in text
    assert "ROLLBACK_REQUIRES_CONFIRMED_PUSH_SUCCESS=YES" in text
    assert "ROLLBACK_ON_PUSH_FAILURE=NO" in text
    assert "ROLLBACK_MARKER_REQUIRED=YES" in text
    assert "DOWNSTREAM_FAILURE_CAN_REACH_ROLLBACK=YES" in text


def test_rollback_gate_is_reachable_after_the_push_step() -> None:
    text = provision_job_text()
    rollback = text.index("Roll back a confirmed Calendar allowlist PUT after downstream failure")
    push = text.index("Push the Calendar Engine allowlist secret")
    readback = text.index("Read back Calendar binding NAME/TYPE only")
    # The rollback step follows the push and the downstream verification steps it
    # must be able to react to.
    assert push < readback < rollback
    gate = text[rollback: rollback + 400]
    assert "if: ${{ failure() && steps.push.outcome == 'success' }}" in gate


def test_rollback_is_bounded_to_confirmed_successful_put_only() -> None:
    text = provision_job_text()
    assert "steps.push.outcome == 'success'" in text
    assert 'touch "${RUNNER_TEMP}/calendar-pushed-${CALENDAR_ALLOWLIST_BINDING}"' in text
    assert 'marker="${RUNNER_TEMP}/calendar-pushed-${CALENDAR_ALLOWLIST_BINDING}"' in text
    assert 'if [ ! -f "${marker}" ]; then' in text
    assert "ROLLBACK_REASON=NO_CONFIRMED_SUCCESSFUL_PUT" in text
    assert "ROLLBACK_SCOPE=CONFIRMED_PARTIAL_PUT_ONLY" in text
    assert "VERSION_ACTIVATION=ROLLBACK_TO_PRE_PROVISION_ABSENT_WHEN_VERIFIED" in text
    assert "VERSION_ACTIVATION=SEPARATE_AUTHORITY_IF_CONVERGENCE_EXHAUSTED" not in text
    assert "ROLLBACK_ON_DOWNSTREAM_VERIFICATION_FAILURE=YES" in text


def test_rollback_delete_failure_is_never_swallowed() -> None:
    """A failed DELETE must fail closed instead of being ignored.

    Every assertion here is scoped to the rollback step's own run block so the
    push step's identical success-envelope literal cannot satisfy it.
    """

    text = provision_job_text()
    rollback = rollback_step_run()
    assert "ROLLBACK_DELETE_FAILURE_NOT_IGNORED=YES" in rollback
    assert "ROLLBACK_API_SUCCESS_REQUIRED=YES" in rollback
    assert "ROLLBACK_DELETE_API_SUCCESS=NO" in rollback
    assert "ROLLBACK_DELETE_TRANSPORT_FAILURE=YES" in rollback
    assert "CLOUDFLARE_ERROR_BODY_OUTPUT=0" in rollback
    # The DELETE result must be captured and inspected, never discarded.
    assert "curl_status=$?" in rollback
    delete_line = [
        line for line in rollback.splitlines() if "-X DELETE" in line and "secrets/" in line
    ]
    assert len(delete_line) == 1
    assert "|| true" not in delete_line[0]
    assert "-w '%{http_code}'" in delete_line[0]
    success_check = "if ! jq -e '.success == true' \"${response}\" >/dev/null; then"
    assert success_check in rollback
    # Non-vacuity: the rollback-only markers must not exist in the push step, so
    # a removal of the rollback check cannot be masked by the push step text.
    assert "ROLLBACK_VERIFIED=YES" not in push_step_run()
    assert "PRE_PROVISION_ABSENT_RESTORED=YES" not in push_step_run()
    assert "ROLLBACK_DELETE_API_SUCCESS=YES" not in push_step_run()
    # Ordering inside the rollback region only.
    capture = rollback.index("curl_status=$?")
    check = rollback.index(success_check)
    api_success = rollback.index("ROLLBACK_DELETE_API_SUCCESS=YES")
    assert capture < check < api_success
    assert success_check in text  # still present in the job (push + rollback)
    assert text.count(success_check) == 2


def test_rollback_region_is_independently_verified_in_yaml_terms() -> None:
    """All rollback evidence literals live inside the rollback step itself."""

    rollback = rollback_step_run()
    for marker in (
        "-X DELETE",
        "-w '%{http_code}'",
        "curl_status=$?",
        "if ! jq -e '.success == true' \"${response}\" >/dev/null; then",
        "ROLLBACK_DELETE_API_SUCCESS=YES",
        "ROLLBACK_VERIFIED=YES",
        "PRE_PROVISION_ABSENT_RESTORED=YES",
    ):
        assert marker in rollback, f"missing in rollback region: {marker}"
    # The reverse direction: these rollback outcomes must not leak into the push
    # step, which is what made the old whole-job assertion vacuous.
    push = push_step_run()
    for marker in (
        "ROLLBACK_DELETE_API_SUCCESS=YES",
        "ROLLBACK_VERIFIED=YES",
        "PRE_PROVISION_ABSENT_RESTORED=YES",
        "ROLLBACK_POST_STATE=ABSENT",
        "curl_status=$?",
    ):
        assert marker not in push, f"rollback outcome leaked into push step: {marker}"


def test_rollback_verifies_post_delete_absent_state() -> None:
    rollback = rollback_step_run()
    assert "ROLLBACK_POST_STATE_ABSENT_REQUIRED=YES" in rollback
    assert "ROLLBACK_POST_STATE_MAX_ATTEMPTS=5" in rollback
    assert "ROLLBACK_POST_STATE_SLEEP_SECONDS=2" in rollback
    assert "for _ in $(seq 1 5); do" in rollback
    assert "echo 'ROLLBACK_POST_STATE=PRESENT_OR_UNVERIFIED'" in rollback
    assert "echo 'ROLLBACK_POST_STATE=ABSENT'" in rollback
    # The post-delete read proves NAME-only absence of the Calendar allowlist.
    assert 'name = os.environ["CALENDAR_ALLOWLIST_BINDING"]' in rollback
    assert 'print("ABSENT" if not hits else "PRESENT")' in rollback


def test_marker_is_removed_only_after_verified_absent() -> None:
    rollback = rollback_step_run()
    assert "MARKER_REMOVED_ONLY_AFTER_VERIFIED_ABSENT=YES" in rollback
    post_state_gate = rollback.index('if [ "${post_state}" != "ABSENT" ]; then')
    marker_removal = rollback.index('rm -f "${marker}"')
    verified = rollback.index("echo 'ROLLBACK_VERIFIED=YES'")
    restored = rollback.index("echo 'PRE_PROVISION_ABSENT_RESTORED=YES'")
    # Verified ABSENT gate -> marker removal -> verified/restored claims.
    assert post_state_gate < marker_removal < verified < restored
    # Every unverified path keeps the marker in place.
    assert "MARKER_REMOVED=NO" in rollback
    unverified_branch = rollback.partition(
        "echo 'ROLLBACK_POST_STATE=PRESENT_OR_UNVERIFIED'"
    )[2].partition("\nfi")[0]
    assert "exit 1" in unverified_branch
    assert 'rm -f "${marker}"' not in unverified_branch


def test_rollback_truth_is_not_overclaimed() -> None:
    """PRE_PROVISION_ABSENT_RESTORED may only be claimed after verification."""

    text = provision_job_text()
    rollback = rollback_step_run()
    assert "ROLLBACK_TRUTH_NOT_OVERCLAIMED=YES" in rollback
    assert "ROLLBACK_OUTCOME_VERIFIED_BEFORE_CLAIM=YES" in text
    restored = rollback.index("echo 'PRE_PROVISION_ABSENT_RESTORED=YES'")
    verified = rollback.index("echo 'ROLLBACK_VERIFIED=YES'")
    assert verified < restored
    # The unproven marker must appear on every fail-closed path, and never
    # together with a restored claim in the same branch.
    assert "PRE_PROVISION_ABSENT_RESTORED=UNPROVEN" in text
    unproven_count = text.count("PRE_PROVISION_ABSENT_RESTORED=UNPROVEN")
    assert unproven_count >= 4


def test_locks_are_recorded() -> None:
    text = provision_job_text()
    for marker in (
        "PRODUCTION_MUTATION=SCOPED_CALENDAR_ALLOWLIST_SECRET",
        "SECRET_VALUE_EMITTED=0",
        "SECRET_VALUES_READBACK=0",
        "RAW_CALENDAR_ID_OUTPUT=0",
        "RAW_BINDING_VALUE_OUTPUT=0",
        "ALLOWLIST_PRODUCTION_MUTATION=SCOPED_CALENDAR_ALLOWLIST_ONLY",
        "CALENDAR_PROVIDER_CALLS=0",
        "GOOGLE_PROVIDER_CALLS=0",
        "OAUTH_CONNECT=0",
        "OAUTH_RECONSENT=0",
        "D1_MUTATION=0",
        "CALENDAR_GRANT_SEED=0",
        "ENGINE_CODE_DEPLOY=0",
        "ENGINE_DEPLOY=0",
    ):
        assert marker in text


def test_source_contract_job_runs_this_contract() -> None:
    text = workflow_text()
    assert (
        "python -m pytest -q .github/tests/test_b54_calendar_authority_provision_gate.py"
        in text
    )
    assert "B54_CALENDAR_AUTHORITY_PROVISION_SOURCE_CONTRACT=PASS" in text


def test_provision_bash_blocks_parse() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for workflow shell syntax validation")
    for index, step in enumerate(provision_job()["steps"]):
        script = step.get("run")
        if not isinstance(script, str):
            continue
        shell = str(step.get("shell", "bash"))
        if not shell.startswith("bash"):
            continue
        script_bytes = script.replace("\r\n", "\n").encode("utf-8")
        result = subprocess.run(
            [bash, "-n"],
            input=script_bytes,
            capture_output=True,
            check=False,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert result.returncode == 0, (
            f"provision step {index} shell syntax failed: {stderr}"
        )
