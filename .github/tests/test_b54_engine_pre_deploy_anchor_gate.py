"""Contract tests for the Engine deploy gate's durable pre-deploy rollback anchor (#3758).

Mirrors for the Engine what #3742 / PR #3745 pinned for B14. Proves that the
deploy job:

  1. resolves the pre-deploy served version through the one canonical authority
     (``cloudflare_served_version_cli.py resolve-active``, #3656) in a read-only
     step positioned after the pre-deploy guards and immediately before the
     mutating command;
  2. records a bounded, durable anchor (version ids and verdict tokens only)
     published as an always()-on artifact with ``if-no-files-found: error``;
  3. separates the deploy ATTEMPT from the deploy OUTCOME honestly:

       anchor refused   -> DEPLOY_ATTEMPTED absent, DEPLOY_EXECUTED=NO, 0 calls
       deploy failed    -> DEPLOY_ATTEMPTED=YES, DEPLOY_EXECUTED=UNKNOWN,
                           anchor preserved (UNKNOWN, never NO: whether
                           Production changed is not knowable from an exit code)
       deploy succeeded -> DEPLOY_ATTEMPTED=YES, DEPLOY_EXECUTED=YES

  4. preserves every existing contract: the post-deploy served-version guard's
     convergence semantics (f88/#2742), the single final PASS emitter, the
     rollback job (#3737 / PR #3744), the A7 CP admission readiness step, and
     ``uv run pywrangler deploy`` as the single deploy authority.

The real step bodies are executed with stubbed curl/uv/git transport, so the
ordering and every fail-closed path are observed rather than asserted from the
YAML. No network, no wrangler, no dispatch, no Production mutation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
CONTRACT_CI = ROOT / ".github" / "workflows" / "b54-engine-deploy-gate-contract-tests.yml"
SCRIPTS_DIR = ROOT / ".github" / "scripts"
TEST_FILENAME = Path(__file__).name

DEPLOY_JOB = "deploy-production-engine"
ROLLBACK_JOB = "rollback-production-engine"
PREMUTATION_STEP = "Premutation exact-main and account assertions"
GUARD_STEP = "Pre-deploy served-version secret guard"
CP_STEP = "Pre-deploy A7 Control Plane admission readiness"
ANCHOR_STEP = "Pre-deploy canonical served-version rollback anchor"
DEPLOY_STEP = "Deploy engine to production"
POST_GUARD_STEP = "Post-deploy served-version secret guard"
SMOKE_STEP = "Post-deploy smoke"
ARTIFACT_STEP = "Publish the bounded pre-mutation anchor evidence artifact"

ANCHOR_VERSION = "bbbbbbbb-0000-0000-0000-000000000000"
TARGET_SHA = "1234567890abcdef1234567890abcdef12345678"

# The account id is pinned publicly in the workflow; the token is a sentinel.
# Both are asserted absent from the artifact, which is a stronger check than
# asserting a placeholder's absence.
ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"
TOKEN = "stub-token-not-a-secret"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow_from_text(text: str) -> dict:
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(text)
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def _workflow() -> dict:
    return _workflow_from_text(_workflow_text())


def _deploy_steps(text: str | None = None) -> list:
    source = text if text is not None else _workflow_text()
    return _workflow_from_text(source)["jobs"][DEPLOY_JOB]["steps"]


def _step(name: str, text: str | None = None) -> dict:
    for step in _deploy_steps(text):
        if step.get("name") == name:
            return step
    raise AssertionError(f"the deploy job has no step named {name!r}")


def _step_run(name: str, text: str | None = None) -> str:
    return str(_step(name, text)["run"])


def _rollback_block() -> str:
    return _workflow_text().split(f"{ROLLBACK_JOB}:", 1)[1]


def _step_window(text: str, name: str) -> tuple[int, int]:
    """The [start, end) span of one step's YAML block, including its newline."""
    start = text.index(f"      - name: {name}")
    nxt = text.find("\n      - name: ", start + 1)
    end = nxt + 1 if nxt != -1 else len(text)
    return start, end


# -- contract predicates ----------------------------------------------------
# Each one raises AssertionError on violation, so the negative controls can
# assert that a mutated workflow is genuinely rejected rather than merely
# different.


def _assert_step_order(steps) -> None:
    """premutation -> guard -> CP readiness -> anchor -> deploy -> post guard -> smoke -> artifact."""
    names = [s.get("name", "") for s in steps]
    for required in (
        PREMUTATION_STEP,
        GUARD_STEP,
        CP_STEP,
        ANCHOR_STEP,
        DEPLOY_STEP,
        POST_GUARD_STEP,
        SMOKE_STEP,
        ARTIFACT_STEP,
    ):
        assert required in names, f"missing deploy-job step: {required}"
    assert names.index(PREMUTATION_STEP) < names.index(GUARD_STEP)
    assert names.index(GUARD_STEP) < names.index(CP_STEP)
    assert names.index(CP_STEP) < names.index(ANCHOR_STEP), (
        "the anchor must be read after the CP admission readiness guard"
    )
    assert names.index(ANCHOR_STEP) < names.index(DEPLOY_STEP), (
        "the pre-deploy read must run before the mutating command"
    )
    assert names.index(DEPLOY_STEP) < names.index(POST_GUARD_STEP)
    assert names.index(POST_GUARD_STEP) < names.index(SMOKE_STEP), (
        "f88: the post-deploy guard is GET-only evidence and must precede the smoke"
    )
    assert names.index(SMOKE_STEP) < names.index(ARTIFACT_STEP)


def _assert_anchor_authority(run: str) -> None:
    assert "cloudflare_served_version_cli.py" in run, "canonical adapter not reused"
    assert "resolve-active" in run
    # A second served-version authority could disagree with the canonical one;
    # the Engine-branded adapter prints its own tokens, so borrowing it here
    # would also couple the anchor to another consumer's output contract.
    assert "b54_engine_served_version_guard.py" not in run
    # INLINE_JQ_NEW=0 / SECOND_VERSION_AUTHORITY=0.
    for forbidden in ("jq", 'result["deployments"]', ".versions[", "python3 -c"):
        assert forbidden not in run, f"shell-side envelope parsing survived: {forbidden}"
    # The step sits before the mutation, so it must be structurally incapable
    # of performing one.
    for mutating in ("wrangler", "uv run", "deploy.sh", "npx "):
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
    assert upload["with"]["path"].endswith("b54-engine-deploy-evidence.txt")
    assert "deployments" not in upload["with"]["path"], (
        "raw envelopes are not a publishable artifact"
    )


# -- execution harness ------------------------------------------------------

# The anchor step runs from the workspace root (no working-directory), so its
# relative `.github/scripts/...` adapter call resolves there; the harness copies
# the real scripts into the fake workspace so the REAL resolver CLI runs.
#
# PATH must be prepended in the shell's own native form. A drive-letter entry is
# accepted for redirection but is skipped during command lookup, which silently
# leaves the real `curl` on PATH -- so the resolver check below is not ceremony:
# without it a stubbing mistake turns into an outbound request, and the negative
# assertions would pass for the wrong reason.
_DRIVER = """#!/usr/bin/env bash
set -uo pipefail
for stubbed in curl uv git python3; do
  chmod +x "${STUB_DIR}/${stubbed}"
done
STUB_NATIVE="$(cd "${STUB_DIR}" && pwd)"
export PATH="${STUB_NATIVE}:${PATH}"
for stubbed in curl uv git python3; do
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

_STUB_GIT = """#!/usr/bin/env bash
# The premutation step calls `git rev-parse` and `git fetch`. Both are stubbed so
# no network and no real repository state can influence the ordering proof.
if [ "$1" = "rev-parse" ]; then
  printf '%s\\n' "${GIT_HEAD_SHA:-}"
  exit 0
fi
exit 0
"""

_STUB_CURL = """#!/usr/bin/env bash
set -uo pipefail
out=""
prev=""
for arg in "$@"; do
  if [ "${prev}" = "-o" ]; then out="${arg}"; fi
  prev="${arg}"
done
if [ -n "${CURL_FAIL:-}" ]; then
  echo 'curl: (7) stub transport refused' >&2
  exit 7
fi
case "${STUB_ENVELOPE_MODE:-canonical}" in
  canonical)
    printf '%s' "${BODY_DEFAULT}" > "${out}"
    ;;
  bare_list)
    printf '%s' '[{"id":"d1","source":"wrangler"}]' > "${out}"
    ;;
  no_success)
    printf '%s' '{"result":{"deployments":[{"versions":[{"version_id":"aaaaaaaa-0000-0000-0000-000000000000","percentage":100}]}]}}' > "${out}"
    ;;
  empty_deployments)
    printf '%s' '{"success":true,"result":{"deployments":[]}}' > "${out}"
    ;;
  split_traffic)
    printf '%s' '{"success":true,"result":{"deployments":[{"versions":[{"version_id":"aaaaaaaa-0000-0000-0000-000000000000","percentage":50},{"version_id":"bbbbbbbb-0000-0000-0000-000000000000","percentage":50}]}]}}' > "${out}"
    ;;
  unsafe_id)
    printf '%s' '{"success":true,"result":{"deployments":[{"versions":[{"version_id":"bad id;rm","percentage":100}]}]}}' > "${out}"
    ;;
  garbage)
    printf 'not-json-at-all' > "${out}"
    ;;
esac
exit 0
"""

_STUB_UV = """#!/usr/bin/env bash
# The deploy command stub. The invocation is counted BEFORE anything else, so a
# started-but-failed deploy is distinguishable from a never-started one.
printf 'DEPLOY_COMMAND_INVOKED\\n' >> "${RUNNER_TEMP}/deploy-invocations.txt"
if [ -n "${DEPLOY_FAIL:-}" ]; then
  echo 'stub deploy command failed' >&2
  exit 1
fi
echo 'stub deploy command ok'
exit 0
"""


# The interpreter running these tests, in the path form MSYS bash accepts.
_NATIVE_PYTHON3 = sys.executable.replace("\\", "/")

# python3 is NOT behavior-stubbed: the shim delegates to the interpreter
# running these tests, so the anchor step executes the REAL canonical resolver
# CLI. It exists because a Windows python3 alias on PATH can carry
# machine-specific interpreter flags (one local shim runs with safe_path,
# which drops the script directory from sys.path and breaks the CLI's own
# sibling import); delegating pins the interpreter to the one this suite
# already validated. CI's python3 would behave identically without the shim.
_PYTHON3_SHIM = f'''#!/usr/bin/env bash
exec "{_NATIVE_PYTHON3}" "$@"
'''


class _Chain:
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
        # One line per deploy-command invocation, so "never reached" and
        # "reached and failed" are distinguishable counts, not a bare boolean.
        self.deploy_calls = (
            len([ln for ln in deploy_invocations.splitlines() if ln.strip()])
            if deploy_invocations
            else 0
        )

    @property
    def mutated(self) -> bool:
        return self.deploy_calls > 0


def _canonical_envelope(version_id: str) -> str:
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
                        "versions": [{"version_id": version_id, "percentage": 100}],
                    }
                ]
            },
        }
    )


def _run_deploy_chain(
    tmp_path,
    *,
    curl_fail: bool = False,
    deploy_fail: bool = False,
    envelope_mode: str = "canonical",
    served_version: str = ANCHOR_VERSION,
    deploy_body_override: str | None = None,
) -> _Chain:
    root = tmp_path / "lane"
    stub = root / "bin"
    runner_temp = root / "runner-temp"
    workspace = root / "workspace"
    steps_dir = root / "steps"
    for directory in (stub, runner_temp, workspace, steps_dir):
        directory.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("curl", _STUB_CURL),
        ("uv", _STUB_UV),
        ("git", _STUB_GIT),
        ("python3", _PYTHON3_SHIM),
    ):
        (stub / name).write_text(text, encoding="utf-8", newline="\n")
    # The anchor step addresses the canonical adapter relatively, from the
    # workspace root; give the fake workspace the real scripts so the REAL
    # resolver runs (reuse, not reimplementation, is the contract under test).
    scripts = workspace / ".github" / "scripts"
    shutil.copytree(SCRIPTS_DIR, scripts)
    app = workspace / "apps" / "padiem-ai-engine"
    app.mkdir(parents=True, exist_ok=True)

    deploy_body = (
        _step_run(DEPLOY_STEP) if deploy_body_override is None else deploy_body_override
    )
    chain = (
        ("00-premutation", _step_run(PREMUTATION_STEP), workspace),
        ("01-anchor", _step_run(ANCHOR_STEP), workspace),
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
    driver.write_text(_DRIVER, encoding="utf-8", newline="\n")

    env = {
        **os.environ,
        "STUB_DIR": _native(stub),
        "STEPS_DIR": _native(steps_dir),
        "RUNNER_TEMP": _native(runner_temp),
        "GITHUB_WORKSPACE": _native(workspace),
        "GIT_HEAD_SHA": TARGET_SHA,
        "B54_TARGET_SHA": TARGET_SHA,
        "CLOUDFLARE_API_TOKEN": TOKEN,
        "CLOUDFLARE_ACCOUNT_ID": ACCOUNT_ID,
        "STUB_SERVED_VERSION": served_version,
        "BODY_DEFAULT": _canonical_envelope(served_version),
        "STUB_ENVELOPE_MODE": envelope_mode,
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
    evidence_file = runner_temp / "b54-engine-deploy-evidence.txt"
    invocations = runner_temp / "deploy-invocations.txt"
    return _Chain(
        result,
        evidence_file.read_text(encoding="utf-8") if evidence_file.exists() else "",
        invocations.read_text(encoding="utf-8") if invocations.exists() else None,
    )


def _assert_no_mutation(out: _Chain) -> None:
    """PRODUCTION_MUTATION=0 for every refused-anchor shape.

    A refusal is the one case where DEPLOY_EXECUTED=NO is truthful, because the
    deploy step provably never ran -- hence deploy calls == 0 and no attempt
    line at all.
    """
    assert out.failed is True, out.output
    assert out.mutated is False, "the deploy command ran without a confirmed anchor"
    assert out.deploy_calls == 0, "the deploy command was invoked without a confirmed anchor"
    assert out.evidence["DEPLOY_EXECUTED"] == "NO"
    assert "DEPLOY_ATTEMPTED" not in out.evidence, (
        "an attempt was recorded even though the anchor refused"
    )
    # A version that was never confirmed must not be recorded, and no PASS
    # token may be emitted for an anchor that does not exist.
    assert "PRE_DEPLOY_SERVED_VERSION_ID" not in out.evidence
    assert "PRE_MUTATION_VERSION_CAPTURED" not in out.evidence
    assert "ROLLBACK_ANCHOR_AVAILABLE" not in out.evidence
    assert "B54_PRE_DEPLOY_ANCHOR=PASS" not in out.output
    assert "B54_ENGINE_DEPLOY_COMMAND=EXIT_ZERO" not in out.output


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
    """A path form both MSYS bash and a Windows interpreter can open."""
    return str(path).replace("\\", "/")


# -- 1: the read runs before the mutating command, and the artifact proves it


def test_deploy_job_step_order_matches_the_mutation_contract() -> None:
    """Static half of the ordering guarantee.

    The execution test below drives the steps in the contract's order by name,
    so it cannot detect a workflow that declares them in the wrong order. This
    is the assertion that does.
    """
    _assert_step_order(_deploy_steps())


def test_pre_deploy_read_runs_before_the_deploy_command(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path)
    assert out.failed is False, out.output
    assert out.mutated is True
    assert "B54_PRE_DEPLOY_ANCHOR=PASS" in out.output
    assert "B54_ENGINE_DEPLOY_COMMAND=EXIT_ZERO" in out.output
    # The final production PASS marker belongs to the post-deploy guard step
    # only (f88); a harness run never reaches it.
    assert "B54_ENGINE_PRODUCTION_DEPLOY=PASS" not in out.output
    # The anchor line is written by the pre-deploy step, DEPLOY_ATTEMPTED by
    # the deploy step before the command, and DEPLOY_EXECUTED on completion --
    # so the artifact's own line order is the execution order.
    lines = out.evidence_text.splitlines()
    anchor = lines.index(f"PRE_DEPLOY_SERVED_VERSION_ID={ANCHOR_VERSION}")
    attempt = lines.index("DEPLOY_ATTEMPTED=YES")
    executed = lines.index("DEPLOY_EXECUTED=YES")
    assert anchor < attempt < executed


def test_anchor_evidence_is_durable_and_bounded(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path)
    assert out.failed is False, out.output
    assert out.evidence["MUTATION_CLASS"] == "DEPLOY"
    assert out.evidence["B54_ENGINE_WORKER_SCRIPT"] == "padiem-ai-engine"
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == ANCHOR_VERSION
    assert out.evidence["PRE_MUTATION_VERSION_CAPTURED"] == "YES"
    assert out.evidence["SOURCE_MAIN_SHA"] == TARGET_SHA
    assert out.evidence["ROLLBACK_ANCHOR_AVAILABLE"] == "YES"
    assert out.evidence["ANCHOR_PREPARED_BEFORE_DEPLOY"] == "YES"
    assert out.evidence["DEPLOY_ATTEMPTED"] == "YES"
    assert out.evidence["DEPLOY_EXECUTED"] == "YES"
    assert out.deploy_calls == 1


def test_anchor_accepts_a_canonical_leading_hyphen_version(tmp_path) -> None:
    # The canonical charset rule allows a leading hyphen; the anchor must
    # record whatever the canonical authority confirmed, and nothing else.
    out = _run_deploy_chain(tmp_path, served_version="-lead-0000-0000-0000-00000000")
    assert out.failed is False, out.output
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == "-lead-0000-0000-0000-00000000"


# -- 2: only a successful canonical envelope anchors (fail closed) ----------


def test_curl_transport_failure_deploys_nothing(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, curl_fail=True)
    _assert_no_mutation(out)


@pytest.mark.parametrize(
    "envelope_mode",
    ["bare_list", "no_success", "empty_deployments", "split_traffic", "garbage"],
)
def test_malformed_envelopes_deploy_nothing(tmp_path, envelope_mode: str) -> None:
    out = _run_deploy_chain(tmp_path, envelope_mode=envelope_mode)
    _assert_no_mutation(out)


def test_unsafe_version_id_is_refused_and_never_echoed(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, envelope_mode="unsafe_id")
    _assert_no_mutation(out)
    # The CLI never reflects a rejected candidate into its output.
    assert "bad id;rm" not in out.output


# -- 3: the attempt and the outcome are separable, and honest about it ------


def test_failed_deploy_keeps_the_anchor_and_records_unknown(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path, deploy_fail=True)
    assert out.failed is True, out.output
    # The command STARTED: the invocation counter distinguishes "reached and
    # failed" from "never reached", which a boolean cannot.
    assert out.deploy_calls == 1
    assert out.evidence["DEPLOY_ATTEMPTED"] == "YES"
    # Whether Production actually changed is not knowable from an exit code,
    # so the artifact records UNKNOWN -- never YES, and never NO.
    assert out.evidence["DEPLOY_EXECUTED"] == "UNKNOWN"
    # The anchor survives: this is exactly the run that needs it.
    assert out.evidence["ROLLBACK_ANCHOR_AVAILABLE"] == "YES"
    assert out.evidence["PRE_DEPLOY_SERVED_VERSION_ID"] == ANCHOR_VERSION
    assert out.evidence["PRE_MUTATION_VERSION_CAPTURED"] == "YES"
    assert "B54_ENGINE_DEPLOY_COMMAND=FAIL" in out.output
    assert "B54_ENGINE_DEPLOY_COMMAND=EXIT_ZERO" not in out.output
    assert "B54_ENGINE_PRODUCTION_DEPLOY=PASS" not in out.output


def test_attempt_is_recorded_before_the_mutating_command() -> None:
    deploy_run = _step_run(DEPLOY_STEP)
    assert "uv run pywrangler deploy" in deploy_run
    assert deploy_run.index("DEPLOY_ATTEMPTED=YES") < deploy_run.index(
        "uv run pywrangler deploy"
    ), "the attempt record must precede the mutating command, not follow it"


# -- 4: the artifact never carries secrets or envelopes ----------------------


def test_anchor_artifact_carries_no_secret_and_no_envelope(tmp_path) -> None:
    out = _run_deploy_chain(tmp_path)
    assert out.failed is False, out.output
    assert TOKEN not in out.evidence_text
    assert ACCOUNT_ID not in out.evidence_text
    assert "Authorization" not in out.evidence_text
    assert "Bearer" not in out.evidence_text
    # No raw API envelope: the JSON shape keys never reach the artifact.
    assert '"percentage"' not in out.evidence_text
    assert '"deployments"' not in out.evidence_text


# -- 5: preserved semantics --------------------------------------------------


def test_anchor_step_is_read_only_and_reuses_the_canonical_authority() -> None:
    run = _step_run(ANCHOR_STEP)
    _assert_anchor_authority(run)
    # The served-version source is the documented REST deployments endpoint:
    # the base URL and the resource path are separate shell strings in the
    # step, so both halves are asserted where they actually appear.
    assert "/workers/scripts/padiem-ai-engine" in run
    assert '"${base}/deployments"' in run
    assert "wrangler@4 deployments list" not in run, (
        "the undocumented wrangler bare-list must not be the served-version source"
    )
    anchor = _step(ANCHOR_STEP)
    assert "working-directory" not in anchor, (
        "the anchor addresses the relative adapter from the workspace root"
    )
    assert "--max-time 30" in run, "the pre-deploy read is time-bounded"


def test_deploy_step_keeps_the_single_deploy_authority_and_command_evidence() -> None:
    deploy = _step(DEPLOY_STEP)
    run = str(deploy["run"])
    assert deploy["working-directory"] == "apps/padiem-ai-engine"
    assert "uv run pywrangler deploy" in run
    # f88: command evidence only; the final PASS marker is emitted elsewhere.
    assert "B54_ENGINE_DEPLOY_COMMAND=EXIT_ZERO" in run
    assert "B54_ENGINE_PRODUCTION_DEPLOY=PASS" not in run
    assert "DEPLOY_EXECUTED=UNKNOWN" in run
    assert "B54_ENGINE_DEPLOY_COMMAND=FAIL" in run


def test_final_deploy_pass_marker_is_emitted_exactly_once() -> None:
    text = _workflow_text()
    assert text.count("echo 'B54_ENGINE_PRODUCTION_DEPLOY=PASS'") == 1
    guard_run = _step_run(POST_GUARD_STEP)
    assert guard_run.index("POST_DEPLOY_SERVED_VERSION_GUARD=PASS") < guard_run.index(
        "B54_ENGINE_PRODUCTION_DEPLOY=PASS"
    )


def test_post_deploy_served_version_guard_semantics_are_untouched() -> None:
    guard_run = _step_run(POST_GUARD_STEP)
    assert 'pre_version="${B54_ENGINE_ACTIVE_VERSION:-}"' in guard_run
    assert "for attempt in $(seq 1 30)" in guard_run
    assert guard_run.count("resolve-active") == 1, (
        "the #2414 contract counts one resolution site inside the poll loop"
    )
    assert "SERVED_VERSION_CHANGED_BY_CODE_DEPLOY=YES" in guard_run
    assert "POST_DEPLOY_SERVED_VERSION_CONVERGED=FAIL" in guard_run


def test_pre_deploy_guard_and_cp_readiness_steps_are_untouched() -> None:
    guard_run = _step_run(GUARD_STEP)
    assert "PREMUTATION_SERVED_VERSION_GUARD=PASS" in guard_run
    assert "b54_engine_served_version_guard.py resolve-active" in guard_run
    cp_run = _step_run(CP_STEP)
    assert "CP_ADMISSION_SERVED_VERSION_RESOLVER=CANONICAL" in cp_run
    assert "pywrangler deploy" not in cp_run


def test_engine_rollback_job_contract_is_untouched() -> None:
    block = _rollback_block()
    assert 'validate-version-id --version-id="${ROLLBACK_TARGET}"' in block
    assert 'npx wrangler@4 rollback "${ROLLBACK_TARGET}"' in block
    assert "--class ROLLBACK" in block
    assert "POST_ROLLBACK_SERVED_EQUALS_TARGET=PASS" in block
    assert "REASON=rollback_version_id is required; implicit previous-version selection is refused" in block


def test_premutation_assertions_are_untouched() -> None:
    run = _step_run(PREMUTATION_STEP)
    assert 'test "$(git rev-parse HEAD)"' in run
    assert 'test "$(git rev-parse origin/main)"' in run
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in run


def test_smoke_idempotency_job_is_untouched() -> None:
    wf = _workflow()
    assert "smoke-idempotency" in wf["jobs"]
    assert wf["jobs"]["smoke-idempotency"]["needs"] == DEPLOY_JOB


def test_artifact_step_contract() -> None:
    _assert_artifact_contract(_deploy_steps())


def test_contract_ci_hosts_the_new_test_file() -> None:
    text = CONTRACT_CI.read_text(encoding="utf-8")
    paths_block = text.split("pull_request:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert f'      - ".github/tests/{TEST_FILENAME}"' in paths_block
    pytest_step = text.split("Run gate contract tests", 1)[1]
    assert f".github/tests/{TEST_FILENAME}" in pytest_step


# -- 6: negative controls -- a mutated workflow is rejected, not different ---


def test_nc_removing_the_anchor_step_turns_the_ordering_contract_red() -> None:
    text = _workflow_text()
    start, end = _step_window(text, ANCHOR_STEP)
    doctored = text[:start] + text[end:]
    with pytest.raises(AssertionError):
        _assert_step_order(_deploy_steps(doctored))


def test_nc_moving_the_anchor_after_the_deploy_turns_the_ordering_contract_red() -> None:
    text = _workflow_text()
    start, end = _step_window(text, ANCHOR_STEP)
    block = text[start:end]
    moved = text[:start] + text[end:]
    pos = moved.index(f"      - name: {POST_GUARD_STEP}")
    doctored = moved[:pos] + block + moved[pos:]
    with pytest.raises(AssertionError):
        _assert_step_order(_deploy_steps(doctored))


def test_nc_silent_missing_artifact_turns_the_artifact_contract_red() -> None:
    doctored = _workflow_text().replace(
        "\n          if-no-files-found: error", "\n          if-no-files-found: warn", 1
    )
    assert doctored != _workflow_text(), "the artifact guard line was not found to mutate"
    with pytest.raises(AssertionError):
        _assert_artifact_contract(_deploy_steps(doctored))


def test_nc_success_only_artifact_turns_the_artifact_contract_red() -> None:
    doctored = _workflow_text().replace(
        "      - name: Publish the bounded pre-mutation anchor evidence artifact\n        if: always()",
        "      - name: Publish the bounded pre-mutation anchor evidence artifact\n        if: success()",
        1,
    )
    assert doctored != _workflow_text(), "the artifact step condition was not found to mutate"
    with pytest.raises(AssertionError):
        _assert_artifact_contract(_deploy_steps(doctored))


def test_nc_second_version_authority_turns_the_authority_contract_red() -> None:
    anchor_run = _step_run(ANCHOR_STEP)
    doctored = anchor_run.replace(
        "cloudflare_served_version_cli.py", "b54_engine_served_version_guard.py", 1
    )
    with pytest.raises(AssertionError):
        _assert_anchor_authority(doctored)


def test_nc_inline_envelope_parsing_turns_the_authority_contract_red() -> None:
    anchor_run = _step_run(ANCHOR_STEP)
    doctored = anchor_run + '\n          jq -e ".success" "${pre_deployments}"\n'
    with pytest.raises(AssertionError):
        _assert_anchor_authority(doctored)


def test_nc_mutating_anchor_step_turns_the_authority_contract_red() -> None:
    anchor_run = _step_run(ANCHOR_STEP)
    doctored = anchor_run + "\n          uv run pywrangler deploy\n"
    with pytest.raises(AssertionError):
        _assert_anchor_authority(doctored)


def test_nc_missing_attempt_record_is_visible_in_a_failed_deploy(tmp_path) -> None:
    """The honesty control: a deploy body that records no attempt produces an
    artifact that cannot distinguish a failed deploy from a refused anchor.
    This is exactly the #3742 round-1 defect; the contract must keep detecting
    it. The doctored body is run in memory; the workflow file is not touched.
    """
    deploy_run = _step_run(DEPLOY_STEP)
    stripped = deploy_run.replace(
        'printf \'DEPLOY_ATTEMPTED=YES\\n\' >> "${RUNNER_TEMP}/b54-engine-deploy-evidence.txt"\n',
        "",
        1,
    ).replace("          echo 'DEPLOY_ATTEMPTED=YES'\n", "", 1)
    assert stripped != deploy_run, "the attempt record was not found to remove"
    out = _run_deploy_chain(tmp_path, deploy_fail=True, deploy_body_override=stripped)
    assert out.failed is True, out.output
    assert out.deploy_calls == 1
    assert "DEPLOY_ATTEMPTED" not in out.evidence
    assert out.evidence["DEPLOY_EXECUTED"] == "UNKNOWN"
