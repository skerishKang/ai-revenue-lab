"""Contract tests for the B64 production deploy gate (#987).

The gate exists because the live b64-ai-reward-router Worker was measured on
2026-10-27 to still serve the 2026-10-23 P0 shell while everything merged since
(#5816 #5819 #5820 #5825 #5831 #5946) sat undeployed — and the repository had no
B64 deploy path to close that gap. These tests prove statically that the new
path cannot over-reach:

  1. it is dispatch-only, so a pull request can never mutate the running Worker;
  2. deploy and rollback each need their own exact confirmation phrase;
  3. it pins the Charliekant account and the exact merged main SHA before any
     mutation;
  4. it refuses a config that declares routes or DNS of its own;
  5. it builds and tests the exact revision it uploads;
  6. it reuses the canonical served-version resolver instead of inventing one,
     and never reads `wrangler deployments list`;
  7. a failed post-deploy verification rolls the anchor back automatically;
  8. it reads bindings by name and type only — no secret value path;
  9. it names what it did not do, so a green run is not read as a full
     production activation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b64-cloudflare-worker-production-deploy-gate.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data.get("on", data.get(True))
    return {"triggers": triggers, "jobs": data["jobs"], "data": data}


def test_gate_file_exists_and_parses() -> None:
    assert WORKFLOW.is_file(), "the B64 deploy gate must exist for CENTRAL to deploy"
    assert isinstance(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), dict)


def test_gate_is_dispatch_only(workflow: dict) -> None:
    assert set(workflow["triggers"]) == {"workflow_dispatch"}, (
        "an ordinary push or pull request must never reach a production Worker"
    )
    inputs = workflow["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation", "rollback_version_id"}
    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert inputs["rollback_version_id"]["required"] is False


def test_concurrency_does_not_cancel_a_running_mutation(workflow: dict) -> None:
    concurrency = workflow["data"]["concurrency"]
    assert concurrency["group"] == "b64-production-deploy"
    assert concurrency["cancel-in-progress"] is False, (
        "cancelling mid-deploy can leave the Worker on an unverified revision"
    )


def test_deploy_and_rollback_are_mutually_exclusive_phrases(workflow: dict) -> None:
    deploy = workflow["jobs"]["deploy-production-b64"]["if"]
    rollback = workflow["jobs"]["rollback-b64"]["if"]
    assert "DEPLOY_B64_AI_REWARD_ROUTER" in deploy
    assert "ROLLBACK_B64_TO_EXACT_VERSION" not in deploy
    assert "ROLLBACK_B64_TO_EXACT_VERSION" in rollback
    assert "DEPLOY_B64_AI_REWARD_ROUTER" not in rollback
    # A deploy dispatch that also names a rollback version is ambiguous, so it
    # must be refused rather than guessed at.
    assert "rollback_version_id == ''" in deploy
    assert "rollback_version_id != ''" in rollback


@pytest.mark.parametrize("job", ["deploy-production-b64", "rollback-b64"])
def test_both_mutation_jobs_require_the_production_environment(workflow: dict, job: str) -> None:
    assert workflow["jobs"][job]["environment"] == "production"


def test_deploy_asserts_exact_main_and_account_before_mutating(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    premutation = next(s for s in steps if "Premutation" in s.get("name", ""))
    run = premutation["run"]
    assert 'test "$(git rev-parse HEAD)"' in run
    assert 'test "$(git rev-parse origin/main)"' in run
    assert "CHARLIEKANT_ACCOUNT_ID" in run
    assert "ACCOUNT_SCOPE_MISMATCH=YES" in run
    # Everything that can change the Worker must come after this assertion.
    order = [s.get("name", "") for s in steps]
    assert order.index("Premutation exact-main and account assertions") < next(
        i for i, name in enumerate(order) if "deploy" in name.lower() and "Dry-run" not in name
    )


def test_deploy_refuses_a_config_that_declares_routes_or_dns(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    guard = next(s for s in steps if "reviewed deployment target" in s.get("name", ""))
    run = guard["run"]
    for forbidden in ("routes", "domain", "custom_domains", "zone_name"):
        assert forbidden in run, f"the guard must refuse a declared {forbidden}"
    assert "workers_dev" in run
    # The D1 binding must point at a provisioned database, not the zero
    # placeholder, or income storage fails closed on every request.
    assert "zero placeholder" in run
    assert "B64_INCOME_DB" in run
    # Independence (owner decision 2026-10-27): B64 binds no other product.
    assert "must declare no service bindings" in run
    assert "B64_PUBLIC_BASE_URL" in run


def test_deploy_builds_and_tests_the_exact_revision(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    build = next(s for s in steps if "Build and test" in s.get("name", ""))
    for command in ("npm ci", "npm run build", "npm run typecheck", "npm test"):
        assert command in build["run"]
    order = [s.get("name", "") for s in steps]
    assert order.index("Build and test the exact revision being deployed") < next(
        i for i, name in enumerate(order) if name.startswith("Read the rollback anchor")
    )


def test_deploy_dry_runs_before_uploading(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    order = [s.get("name", "") for s in steps]
    dry = next(i for i, name in enumerate(order) if "Dry-run" in name)
    upload = next(i for i, name in enumerate(order) if name.startswith("Read the rollback anchor"))
    assert dry < upload
    dry_step = next(s for s in steps if "Dry-run" in s.get("name", ""))
    assert "deploy --dry-run" in dry_step["run"]


def test_gate_reuses_the_canonical_served_version_resolver(workflow_text: str) -> None:
    assert "cloudflare_served_version_cli.py" in workflow_text
    assert "resolve-active" in workflow_text
    assert "validate-version-id" in workflow_text
    # `wrangler deployments list` is not a served-version authority: superseded
    # deployments still record 100% in their own history.
    assert "deployments list" not in workflow_text


def test_failed_verification_rolls_the_anchor_back(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    deploy = next(s for s in steps if s.get("name", "").startswith("Read the rollback anchor"))
    assert "restore()" in deploy["run"]
    assert "wrangler@4 rollback" in deploy["run"]
    assert "B64_SERVED_VERSION_MISMATCH" in deploy["run"]
    parity = next(s for s in steps if "public host" in s.get("name", ""))
    assert "trap restore ERR" in parity["run"], (
        "a revision that fails the live parity checks must not stay serving traffic"
    )


def test_parity_checks_cover_every_merged_surface(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    parity = next(s for s in steps if "public host" in s.get("name", ""))["run"]
    # Each merged slice that the 2026-10-23 shell is missing must be named, so a
    # red run points at the revision that failed to land.
    for marker in (
        "/healthz",
        "data-theme",
        "theme-toggle",
        "수익 기회 보기",
        "INCOME_PIPELINE",
        "/income",
        "/detail?id=pub-prolific-participate",
        "form-action 'self'",
        "B64 계정으로 이용할 수 있습니다",
        'action="/join"',
    ):
        assert marker in parity, f"the parity step must verify {marker}"


def test_secret_values_are_never_read_or_printed(workflow_text: str) -> None:
    assert not re.search(r"wrangler[^\n]*secret\s+(get|list)", workflow_text), (
        "secret values are write-only; a read attempt is a misuse of the API"
    )
    assert "secret put" not in workflow_text, (
        "registering PADIEM_SESSION_SECRET belongs to b64-session-secret-activation-gate.yml"
    )
    readback = next(
        line for line in workflow_text.splitlines() if "Read back live bindings" in line
    )
    assert "names and types only" in readback.lower()
    assert "LIVE_BINDING_NAMES" in workflow_text


def test_every_cloudflare_calling_step_declares_its_own_credentials(workflow: dict) -> None:
    """A step does not inherit env from its siblings (#5853 CENTRAL review).

    On a clean runner a missing token makes wrangler fall back to an interactive
    OAuth prompt, so the mutation either hangs or fails after the upload already
    happened — which is exactly when a rollback must be guaranteed to work.
    """
    offenders = []
    for job_id, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            run = step.get("run", "")
            needs_token = "api.cloudflare.com" in run or "wrangler@4 rollback" in run
            if not needs_token:
                continue
            env = step.get("env", {}) or {}
            if "CLOUDFLARE_API_TOKEN" not in env:
                offenders.append(f"{job_id} / {step.get('name')}")
    assert not offenders, "steps that call Cloudflare must declare CLOUDFLARE_API_TOKEN: " + "; ".join(offenders)


def test_every_step_script_is_shell_valid(workflow: dict) -> None:
    """`bash -n` on each run block, because a heredoc or quote slip inside a
    YAML literal is otherwise discovered at the moment the gate is mutating the
    production Worker."""
    import shutil
    import subprocess
    import tempfile

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available on this runner")
    from pathlib import Path

    failures = []
    for job_id, job in workflow["jobs"].items():
        for index, step in enumerate(job.get("steps", [])):
            run = step.get("run")
            if not run:
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as handle:
                handle.write(run)
                script = Path(handle.name)
            try:
                result = subprocess.run(
                    [bash, "-n", str(script)], capture_output=True, text=True, timeout=30
                )
            finally:
                script.unlink(missing_ok=True)
            if result.returncode != 0:
                failures.append(f"{job_id} step {index} ({step.get('name')}): {result.stderr.strip()}")
    assert not failures, "invalid shell in the gate: " + " | ".join(failures)


def test_binding_readback_fails_closed_on_declared_binding_drift(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    readback = next(s for s in steps if "Read back live bindings" in s.get("name", ""))["run"]
    assert "B64_BINDING_PARITY=" in readback
    assert "sys.exit(1)" in readback, "a binding the baseline declares must not go missing silently"
    assert "if missing:" in readback, (
        "every declared binding is load-bearing for authentication or storage, so "
        "none of them may be excused at readback time"
    )
    assert "PADIEM_SESSION_SECRET" not in readback, (
        "B64 holds no signing secret; a stale exception would hide a real gap"
    )
    assert "BINDING_BASELINE=EVIDENCE_ONLY" in readback, (
        "section 8: the readback is evidence; the baseline amendment is its own reviewed PR"
    )
    assert "B64_SESSION_SECRET_BINDING=" in readback, (
        "the owner-minted session key is not a wrangler-declared binding, so the "
        "gate must name its status instead of leaving login silently unavailable"
    )


def test_gate_declares_what_it_did_not_do(workflow: dict) -> None:
    steps = workflow["jobs"]["deploy-production-b64"]["steps"]
    record = next(s for s in steps if "did and did not prove" in s.get("name", ""))["run"]
    for claim in (
        "B64_ZONE_ROUTE_CREATED=NO",
        "B64_D1_PROVISIONED_BY_THIS_GATE=NO",
        "B64_SESSION_SECRET_REGISTERED_BY_THIS_GATE=NO",
        "B64_SIGNED_SESSION_E2E=NOT_RUN",
    ):
        assert claim in record, f"the run summary must keep {claim} visible"


def test_gate_targets_only_the_b64_worker(workflow_text: str) -> None:
    names = set(re.findall(r"--name\s+\"?([A-Za-z0-9_./${}:-]+)\"?", workflow_text))
    for value in names:
        assert value in {"${B64_WORKER}", "b64-ai-reward-router"}, value
    assert "B64_WORKER: b64-ai-reward-router" in workflow_text
    # Another product's Worker must never be a target of this file.
    for other in ("padiem-chat", "padiem-ai-engine", "ai-revenue-korean-ai-platform"):
        assert f"--name {other}" not in workflow_text
        assert f"--name \"{other}\"" not in workflow_text
