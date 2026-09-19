"""Static contract tests for the B54 Telegram authority provision gate.

These tests never call Cloudflare, Telegram, or D1. They pin the safety
invariants of the provision gate so a future edit cannot silently widen the
mutation scope, leak a secret value into logs, or drop the exact-main and
single-use confirmation guards.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(".github/workflows/b54-telegram-authority-provision-gate.yml")

CONFIRMATION_PHRASE = "CONFIRM_PROVISION_TELEGRAM_AUTHORITY"
TOKEN_BINDING = "ENGINE_TELEGRAM_BOT_TOKEN"
PAIRED_CHAT_BINDING = "ENGINE_TELEGRAM_PAIRED_CHAT_IDS"
TOKEN_SECRET = "B54_TELEGRAM_BOT_TOKEN"
PAIRED_CHAT_SECRET = "B54_TELEGRAM_PAIRED_CHAT_IDS"


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


def test_workflow_parses_and_default_dispatch_is_preflight() -> None:
    document = workflow_document()
    # PyYAML resolves the bare ``on`` key to boolean True (YAML 1.1).
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert input_default(inputs, "mode") == "repository_preflight"
    assert input_default(inputs, "target_sha") == ""
    assert input_default(inputs, "confirmation") == ""


def test_permissions_are_read_only() -> None:
    assert workflow_document()["permissions"] == {"contents": "read"}


def test_mutation_job_requires_mode_confirmation_and_production_environment() -> None:
    job = provision_job()
    guard = job["if"]
    assert "github.event.inputs.mode == 'provision_telegram_authority'" in guard
    assert f"github.event.inputs.confirmation == '{CONFIRMATION_PHRASE}'" in guard
    assert job["environment"] == "production"


def test_mutation_job_requires_exact_current_main() -> None:
    text = provision_job_text()
    assert 'expected="${{ github.event.inputs.target_sha }}"' in text
    assert 'test "$(git rev-parse HEAD)" = "${expected}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${expected}"' in text
    assert "fetch-depth: 1" in text
    assert "persist-credentials: false" in text


def test_secret_sources_are_referenced_once_each() -> None:
    text = provision_job_text()
    assert f"TELEGRAM_BOT_TOKEN_SOURCE: ${{{{ secrets.{TOKEN_SECRET} }}}}" in text
    assert (
        f"TELEGRAM_PAIRED_CHAT_IDS_SOURCE: ${{{{ secrets.{PAIRED_CHAT_SECRET} }}}}"
        in text
    )
    assert text.count(f"secrets.{TOKEN_SECRET}") == 1
    assert text.count(f"secrets.{PAIRED_CHAT_SECRET}") == 1


def test_bound_binding_names_are_canonical() -> None:
    env = workflow_document()["env"]
    assert env["TELEGRAM_BOT_TOKEN_BINDING"] == TOKEN_BINDING
    assert env["TELEGRAM_PAIRED_CHAT_BINDING"] == PAIRED_CHAT_BINDING
    assert env["ENGINE_WORKER"] == "padiem-ai-engine"


@pytest.mark.parametrize(
    "pattern",
    [
        r'echo\s+"?\$\{?TELEGRAM_BOT_TOKEN_SOURCE',
        r'echo\s+"?\$\{?TELEGRAM_PAIRED_CHAT_IDS_SOURCE',
        r'print\(\s*os\.environ\[\s*"TELEGRAM_BOT_TOKEN_SOURCE',
        r'print\(\s*os\.environ\[\s*"TELEGRAM_PAIRED_CHAT_IDS_SOURCE',
        r"\bset -x\b",
        r"ACTIONS_RUNNER_DEBUG",
        r"ACTIONS_STEP_DEBUG",
    ],
)
def test_secret_values_are_never_emitted(pattern: str) -> None:
    assert re.search(pattern, workflow_text()) is None


@pytest.mark.parametrize(
    "forbidden",
    [
        "api.telegram.org",
        "sendMessage",
        "editMessageText",
        "answerCallbackQuery",
        "setWebhook",
        "d1/database",
        "wrangler d1",
        "git push",
    ],
)
def test_forbidden_effect_surfaces_are_absent(forbidden: str) -> None:
    assert forbidden not in workflow_text()


def test_no_worker_code_deploy_surface() -> None:
    text = workflow_text()
    assert "/content" not in text
    assert not re.search(r"-X\s+POST[^\n]*deployments", text)


def test_secret_push_removes_payload_files() -> None:
    text = provision_job_text()
    assert 'rm -f "${payload}"' in text
    assert 'rm -f "${token_payload}"' in text
    assert 'rm -f "${allowlist_payload}"' in text


def test_readback_is_name_type_only() -> None:
    text = provision_job_text()
    assert "TELEGRAM_BOT_TOKEN_SERVED_BINDING=" in text
    assert "TELEGRAM_PAIRED_CHAT_ALLOWLIST_SERVED_BINDING=" in text
    assert "TELEGRAM_ACTIVE_VERSION_OWNS_AUTHORITY=" in text
    assert 'if hits[0].get("type") != "secret_text":' in text
    assert "SECRET_VALUES_READBACK=0" in text


def test_source_shape_gate_matches_engine_runtime_contract() -> None:
    text = provision_job_text()
    assert r'[0-9]{6,64}:[A-Za-z0-9_-]{20,128}' in text
    assert 'chat_id == 0 or not -(2**63) < chat_id < 2**63' in text
    assert 'TELEGRAM_PAIRED_CHAT_ID_DUPLICATE=FAIL' in text


def test_create_path_refuses_preexisting_target_bindings_before_put() -> None:
    text = provision_job_text()
    precheck = text.index("Require create-only Telegram target state immediately before mutation")
    push = text.index("Push the two Telegram Engine secrets")
    assert precheck < push
    assert 'TELEGRAM_PREMUTATION_TARGETS_ABSENT=PASS' in text
    assert 'TELEGRAM_PROVISION_MODE=CREATE_ONLY_REFUSE_EXISTING' in text
    assert 'token != "ABSENT" or allowlist != "ABSENT"' in text


def test_secret_put_requires_cloudflare_success_body() -> None:
    text = provision_job_text()
    guard = """if ! jq -e '.success == true' "${response}" >/dev/null; then"""
    assert guard in text
    guard_index = text.index(guard)
    pass_index = text.index('echo "${binding_name}_PUT=PASS"', guard_index)
    assert guard_index < pass_index
    assert "CLOUDFLARE_API_SUCCESS=FAIL" in text[guard_index:pass_index]
    assert "return 1" in text[guard_index:pass_index]


def test_cloudflare_error_body_is_never_emitted() -> None:
    text = provision_job_text()
    assert "CLOUDFLARE_ERROR_BODY_OUTPUT=0" in text
    assert "errors: [(.errors // [])[] | {code, message}]" not in text


def test_served_version_check_uses_bounded_convergence_poll() -> None:
    text = provision_job_text()
    assert "for _ in $(seq 1 30)" in text
    assert "sleep 2" in text
    assert "TELEGRAM_SERVED_VERSION_CONVERGENCE_MAX_ATTEMPTS=30" in text
    assert "TELEGRAM_ACTIVE_VERSION_OWNS_AUTHORITY=PASS" in text


def test_pending_version_activation_is_not_reported_as_success() -> None:
    text = provision_job_text()
    pending = "TELEGRAM_RUNTIME_AUTHORITY=PROVISIONED_PENDING_VERSION_ACTIVATION"
    assert pending in text
    tail = text.partition(pending)[2]
    assert "TELEGRAM_ACTIVE_VERSION_OWNS_AUTHORITY=FAIL" in tail
    assert "exit 1" in tail


def test_rollback_is_bounded_to_confirmed_successful_puts_only() -> None:
    text = provision_job_text()
    assert "steps.push.outcome == 'failure'" in text
    assert 'touch "${RUNNER_TEMP}/telegram-pushed-${binding_name}"' in text
    assert 'marker="${RUNNER_TEMP}/telegram-pushed-${name}"' in text
    assert 'if [ -f "${marker}" ]; then' in text
    assert "ROLLBACK_REASON=NO_CONFIRMED_SUCCESSFUL_PUT" in text
    assert "ROLLBACK_SCOPE=CONFIRMED_PARTIAL_PUT_ONLY" in text
    assert "telegram-rollback-settings.json" not in text
    assert "base}/secrets/${name}" in text
    assert "VERSION_ACTIVATION=SEPARATE_AUTHORITY_IF_CONVERGENCE_EXHAUSTED" in text


def test_locks_are_recorded() -> None:
    text = provision_job_text()
    for marker in (
        "PRODUCTION_MUTATION=SCOPED_TELEGRAM_AUTHORITY_SECRETS",
        "SECRET_VALUE_EMITTED=0",
        "RAW_BOT_TOKEN_OUTPUT=0",
        "RAW_CHAT_ID_OUTPUT=0",
        "RAW_BINDING_VALUE_OUTPUT=0",
        "TELEGRAM_PROVIDER_CALLS=0",
        "TELEGRAM_SEND=0",
        "TELEGRAM_EDIT=0",
        "TELEGRAM_CALLBACK_WRITE=0",
        "WEBHOOK_MUTATION=0",
        "D1_MUTATION=0",
        "ENGINE_CODE_DEPLOY=0",
        "ENGINE_DEPLOY=0",
    ):
        assert marker in text


def test_source_contract_job_runs_this_contract() -> None:
    text = workflow_text()
    assert (
        "python -m pytest -q .github/tests/test_b54_telegram_authority_provision_gate.py"
        in text
    )
    assert "B54_TELEGRAM_AUTHORITY_PROVISION_SOURCE_CONTRACT=PASS" in text