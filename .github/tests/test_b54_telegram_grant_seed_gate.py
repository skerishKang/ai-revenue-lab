"""Static contract tests for the B54 Telegram READ grant seed gate.

These tests never call Cloudflare, Telegram, or D1. They pin the safety
invariants of the one-shot seed gate so a future edit cannot silently widen
the mutation scope, leak refs, or break the cross-step pre-state handoff that
must decide whether the canonical INSERT may run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(".github/workflows/b54-telegram-grant-seed-gate.yml")

CONFIRMATION_PHRASE = "RUN_B54_TELEGRAM_GRANT_SEED_ONCE"
PRE_STATE_ENV = "TELEGRAM_SEED_GATE_PRE_STATE"
APP_ID = "b54-padiem-claw-telegram"
AGENT_ID = "agent:padiem:claw_telegram_reader@1"
CONNECTOR_ID = "connector:telegram:bot@1"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow_document() -> dict:
    return yaml.safe_load(workflow_text())


def live_job() -> dict:
    jobs = workflow_document()["jobs"]
    assert "live-telegram-seed" in jobs
    return jobs["live-telegram-seed"]


def live_job_text() -> str:
    marker = "  live-telegram-seed:"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "live seed job not found"
    return marker + tail


def test_workflow_parses_and_permissions_are_read_only() -> None:
    document = workflow_document()
    assert document["permissions"] == {"contents": "read"}


def test_pull_request_trigger_covers_gate_and_contract_tests() -> None:
    document = workflow_document()
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict)
    paths = triggers["pull_request"]["paths"]
    assert ".github/workflows/b54-telegram-grant-seed-gate.yml" in paths
    assert ".github/tests/test_b54_telegram_grant_seed_gate.py" in paths


def test_live_job_requires_confirmation_and_production_environment() -> None:
    job = live_job()
    guard = " ".join(str(job["if"]).split())
    assert "github.event.inputs.confirmation == " + f"'{CONFIRMATION_PHRASE}'" in guard
    assert job["environment"] == "production"
    assert job["needs"] == "source-contract"


def test_live_job_requires_exact_current_main() -> None:
    text = live_job_text()
    assert "${{ github.event.inputs.target_sha }}" in text
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in text
    assert "persist-credentials: false" in text


def test_pre_state_handoff_publishes_to_github_env() -> None:
    text = live_job_text()
    assignment = f'echo "{PRE_STATE_ENV}=${{state}}" >> "${{GITHUB_ENV}}"'
    assert assignment in text
    for line in text.splitlines():
        if f"{PRE_STATE_ENV}=${{state}}" in line:
            assert "GITHUB_ENV" in line, (
                f"{PRE_STATE_ENV} is emitted as a log echo without $GITHUB_ENV "
                "handoff; the consumer step runs under `set -u` in a fresh shell "
                "and dies with an unbound variable before any seed decision"
            )


def test_consumer_guard_branches_only_on_exact_provisioned_values() -> None:
    text = live_job_text()
    assert f'if [ "${{{PRE_STATE_ENV}}}" != "ABSENT_ZERO" ]; then' in text


def test_noncanonical_pre_state_refuses_before_execute_step() -> None:
    text = live_job_text()
    refuse = text.index("TELEGRAM_PRE_SEED_STATE=NONCANONICAL")
    refuse_tail = text[refuse: text.index("Execute exactly one", refuse)]
    assert "exit 1" in refuse_tail
    assert "TELEGRAM_GRANT_SEED=0" in refuse_tail
    assert "D1_MUTATION=0" in refuse_tail
    exec_guard = text.index(f'"${{{PRE_STATE_ENV}}}"')
    assert refuse < exec_guard


def test_already_seeded_pre_state_skips_mutation() -> None:
    text = live_job_text()
    skip = text.index("TELEGRAM_PRE_SEED_STATE=EXACT_ACTIVE_READ")
    skip_tail = text[skip: skip + 600]
    assert "TELEGRAM_SEED_SKIPPED_ALREADY_SEEDED=YES" in skip_tail


def test_execute_step_reviews_canonical_read_only_sql_before_d1() -> None:
    text = live_job_text()
    exec_block = text.partition("Execute exactly one")[2]
    assert f"'{APP_ID}'" in exec_block or "TELEGRAM_APP_ID" in exec_block
    assert "reviewed seed SQL deviates from the canonical Telegram identity" in exec_block
    assert "reviewed seed SQL deviates from the READ-only columns" in exec_block
    assert "misses the canonical upsert" in exec_block
    assert 'ON CONFLICT(app_id, connector_id) DO UPDATE SET active=1' in exec_block
    assert "TELEGRAM_SEED_SQL_REVIEWED=PASS" in exec_block


def test_execute_step_requires_cloudflare_success_envelope() -> None:
    text = live_job_text()
    exec_block = text.partition("Execute exactly one")[2]
    assert 'if payload.get("success") is not True:' in exec_block
    assert "Telegram READ grant mutation failed" in exec_block
    assert "Telegram READ grant mutation envelope invalid" in exec_block


def test_post_seed_attestation_requires_exact_active_read() -> None:
    text = live_job_text()
    attest_block = text.partition("Attest the post-seed")[-1]
    assert 'print("TELEGRAM_GRANT_STATE=EXACT_ACTIVE_READ")' in attest_block
    assert "TELEGRAM_GRANT_STATE=NONCANONICAL" in attest_block
    assert "post-seed Telegram grant state is noncanonical" in attest_block
    assert "TELEGRAM_GRANT_ATTESTED=1" in attest_block
    assert "ROW_VALUE_OUTPUT=AGGREGATES_ONLY" in attest_block
    assert "D1_QUERY_MODE=READ_ONLY" in attest_block


def test_derived_identifiers_are_masked() -> None:
    text = live_job_text()
    assert "::add-mask::" in text
    assert "D1_IDENTIFIER_OUTPUT=0" in text
    assert "ENGINE_VERSION_ID_OUTPUT=0" in text or "RAW_ENGINE_VERSION" in text


@pytest.mark.parametrize(
    "pattern",
    [
        r"\bset -x\b",
        r"ACTIONS_RUNNER_DEBUG",
        r"ACTIONS_STEP_DEBUG",
        r"secrets\.B54_TELEGRAM",
        r"print\(\s*f?[\"']TELEGRAM_SEED_GATE_PRE_STATE\",?\s*state",
    ],
)
def test_no_debug_or_secret_surface(pattern: str) -> None:
    assert re.search(pattern, workflow_text()) is None


@pytest.mark.parametrize(
    "forbidden",
    [
        "api.telegram.org",
        "sendMessage",
        "editMessageText",
        "answerCallbackQuery",
        "setWebhook",
        "secret_text",
        "wrangler deploy",
        "wrangler versions",
        "-X POST \"${auth[@]}\" \"${base}/deployments\"",
        "/content",
        "git push",
        "put_secret",
        "secret_text",
    ],
)
def test_forbidden_effect_surfaces_are_absent(forbidden: str) -> None:
    assert forbidden not in workflow_text()


def test_seed_emits_no_raw_refs() -> None:
    text = live_job_text()
    assert "RAW_BINDING_REF_OUTPUT=0" in text
    assert "RAW_ACTOR_REF_OUTPUT=0" in text


def test_source_contract_job_runs_this_contract() -> None:
    text = workflow_text()
    assert (
        "python -m pytest -q .github/tests/test_b54_telegram_grant_seed_gate.py"
        in text
    )
    assert "B54_TELEGRAM_GRANT_SEED_GATE_SOURCE_CONTRACT=PASS" in text


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
