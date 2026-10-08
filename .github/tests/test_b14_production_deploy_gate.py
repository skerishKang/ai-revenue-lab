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

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
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
    assert set(inputs) == {"target_sha", "confirmation", "rollback_version_id"}
    # #3704: the target is optional only at the schema level, so a deploy
    # dispatch is not forced to name one. The rollback branch itself refuses
    # without it, which is what test_rollback_refuses_an_unnamed_target_before_mutating
    # proves by execution.
    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert inputs["rollback_version_id"]["required"] is False
    assert inputs["rollback_version_id"]["type"] == "string"


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
    # #3704: the bare form is the defect, not just a weaker style. Wrangler's
    # implicit "previous upload" selection is the only rollback shape that can
    # succeed against a version no evidence named.
    assert not re.search(r"npx wrangler@\d+ rollback\s+--message", text), (
        "bare `wrangler rollback` survived: the target must be an argument"
    )
    assert 'npx wrangler@4 rollback "${ROLLBACK_TARGET}"' in text
    # The deploy job must stay unable to roll anything back on its own.
    deploy = wf["jobs"]["deploy-production-b14"]
    assert "ROLLBACK" not in deploy["if"]


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
    subprocess.run(
        [_bash(), "-n", str(DEPLOY_SH)],
        check=True,
        capture_output=True,
    )


def _bash() -> str:
    # CI (ubuntu) always has /bin/bash. Locally on Windows, resolve Git Bash
    # explicitly because subprocess does not go through the shell's PATH.
    bash = shutil.which("bash")
    if bash is not None:
        return bash
    git = shutil.which("git")
    if git is not None:
        candidate = Path(git).resolve().parents[2] / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    raise AssertionError("bash not found; these contracts execute the real bash step")


def _native(path) -> str:
    """A path form both MSYS bash and a Windows interpreter can open.

    Forward slashes are native on Linux and accepted on Windows, so the same
    test body runs unchanged in CI and in a Windows worktree.
    """
    return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# #3704: the rollback branch must name its target and then prove that target is
# serving.
#
# The static tests below pin the contract's shape. The tests after them execute
# the real step body with curl/npx/sleep replaced on PATH, because "the step
# prints a PASS token" and "the step prints PASS only when the served version
# equals the named target" are different claims -- only the second one is the
# rollback guarantee #3523 asks for.
# ---------------------------------------------------------------------------

PRE_VERSION = "aaaaaaaa-0000-0000-0000-000000000000"
TARGET_VERSION = "bbbbbbbb-1111-1111-1111-111111111111"
WRONG_VERSION = "cccccccc-2222-2222-2222-222222222222"

_STUB_CURL = """#!/usr/bin/env bash
set -uo pipefail
out=""
prev=""
for arg in "$@"; do
  if [ "${prev}" = "-o" ]; then out="${arg}"; fi
  prev="${arg}"
done
count="${RUNNER_TEMP}/curl-call-count"
n=0
if [ -f "${count}" ]; then n="$(cat "${count}")"; fi
n=$((n + 1))
printf '%s' "${n}" > "${count}"
if [ -n "${CURL_FAIL:-}" ]; then exit 22; fi
var="BODY_${n}"
body="${!var:-${BODY_DEFAULT:-}}"
printf '%s' "${body}" > "${out}"
"""

_STUB_NPX = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${RUNNER_TEMP}/npx-argv.txt"
if [ -n "${NPX_FAIL:-}" ]; then exit 1; fi
exit 0
"""

_STUB_SLEEP = """#!/usr/bin/env bash
exit 0
"""

# The step runs with working-directory apps/korean-ai-platform, so the harness
# reproduces that cwd instead of running from the workspace root.
#
# PATH must be prepended in the shell's own native form. A drive-letter entry is
# accepted for redirection but is skipped during command lookup, which silently
# leaves the real `curl` on PATH -- so the resolver check below is not ceremony:
# without it a stubbing mistake turns into an outbound provider request, and the
# negative assertions would pass for the wrong reason.
_DRIVER = """#!/usr/bin/env bash
set -uo pipefail
chmod +x "${STUB_DIR}/curl" "${STUB_DIR}/npx" "${STUB_DIR}/sleep"
STUB_NATIVE="$(cd "${STUB_DIR}" && pwd)"
export PATH="${STUB_NATIVE}:${PATH}"
for stubbed in curl npx sleep; do
  resolved="$(command -v "${stubbed}" || true)"
  if [ "${resolved}" != "${STUB_NATIVE}/${stubbed}" ]; then
    printf 'HARNESS_ABORT=%s=%s\\n' "${stubbed}" "${resolved}"
    exit 8
  fi
done
mkdir -p "${RUNNER_TEMP}/apps/korean-ai-platform"
cd "${RUNNER_TEMP}/apps/korean-ai-platform" || exit 9
bash "${STEP_SCRIPT}"
printf 'STEP_EXIT=%s\\n' "$?"
"""


def _rollback_run_step() -> dict:
    steps = _workflow()["jobs"]["rollback-production-b14"]["steps"]
    run_steps = [s for s in steps if "run" in s]
    assert len(run_steps) == 1, (
        "the rollback branch is one bounded step: capture, mutate and prove in "
        "one shell so the pre-state cannot be lost between steps"
    )
    return run_steps[0]


def _rollback_run() -> str:
    return _rollback_run_step()["run"]


def _envelope_body(versions: list) -> str:
    """A documented successful Cloudflare deployments envelope."""
    return json.dumps(
        {
            "success": True,
            "errors": [],
            "messages": [],
            "result": {
                "deployments": [
                    {
                        "id": "d1",
                        "source": "wrangler",
                        "strategy": "percentage",
                        "versions": versions,
                    }
                ]
            },
        }
    )


def _served(version_id: str, percentage: int = 100) -> dict:
    return {"version_id": version_id, "percentage": percentage}


class _StepRun:
    def __init__(self, result, evidence_text: str, npx_argv) -> None:
        self.output = (result.stdout or "") + (result.stderr or "")
        if "HARNESS_ABORT=" in self.output:
            raise AssertionError(f"stub transport did not resolve: {self.output}")
        marker = re.search(r"STEP_EXIT=(\d+)", self.output)
        assert marker, f"the step never reported an exit code: {self.output[-400:]}"
        # The stub prints nothing that the real client prints. This is the
        # positive half of the guard above: it fails loudly if a request ever
        # reached the network instead of the stub.
        assert "The requested URL returned error" not in self.output, (
            "a real HTTP response was observed; the rollback step must only ever "
            "talk to the stub transport in tests"
        )
        self.exit_code = int(marker.group(1))
        self.evidence_text = evidence_text
        self.evidence = dict(
            line.split("=", 1) for line in evidence_text.splitlines() if "=" in line
        )
        self.npx_argv = npx_argv

    @property
    def mutated(self) -> bool:
        return self.npx_argv is not None


def _run_rollback_step(tmp_path, *, bodies, target=TARGET_VERSION, **flags) -> _StepRun:
    root = tmp_path / "lane"
    stub = root / "bin"
    runner_temp = root / "runner-temp"
    stub.mkdir(parents=True, exist_ok=True)
    runner_temp.mkdir(parents=True, exist_ok=True)
    for name, body in (("curl", _STUB_CURL), ("npx", _STUB_NPX), ("sleep", _STUB_SLEEP)):
        (stub / name).write_text(body, encoding="utf-8", newline="\n")
    step = root / "step.sh"
    step.write_text(_rollback_run(), encoding="utf-8", newline="\n")
    driver = root / "driver.sh"
    driver.write_text(_DRIVER, encoding="utf-8", newline="\n")

    env = {
        **os.environ,
        "STUB_DIR": _native(stub),
        "RUNNER_TEMP": _native(runner_temp),
        "STEP_SCRIPT": _native(step),
        "ROLLBACK_TARGET": target,
        "B14_SERVED_VERSION_SCRIPTS": _native(SCRIPTS_DIR),
        "CLOUDFLARE_API_TOKEN": "stub-token-must-not-be-echoed",
        "CLOUDFLARE_ACCOUNT_ID": "stub-account-must-not-be-echoed",
    }
    for index, body in bodies.items():
        env[f"BODY_{index}"] = body
    env["BODY_DEFAULT"] = bodies.get("default", bodies.get(1, ""))
    for flag in ("curl_fail", "npx_fail"):
        if flags.get(flag):
            env[flag.upper()] = "1"

    result = subprocess.run(
        [_bash(), _native(driver)],
        cwd=_native(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    evidence_file = runner_temp / "b14-rollback-evidence.txt"
    argv_file = runner_temp / "npx-argv.txt"
    return _StepRun(
        result,
        evidence_file.read_text(encoding="utf-8") if evidence_file.exists() else "",
        argv_file.read_text(encoding="utf-8") if argv_file.exists() else None,
    )


def test_rollback_uses_only_the_canonical_adapters() -> None:
    run = _rollback_run()
    assert "cloudflare_served_version_cli.py" in run
    assert "cloudflare_mutation_evidence.py" in run
    assert "validate-version-id" in run
    assert run.count("resolve-active") == 2, (
        "one pre-mutation baseline and one per-attempt readback resolver call"
    )
    assert run.count('--class ROLLBACK') == 2, "open-window poll plus closed-window decision"
    assert run.count("--window-open") == 1
    # The Engine-branded adapter must not be borrowed: it carries Engine output
    # tokens, so depending on it would couple B14 to another lane's contract.
    assert "b54_engine_served_version_guard.py" not in run


def test_rollback_step_parses_no_envelope_in_shell() -> None:
    """INLINE_JQ_NEW=0: every envelope decision goes through the canonical CLI."""
    run = _rollback_run()
    for forbidden in ("jq", 'result["deployments"]', ".versions[", "python3 -c"):
        assert forbidden not in run, f"shell-side envelope parsing survived: {forbidden}"


def test_rollback_validates_the_target_in_the_unambiguous_form() -> None:
    """Every canonical id the step hands to an adapter uses the unambiguous form.

    `--flag "${VALUE}"` makes argparse read a value that begins with `-` as an
    option and refuse it with a usage error before the canonical predicate is
    consulted, so the gate would reject ids its own grammar accepts. Asserted over
    all three id-carrying flags, because a pre-version comes out of the resolver
    under the same grammar as a dispatched target.
    """
    run = _rollback_run()
    for flag in ("--version-id", "--pre-version", "--target-version"):
        assert flag + '="${' in run, flag
        assert flag + ' "${' not in run, f"{flag} still passes its value as a token"


def test_rollback_step_order_is_refuse_validate_capture_mutate_prove() -> None:
    """The order is the guarantee, so it is asserted as an order."""
    run = _rollback_run()
    positions = []
    for needle in (
        'if [ -z "${ROLLBACK_TARGET:-}" ]',
        "validate-version-id",
        'pre_version="$(python3',
        "npx wrangler@4 rollback",
        "--window-open",
        "B14_PRODUCTION_ROLLBACK=PASS",
    ):
        found = run.find(needle, (positions[-1] + 1) if positions else 0)
        assert found != -1, f"missing or out of order: {needle}"
        positions.append(found)


def test_rollback_readback_window_matches_the_evidence_ceiling() -> None:
    """A longer poll would hit the primitive's own ceiling and decide nothing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cloudflare_mutation_evidence", SCRIPTS_DIR / "cloudflare_mutation_evidence.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    attempts = re.search(r"for attempt in \$\(seq 1 (\d+)\)", _rollback_run())
    assert attempts, "the readback window must be a bounded loop"
    assert int(attempts.group(1)) == module.MAX_OBSERVATIONS == module.POLL_ATTEMPTS


def test_evidence_artifact_is_bounded_and_published_even_on_failure() -> None:
    steps = _workflow()["jobs"]["rollback-production-b14"]["steps"]
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "always()", (
        "a failed rollback is exactly the case the evidence is needed for"
    )
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["path"].endswith("b14-rollback-evidence.txt")
    assert "deployments" not in upload["with"]["path"], (
        "raw envelopes are not a publishable artifact"
    )
    # The artifact is written only through `record`, so every line it can carry
    # is checkable here: a credential-shaped literal must never be one.
    for literal in re.findall(r'record "[^"]*"', _rollback_run()):
        for forbidden in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "Authorization"):
            assert forbidden not in literal, f"recorded literal names a secret: {literal}"
    assert 'record "RAW_DEPLOYMENTS_ENVELOPE_INCLUDED=NO"' in _rollback_run()
    assert 'record "SECRET_VALUES_INCLUDED=NO"' in _rollback_run()


def test_rollback_passes_only_when_the_named_target_is_serving(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(TARGET_VERSION)]),
        },
    )
    assert out.exit_code == 0, out.output
    assert "B14_PRODUCTION_ROLLBACK=PASS" in out.output
    assert f"rollback {TARGET_VERSION}" in out.npx_argv, (
        "the version named by the evidence must be the version Wrangler received"
    )
    assert out.evidence["ROLLBACK_TARGET_VERSION_ID"] == TARGET_VERSION
    assert out.evidence["PRE_ROLLBACK_SERVED_VERSION_ID"] == PRE_VERSION
    assert out.evidence["POST_ROLLBACK_SERVED_VERSION_ID"] == TARGET_VERSION
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "ROLLBACK_TARGET_OBSERVED"
    assert out.evidence["POST_ROLLBACK_CONVERGENCE_READS"] == "1"
    # A command exit is recorded, never mistaken for the verdict.
    assert out.evidence["ROLLBACK_COMMAND_EXIT_ZERO_AS_FINAL_PASS"] == "NO"
    assert "stub-token-must-not-be-echoed" not in out.output + out.evidence_text
    assert "stub-account-must-not-be-echoed" not in out.output + out.evidence_text


def test_rollback_accepts_a_canonical_leading_hyphen_target(tmp_path) -> None:
    """A target the canonical grammar accepts must survive the whole step.

    Cloudflare issues UUID version ids, so this is contract parity rather than an
    expected production value: the gate must refuse exactly what the predicate
    refuses and accept exactly what it accepts.
    """
    target = "-safe-version"
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(target)]),
        },
        target=target,
    )
    assert out.exit_code == 0, out.output
    assert "VERSION_ID_SAFE=NO" not in out.output
    assert out.evidence["ROLLBACK_TARGET_VERSION_ID"] == target
    assert out.evidence["POST_ROLLBACK_SERVED_VERSION_ID"] == target
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "ROLLBACK_TARGET_OBSERVED"
    assert f"rollback {target}" in out.npx_argv


def test_rollback_accepts_a_canonical_leading_hyphen_pre_version(tmp_path) -> None:
    """The pre-mutation read carries the same grammar, so it must survive too."""
    pre = "-pre-version"
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(pre)]),
            "default": _envelope_body([_served(TARGET_VERSION)]),
        },
    )
    assert out.exit_code == 0, out.output
    assert out.evidence["PRE_ROLLBACK_SERVED_VERSION_ID"] == pre
    assert out.evidence["POST_ROLLBACK_SERVED_VERSION_ID"] == TARGET_VERSION
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "ROLLBACK_TARGET_OBSERVED"


def test_rollback_keeps_reading_while_the_target_is_not_yet_serving(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            2: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(TARGET_VERSION)]),
        },
    )
    assert out.exit_code == 0, out.output
    assert out.evidence["POST_ROLLBACK_CONVERGENCE_READS"] == "2"
    assert out.evidence["POST_ROLLBACK_SERVED_EQUALS_TARGET"] == "PASS"


def test_rollback_fails_closed_when_the_window_times_out(tmp_path) -> None:
    """A wrong served version never becomes a PASS, even after the full window."""
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(WRONG_VERSION)]),
        },
    )
    assert out.exit_code != 0
    assert "B14_PRODUCTION_ROLLBACK=PASS" not in out.output
    assert "POST_ROLLBACK_SERVED_EQUALS_TARGET=FAIL" in out.output
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "ROLLBACK_TARGET_NOT_OBSERVED"
    # The bounded window is exhausted and then closes as FAIL, not as silence.
    assert out.evidence["POST_ROLLBACK_CONVERGENCE_READS"] == "30"


def test_rollback_fails_closed_on_split_active_versions(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(TARGET_VERSION, 50), _served(WRONG_VERSION, 50)]),
        },
    )
    assert out.exit_code != 0
    assert "B14_PRODUCTION_ROLLBACK=PASS" not in out.output
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "NO_ACCEPTABLE_OBSERVATION"
    assert out.evidence["MUTATION_EVIDENCE_REJECTED_OBSERVATIONS"] == "30"
    assert "REASON=version-count" in out.output


def test_rollback_fails_closed_on_a_malformed_served_id(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served("bad id;echo token", 100)]),
        },
    )
    assert out.exit_code != 0
    assert "B14_PRODUCTION_ROLLBACK=PASS" not in out.output
    assert out.evidence["MUTATION_EVIDENCE_REASON"] == "NO_ACCEPTABLE_OBSERVATION"
    assert "bad id" not in out.output, "a refused candidate must not be reflected"


def test_rollback_fails_closed_when_every_read_errors(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={1: _envelope_body([_served(PRE_VERSION)])},
        curl_fail=True,
    )
    assert out.exit_code != 0
    assert "B14_PRODUCTION_ROLLBACK=PASS" not in out.output
    # Transport failure hits the pre-mutation read first, so nothing is mutated.
    assert out.mutated is False


def test_rollback_never_mutates_without_a_pre_mutation_baseline(tmp_path) -> None:
    """A non-canonical pre-state is refused before Wrangler is reached."""
    out = _run_rollback_step(
        tmp_path,
        bodies={1: json.dumps([{"versions": [_served(PRE_VERSION)]}])},
    )
    assert out.exit_code != 0
    assert out.mutated is False
    assert "PRE_MUTATION_VERSION_CAPTURED=YES" not in out.output
    assert "REASON=canonical resolver refused the pre-rollback deployments read" in out.output


def test_rollback_refuses_an_unnamed_target_before_mutating(tmp_path) -> None:
    out = _run_rollback_step(tmp_path, bodies={}, target="")
    assert out.exit_code != 0
    assert out.mutated is False
    assert "ROLLBACK_TARGET_EXPLICIT=NO" in out.output
    assert "B14_PRODUCTION_ROLLBACK=FAIL" in out.output
    # The refusal is itself durable evidence, not only a log line.
    assert out.evidence["MUTATION_CLASS"] == "ROLLBACK"
    assert "ROLLBACK_TARGET_VERSION_ID" not in out.evidence


def test_rollback_refuses_a_hostile_target_without_echoing_it(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={1: _envelope_body([_served(PRE_VERSION)])},
        target="bad version;echo stub-token",
    )
    assert out.exit_code != 0
    assert out.mutated is False
    assert "VERSION_ID_SAFE=NO" in out.output
    assert "REASON=version-id" in out.output
    assert "bad version" not in out.output


def test_rollback_does_not_pass_when_the_command_fails(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(TARGET_VERSION)]),
        },
        npx_fail=True,
    )
    assert out.exit_code != 0
    assert "B14_PRODUCTION_ROLLBACK=PASS" not in out.output
    assert "B14_ROLLBACK_COMMAND=EXIT_ZERO" not in out.evidence


def test_rollback_evidence_file_is_the_only_publishable_output(tmp_path) -> None:
    out = _run_rollback_step(
        tmp_path,
        bodies={
            1: _envelope_body([_served(PRE_VERSION)]),
            "default": _envelope_body([_served(TARGET_VERSION)]),
        },
    )
    assert out.evidence_text.splitlines()[0] == "MUTATION_CLASS=ROLLBACK"
    assert "success" not in out.evidence_text, "an envelope body leaked into the artifact"


CONTRACT_CI = ROOT / ".github" / "workflows" / "b14-deploy-gate-contract-tests.yml"


def test_contract_ci_reruns_when_a_canonical_adapter_changes() -> None:
    """The gate now consumes two shared adapters, so both must re-trigger it."""
    data = yaml.safe_load(CONTRACT_CI.read_text(encoding="utf-8"))
    trigger = data.get("on", data.get(True))
    paths = trigger["pull_request"]["paths"]
    for required in (
        "b14-production-deploy-gate.yml",
        "test_b14_production_deploy_gate.py",
        "cloudflare_served_version_cli.py",
        "cloudflare_served_version.py",
        "cloudflare_mutation_evidence.py",
        "test_cloudflare_served_version_cli.py",
    ):
        assert any(required in p for p in paths), (
            f"{required} is consumed by the B14 gate but is not a pull_request path"
        )
    runs = "\n".join(s["run"] for s in data["jobs"]["gate-contract-tests"]["steps"] if "run" in s)
    assert "test_b14_production_deploy_gate.py" in runs
    assert "test_cloudflare_served_version_cli.py" in runs, (
        "the adapter the rollback branch validates through has no CI runner"
    )


# ---------------------------------------------------------------------------
# #3742: the normal deploy path must anchor what was serving BEFORE deploy.sh.
#
# #3704 gave the ROLLBACK lane a durable pre-mutation anchor, but that anchor is
# produced inside the rollback job. The deploy path -- the mutation that creates
# the need to roll back -- still had none, so the version to return to existed
# only as a run-log line that no artifact carried.
#
# The static tests pin the contract's shape. The tests after them execute the
# real step bodies with curl/npx/sleep/git and deploy.sh replaced on PATH,
# because "the job prints a PASS token" and "the job cannot deploy until a
# served version has actually been confirmed" are different claims -- only the
# second one is the guarantee #3523 asks for.
# ---------------------------------------------------------------------------

DEPLOY_JOB = "deploy-production-b14"
PREMUTATION_STEP = "Premutation exact-main and account assertions"
ANCHOR_STEP = "Pre-deploy canonical served-version rollback anchor"
DEPLOY_STEP = "Deploy B14 via canonical pipeline (deploy.sh)"
POST_DEPLOY_STEP = (
    "Post-deploy verification (version 100% + engine binding + Kilo catalog marker)"
)
ARTIFACT_STEP = "Publish the bounded pre-mutation anchor evidence artifact"

ANCHOR_VERSION = "aaaaaaaa-0000-0000-0000-000000000000"
TARGET_SHA = "1234567890abcdef1234567890abcdef12345678"

# The account id is pinned publicly in the workflow; the token is a sentinel.
# Both are asserted absent from the artifact, which is a stronger check than
# asserting a placeholder's absence.
ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"
TOKEN = "stub-token-must-not-be-echoed"


def _deploy_steps() -> list:
    return _workflow()["jobs"][DEPLOY_JOB]["steps"]


def _step(name: str) -> dict:
    for step in _deploy_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"the deploy job has no step named {name!r}")


def _anchor_run() -> str:
    return _step(ANCHOR_STEP)["run"]


def _deploy_run() -> str:
    return _step(DEPLOY_STEP)["run"]


# -- contract predicates ----------------------------------------------------
# Each one raises AssertionError on violation, so the negative controls at the
# bottom can assert that a mutated workflow is genuinely rejected rather than
# merely different.


def _assert_step_order(steps) -> None:
    """exact-main -> canonical read -> anchor prepared -> deploy.sh -> post-deploy."""
    names = [s.get("name", "") for s in steps]
    for required in (
        PREMUTATION_STEP,
        ANCHOR_STEP,
        DEPLOY_STEP,
        POST_DEPLOY_STEP,
        ARTIFACT_STEP,
    ):
        assert required in names, f"missing deploy-job step: {required}"
    assert names.index(PREMUTATION_STEP) < names.index(ANCHOR_STEP), (
        "the anchor must be read after the exact-main assertion"
    )
    assert names.index(ANCHOR_STEP) < names.index(DEPLOY_STEP), (
        "the pre-deploy read must run before deploy.sh"
    )
    assert names.index(DEPLOY_STEP) < names.index(POST_DEPLOY_STEP)
    assert names.index(POST_DEPLOY_STEP) < names.index(ARTIFACT_STEP)


def _assert_anchor_authority(run: str) -> None:
    assert "cloudflare_served_version_cli.py" in run, "canonical adapter not reused"
    assert "resolve-active" in run
    # A second served-version authority could disagree with the canonical one.
    assert "b54_engine_served_version_guard.py" not in run, (
        "the Engine-branded adapter must not be borrowed into B14"
    )
    # INLINE_JQ_NEW=0 / SECOND_VERSION_AUTHORITY=0.
    for forbidden in ("jq", 'result["deployments"]', ".versions[", "python3 -c"):
        assert forbidden not in run, f"shell-side envelope parsing survived: {forbidden}"
    # The step sits before the mutation, so it must be structurally incapable of
    # performing one.
    for mutating in ("wrangler", "deploy.sh", "npx "):
        assert mutating not in run, f"the pre-mutation read must stay read-only: {mutating}"


def _assert_artifact_contract(steps) -> None:
    uploads = [
        s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert len(uploads) == 1, "the deploy path publishes exactly one evidence artifact"
    upload = uploads[0]
    assert upload["if"] == "always()", (
        "a run that stopped before deploying is exactly the case the anchor is needed for"
    )
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["if-no-files-found"] == "error", (
        "a missing artifact must never read as a silent PASS"
    )
    assert upload["with"]["path"].endswith("b14-deploy-evidence.txt")
    assert "deployments" not in upload["with"]["path"], (
        "raw envelopes are not a publishable artifact"
    )


# -- execution harness ------------------------------------------------------

_STUB_GIT = """#!/usr/bin/env bash
# The premutation step calls `git rev-parse` and `git fetch`. Both are stubbed so
# no network and no real repository state can influence the ordering proof.
if [ "$1" = "rev-parse" ]; then
  printf '%s\\n' "${GIT_HEAD_SHA:-}"
  exit 0
fi
exit 0
"""

_STUB_DEPLOY_SH = """#!/usr/bin/env bash
printf 'DEPLOY_SH_INVOKED\\n' >> "${RUNNER_TEMP}/deploy-invocations.txt"
printf 'Current Version ID: %s\\n' \
  "${DEPLOY_EMITS_VERSION:-11111111-2222-3333-4444-555555555555}"
if [ -n "${DEPLOY_FAIL:-}" ]; then exit 1; fi
exit 0
"""

# Reproduces the deploy job's own semantics: steps run in declared order from the
# workspace root unless the step declares a working-directory, and the job stops
# at the first failing step. That last part is what turns "deploy.sh never ran"
# from an assumption into an observed consequence.
_DEPLOY_DRIVER = """#!/usr/bin/env bash
set -uo pipefail
for stubbed in curl npx sleep git; do
  chmod +x "${STUB_DIR}/${stubbed}"
done
STUB_NATIVE="$(cd "${STUB_DIR}" && pwd)"
export PATH="${STUB_NATIVE}:${PATH}"
for stubbed in curl npx sleep git; do
  resolved="$(command -v "${stubbed}" || true)"
  if [ "${resolved}" != "${STUB_NATIVE}/${stubbed}" ]; then
    printf 'HARNESS_ABORT=%s=%s\\n' "${stubbed}" "${resolved}"
    exit 8
  fi
done
cd "${GITHUB_WORKSPACE}" || exit 9
job_failed=0
for step in "${STEPS_DIR}"/[0-9][0-9]-*.sh; do
  bash "${step}"
  rc=$?
  printf 'STEP_EXIT_%s=%s\\n' "$(basename "${step}" .sh)" "${rc}"
  if [ "${rc}" -ne 0 ]; then
    job_failed=1
    break
  fi
done
printf 'JOB_FAILED=%s\\n' "${job_failed}"
"""


class _DeployChain:
    def __init__(self, result, evidence_text: str, deploy_invocations: str | None) -> None:
        self.output = (result.stdout or "") + (result.stderr or "")
        if "HARNESS_ABORT=" in self.output:
            raise AssertionError(f"stub transport did not resolve: {self.output}")
        # The stub prints nothing a real client prints. This fails loudly if a
        # request ever reached the network instead of the stub.
        assert "The requested URL returned error" not in self.output, (
            "a real HTTP response was observed; the deploy chain must only ever "
            "talk to the stub transport in tests"
        )
        marker = re.search(r"JOB_FAILED=(\d+)", self.output)
        assert marker, f"the chain never reported: {self.output[-500:]}"
        self.failed = marker.group(1) == "1"
        self.evidence_text = evidence_text
        self.evidence = dict(
            line.split("=", 1) for line in evidence_text.splitlines() if "=" in line
        )
        # One line per deploy.sh invocation, so "never reached" and "reached and
        # failed" are distinguishable counts rather than a bare boolean.
        self.deploy_calls = (
            len([ln for ln in deploy_invocations.splitlines() if ln.strip()])
            if deploy_invocations
            else 0
        )

    @property
    def mutated(self) -> bool:
        return self.deploy_calls > 0


def _run_deploy_chain(
    tmp_path,
    *,
    body,
    curl_fail: bool = False,
    deploy_fail: bool = False,
    deploy_run_override: str | None = None,
) -> _DeployChain:
    root = tmp_path / "lane"
    stub = root / "bin"
    runner_temp = root / "runner-temp"
    workspace = root / "workspace"
    steps_dir = root / "steps"
    for directory in (stub, runner_temp, workspace, steps_dir):
        directory.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("curl", _STUB_CURL),
        ("npx", _STUB_NPX),
        ("sleep", _STUB_SLEEP),
        ("git", _STUB_GIT),
    ):
        (stub / name).write_text(text, encoding="utf-8", newline="\n")
    app = workspace / "apps" / "korean-ai-platform"
    app.mkdir(parents=True, exist_ok=True)
    (app / "deploy.sh").write_text(_STUB_DEPLOY_SH, encoding="utf-8", newline="\n")

    deploy_body = (
        _step(DEPLOY_STEP)["run"]
        if deploy_run_override is None
        else deploy_run_override
    )
    chain = (
        ("00-premutation", _step(PREMUTATION_STEP)["run"], workspace),
        ("01-anchor", _step(ANCHOR_STEP)["run"], workspace),
        ("02-deploy", deploy_body, app),
    )
    for name, run, cwd in chain:
        expanded = run.replace("${{ github.event.inputs.target_sha }}", TARGET_SHA)
        (steps_dir / f"{name}.sh").write_text(
            f'cd "{_native(cwd)}" || exit 9\n{expanded}',
            encoding="utf-8",
            newline="\n",
        )
    driver = root / "driver.sh"
    driver.write_text(_DEPLOY_DRIVER, encoding="utf-8", newline="\n")

    env = {
        **os.environ,
        "STUB_DIR": _native(stub),
        "STEPS_DIR": _native(steps_dir),
        "RUNNER_TEMP": _native(runner_temp),
        "GITHUB_WORKSPACE": _native(workspace),
        "B14_SERVED_VERSION_SCRIPTS": _native(SCRIPTS_DIR),
        "B14_TARGET_SHA": TARGET_SHA,
        "GIT_HEAD_SHA": TARGET_SHA,
        "CLOUDFLARE_API_TOKEN": TOKEN,
        "CLOUDFLARE_ACCOUNT_ID": ACCOUNT_ID,
        "BODY_1": body,
        "BODY_DEFAULT": body,
    }
    if curl_fail:
        env["CURL_FAIL"] = "1"
    if deploy_fail:
        env["DEPLOY_FAIL"] = "1"

    result = subprocess.run(
        [_bash(), _native(driver)],
        cwd=_native(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    evidence_file = runner_temp / "b14-deploy-evidence.txt"
    invocations = runner_temp / "deploy-invocations.txt"
    return _DeployChain(
        result,
        evidence_file.read_text(encoding="utf-8") if evidence_file.exists() else "",
        invocations.read_text(encoding="utf-8") if invocations.exists() else None,
    )


def _assert_no_mutation(out: _DeployChain) -> None:
    """PRODUCTION_MUTATION=0 for every refused-anchor shape.

    A refusal is the one case where DEPLOY_EXECUTED=NO is truthful, because the
    deploy step provably never ran -- hence deploy.sh calls == 0 and no attempt
    line at all.
    """
    assert out.failed is True, out.output
    assert out.mutated is False, "deploy.sh ran without a confirmed anchor"
    assert out.deploy_calls == 0, "deploy.sh was invoked without a confirmed anchor"
    assert out.evidence["DEPLOY_EXECUTED"] == "NO"
    assert "DEPLOY_ATTEMPTED" not in out.evidence, (
        "an attempt was recorded even though the anchor refused"
    )
    # A version that was never confirmed must not be recorded, and no PASS token
    # may be emitted for an anchor that does not exist.
    assert "PRE_DEPLOY_SERVED_VERSION_ID" not in out.evidence
    assert "PRE_MUTATION_VERSION_CAPTURED" not in out.evidence
    assert "ROLLBACK_ANCHOR_AVAILABLE" not in out.evidence
    assert "B14_PRE_DEPLOY_ANCHOR=PASS" not in out.output
    assert "B14_CANONICAL_PIPELINE_DEPLOY=PASS" not in out.output


# -- 1 and 7: the read runs before deploy.sh, and the artifact proves it -----


def test_deploy_job_step_order_matches_the_mutation_contract() -> None:
    """Static half of the ordering guarantee.

    The execution test below drives the steps in the contract's order by name, so
    it cannot detect a workflow that declares them in the wrong order. This is
    the assertion that does.
    """
    _assert_step_order(_deploy_steps())


def test_pre_deploy_read_runs_before_deploy_sh(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]))
    assert out.failed is False, out.output
    assert out.mutated is True
    assert "B14_PRE_DEPLOY_ANCHOR=PASS" in out.output
    assert "B14_CANONICAL_PIPELINE_DEPLOY=PASS" in out.output
    # The anchor line is written by the pre-deploy step and DEPLOY_EXECUTED=YES
    # by the deploy step, so the artifact's own line order is the execution
    # order -- the read really did happen before the mutation.
    lines = out.evidence_text.splitlines()
    assert lines.index(f"PRE_DEPLOY_SERVED_VERSION_ID={ANCHOR_VERSION}") < lines.index(
        "DEPLOY_EXECUTED=YES"
    )


def test_anchor_evidence_artifact_is_durable_and_bounded(tmp_path) -> None:
    _assert_artifact_contract(_deploy_steps())
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]))
    assert out.evidence["MUTATION_CLASS"] == "DEPLOY"
    assert out.evidence["B14_WORKER_SCRIPT"] == "ai-revenue-korean-ai-platform"
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == ANCHOR_VERSION
    assert out.evidence["PRE_MUTATION_VERSION_CAPTURED"] == "YES"
    assert out.evidence["SOURCE_MAIN_SHA"] == TARGET_SHA
    assert out.evidence["ROLLBACK_ANCHOR_AVAILABLE"] == "YES"
    assert out.evidence["ANCHOR_PREPARED_BEFORE_DEPLOY"] == "YES"
    assert out.evidence["DEPLOY_ATTEMPTED"] == "YES"
    assert out.evidence["DEPLOY_EXECUTED"] == "YES"


# -- 2: only a valid active version becomes the anchor ----------------------


def test_only_a_valid_active_version_becomes_the_anchor(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]))
    assert out.failed is False, out.output
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == ANCHOR_VERSION


def test_anchor_accepts_a_canonical_leading_hyphen_version(tmp_path) -> None:
    """An id the canonical grammar accepts must survive the whole step.

    Cloudflare issues UUID version ids, so this is contract parity rather than
    an expected production value: the gate must accept exactly what the canonical
    predicate accepts.
    """
    version = "-pre-version"
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(version)]))
    assert out.failed is False, out.output
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == version
    assert out.mutated is True


def test_anchor_reads_the_documented_rest_endpoint() -> None:
    run = _anchor_run()
    # The URL is composed the way the rollback branch composes it -- a `base`
    # variable plus a relative path -- so both halves are asserted.
    assert "/workers/scripts/ai-revenue-korean-ai-platform" in run
    assert '"${base}/deployments"' in run
    assert "api.cloudflare.com/client/v4/accounts" in run
    assert "wrangler@4 deployments list" not in run, (
        "the undocumented wrangler bare-list must not be the served-version source"
    )


def test_anchor_reuses_the_canonical_authority_only() -> None:
    _assert_anchor_authority(_anchor_run())


# -- deploy attempt vs deploy outcome (CENTRAL review round 1) --------------
#
# `set -euo pipefail` ends the deploy step the moment deploy.sh exits non-zero,
# so evidence written AFTER the command is lost exactly when it matters: a
# deploy that started and failed can still have mutated Production, and an
# artifact with no attempt line would read identically to one where the anchor
# refused and deploy.sh was never reached. The attempt is therefore recorded
# before the command, and a failed deploy records UNKNOWN -- never YES, and
# never NO.


def _assert_deploy_attempt_evidence(run: str) -> None:
    assert "DEPLOY_ATTEMPTED=YES" in run, "the deploy attempt is not recorded"
    assert run.index("DEPLOY_ATTEMPTED=YES") < run.index("bash ./deploy.sh"), (
        "the attempt must be recorded BEFORE the mutating command"
    )
    assert run.index("bash ./deploy.sh") < run.index("DEPLOY_EXECUTED=YES"), (
        "execution may only be recorded once the command has succeeded"
    )
    # A failed deploy is not knowably a non-mutation, so this step must never
    # assert NO. Only the anchor step may, and only when it refused.
    assert "DEPLOY_EXECUTED=NO" not in run, (
        "a failed deploy must not be asserted as 'not executed'"
    )


def test_deploy_attempt_is_recorded_before_the_mutating_command() -> None:
    _assert_deploy_attempt_evidence(_deploy_run())


def test_successful_deploy_records_attempt_then_execution(tmp_path) -> None:
    """Success: ATTEMPTED=YES, EXECUTED=YES, success marker=PASS."""
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]))
    assert out.failed is False, out.output
    assert out.deploy_calls == 1
    assert out.evidence["DEPLOY_ATTEMPTED"] == "YES"
    assert out.evidence["DEPLOY_EXECUTED"] == "YES"
    assert "B14_CANONICAL_PIPELINE_DEPLOY=PASS" in out.output
    assert "B14_CANONICAL_PIPELINE_DEPLOY=FAIL" not in out.output
    lines = out.evidence_text.splitlines()
    assert lines.index("DEPLOY_ATTEMPTED=YES") < lines.index("DEPLOY_EXECUTED=YES")


def test_failed_deploy_records_the_attempt_and_no_success(tmp_path) -> None:
    """deploy.sh failed: ATTEMPTED=YES, EXECUTED=UNKNOWN, no success marker.

    The anchor must survive a failed deploy -- after a deploy that started and
    failed, the pre-mutation version is exactly the version to return to.
    """
    out = _run_deploy_chain(
        tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]), deploy_fail=True
    )
    assert out.failed is True, out.output
    assert out.deploy_calls == 1, "deploy.sh was attempted; the artifact must say so"
    assert out.evidence["DEPLOY_ATTEMPTED"] == "YES"
    # Neither a false success nor a false "nothing happened".
    assert out.evidence["DEPLOY_EXECUTED"] == "UNKNOWN"
    assert out.evidence["DEPLOY_EXECUTED"] != "YES"
    assert out.evidence["DEPLOY_EXECUTED"] != "NO"
    assert "B14_CANONICAL_PIPELINE_DEPLOY=PASS" not in out.output
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == ANCHOR_VERSION
    assert out.evidence["MUTATION_CLASS"] == "DEPLOY"
    assert out.evidence_text.strip() != "", "the anchor artifact must still be publishable"
    lines = out.evidence_text.splitlines()
    assert lines.index("DEPLOY_ATTEMPTED=YES") < lines.index("DEPLOY_EXECUTED=UNKNOWN")


def test_anchor_refusal_records_no_attempt_and_no_execution(tmp_path) -> None:
    """Anchor refused: ATTEMPTED absent, EXECUTED=NO, deploy.sh calls=0."""
    out = _run_deploy_chain(
        tmp_path,
        body=_envelope_body([_served(ANCHOR_VERSION, 50), _served(WRONG_VERSION, 50)]),
    )
    _assert_no_mutation(out)
    assert out.deploy_calls == 0
    assert "DEPLOY_ATTEMPTED" not in out.evidence
    assert out.evidence["DEPLOY_EXECUTED"] == "NO"


# -- 3 to 6: every refused read is a fail-closed non-mutation ---------------


def test_malformed_or_missing_envelope_never_mutates(tmp_path) -> None:
    shapes = {
        "bare_list": json.dumps([{"versions": [_served(ANCHOR_VERSION)]}]),
        "no_success_wrapper": json.dumps(
            {"deployments": [_deployment(ANCHOR_VERSION, 100)]}
        ),
        "empty_body": "",
        "not_json": "not-json",
        "empty_deployments": _envelope_body([]),
    }
    for label, body in shapes.items():
        out = _run_deploy_chain(tmp_path / label, body=body)
        _assert_no_mutation(out)


def test_split_traffic_never_mutates(tmp_path) -> None:
    out = _run_deploy_chain(
        tmp_path,
        body=_envelope_body([_served(ANCHOR_VERSION, 50), _served(WRONG_VERSION, 50)]),
    )
    _assert_no_mutation(out)


def test_active_version_not_at_full_traffic_never_mutates(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION, 90)]))
    _assert_no_mutation(out)


def test_unsafe_version_id_never_mutates(tmp_path) -> None:
    out = _run_deploy_chain(
        tmp_path, body=_envelope_body([_served("bad id;echo " + TOKEN)])
    )
    _assert_no_mutation(out)
    assert "bad id" not in out.output, "a refused candidate must not be reflected"
    assert TOKEN not in out.output


def test_resolver_failure_never_mutates(tmp_path) -> None:
    out = _run_deploy_chain(
        tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]), curl_fail=True
    )
    _assert_no_mutation(out)


# -- 8: no secret, account id or envelope in the artifact -------------------


def test_anchor_artifact_carries_no_secret_and_no_envelope(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, body=_envelope_body([_served(ANCHOR_VERSION)]))
    for forbidden in (TOKEN, ACCOUNT_ID, "Authorization", "Bearer"):
        assert forbidden not in out.evidence_text, f"{forbidden} leaked into the artifact"
        assert forbidden not in out.output, f"{forbidden} leaked into the run log"
    for envelope_token in ("success", "versions", "result"):
        assert envelope_token not in out.evidence_text, (
            f"an envelope body leaked into the artifact: {envelope_token}"
        )
    assert out.evidence["RAW_DEPLOYMENTS_ENVELOPE_INCLUDED"] == "NO"
    assert out.evidence["SECRET_VALUES_INCLUDED"] == "NO"
    assert out.evidence["ACCOUNT_ID_INCLUDED"] == "NO"
    # Every line the artifact can carry is written through `record`, so no
    # credential-shaped literal can reach it.
    for literal in re.findall(r'record "[^"]*"', _anchor_run()):
        for forbidden in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "Authorization"):
            assert forbidden not in literal, f"recorded literal names a secret: {literal}"


# -- 9: the existing deploy / post-deploy / rollback contracts survive ------


def test_deploy_and_post_deploy_semantics_are_preserved() -> None:
    run = _deploy_run()
    assert "bash ./deploy.sh" in run, "deploy.sh must remain the canonical pipeline"
    assert "B14_CANONICAL_PIPELINE_DEPLOY=PASS" in run
    text = _workflow_text()
    for preserved in (
        "POST_DEPLOY_VERSION_AT_100=PASS",
        "ENGINE_B14_BOUND_SMOKE=PASS",
        "B14_KILO_CATALOG_MARKER=PASS",
        "B14_PRODUCTION_DEPLOY_SMOKE=PASS",
        "/workers/scripts/ai-revenue-korean-ai-platform/deployments",
    ):
        assert preserved in text, f"post-deploy contract lost: {preserved}"


def test_the_rollback_contract_from_3704_is_untouched() -> None:
    jobs = _workflow()["jobs"]
    rollback = jobs["rollback-production-b14"]
    assert rollback["if"] == (
        "github.event.inputs.confirmation == 'ROLLBACK_B14_TO_PREVIOUS_VERSION'"
    )
    # #3704's shape, unchanged: one bounded step plus one always() artifact.
    steps = rollback["steps"]
    assert len([s for s in steps if "run" in s]) == 1
    assert (
        len(
            [
                s
                for s in steps
                if str(s.get("uses", "")).startswith("actions/upload-artifact")
            ]
        )
        == 1
    )
    assert "PRE_ROLLBACK_SERVED_VERSION_ID" in steps[2]["run"]
    # The deploy job must still be unable to roll anything back on its own.
    assert "ROLLBACK" not in jobs[DEPLOY_JOB]["if"]


# -- negative controls ------------------------------------------------------
# A contract test that still passes when the guarantee is removed proves
# nothing. Each control below deletes or inverts exactly one property and
# asserts the matching predicate goes RED.


def _mutated_steps(mutator) -> list:
    jobs = copy.deepcopy(_workflow()["jobs"])
    steps = jobs[DEPLOY_JOB]["steps"]
    mutator(steps)
    return steps


def _find(steps, name: str) -> dict:
    return next(s for s in steps if s.get("name") == name)


def test_negative_control_removing_the_pre_read_goes_red() -> None:
    def mutator(steps) -> None:
        steps[:] = [s for s in steps if s.get("name") != ANCHOR_STEP]

    with pytest.raises(AssertionError):
        _assert_step_order(_mutated_steps(mutator))


def test_negative_control_reordering_the_pre_read_after_deploy_goes_red() -> None:
    def mutator(steps) -> None:
        anchor = _find(steps, ANCHOR_STEP)
        steps.remove(anchor)
        steps.insert(steps.index(_find(steps, DEPLOY_STEP)) + 1, anchor)

    with pytest.raises(AssertionError):
        _assert_step_order(_mutated_steps(mutator))


def test_negative_control_moving_the_pre_read_before_exact_main_goes_red() -> None:
    def mutator(steps) -> None:
        anchor = _find(steps, ANCHOR_STEP)
        steps.remove(anchor)
        steps.insert(steps.index(_find(steps, PREMUTATION_STEP)), anchor)

    with pytest.raises(AssertionError):
        _assert_step_order(_mutated_steps(mutator))


def test_negative_control_removing_the_artifact_step_goes_red() -> None:
    def mutator(steps) -> None:
        steps[:] = [s for s in steps if s.get("name") != ARTIFACT_STEP]

    with pytest.raises(AssertionError):
        _assert_artifact_contract(_mutated_steps(mutator))


def test_negative_control_artifact_without_always_goes_red() -> None:
    def mutator(steps) -> None:
        _find(steps, ARTIFACT_STEP)["if"] = "success()"

    with pytest.raises(AssertionError):
        _assert_artifact_contract(_mutated_steps(mutator))


def test_negative_control_silent_missing_artifact_goes_red() -> None:
    def mutator(steps) -> None:
        _find(steps, ARTIFACT_STEP)["with"]["if-no-files-found"] = "warn"

    with pytest.raises(AssertionError):
        _assert_artifact_contract(_mutated_steps(mutator))


def test_negative_control_a_second_version_authority_goes_red() -> None:
    run = _anchor_run().replace(
        "cloudflare_served_version_cli.py", "b54_engine_served_version_guard.py"
    )
    with pytest.raises(AssertionError):
        _assert_anchor_authority(run)


def test_negative_control_inline_envelope_parsing_goes_red() -> None:
    run = _anchor_run() + '\n          jq -r ".result.deployments[0]"'
    with pytest.raises(AssertionError):
        _assert_anchor_authority(run)


def test_negative_control_a_mutating_anchor_goes_red() -> None:
    run = _anchor_run() + "\n          npx wrangler@4 deploy"
    with pytest.raises(AssertionError):
        _assert_anchor_authority(run)


def _deploy_run_without_attempt() -> str:
    return "\n".join(
        line for line in _deploy_run().splitlines() if "DEPLOY_ATTEMPTED" not in line
    )


# The deploy step exactly as it stood before this correction: no attempt record,
# and the only evidence line placed AFTER the command, where `set -euo pipefail`
# destroys it the moment deploy.sh exits non-zero.
_PRE_CORRECTION_DEPLOY_RUN = """set -euo pipefail
bash ./deploy.sh 2>&1 | tee /tmp/b14-deploy.log
printf 'DEPLOY_EXECUTED=YES\\n' >> "${RUNNER_TEMP}/b14-deploy-evidence.txt"
echo 'B14_CANONICAL_PIPELINE_DEPLOY=PASS'
"""


def test_negative_control_removing_the_attempt_record_goes_red() -> None:
    with pytest.raises(AssertionError):
        _assert_deploy_attempt_evidence(_deploy_run_without_attempt())


def test_negative_control_recording_the_attempt_after_the_command_goes_red() -> None:
    """The original defect's shape: written after the command, so a failure eats it.

    Both attempt lines move, not just the printf -- an echo left above the
    command would satisfy the ordering check while still producing nothing
    durable once the step aborts.
    """
    lines = _deploy_run().splitlines()
    attempt = [line for line in lines if "DEPLOY_ATTEMPTED" in line]
    rest = [line for line in lines if "DEPLOY_ATTEMPTED" not in line]
    moved = "\n".join(rest + attempt)
    with pytest.raises(AssertionError):
        _assert_deploy_attempt_evidence(moved)


def test_negative_control_asserting_no_execution_on_failure_goes_red() -> None:
    run = _deploy_run() + (
        "\n          printf 'DEPLOY_EXECUTED=NO\\n' >> "
        '"${RUNNER_TEMP}/b14-deploy-evidence.txt"'
    )
    with pytest.raises(AssertionError):
        _assert_deploy_attempt_evidence(run)


def test_negative_control_a_failed_deploy_without_the_attempt_line_loses_the_evidence(
    tmp_path,
) -> None:
    """Execution-level restatement of the defect this correction removes.

    With the attempt line removed, a deploy that started and failed leaves an
    artifact that is indistinguishable from an anchor refusal: no attempt, no
    execution, and no way to tell Production may have been touched. The
    corrected step is run alongside it and must differ on exactly this point.
    """
    broken = _run_deploy_chain(
        tmp_path / "broken",
        body=_envelope_body([_served(ANCHOR_VERSION)]),
        deploy_fail=True,
        deploy_run_override=_PRE_CORRECTION_DEPLOY_RUN,
    )
    assert broken.deploy_calls == 1
    assert "DEPLOY_ATTEMPTED" not in broken.evidence, (
        "the defect is present: a deploy was attempted and the artifact cannot say so"
    )
    # Worse than UNKNOWN: the pre-correction step aborts before writing
    # anything at all, so the artifact cannot distinguish this from a refusal.
    assert "DEPLOY_EXECUTED" not in broken.evidence

    fixed = _run_deploy_chain(
        tmp_path / "fixed",
        body=_envelope_body([_served(ANCHOR_VERSION)]),
        deploy_fail=True,
    )
    assert fixed.deploy_calls == 1
    assert fixed.evidence["DEPLOY_ATTEMPTED"] == "YES"
    assert fixed.evidence["DEPLOY_EXECUTED"] == "UNKNOWN"
