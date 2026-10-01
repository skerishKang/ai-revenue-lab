#!/usr/bin/env python3
"""Static contract tests for the Vercel parser source-only live gate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-vercel-parser-live-probe-gate.yml"
MODULE = ROOT / "apps/korean-ai-code-agent/src/kagent/vercel_parser_live_gate.py"
TEST = ROOT / "apps/korean-ai-code-agent/tests/test_vercel_parser_live_gate.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_pull_request_is_source_only_and_push_is_absent() -> None:
    workflow = text(WORKFLOW)
    trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "pull_request:" in trigger
    assert "push:" not in trigger
    source = workflow.split("\n  source-contract:\n", 1)[1].split("\n  future-live-probe:\n", 1)[0]
    assert "test_vercel_parser_live_gate.py" in source
    assert "PROVIDER_CALLS=0" in source
    assert "SANDBOX_ALLOCATIONS=0" in source


def test_future_live_job_is_dispatch_only_and_inert() -> None:
    workflow = text(WORKFLOW)
    live = workflow.split("\n  future-live-probe:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in live
    assert "LIVE_PROVIDER_CALL=BLOCKED_NOT_IMPLEMENTED" in live
    assert "VERCEL_SANDBOX_CREATE=0" in live
    assert "PARSER_PROCESS_START=0" in live
    assert "gh workflow run" not in workflow
    assert "vercel " not in workflow.lower()


def test_exact_main_confirmation_parser_deadline_and_ttl_guards_exist() -> None:
    workflow = text(WORKFLOW)
    for marker in (
        "EXACT_MAIN_GUARD=PASS",
        "CENTRAL_CONFIRMATION=PASS",
        "PARSER_HARD_DEADLINE_GUARD=PASS",
        "SANDBOX_TTL_GUARD=PASS",
        "CENTRAL_VERCEL_PARSER_LIVE_PROBE=YES",
        "git rev-parse origin/main",
        'test "${PARSER_DEADLINE_SECONDS}" -eq 30',
        'test "${SANDBOX_TTL_SECONDS}" -le 300',
    ):
        assert marker in workflow, marker


def test_module_reuses_existing_authorities_and_has_no_provider_transport() -> None:
    module = text(MODULE)
    for marker in (
        "SandboxProviderCandidate.VERCEL_SANDBOX",
        "build_candidate_launch_profile",
        "build_live_probe_plan",
        "padiem_ai_core.isolated_parser_client",
        "single_fresh_nonpersistent_sandbox",
        "PARSER_HARD_DEADLINE_SECONDS = 30",
    ):
        assert marker in module, marker

    forbidden = (
        "requests.get",
        "requests.post",
        "httpx.",
        "urllib",
        "subprocess",
        "os.environ",
        "credential_value",
        "api_token",
        "raw_provider_payload",
    )
    for token in forbidden:
        assert token not in module, token


def test_runtime_evidence_remains_required_and_unproven() -> None:
    module = text(MODULE)
    for token in (
        "metadata_negative_test_required",
        "process_tree_death_required",
        "non_resurrection_required",
        "resource_limits_required",
        "live_dispatch_allowed",
    ):
        assert token in module, token
    assert "VERCEL_PARSER_LIVE_DISPATCH_TRIGGERED = False" in module


def test_workflow_has_no_secret_or_production_authority() -> None:
    workflow = text(WORKFLOW)
    assert "secrets." not in workflow
    assert "CREDENTIAL_BINDING=0" in workflow
    assert "PRODUCTION_BINDING=0" in workflow
    assert "contents: write" not in workflow
    assert "actions: write" not in workflow


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"{len(tests)} static Vercel parser gate tests passed")
