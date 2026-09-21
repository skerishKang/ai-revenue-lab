"""Contract tests for the B54 Engine Agent Preview Pilot lane (#2786 Stage 11-C M3-3.5).

These tests read the workflow, caller, and preview environment declarations only. They
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
CALLER_WRANGLER_PATH = REPO / "apps" / "padiem-ai-engine" / "preview-caller" / "wrangler.toml"
PRODUCTION_GATE_PATH = REPO / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"

PREVIEW_WORKER = "padiem-ai-engine-preview"
PREVIEW_CALLER_WORKER = "padiem-ai-engine-preview-caller"
PRODUCTION_WORKER = "padiem-ai-engine"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML parses the bare `on:` key as the boolean True.
    return workflow.get("on", workflow.get(True))


def _wrangler() -> dict:
    return tomllib.loads(WRANGLER_PATH.read_text(encoding="utf-8"))


def _caller_wrangler() -> dict:
    return tomllib.loads(CALLER_WRANGLER_PATH.read_text(encoding="utf-8"))


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


def test_pilot_job_requires_the_exact_run_pilot_phrase() -> None:
    workflow = _workflow()
    pilot = workflow["jobs"]["preview-pilot"]
    assert pilot["if"] == "github.event.inputs.run_pilot == 'RUN_B54_ENGINE_AGENT_PREVIEW_PILOT'"
    assert WORKFLOW_PATH.read_text(encoding="utf-8").count("RUN_B54_ENGINE_AGENT_PREVIEW_PILOT") >= 2


def test_every_mutating_job_asserts_the_exact_target_sha() -> None:
    workflow = _workflow()
    for job in ("preview-config-guard", "deploy-preview", "preview-pilot"):
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


def test_no_step_deploys_production_worker() -> None:
    for command in _run_commands(_workflow()):
        for line in command.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "pywrangler deploy" in stripped or "wrangler deploy" in stripped:
                # Must be scoped to preview environment or the caller app dir
                is_preview_env = "--env preview" in stripped
                is_caller_deploy = stripped.startswith("npx wrangler deploy")
                assert is_preview_env or is_caller_deploy, f"Unscoped deploy: {stripped}"
                # The production worker name must NEVER be the target
                assert PRODUCTION_WORKER not in stripped or is_preview_env, stripped
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert PRODUCTION_GATE_PATH.name not in text
    assert PREVIEW_WORKER in text
    assert PREVIEW_CALLER_WORKER in text


def test_caller_wrangler_isolation() -> None:
    caller = _caller_wrangler()
    assert caller["name"] == PREVIEW_CALLER_WORKER
    assert caller["main"] == "worker.mjs"
    assert caller["workers_dev"] is True

    # Service binding target is fixed strictly to preview
    services = caller.get("services", [])
    assert len(services) == 1
    assert services[0]["binding"] == "PREVIEW_ENGINE"
    assert services[0]["service"] == PREVIEW_WORKER
    assert services[0]["service"] != PRODUCTION_WORKER

    # Forbidden resources
    for forbidden in ("d1_databases", "kv_namespaces", "r2_buckets", "vars_secret"):
        assert forbidden not in caller

    # Production worker must not be referenced anywhere in caller configuration
    raw_caller = CALLER_WRANGLER_PATH.read_text(encoding="utf-8")
    assert f'service = "{PRODUCTION_WORKER}"' not in raw_caller
    assert PRODUCTION_WORKER not in caller.get("vars", {})


def test_pilot_workflow_has_teardown() -> None:
    workflow = _workflow()
    pilot_text = _job_text(workflow, "preview-pilot")
    assert "Teardown preview caller and ephemeral secret" in pilot_text
    assert "npx wrangler delete" in pilot_text
    assert "PREVIEW_PILOT_TEARDOWN=PASS" in pilot_text
    # Teardown must run even if previous steps fail
    assert "if: always()" in pilot_text


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


def test_workflow_has_no_subdomain_api_dependency() -> None:
    """The workflow must not call Cloudflare API /workers/subdomain endpoint."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "/workers/subdomain" not in text
    assert "workers/subdomain" not in text


def test_caller_url_capture_and_validation() -> None:
    """The workflow must capture caller URL and perform strict URL validation."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "CALLER_BASE_URL" in text
    assert "https://${PREVIEW_CALLER_WORKER}." in text
    assert "grep -Eq '^https://[a-zA-Z0-9.-]+\\.workers\\.dev$'" in text
    assert "/run-pilot" in text


