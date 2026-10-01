#!/usr/bin/env python3
"""Static contracts for the owner-gated #3283 Vercel parser runtime probe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-vercel-parser-live-probe-gate.yml"
GATE = ROOT / "apps/korean-ai-code-agent/src/kagent/vercel_parser_live_gate.py"
RUNTIME = ROOT / "apps/korean-ai-code-agent/src/kagent/vercel_parser_probe_runtime.py"
RUNTIME_TEST = ROOT / "apps/korean-ai-code-agent/tests/test_vercel_parser_probe_runtime.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_pull_request_path_is_source_only_and_push_is_absent() -> None:
    workflow = text(WORKFLOW)
    trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "pull_request:" in trigger
    assert "workflow_dispatch:" in trigger
    assert "push:" not in trigger

    source = workflow.split("\n  source-contract:\n", 1)[1].split("\n  live-probe:\n", 1)[0]
    assert "test_vercel_parser_probe_runtime.py" in source
    assert "PROVIDER_CALLS=0" in source
    assert "SANDBOX_ALLOCATIONS=0" in source
    assert "CREDENTIAL_VALUE_READS=0" in source
    assert "CREDENTIAL_MUTATIONS=0" in source
    assert "secrets." not in source
    assert "vercel-sandbox==0.7.0" not in source


def test_live_job_requires_dispatch_exact_owner_comment_and_nonproduction_only() -> None:
    workflow = text(WORKFLOW)
    live = workflow.split("\n  live-probe:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in live
    for marker in (
        "OWNER_VERCEL_PARSER_LIVE_PROBE_APPROVED=YES",
        "AUTHORIZED_SHA=${TARGET_SHA}",
        "TARGET_ENVIRONMENT=non_production",
        "MAX_SANDBOX_ALLOCATIONS=1",
        "MAX_LOGICAL_PROVIDER_OPERATIONS=12",
        "PRODUCTION_BINDING=NO",
        "P4=NO",
        "/issues/3283",
        "GITHUB_REPOSITORY_OWNER",
    ):
        assert marker in live, marker
    assert "git rev-parse origin/main" in live
    assert "gh workflow run" not in workflow


def test_live_credentials_exist_only_after_owner_gate_and_are_never_echoed() -> None:
    workflow = text(WORKFLOW)
    live = workflow.split("\n  live-probe:\n", 1)[1]
    owner_gate = live.index("Validate exact repository-owner approval")
    credential_step = live.index("Require host-side Vercel bindings")
    probe_step = live.index("Run exactly one non-Production Vercel parser runtime probe")
    assert owner_gate < credential_step < probe_step
    for name in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
        assert f"secrets.{name}" in live
    assert "echo \"$VERCEL" not in live
    assert "VERCEL_GUEST_CREDENTIAL_INJECTION=0" in live
    assert "contents: write" not in workflow
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow


def test_runtime_reuses_canonical_parser_and_cloud_m1_resource_authority() -> None:
    runtime = text(RUNTIME)
    gate = text(GATE)
    for marker in (
        "padiem_ai_core.isolated_parser_client",
        "IsolatedParserClient",
        "SandboxSecurityPolicy",
        "SandboxAppliedLimits",
        "SandboxSecurityPolicy().require_within_bounds",
        "PARSER_HARD_DEADLINE_SECONDS",
        "VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS = 12",
    ):
        assert marker in runtime, marker
    assert "build_candidate_launch_profile" in gate
    assert "SandboxProviderCandidate.VERCEL_SANDBOX" in gate


def test_runtime_request_shape_is_fresh_deny_all_nonpersistent_and_guest_secret_free() -> None:
    runtime = text(RUNTIME)
    for marker in (
        "NetworkPolicy.deny_all()",
        "persistent=False",
        "ports=[]",
        "env=None",
        "VERCEL_PROBE_VCPUS = 1",
        "VERCEL_PROBE_MEMORY_MB = 2048",
        "execution_time_limit=ttl_seconds",
        "SyncSandboxClient",
        'SandboxServiceOptions(region="iad1")',
    ):
        assert marker in runtime, marker


def test_runtime_measures_both_process_tree_death_paths_and_terminal_absence() -> None:
    runtime = text(RUNTIME)
    for marker in (
        "kill_after=authorization.parser_deadline_seconds",
        "_process_absent(sandbox, timeout_token",
        "_kill_bounded(cancellation_process",
        "_process_absent(",
        "sandbox.stop()",
        "sandbox.destroy()",
        "_provider_absent_after_destroy",
    ):
        assert marker in runtime, marker
    assert '"FALLBACK_CANDIDATE": None if self.accepted else "E2B"' in runtime


def test_runtime_output_is_bounded_and_excludes_raw_sensitive_material() -> None:
    runtime = text(RUNTIME)
    for marker in (
        '"RAW_PROVIDER_PAYLOAD_OUTPUT": self.raw_provider_payload_output',
        '"RAW_DOCUMENT_OUTPUT": self.raw_document_output',
        '"PROVIDER_CREDENTIAL_OUTPUT": self.provider_credential_output',
        'print(f"FAILURE_CLASS={type(exc).__name__}")',
    ):
        assert marker in runtime, marker
    assert "print(str(exc))" not in runtime
    assert "traceback.print" not in runtime
    assert "os.environ" not in runtime
    assert "credential_value" not in runtime.split("class VercelPythonSdkProbeProvider", 1)[1]


def test_source_runtime_does_not_execute_on_import_or_bind_production() -> None:
    runtime = text(RUNTIME)
    for marker in (
        '"provider_calls_at_import": 0',
        '"sandbox_allocations_at_import": 0',
        '"production_binding": False',
        '"production_ready_claim": False',
    ):
        assert marker in runtime, marker
    assert "execute_authorized_vercel_parser_probe(" in runtime
    assert "if __name__ == \"__main__\":" in runtime
    assert RUNTIME_TEST.exists()


def test_workflow_preserves_exact_main_deadline_ttl_and_no_production_deploy() -> None:
    workflow = text(WORKFLOW)
    for marker in (
        "EXACT_MAIN_GUARD=PASS",
        "CENTRAL_CONFIRMATION=PASS",
        'test "${PARSER_DEADLINE_SECONDS}" -eq 30',
        'test "${SANDBOX_TTL_SECONDS}" -le 300',
        "B14_PRODUCTION_DEPLOY=NO",
        "B66_PRODUCTION_DEPLOY=NO",
        "P4=NO",
    ):
        assert marker in workflow, marker


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"{len(tests)} static Vercel parser probe tests passed")
