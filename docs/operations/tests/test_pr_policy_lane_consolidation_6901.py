"""#6901: the PR policy lane is one trusted chain, not three parallel workflows.

Before this change a pull request started three lanes at once: an echo-only
``com2-pr-policy-trigger.yml``, ``com2-pr-auto-sandbox.yml`` via ``workflow_run``,
and ``operations-policy-guard.yml``. The echo lane's ``COM2 policy dispatch``
check was always green because it only printed a marker, the guard's blocking
suite was skipped for same-repository PRs, and the sandbox owned the actual
verdict. Nothing in that trio told the reader which lane produced the required
result.

These assertions pin the replacement wiring so a later edit cannot silently:

1. reintroduce an echo-only PR lane whose green check reads like a policy pass;
2. break the ``workflow_run`` source of the required ``COM2 full policy`` context,
   or let another workflow mark it pending;
3. drop a policy suite target that one of the two remaining lanes used to run.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
SANDBOX = WORKFLOWS / "com2-pr-auto-sandbox.yml"
GUARD = WORKFLOWS / "operations-policy-guard.yml"
HOSTED_BACKUP = WORKFLOWS / "operations-policy-guard-hosted-backup.yml"
REQUIRED_CONTEXT = '"context":"COM2 full policy"'
PENDING_REQUIRED_CONTEXT = '"state":"pending","context":"COM2 full policy"'

# Every suite target the guard ran before the consolidation must still run in one
# of the two remaining lanes; the sandbox is the same-repository executor.
SUITE_TARGETS = (
    "docs/operations/tests",
    ".github/tests/test_3989_engine_living_learning_ci_scope.py",
    ".github/tests/test_pr_contract_guard.py",
    ".github/tests/test_r2_credential_authority_split.py",
    ".github/tests/test_b62_pr_preview_trigger_scope.py",
    ".github/tests/test_b62_worker_deploy_trigger_scope.py",
    ".github/tests/test_cross_lane_test_dependency_guard.py",
    ".github/tests/test_frozen_source_checkout_byte_guard.py",
    ".github/tests/test_verify_import_origin.py",
    "tools/b66_generic/tests/test_b66_generic_archive_bounds.py",
    ".github/tests/test_3989_operations_guard_pytest_batch.py",
)
SUITE_SCRIPTS = (
    ".github/scripts/cross_lane_test_dependency_guard.py",
    ".github/scripts/frozen_source_checkout_byte_guard.py",
)


def _text(path: Path) -> str:
    assert path.is_file(), path
    return path.read_text(encoding="utf-8")


def test_no_echo_only_pr_lane_remains() -> None:
    assert not (WORKFLOWS / "com2-pr-policy-trigger.yml").exists()
    for workflow in WORKFLOWS.glob("*.yml"):
        text = _text(workflow)
        assert "COM2_PR_TRIGGER=READY" not in text, workflow.name
        assert "name: COM2 PR Policy Trigger" not in text, workflow.name


def test_sandbox_consumes_the_guard_run_and_still_resolves_the_exact_head() -> None:
    sandbox = _text(SANDBOX)
    assert 'workflows: ["Operations Policy Guard"]' in sandbox
    assert "types: [completed]" in sandbox
    for condition in (
        "github.event.workflow_run.event == 'pull_request'",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.pull_requests[0].number != null",
    ):
        assert condition in sandbox, condition
    # The event is only a hint: the still-open exact PR head is re-resolved.
    assert '[[ "$data" == "$EXPECTED open $GITHUB_REPOSITORY" ]]' in sandbox
    assert 'test "$(git -C "$src" rev-parse HEAD)" = "${{ steps.target.outputs.sha }}"' in sandbox


def test_required_context_stays_with_the_sandbox_and_the_documented_backup() -> None:
    sandbox = _text(SANDBOX)
    assert PENDING_REQUIRED_CONTEXT in sandbox
    assert "export STATE=failure" in sandbox
    others = sorted(
        workflow.name
        for workflow in WORKFLOWS.glob("*.yml")
        if workflow.name != SANDBOX.name and PENDING_REQUIRED_CONTEXT in _text(workflow)
    )
    assert others == [], f"another workflow marks the required context: {others}"
    assert REQUIRED_CONTEXT in _text(HOSTED_BACKUP)


def test_guard_keeps_its_report_job_and_its_fork_only_suite() -> None:
    guard = _text(GUARD)
    assert "  policy-consistency:" in guard
    assert "  pr-contract:" in guard
    assert "name: Operating policy consistency" in guard
    assert "name: Pull request contract report" in guard
    assert "run: python .github/scripts/pr_contract_guard.py" in guard
    # The same-repository skip is deliberate: the sandbox owns that verdict.
    assert (
        "github.event_name == 'workflow_dispatch' || "
        "github.event.pull_request.head.repo.full_name != github.repository"
    ) in guard


def test_no_policy_suite_target_or_script_was_lost() -> None:
    guard, sandbox = _text(GUARD), _text(SANDBOX)
    for target in SUITE_TARGETS:
        assert target in guard, f"guard lost {target}"
        assert target in sandbox, f"sandbox lost {target}"
    for script in SUITE_SCRIPTS:
        assert guard.count("run: python " + script) == 1, script
        assert script in sandbox, script
