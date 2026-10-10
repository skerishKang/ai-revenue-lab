from __future__ import annotations

from copy import deepcopy
import json
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"


def test_b62_browser_qa_does_not_fan_out_for_tests_or_worker_entrypoint_only() -> None:
    """Browser QA should follow browser/runtime surfaces, not every Chat file.

    The B62 browser workflows run the ASGI app via uvicorn, not the Cloudflare
    Worker entrypoint. Test-file-only changes also cannot affect the rendered
    product. If a browser workflow keeps the broad apps/padiem-chat/** trigger,
    it must explicitly exclude those two non-browser surfaces.
    """

    manifest_path = REPO / ".github" / "ci" / "b62_browser_qa_paths.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["jobs"]
    assert len(manifest) == 16
    unified = (WORKFLOWS / "b62-browser-qa-unified.yml").read_text(encoding="utf-8")
    assert not list(WORKFLOWS.glob("b62-*-browser-qa.yml"))
    for job, paths in manifest.items():
        assert f"  {job}:" in unified, job
        assert isinstance(paths, list), job
        if "apps/padiem-chat/**" not in paths:
            continue
        assert "!apps/padiem-chat/tests/**" in paths, (
            f"{job} broadly watches apps/padiem-chat/** but does not "
            "exclude tests-only changes"
        )
        assert "!apps/padiem-chat/worker.py" in paths, (
            f"{job} broadly watches apps/padiem-chat/** but does not "
            "exclude the Cloudflare Worker entrypoint that this browser QA "
            "does not execute"
        )


def test_repository_wide_test_scope_policy_is_canonical() -> None:
    policy = REPO / "docs" / "operations" / "TEST_SCOPE_AND_DELIVERY_POLICY.md"
    text = policy.read_text(encoding="utf-8")
    assert "CANONICAL REPOSITORY-WIDE POLICY" in text
    assert "TEST_COUNT != CONFIDENCE" in text
    assert "OBSERVATIONAL_NONBLOCKING_CHECK" in text
    assert "AUTOMATIC_WHOLE_REPOSITORY_SUITE=NO" in text


# #3769 / #3753 / #3764: permanent guard under the existing #3527
# Operations Policy Guard's always-run "docs/operations/tests" collection.
# This intentionally DOES NOT edit the CI workflow or the shared guard YAML:
# PR #3682 owns the latter insertion point.
B62_CHAT_CI = WORKFLOWS / "b62-padiem-chat-ci.yml"
B62_CHAT_EXPECTED_PATHS = (
    "apps/padiem-chat/**",
    "apps/korean-ai-platform/**",
    "packages/padiem-ai-core/**",
    "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py",
    "reference/business-62-padiem-chat-v1/**",
    ".github/scripts/b62_cloudflare_*.py",
    ".github/scripts/b14_model_registration_ci_plan.py",
    # #3989 scoped Chat CI source/guard changes always trigger FULL lane.
    ".github/scripts/b62_ci_impact_scope_3989.py",
    ".github/tests/test_b62_ci_impact_scope_3989.py",
    ".github/scripts/b62_worker_probe_*.sh",
    ".github/tests/test_3989_b62_worker_probe_parallel.py",
    ".github/tests/test_3989_b62_parallel_runtime_jobs.py",
    ".github/workflows/b62-padiem-chat-ci.yml",
    ".github/workflows/b62-cloudflare-worker-deploy.yml",
)
B62_CHAT_EXPECTED_JOBS = {
    "registry-ci-plan",
    "b62-registry-contract",
    "b62-test",
    "b62-full-suite",
    "b62-worker-suite",
    "b62-static-ui",
    "b14-multimodal-test",
}


def _b62_chat_ci_document() -> dict:
    document = yaml.safe_load(B62_CHAT_CI.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _b62_chat_ci_events(document: dict) -> dict:
    # PyYAML 1.1 treats the unquoted GitHub Actions key 'on' as boolean True.
    events = document.get("on", document.get(True))
    assert isinstance(events, dict), "B62 Chat CI must declare event triggers"
    return events


def _assert_b62_chat_ci_parity(document: dict) -> None:
    """Pin both event scopes to #3764, not merely to one another.

    If both trigger arrays drift in the same way, simple equality would pass.
    An independent exact path source-contract pin must also reject that case.
    """
    events = _b62_chat_ci_events(document)
    assert set(events) == {"push", "pull_request", "workflow_dispatch"}
    assert events["workflow_dispatch"] is None

    push, review = events["push"], events["pull_request"]
    assert isinstance(push, dict) and isinstance(review, dict)
    assert set(push) == {"branches", "paths"}, "no wider push controls"
    assert push["branches"] == ["main"], "only main may trigger push CI"
    assert set(review) == {"paths"}, "preserve review trigger semantics"
    for name, block in (("push", push), ("pull_request", review)):
        paths = block["paths"]
        assert isinstance(paths, list)
        assert len(paths) == len(B62_CHAT_EXPECTED_PATHS) == len(set(paths)), name
        assert tuple(paths) == B62_CHAT_EXPECTED_PATHS, (
            f"{name} changed #3764 dependency trigger paths"
        )
    assert push["paths"] == review["paths"], "main and PR coverage diverged"
    assert set(document["jobs"]) == B62_CHAT_EXPECTED_JOBS, (
        "preserve the B62 job graph and required gate"
    )



# #3989: expensive B62 main regression should follow latest qualifying commit.
# The exact workflow expression is pinned below; the Python examples document
# its event-specific group semantics, not an alternate runtime implementation.
B62_EXPECTED_CONCURRENCY = (
    "b62-padiem-chat-ci-${{ "
    "github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) "
    "|| github.event_name == 'push' && format('push-{0}', github.ref) "
    "|| format('manual-{0}', github.run_id) }}"
)


def test_b62_main_push_ci_coalescing_preserves_stable_required_gate() -> None:
    workflow = _b62_chat_ci_document()
    concurrency = workflow["concurrency"]
    assert set(concurrency) == {"group", "cancel-in-progress"}
    assert concurrency["group"] == B62_EXPECTED_CONCURRENCY
    assert concurrency["cancel-in-progress"] is True
    # Cancellation applies only to this CI workflow. The stable required
    # check must fan in full host/Worker for runtime changes and static UI
    # security/JS checks for proven static-only changes.
    aggregate = workflow["jobs"]["b62-test"]
    assert aggregate["name"] == "b62-test"
    assert aggregate["if"] == "always()"
    assert "b62-full-suite" in aggregate["needs"]
    assert "b62-worker-suite" in aggregate["needs"]
    assert "b62-static-ui" in aggregate["needs"]


def test_b62_main_push_group_is_distinct_from_pr_and_manual_groups() -> None:
    # The above pinned event expression must yield precisely these outcomes:
    # - two B62-relevant main pushes share one group (supersede stale work)
    # - other PRs never cancel each other, and force-pushes to one PR can
    #   supersede only that PR's previous test run
    # - manually dispatched diagnostics remain independent even on main
    def example_group(event: str, *, number: int = 0,
                      ref: str = "refs/heads/main", run_id: int = 0) -> str:
        if event == "pull_request":
            return f"b62-padiem-chat-ci-pr-{number}"
        if event == "push":
            return f"b62-padiem-chat-ci-push-{ref}"
        return f"b62-padiem-chat-ci-manual-{run_id}"

    assert example_group("push", run_id=38009178502) == example_group(
        "push", run_id=38009215242
    )
    assert example_group("pull_request", number=4083, run_id=1) == example_group(
        "pull_request", number=4083, run_id=2
    )
    assert example_group("pull_request", number=4083) != example_group(
        "pull_request", number=4084
    )
    assert example_group("push", ref="refs/heads/main") != example_group(
        "pull_request", number=4083
    )
    assert example_group("workflow_dispatch", run_id=9001) != example_group(
        "workflow_dispatch", run_id=9002
    )
    assert example_group("workflow_dispatch", run_id=9001) != example_group(
        "push", ref="refs/heads/main"
    )


def _b62_chat_segment_glob(pattern: str, path: str) -> bool:
    """GitHub path-filter glob subset needed for the current retained entries.

    Segment-wise fnmatch prevents a single '*' from crossing '/'.
    '**' matches zero or more complete path segments.
    """
    patterns, parts = pattern.split("/"), path.split("/")

    def walk(i: int, j: int) -> bool:
        if i == len(patterns):
            return j == len(parts)
        if patterns[i] == "**":
            return any(walk(i + 1, k) for k in range(j, len(parts) + 1))
        return (
            j < len(parts)
            and fnmatchcase(parts[j], patterns[i])
            and walk(i + 1, j + 1)
        )

    return walk(0, 0)


def _b62_chat_ci_path_triggers(path: str, event: str, branch: str = "main") -> bool:
    document = _b62_chat_ci_document()
    events = _b62_chat_ci_events(document)
    assert event in ("push", "pull_request")
    if event == "push" and branch not in events["push"]["branches"]:
        return False
    return any(_b62_chat_segment_glob(p, path) for p in events[event]["paths"])


def test_b62_chat_ci_push_and_pr_share_exact_dependency_path_contract() -> None:
    """Existing #3527 policy job runs this test on every PR."""
    _assert_b62_chat_ci_parity(_b62_chat_ci_document())


@pytest.mark.parametrize("event", ("push", "pull_request"))
@pytest.mark.parametrize("index", range(len(B62_CHAT_EXPECTED_PATHS)))
def test_b62_chat_ci_deleted_dependency_path_is_rejected(event: str, index: int) -> None:
    document = deepcopy(_b62_chat_ci_document())
    del _b62_chat_ci_events(document)[event]["paths"][index]
    with pytest.raises(AssertionError):
        _assert_b62_chat_ci_parity(document)


@pytest.mark.parametrize("event", ("push", "pull_request"))
@pytest.mark.parametrize("index", range(len(B62_CHAT_EXPECTED_PATHS)))
def test_b62_chat_ci_modified_dependency_path_is_rejected(event: str, index: int) -> None:
    document = deepcopy(_b62_chat_ci_document())
    paths = _b62_chat_ci_events(document)[event]["paths"]
    paths[index] = paths[index] + ".drift"
    with pytest.raises(AssertionError):
        _assert_b62_chat_ci_parity(document)


@pytest.mark.parametrize("index", range(len(B62_CHAT_EXPECTED_PATHS)))
def test_b62_chat_ci_matching_two_sided_drift_is_rejected(index: int) -> None:
    """Equality alone cannot catch a shared accidental narrowing."""
    document = deepcopy(_b62_chat_ci_document())
    events = _b62_chat_ci_events(document)
    for event in ("push", "pull_request"):
        events[event]["paths"][index] = "docs/incorrect-ci-scope/**"
    with pytest.raises(AssertionError):
        _assert_b62_chat_ci_parity(document)


@pytest.mark.parametrize("branches", ([], ["release"], ["main", "develop"], None))
def test_b62_chat_ci_main_only_branch_gate_cannot_drift(branches: object) -> None:
    document = deepcopy(_b62_chat_ci_document())
    _b62_chat_ci_events(document)["push"]["branches"] = branches
    with pytest.raises(AssertionError):
        _assert_b62_chat_ci_parity(document)


@pytest.mark.parametrize("event", ("push", "pull_request"))
def test_b62_chat_ci_dependency_globs_match_only_intended_scope(event: str) -> None:
    included = (
        "apps/padiem-chat/app/main.py",
        "apps/padiem-chat/static/app.js",
        "apps/korean-ai-platform/app/pilot/router_core.py",
        "packages/padiem-ai-core/padiem_ai_core/b14_execution.py",
        "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py",
        "reference/business-62-padiem-chat-v1/template.json",
        ".github/scripts/b62_cloudflare_deployed_parity.py",
        ".github/scripts/b14_model_registration_ci_plan.py",
        ".github/workflows/b62-padiem-chat-ci.yml",
        ".github/workflows/b62-cloudflare-worker-deploy.yml",
    )
    excluded = (
        "README.md",
        "docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md",
        "apps/personal-video-archive/app.py",
        "tools/b66_generic/analyze.py",
        "apps/padiem-chat-extra/app/main.py",
        "packages/padiem-ai-core-extra/padiem_ai_core/a.py",
        "packages/padiem-control-plane/padiem_control_plane/product_tier_routes_v2.py",
        "reference/business-62-padiem-chat-v1-old/template.json",
        ".github/scripts/b62_preview_smoke.py",
        ".github/scripts/nested/b62_cloudflare_guard.py",
        ".github/workflows/b62-browser-persistence-audit.yml",
    )
    for path in included:
        assert _b62_chat_ci_path_triggers(path, event), path
    for path in excluded:
        assert not _b62_chat_ci_path_triggers(path, event), path
    if event == "push":
        for path in included:
            assert not _b62_chat_ci_path_triggers(path, event, "feature"), path
