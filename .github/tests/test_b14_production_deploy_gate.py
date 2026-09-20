"""Contract tests for the B14 production deploy gate workflow (#1955).

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger a production mutation);
  2. carries the exact-SHA + account premutation assertions, fail-closed;
  3. deploys via the repository's canonical pipeline (bash ./deploy.sh);
  4. verifies post-deploy version-at-100 + engine b14_service_bound smoke;
  5. exposes a separately-confirmed rollback job;
and that deploy.sh itself remains syntactically valid (bash -n).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b14-production-deploy-gate.yml"
DEPLOY_SH = ROOT / "apps" / "korean-ai-platform" / "deploy.sh"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_workflow_parses_and_is_dispatch_only() -> None:
    wf = _workflow()
    assert set(wf["triggers"]) == {"workflow_dispatch"}, (
        "gate must be workflow_dispatch-only: an ordinary pull request must "
        "never trigger a production mutation"
    )
    inputs = wf["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    for spec in inputs.values():
        assert spec["required"] is True


def test_deploy_job_requires_exact_confirmation_phrase() -> None:
    wf = _workflow()
    deploy = wf["jobs"]["deploy-production-b14"]
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B14_FROM_EXACT_MAIN'"
    assert deploy["environment"] == "production"


def test_premutation_assertions_are_fail_closed_and_non_interactive() -> None:
    text = _workflow_text()
    assert "set -euo pipefail" in text
    # HEAD == TARGET_SHA, origin/main == TARGET_SHA, account id pinned.
    assert re.search(r'test "\$\(git rev-parse HEAD\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert re.search(r'test "\$\(git rev-parse origin/main\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert "9be14bb7b8974e65d0afba647ab16932" in text
    # No interactive constructs in the gate.
    assert "workflow_dispatch" in text
    for forbidden in ("Read-Host", "prompt", "--interactive"):
        assert forbidden not in text


def test_deploy_step_uses_canonical_pipeline() -> None:
    text = _workflow_text()
    assert "bash ./deploy.sh" in text, (
        "the gate must run the repository's canonical deploy.sh, not a "
        "duplicated build pipeline"
    )
    # No duplicated canonical steps in the workflow itself
    # (deployments list / rollback are verification-recovery commands, not deploys).
    assert "pywrangler sync" not in text
    assert not re.search(r"npx wrangler@\d+ deploy(?!ments)", text)


def test_post_deploy_verification_is_blocking() -> None:
    text = _workflow_text()
    assert "Current Version ID" in text
    # #2451: the served-version source is the documented REST deployments
    # endpoint, not the undocumented wrangler bare list.
    assert "/workers/scripts/ai-revenue-korean-ai-platform/deployments" in text
    assert "POST_DEPLOY_VERSION_AT_100=PASS" in text
    assert '"b14_service_bound":true' in text
    assert "ENGINE_B14_BOUND_SMOKE=PASS" in text
    assert "B14_KILO_CATALOG_MARKER=PASS" in text
    # Verification runs inside the deploy job (needs: semantics via same job).
    deploy = _workflow()["jobs"]["deploy-production-b14"]
    step_names = [step.get("name", "") for step in deploy["steps"]]
    assert any("Post-deploy verification" in name for name in step_names)


def test_rollback_job_is_separately_confirmed() -> None:
    wf = _workflow()
    rollback = wf["jobs"]["rollback-production-b14"]
    assert rollback["if"] == "github.event.inputs.confirmation == 'ROLLBACK_B14_TO_PREVIOUS_VERSION'"
    assert rollback["environment"] == "production"
    text = _workflow_text()
    assert "npx wrangler@4 rollback" in text


def test_retire_secret_job_is_separately_confirmed_and_idempotent() -> None:
    # #1933 S2-c: dead-secret removal needs its own confirmation token, must
    # be a no-op when the secret is already gone, and must verify after state.
    wf = _workflow()
    retire = wf["jobs"]["retire-openrouter-secret"]
    assert retire["if"] == (
        "github.event.inputs.confirmation == 'RETIRE_B14_SECRET_OPENROUTER_API_KEY'"
    )
    assert retire["environment"] == "production"
    text = _workflow_text()
    assert "npx wrangler@4 secret delete OPENROUTER_API_KEY" in text
    # wrangler 4 secret delete has no --force flag (run 34088852828 proved
    # "Unknown argument: force"); CI non-TTY skips the confirm prompt.
    assert "secret delete OPENROUTER_API_KEY --force" not in text
    assert "SECRET_ALREADY_ABSENT" in text
    assert "B14_SECRET_RETIRED=OPENROUTER_API_KEY" in text
    assert "b14-secrets-after.json" in text
    # CTO S3 review: wrangler 4 secret list takes --format json, not --json;
    # an empty/invalid listing must fail closed; grep 판정 금지.
    assert "secret list --format json" in text
    assert "secret list --json" not in text
    assert "EMPTY_OR_INVALID_SECRET_LIST" in text
    assert "SECRETS_BEFORE=" in text
    # CTO #2042 review: secret delete creates and immediately deploys a new
    # Worker version, so the job must verify post-retire serving health; the
    # old "cannot change deployed code" claim was false and must stay out.
    assert "deploys it immediately" in text
    assert "B14_POST_RETIRE_HEALTH=PASS" in text
    assert "cannot change deployed code" not in text
    assert "does not create or shift a serving version" not in text
    # The removal must never be bundled into the deploy job's condition.
    deploy = wf["jobs"]["deploy-production-b14"]
    assert "RETIRE" not in deploy["if"]


SCRIPTS_DIR = ROOT / ".github" / "scripts"


def _embedded_version_check_script() -> str:
    """Extract the python heredoc that validates the deployments envelope."""
    text = _workflow_text()
    match = re.search(
        r"python3 - \"\$VERSION_ID\" <<'PY'\n(.*?)\n\s*PY\n",
        text,
        re.DOTALL,
    )
    assert match, "version-check heredoc not found in gate workflow"
    return textwrap.dedent(match.group(1))


def _run_version_check(tmp_path, payload, expected: str) -> subprocess.CompletedProcess:
    script = _embedded_version_check_script()
    json_file = tmp_path / "deployments.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", script, expected],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "B14_DEPLOYMENTS_JSON": str(json_file),
            "B14_SERVED_VERSION_SCRIPTS": str(SCRIPTS_DIR),
        },
    )


def _canonical_resolver():
    """Import the shared canonical served-version primitive."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cloudflare_served_version",
        SCRIPTS_DIR / "cloudflare_served_version.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _envelope(deployments) -> dict:
    """A documented successful Cloudflare deployments envelope."""
    return {"success": True, "errors": [], "messages": [], "result": {"deployments": deployments}}


def _deployment(version_id: str, percentage: int, deployment_id: str = "d1") -> dict:
    return {
        "id": deployment_id,
        "source": "wrangler",
        "strategy": "percentage",
        "versions": [{"version_id": version_id, "percentage": percentage}],
        "created_on": "2026-09-06T09:13:00.000000Z",
    }


# ---------------------------------------------------------------------------
# #2451 child: the post-deploy version check must answer "is the version I just
# deployed the one serving traffic right now?" through the shared canonical
# resolver -- never by scanning deployment history for the expected id.
# ---------------------------------------------------------------------------


def test_version_check_accepts_active_deployment_at_100(tmp_path) -> None:
    """The documented active deployment (result.deployments[0]) at 100% passes."""
    expected = "065fe361-9e94-4e56-8025-3b372cca3459"
    result = _run_version_check(
        tmp_path, _envelope([_deployment(expected, 100)]), expected
    )
    assert result.returncode == 0, result.stderr
    assert "POST_DEPLOY_VERSION_AT_100=PASS" in result.stdout
    assert "CANONICAL_SERVED_VERSION_REUSED=YES" in result.stdout
    assert "HISTORICAL_DEPLOYMENT_ACCEPTED=NO" in result.stdout
    assert f"CANONICAL_SERVED_VERSION_RESOLVED={expected}" in result.stdout


def test_wrangler_raw_list_is_refused(tmp_path) -> None:
    """Regression: the bare wrangler list is never coerced into the canonical shape.

    The measured wrangler 4.129 shape is a bare, oldest-first list. Before this
    child the gate scanned it and accepted the expected version wherever it
    appeared -- including a superseded entry still recording percentage 100.
    """
    expected = "065fe361-9e94-4e56-8025-3b372cca3459"
    payload = [
        {
            "id": "7977047f-c42f-4ee2-9a8d-b8cfac39ef35",
            "source": "wrangler",
            "strategy": "percentage",
            "versions": [
                {"version_id": "26a82829-ac8a-4f8d-8de6-1d413c18a7a1", "percentage": 100}
            ],
            "created_on": "2026-09-03T04:51:05.028663Z",
        },
        {
            "id": "aabbccdd-0000-1111-2222-333344445555",
            "source": "wrangler",
            "strategy": "percentage",
            "versions": [{"version_id": expected, "percentage": 100}],
            "created_on": "2026-09-06T09:13:00.000000Z",
        },
    ]
    result = _run_version_check(tmp_path, payload, expected)
    assert result.returncode != 0, "a raw wrangler list must never prove a served version"
    assert "POST_DEPLOY_VERSION_AT_100=PASS" not in result.stdout
    assert "CANONICAL_SERVED_VERSION_REASON=envelope" in result.stdout


def test_deployments_object_without_success_envelope_is_refused(tmp_path) -> None:
    """{"deployments": [...]} alone carries no served proof; fail closed."""
    result = _run_version_check(
        tmp_path, {"deployments": [_deployment("abc123", 100)]}, "abc123"
    )
    assert result.returncode != 0
    assert "POST_DEPLOY_VERSION_AT_100=PASS" not in result.stdout
    assert "CANONICAL_SERVED_VERSION_REASON=envelope" in result.stdout


def test_list_shaped_result_is_refused(tmp_path) -> None:
    result = _run_version_check(
        tmp_path, {"success": True, "result": [_deployment("abc123", 100)]}, "abc123"
    )
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=result-object" in result.stdout


def test_result_versions_shortcut_is_refused(tmp_path) -> None:
    result = _run_version_check(
        tmp_path,
        {"success": True, "result": {"versions": [{"version_id": "abc123", "percentage": 100}]}},
        "abc123",
    )
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=deployment-records" in result.stdout


def test_expected_version_only_in_historical_deployment_fails(tmp_path) -> None:
    """The core false-pass regression.

    The deployed version sits at 100% in a *superseded* deployment while a newer
    deployment serves something else. History holds the expected id, so an
    "anywhere in history" scan passes -- the canonical resolver must not.
    """
    expected = "065fe361-9e94-4e56-8025-3b372cca3459"
    payload = _envelope(
        [
            _deployment("11111111-2222-3333-4444-555555555555", 100, "active"),
            _deployment(expected, 100, "superseded"),
        ]
    )
    result = _run_version_check(tmp_path, payload, expected)
    assert result.returncode != 0, "a historical occurrence must not satisfy the gate"
    assert "POST_DEPLOY_VERSION_AT_100=PASS" not in result.stdout
    assert "B14_SERVED_VERSION_MISMATCH=YES" in result.stdout


def test_historical_deployment_at_100_never_satisfies_expected(tmp_path) -> None:
    """Same shape, asserted from the resolver side: it returns the active id."""
    expected = "065fe361-9e94-4e56-8025-3b372cca3459"
    active = "11111111-2222-3333-4444-555555555555"
    payload = _envelope(
        [_deployment(active, 100, "active"), _deployment(expected, 100, "superseded")]
    )
    canonical = _canonical_resolver()
    assert canonical.resolve_served_version_id(payload) == active
    result = _run_version_check(tmp_path, payload, expected)
    assert result.returncode != 0
    assert f"CANONICAL_SERVED_VERSION_RESOLVED={active}" not in result.stdout


def test_version_check_rejects_wrong_version(tmp_path) -> None:
    result = _run_version_check(
        tmp_path,
        _envelope([_deployment("26a82829-ac8a-4f8d-8de6-1d413c18a7a1", 100)]),
        "ffffffff-0000-0000-0000-000000000000",
    )
    assert result.returncode != 0
    assert "B14_SERVED_VERSION_MISMATCH=YES" in result.stdout


def test_active_deployment_not_at_full_traffic_is_refused(tmp_path) -> None:
    result = _run_version_check(tmp_path, _envelope([_deployment("abc123", 50)]), "abc123")
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=traffic" in result.stdout


def test_active_deployment_with_split_versions_is_refused(tmp_path) -> None:
    deployment = _deployment("abc123", 100)
    deployment["versions"] = [
        {"version_id": "abc123", "percentage": 50},
        {"version_id": "def456", "percentage": 50},
    ]
    result = _run_version_check(tmp_path, _envelope([deployment]), "abc123")
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=version-count" in result.stdout


def test_unsafe_version_id_is_refused(tmp_path) -> None:
    result = _run_version_check(tmp_path, _envelope([_deployment("bad id;rm", 100)]), "bad id;rm")
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=version-id" in result.stdout


def test_empty_deployment_history_is_refused(tmp_path) -> None:
    result = _run_version_check(tmp_path, _envelope([]), "abc123")
    assert result.returncode != 0
    assert "CANONICAL_SERVED_VERSION_REASON=deployment-records" in result.stdout


def test_gate_decision_matches_the_canonical_resolver_matrix(tmp_path) -> None:
    """Reuse, not reimplementation: the gate must agree with the primitive."""
    canonical = _canonical_resolver()
    matrix = [
        (_envelope([_deployment("aaa", 100)]), "aaa", True),
        (_envelope([_deployment("aaa", 100), _deployment("bbb", 100)]), "bbb", False),
        (_envelope([_deployment("aaa", 100)]), "bbb", False),
        (_envelope([_deployment("aaa", 50)]), "aaa", False),
        ([_deployment("aaa", 100)], "aaa", False),
        ({"deployments": [_deployment("aaa", 100)]}, "aaa", False),
        (
            {
                "success": True,
                "result": {"versions": [{"version_id": "aaa", "percentage": 100}]},
            },
            "aaa",
            False,
        ),
    ]
    for payload, expected, should_pass in matrix:
        try:
            canonical_pass = canonical.resolve_served_version_id(payload) == expected
        except canonical.ServedVersionResolutionError:
            canonical_pass = False
        result = _run_version_check(tmp_path, payload, expected)
        assert (result.returncode == 0) == should_pass, (payload, expected)
        assert (result.returncode == 0) == canonical_pass, (
            "gate must not disagree with the canonical resolver",
            payload,
            expected,
        )


def test_workflow_delegates_to_the_canonical_resolver() -> None:
    script = _embedded_version_check_script()
    assert "from cloudflare_served_version import" in script
    assert "resolve_served_version_id(payload)" in script
    assert "ServedVersionResolutionError" in script


def test_no_history_scan_in_the_embedded_check() -> None:
    """Every entry in the list used to be searched; now none may be."""
    script = _embedded_version_check_script()
    for forbidden in ("for entry in deployments", "for v in entry", "match is not None"):
        assert forbidden not in script, f"history scan survived: {forbidden}"
    assert "isinstance(payload, list)" not in script
    assert 'payload.get("deployments")' not in script


def test_post_deploy_step_reads_the_documented_rest_endpoint() -> None:
    text = _workflow_text()
    assert "/workers/scripts/ai-revenue-korean-ai-platform/deployments" in text
    assert "wrangler@4 deployments list --json" not in text, (
        "the undocumented wrangler bare-list must not be the served-version source"
    )
    assert "B14_SERVED_VERSION_SCRIPTS" in text


def test_deploy_sh_is_syntactically_valid() -> None:
    # CI (ubuntu) always has /bin/bash. Locally on Windows, resolve Git Bash
    # explicitly because subprocess does not go through the shell's PATH.
    bash = shutil.which("bash")
    if bash is None:
        git = shutil.which("git")
        if git is not None:
            candidate = Path(git).resolve().parents[2] / "bin" / "bash.exe"
            bash = str(candidate) if candidate.exists() else None
    if bash is None:
        raise AssertionError("bash not found; contract requires bash -n on deploy.sh")
    subprocess.run(
        [bash, "-n", str(DEPLOY_SH)],
        check=True,
        capture_output=True,
    )
