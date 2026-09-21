"""Contract tests for the B54 Engine Agent Preview Pilot lane (#2786 Stage 11-C M3-2).

These tests read the workflow and the preview environment declaration only. They
never dispatch, deploy, or contact Cloudflare: the point is that a merged file can
not deploy anything by itself, and that the preview environment stays isolated
from Production.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO / ".github" / "workflows" / "b54-engine-agent-preview-pilot.yml"
WRANGLER_PATH = REPO / "apps" / "padiem-ai-engine" / "wrangler.toml"
PRODUCTION_GATE_PATH = REPO / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"

PREVIEW_WORKER = "padiem-ai-engine-preview"
PRODUCTION_WORKER = "padiem-ai-engine"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML parses the bare `on:` key as the boolean True.
    return workflow.get("on", workflow.get(True))


def _wrangler() -> dict:
    return tomllib.loads(WRANGLER_PATH.read_text(encoding="utf-8"))


def _job_text(workflow: dict, job: str) -> str:
    return yaml.safe_dump(workflow["jobs"][job])


def test_workflow_is_dispatch_only() -> None:
    workflow = _workflow()
    triggers = _triggers(workflow)
    assert set(triggers) == {"workflow_dispatch"}
    assert "pull_request:" not in WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "push:" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_deploy_job_requires_the_exact_confirmation_phrase() -> None:
    workflow = _workflow()
    deploy = workflow["jobs"]["deploy-preview"]
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_AGENT_PREVIEW'"
    assert WORKFLOW_PATH.read_text(encoding="utf-8").count("DEPLOY_B54_ENGINE_AGENT_PREVIEW") >= 2


def test_every_mutating_job_asserts_the_exact_target_sha() -> None:
    workflow = _workflow()
    for job in ("preview-config-guard", "deploy-preview"):
        text = _job_text(workflow, job)
        assert "PREMUTATION_EXACT_MAIN_SHA" in text
        assert "origin/main" in text


def _run_commands(workflow: dict) -> list[str]:
    commands: list[str] = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            command = step.get("run")
            if isinstance(command, str):
                commands.append(command)
    return commands


def test_no_step_deploys_outside_the_preview_environment() -> None:
    for command in _run_commands(_workflow()):
        for line in command.splitlines():
            if "pywrangler deploy" in line or " wrangler deploy" in line:
                assert "--env preview" in line, line
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert PRODUCTION_GATE_PATH.name not in text
    assert "padiem-ai-engine-preview" in text


def test_pilot_job_fails_closed_without_an_internal_caller() -> None:
    text = _job_text(_workflow(), "preview-pilot")
    assert "PREVIEW_PILOT_CALLER=NOT_PROVISIONED" in text
    assert "PREVIEW_PILOT=DEFERRED" in text
    assert text.count("exit 1") >= 1
    assert "workers_dev" in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_preview_environment_is_isolated() -> None:
    preview = _wrangler()["env"]["preview"]
    assert preview["name"] == PREVIEW_WORKER
    assert preview["workers_dev"] is False
    assert preview["vars"] == {
        "ENGINE_DEPLOY_ENV": "preview",
        "ENGINE_AGENT_PREVIEW_ENABLED": "ENABLE_PREVIEW_AGENT_PILOT",
    }
    for forbidden in ("services", "d1_databases", "kv_namespaces", "r2_buckets", "vars_secret"):
        assert forbidden not in preview


def test_production_block_is_unchanged() -> None:
    wrangler = _wrangler()
    assert wrangler["name"] == PRODUCTION_WORKER
    assert wrangler["workers_dev"] is False
    assert wrangler["main"] == "worker_identity.py"
    # Production carries no vars section at all, so no preview marker can leak in.
    assert "vars" not in wrangler
    assert set(wrangler) - {"env", "name", "main", "compatibility_date", "compatibility_flags", "workers_dev"} == {
        "services",
        "d1_databases",
    }
