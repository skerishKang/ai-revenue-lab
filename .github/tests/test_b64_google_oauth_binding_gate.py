"""Contract tests for the B64 independent-identity activation gate (#987).

This gate is the only reviewed path that touches B64's production D1 schema and
B64's production credential bindings. It was added by #5975 and extended twice:
#5989 made it apply the additive Google identity table and report the Google
bindings, and this revision makes it BIND B64's own Google OAuth client from the
`production` environment secrets, because the repository had no path at all from
a registered Google credential to the running Worker.

What these tests pin, statically:

  1. the gate stays dispatch-only behind an exact confirmation phrase, on the
     `production` environment, with no cancellation mid-mutation;
  2. the premutation assertions (exact main SHA, designated Cloudflare account)
     are still there, so a PR can never reach production state;
  3. the D1 half stays additive — both migrations applied, no destructive
     statement anywhere, and the row count is compared before and after;
  4. the Google half moves values only from an `env:` mapping into stdin of
     `wrangler secret put`, and a failed binding fails the run;
  5. a credential value can never be echoed, written into the workspace, or
     placed in a command line the runner prints;
  6. the gate still deploys no Worker revision and creates no OAuth client, and
     says so in its own completion boundary;
  7. every shell block is syntactically valid.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b64-independent-identity-activation-gate.yml"

GOOGLE_SECRET_NAMES = ("B64_GOOGLE_CLIENT_ID", "B64_GOOGLE_CLIENT_SECRET")
GOOGLE_ENV_VARS = ("GOOGLE_CLIENT_ID_VALUE", "GOOGLE_CLIENT_SECRET_VALUE")


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def data() -> dict:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "the gate must be a mapping"
    return loaded


@pytest.fixture(scope="module")
def job(data: dict) -> dict:
    jobs = data["jobs"]
    assert list(jobs) == ["activate"], "this gate owns exactly one mutation job"
    return jobs["activate"]


@pytest.fixture(scope="module")
def steps(job: dict) -> list[dict]:
    return job["steps"]


@pytest.fixture(scope="module")
def run_blocks(steps: list[dict]) -> list[tuple[str, str]]:
    return [(step.get("name", ""), step["run"]) for step in steps if step.get("run")]


def test_gate_file_exists_and_parses() -> None:
    assert WORKFLOW.is_file(), "the B64 identity activation gate must exist"
    assert isinstance(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), dict)


def test_gate_is_dispatch_only_behind_an_exact_phrase(data: dict, job: dict) -> None:
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"workflow_dispatch"}, (
        "an ordinary push or pull request must never reach production D1 or bindings"
    )
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert "ACTIVATE_B64_INDEPENDENT_IDENTITY" in job["if"], (
        "the job itself must re-check the confirmation phrase, not only the input"
    )


def test_gate_runs_on_the_production_environment_without_cancellation(data: dict, job: dict) -> None:
    assert job["environment"] == "production", (
        "the Google client values are production environment secrets; only that "
        "environment can read them, so the gate must not run anywhere else"
    )
    concurrency = data["concurrency"]
    assert concurrency["cancel-in-progress"] is False, (
        "cancelling between a migration and its readback leaves half-applied state"
    )


def test_premutation_still_pins_exact_main_and_the_designated_account(steps: list[dict]) -> None:
    first_run = next(step["run"] for step in steps if step.get("run"))
    assert 'git rev-parse HEAD' in first_run and 'git rev-parse origin/main' in first_run
    assert 'TARGET_SHA' in first_run
    assert "9be14bb7b8974e65d0afba647ab16932" in first_run, (
        "the Charliekant account is the only scope this gate may touch"
    )
    assert "test -n \"$CLOUDFLARE_API_TOKEN\"" in first_run


def test_d1_half_stays_additive_and_measurable(workflow_text: str, steps: list[dict]) -> None:
    assert re.search(r"DROP TABLE|DELETE FROM|ALTER TABLE|TRUNCATE|DROP INDEX", workflow_text, re.I) is None, (
        "this gate may add tables and nothing else; existing member, session and "
        "income rows are owner data"
    )
    applied = "\n".join(step["run"] for step in steps if step.get("run"))
    assert "0002_b64_member.sql" in applied and "0003_b64_google_identity.sql" in applied
    assert "b64_member_google" in applied, "the Google identity table must be verified to exist"
    assert "B64_D1_ROWS_PRESERVED" in applied, (
        "the gate must prove the additive migration removed no row, not assert it"
    )
    assert applied.count("b64-rowcount-before.json") >= 2, "the count is taken before and compared after"


def test_google_values_enter_only_through_an_env_mapping(steps: list[dict]) -> None:
    bound = [step for step in steps if step.get("run") and "wrangler@4 secret put B64_GOOGLE_CLIENT_ID" in step["run"]]
    assert len(bound) == 1, "exactly one step may write the Google bindings"
    env = bound[0].get("env") or {}
    assert set(env) >= set(GOOGLE_ENV_VARS)
    for name, var in zip(GOOGLE_SECRET_NAMES, GOOGLE_ENV_VARS):
        assert env[var] == "${{ secrets.%s }}" % name, (
            "the value must come from the environment secret and nothing else"
        )


def test_no_step_reads_a_github_context_inside_a_shell_script(run_blocks: list[tuple[str, str]]) -> None:
    for name, script in run_blocks:
        assert "secrets." not in script, (
            f"step {name!r} reaches a secret in the script body; a context there "
            "is substituted before bash sees it and lands in the echoed command"
        )


def test_google_values_reach_wrangler_only_through_stdin(run_blocks: list[tuple[str, str]]) -> None:
    script = next(script for name, script in run_blocks if "wrangler@4 secret put B64_GOOGLE_CLIENT_ID" in script)
    for var, binding in zip(GOOGLE_ENV_VARS, GOOGLE_SECRET_NAMES):
        needle = "printf '%s' \"${" + var + "}\""
        pattern = re.escape(needle) + r"\s*\\\n\s*\|\s*npx --yes wrangler@4 secret put " + re.escape(binding)
        assert re.search(pattern, script), (
            f"{var} must be piped into `wrangler secret put {binding}`; anything on "
            "a command line is printed by the runner"
        )
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo") or stripped.startswith("printf '%s\\n'"):
            for var in GOOGLE_ENV_VARS:
                assert var not in stripped, f"{var} is being echoed by {stripped!r}"
    assert "RUNNER_TEMP" in script and script.count("> \"${RUNNER_TEMP}/b64-google-client") == 2, (
        "the wrangler output is captured to the runner temp dir, never streamed to the log"
    )


def test_binding_is_verified_after_it_is_written(run_blocks: list[tuple[str, str]]) -> None:
    script = next(script for name, script in run_blocks if "wrangler@4 secret put B64_GOOGLE_CLIENT_ID" in script)
    assert "B64_GOOGLE_BINDING_VERIFIED=YES" in script
    assert "secret_text CONFIRMED" in script
    assert "assert len(matches)==1" in script, (
        "a binding that is absent, duplicated or the wrong type must fail the run"
    )
    assert re.search(r'if \[ -n "\$\{missing\}" \]; then[\s\S]*?exit 0', script), (
        "a half-registered configuration writes nothing: a client id without its "
        "secret would render the entry and then fail mid-round-trip"
    )


def test_gate_still_deploys_no_worker_revision_and_mints_no_client(workflow_text: str) -> None:
    assert "wrangler@4 deploy" not in workflow_text, (
        "the deploy gate owns Worker revisions; this gate owns schema and bindings"
    )
    assert "B64_WORKER_REVISION_DEPLOYED_BY_THIS_GATE=NO" in workflow_text
    assert "B64_GOOGLE_OAUTH_CLIENT_CREATED_BY_THIS_GATE=NO" in workflow_text
    assert "B64_GOOGLE_SECRET_VALUES_PRINTED=NO" in workflow_text


def test_every_shell_block_is_valid(run_blocks: list[tuple[str, str]]) -> None:
    for name, script in run_blocks:
        result = subprocess.run(
            ["bash", "-n"], input=script.encode("utf-8"), capture_output=True, check=False
        )
        assert result.returncode == 0, f"step {name!r} is not valid bash: {result.stderr.decode('utf-8', 'replace')}"
