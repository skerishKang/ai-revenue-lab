"""#5895 staged Chat rollout: promote on a passing smoke, restore on a failing one."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_staged_chat_rollout.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"

spec = importlib.util.spec_from_file_location("b62_staged_chat_rollout", SCRIPT)
roll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roll)

PREV = "11111111-1111-1111-1111-111111111111"
NEW = "22222222-2222-2222-2222-222222222222"
WRANGLER = ["wrangler"]


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRunner:
    def __init__(self, smoke_rc: int) -> None:
        self.smoke_rc = smoke_rc
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []

    def __call__(self, argv, *, env=None):
        argv = list(argv)
        self.calls.append(argv)
        self.envs.append(env)
        if argv[1:3] == ["versions", "upload"]:
            return _Result(0, stdout=f"Uploaded padiem-chat\nVersion ID: {NEW}\n")
        if argv[1:3] == ["versions", "deploy"]:
            return _Result(0)
        return _Result(self.smoke_rc)


def _deploy_calls(runner: _FakeRunner) -> list[list[str]]:
    return [c for c in runner.calls if c[1:3] == ["versions", "deploy"]]


def test_a_passing_smoke_promotes_the_new_version_to_full_traffic() -> None:
    runner = _FakeRunner(smoke_rc=0)
    version = roll.rollout(
        wrangler=WRANGLER, config="cfg.toml", previous_version=PREV,
        percent=10, settle_seconds=0,
        smokes=[["smoke-a"], ["smoke-b"]], runner=runner, sleep=lambda _s: None,
    )
    assert version == NEW
    deploys = _deploy_calls(runner)
    assert deploys[0] == ["wrangler", "versions", "deploy", f"{PREV}@90", f"{NEW}@10", "--yes", "--config", "cfg.toml"]
    assert deploys[-1] == ["wrangler", "versions", "deploy", f"{NEW}@100", "--yes", "--config", "cfg.toml"]
    assert len(deploys) == 2
    smoke_calls = [c for c in runner.calls if c[0].startswith("smoke-")]
    assert smoke_calls == [["smoke-a"], ["smoke-b"]]
    for env in [e for c, e in zip(runner.calls, runner.envs) if c[0].startswith("smoke-")]:
        assert env["B62_STAGED_VERSION_HEADER"] == "Cloudflare-Workers-Version-Key"
        assert env["B62_STAGED_VERSION_ID"] == NEW


def test_a_failing_smoke_restores_the_previous_version_and_never_promotes() -> None:
    runner = _FakeRunner(smoke_rc=1)
    with pytest.raises(roll.StagedRolloutError, match="STAGED_SMOKE_FAILED"):
        roll.rollout(
            wrangler=WRANGLER, config="cfg.toml", previous_version=PREV,
            percent=10, settle_seconds=0,
            smokes=[["smoke-a"]], runner=runner, sleep=lambda _s: None,
        )
    deploys = _deploy_calls(runner)
    assert deploys[0] == ["wrangler", "versions", "deploy", f"{PREV}@90", f"{NEW}@10", "--yes", "--config", "cfg.toml"]
    assert deploys[-1] == ["wrangler", "versions", "deploy", f"{PREV}@100", "--yes", "--config", "cfg.toml"]
    assert all(f"{NEW}@100" not in c for c in runner.calls)


def test_the_gate_step_runs_the_staged_rollout_with_one_constant_pair() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "b62_staged_chat_rollout.py" in text
    assert 'STAGED_TRAFFIC_PERCENT: "10"' in text
    assert 'STAGED_SETTLE_SECONDS: "20"' in text
    assert "post_deploy_real_chat_smoke.py --lane chat" in text
    assert "post_deploy_signed_in_smoke.py" in text
    assert "- name: Deploy production code preserving the full binding set" in text
