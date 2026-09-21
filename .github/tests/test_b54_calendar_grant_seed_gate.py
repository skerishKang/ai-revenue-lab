"""Static contract tests for the B54 Calendar READ grant seed gate.

These tests never call Cloudflare, Google, or D1. They pin the safety
invariants of the one-shot Calendar seed gate so a future edit cannot silently
widen the mutation scope, invent a trusted Calendar ref in source, leak a ref
or calendar id, or break the cross-step pre-state handoff that decides whether
the canonical INSERT may run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(".github/workflows/b54-calendar-grant-seed-gate.yml")

CONFIRMATION_PHRASE = "RUN_B54_CALENDAR_GRANT_SEED_ONCE"
PRE_STATE_ENV = "CALENDAR_SEED_GATE_PRE_STATE"
APP_ID = "b54-padiem-claw-calendar"
AGENT_ID = "agent:padiem:claw_calendar_reader@1"
CONNECTOR_ID = "connector:google:calendar@1"
BINDING_REF_SECRET = "B54_CALENDAR_BINDING_REF"
ACTOR_REF_SECRET = "B54_CALENDAR_ACTOR_REF"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow_document() -> dict:
    return yaml.safe_load(workflow_text())


def live_job() -> dict:
    jobs = workflow_document()["jobs"]
    assert "live-calendar-seed" in jobs
    return jobs["live-calendar-seed"]


def live_job_text() -> str:
    marker = "  live-calendar-seed:"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "live seed job not found"
    return marker + tail


def test_workflow_parses_and_permissions_are_read_only() -> None:
    document = workflow_document()
    assert document["permissions"] == {"contents": "read"}


def test_pull_request_trigger_covers_gate_contract_and_shared_seed_script() -> None:
    triggers = workflow_document().get("on", workflow_document().get(True))
    paths = triggers["pull_request"]["paths"]
    assert ".github/workflows/b54-calendar-grant-seed-gate.yml" in paths
    assert ".github/tests/test_b54_calendar_grant_seed_gate.py" in paths
    assert "apps/padiem-ai-engine/scripts/connector_grant_seed.py" in paths
    assert "apps/padiem-ai-engine/tests/test_connector_grant_seed_script.py" in paths


def test_live_job_requires_confirmation_and_production_environment() -> None:
    job = live_job()
    guard = " ".join(str(job["if"]).split())
    assert "github.event.inputs.confirmation == " + f"'{CONFIRMATION_PHRASE}'" in guard
    assert "github.event_name == 'workflow_dispatch'" in guard
    assert job["environment"] == "production"
    assert job["needs"] == "source-contract"


def test_live_job_is_unreachable_from_pull_request_and_push() -> None:
    guard = " ".join(str(live_job()["if"]).split())
    assert "push" not in guard
    assert "pull_request" not in guard


def test_live_job_requires_exact_current_main() -> None:
    text = live_job_text()
    assert "${{ github.event.inputs.target_sha }}" in text
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in text
    assert "persist-credentials: false" in text


def test_live_job_installs_seed_script_runtime_dependencies_before_execute() -> None:
    text = live_job_text()
    assert "actions/setup-python@v5" in text
    install = "-e packages/padiem-ai-core"
    assert install in text
    assert text.index(install) < text.index("Execute exactly one")
    assert "CALENDAR_SEED_SCRIPT_DEPS=INSTALLED" in text


def test_trusted_refs_come_only_from_repository_secrets() -> None:
    text = live_job_text()
    assert f"CALENDAR_BINDING_REF_SOURCE: ${{{{ secrets.{BINDING_REF_SECRET} }}}}" in text
    assert f"CALENDAR_ACTOR_REF_SOURCE: ${{{{ secrets.{ACTOR_REF_SECRET} }}}}" in text
    assert text.count(f"secrets.{BINDING_REF_SECRET}") == 1
    assert text.count(f"secrets.{ACTOR_REF_SECRET}") == 1


def test_no_calendar_ref_is_invented_in_source() -> None:
    text = workflow_text()
    # The live job must never carry a literal Calendar binding/actor ref.
    live = live_job_text()
    assert "bind:calendar" not in text
    assert "bind:calendar" not in live
    # No default/synthetic ref declaration exists anywhere in the gate.
    for forbidden in (
        "DEFAULT_BINDING_REF =",
        "DEFAULT_ACTOR_REF =",
        "SYNTHETIC_REF =",
        "DEFAULT_BINDING_REF=",
        "DEFAULT_ACTOR_REF=",
        "SYNTHETIC_REF=",
    ):
        assert forbidden not in text
    # Any ref literal may only appear in the labelled dry-run placeholders of the
    # source-contract job, never in the live mutation job.
    assert "dry-run-binding-ref" not in live
    assert "dry-run-actor-ref" not in live
    assert "dry-run-binding-ref" in text


def test_trusted_refs_are_required_before_any_d1_call() -> None:
    text = live_job_text()
    ref_step = text.index("Require trusted Calendar refs before any D1 call")
    pre_state = text.index("Guard on the pre-seed Calendar grant aggregate")
    assert ref_step < pre_state
    assert "TRUSTED_BINDING_REF_REQUIRED=YES" in text
    assert "TRUSTED_ACTOR_REF_REQUIRED=YES" in text
    assert "MISSING_REF_FAILS_BEFORE_D1=YES" in text
    assert "CALENDAR_TRUSTED_REFS_PRESENT=PASS" in text
    assert "CALENDAR_SYNTHETIC_REF_DEFAULT=NO" in text


@pytest.mark.parametrize(
    "pattern",
    [
        r'echo\s+"?\$\{?CALENDAR_BINDING_REF_SOURCE',
        r'echo\s+"?\$\{?CALENDAR_ACTOR_REF_SOURCE',
        r'print\(\s*os\.environ\[\s*"CALENDAR_BINDING_REF_SOURCE',
        r'print\(\s*os\.environ\[\s*"CALENDAR_ACTOR_REF_SOURCE',
        r"\bset -x\b",
        r"ACTIONS_RUNNER_DEBUG",
        r"ACTIONS_STEP_DEBUG",
    ],
)
def test_ref_values_are_never_emitted(pattern: str) -> None:
    assert re.search(pattern, workflow_text()) is None


def test_ref_source_variables_only_appear_in_reviewed_safe_forms() -> None:
    """Any echo/print of a trusted Calendar ref variable would leak it."""

    offenders = [
        line
        for line in workflow_text().splitlines()
        if any(
            name in line
            for name in ("CALENDAR_BINDING_REF_SOURCE", "CALENDAR_ACTOR_REF_SOURCE")
        )
        and ("echo" in line or "print(" in line)
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "forbidden",
    [
        "googleapis.com",
        "oauth2.googleapis.com",
        "www.googleapis.com/calendar",
        "calendar/v3",
        "events.insert",
        "events.update",
        "events.delete",
        "secret_text",
        "wrangler deploy",
        "wrangler versions",
        "git push",
        "put_secret",
        "VALUES (",
    ],
)
def test_forbidden_effect_surfaces_are_absent(forbidden: str) -> None:
    assert forbidden not in workflow_text()


def test_no_second_insert_authority_in_the_workflow() -> None:
    text = workflow_text()
    # The only INSERT text is the grep assertion over the canonical script's
    # dry-run output; the workflow never composes its own column list.
    assert "INSERT INTO padiem_engine_connector_grants" in text
    assert text.count("INSERT INTO") == text.count('grep -Fq "INSERT INTO')


def test_pre_state_handoff_publishes_to_github_env() -> None:
    text = live_job_text()
    assignment = f'echo "{PRE_STATE_ENV}=${{state}}" >> "${{GITHUB_ENV}}"'
    assert assignment in text
    for line in text.splitlines():
        if f"{PRE_STATE_ENV}=${{state}}" in line:
            assert "GITHUB_ENV" in line


def test_consumer_guard_branches_only_on_exact_provisioned_values() -> None:
    text = live_job_text()
    assert f'if [ "${{{PRE_STATE_ENV}}}" != "ABSENT_ZERO" ]; then' in text


def test_noncanonical_pre_state_refuses_before_execute_step() -> None:
    text = live_job_text()
    refuse = text.index("CALENDAR_PRE_SEED_STATE=NONCANONICAL")
    refuse_tail = text[refuse: text.index("Execute exactly one", refuse)]
    assert "exit 1" in refuse_tail
    assert "CALENDAR_GRANT_SEED=0" in refuse_tail
    assert "D1_MUTATION=0" in refuse_tail
    exec_guard = text.index(f'"${{{PRE_STATE_ENV}}}"')
    assert refuse < exec_guard


def test_already_seeded_pre_state_skips_mutation() -> None:
    text = live_job_text()
    skip = text.index("CALENDAR_PRE_SEED_STATE=EXACT_ACTIVE_READ")
    skip_tail = text[skip: skip + 600]
    assert "CALENDAR_SEED_SKIPPED_ALREADY_SEEDED=YES" in skip_tail
    assert "D1_MUTATION=0" in skip_tail


def test_execute_step_reviews_canonical_read_only_sql_before_d1() -> None:
    text = live_job_text()
    exec_block = text.partition("Execute exactly one")[2]
    assert "--connector calendar" in exec_block
    assert "--capabilities read" in exec_block
    assert "reviewed seed SQL deviates from the canonical Calendar identity" in exec_block
    assert "reviewed seed SQL deviates from the READ-only columns" in exec_block
    assert "misses the canonical upsert" in exec_block
    assert "CALENDAR_SEED_SQL_REVIEWED=PASS" in exec_block
    assert "CALENDAR_SEED_SQL_SCOPE=READ_ONLY" in exec_block


def test_execute_step_requires_cloudflare_success_envelope() -> None:
    text = live_job_text()
    exec_block = text.partition("Execute exactly one")[2]
    assert 'if payload.get("success") is not True:' in exec_block
    assert "Calendar READ grant mutation failed" in exec_block
    assert "Calendar READ grant mutation envelope invalid" in exec_block


def test_post_seed_attestation_requires_exact_active_read() -> None:
    text = live_job_text()
    attest_block = text.partition("Attest the post-seed")[-1]
    assert 'print("CALENDAR_GRANT_STATE=EXACT_ACTIVE_READ")' in attest_block
    assert "CALENDAR_GRANT_STATE=NONCANONICAL" in attest_block
    assert "post-seed Calendar grant state is noncanonical" in attest_block
    assert "CALENDAR_GRANT_ATTESTED=1" in attest_block
    assert "ROW_VALUE_OUTPUT=AGGREGATES_ONLY" in attest_block
    assert "D1_QUERY_MODE=READ_ONLY" in attest_block
    assert "SECRET_PRESENT != CALENDAR_SCOPE_GRANTED" in attest_block
    assert "CALENDAR_OAUTH_SCOPE_STATUS=UNVERIFIED_WITHOUT_PROVIDER" in attest_block


def test_seed_emits_no_raw_refs_or_calendar_ids() -> None:
    text = live_job_text()
    for marker in (
        "RAW_BINDING_REF_OUTPUT=0",
        "RAW_ACTOR_REF_OUTPUT=0",
        "RAW_CALENDAR_ID_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "ROW_VALUE_OUTPUT=AGGREGATES_ONLY",
    ):
        assert marker in text


def test_calendar_write_surfaces_stay_locked() -> None:
    text = live_job_text()
    for marker in (
        "CALENDAR_CREATE=0",
        "CALENDAR_UPDATE=0",
        "CALENDAR_DELETE=0",
        "CALENDAR_RESPOND=0",
        "CALENDAR_WRITE=0",
        "GOOGLE_OAUTH_MUTATION=0",
        "SECRET_MUTATION=0",
        "ENGINE_DEPLOY=0",
    ):
        assert marker in text


def test_derived_identifiers_are_masked() -> None:
    text = live_job_text()
    assert "::add-mask::" in text
    assert "D1_IDENTIFIER_OUTPUT=0" in text
    assert "ENGINE_VERSION_ID_OUTPUT=0" in text


def test_source_contract_proves_the_canonical_read_only_sql_without_executing() -> None:
    text = workflow_text()
    assert "CALENDAR_SEED_SQL_CONTRACT=PASS" in text
    assert "CALENDAR_SEED_SQL_SCOPE=READ_ONLY" in text
    assert "CALENDAR_GRANT_SEED_EXECUTED=0" in text
    assert "D1_MUTATION=0" in text


def test_source_contract_job_runs_this_contract() -> None:
    text = workflow_text()
    assert (
        "python -m pytest -q .github/tests/test_b54_calendar_grant_seed_gate.py"
        in text
    )
    assert "B54_CALENDAR_GRANT_SEED_GATE_SOURCE_CONTRACT=PASS" in text


def test_live_seed_bash_blocks_parse() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for workflow shell syntax validation")
    for index, step in enumerate(live_job()["steps"]):
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
            f"live seed step {index} shell syntax failed: {stderr}"
        )
