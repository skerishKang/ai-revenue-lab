from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
STATE_CONFIG = ROOT / ("wrang" + "ler.local-agent-broker.jsonc")
EDGE_CONFIG = ROOT / ("wrang" + "ler.local-agent-broker-edge.jsonc")
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "b54-local-agent-broker-production-gate.yml"


def test_state_config_declares_server_owned_authority_and_required_secret_name_only() -> None:
    config = json.loads(STATE_CONFIG.read_text(encoding="utf-8"))
    assert config["name"] == "padiem-local-agent-broker-state"
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert "routes" not in config
    assert config["vars"] == {
        "LOCAL_AGENT_BROKER_AUTHORITY_REF": "control-plane.local-agent-broker.production.v1"
    }
    assert config["secrets"] == {"required": ["LOCAL_AGENT_BROKER_PEPPER"]}
    assert config["durable_objects"]["bindings"] == [
        {
            "name": "LOCAL_AGENT_BROKER_STATE",
            "class_name": "LocalAgentBrokerDurableObject",
        }
    ]
    assert config["exports"]["LocalAgentBrokerDurableObject"] == {
        "type": "durable-object",
        "storage": "sqlite",
    }


def test_edge_config_remains_private_until_separate_route_activation() -> None:
    config = json.loads(EDGE_CONFIG.read_text(encoding="utf-8"))
    assert config["name"] == "padiem-local-agent-broker-edge"
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert "routes" not in config
    assert config["services"] == [
        {
            "binding": "LOCAL_AGENT_BROKER_SERVICE",
            "service": "padiem-local-agent-broker-state",
        }
    ]


def test_production_gate_is_manual_only_exact_sha_and_defaults_to_non_mutating_preflight() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "repository_preflight" in text
    assert "cloudflare_readonly" in text
    assert "bootstrap_private" in text
    assert "default: repository_preflight" in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in text
    assert 'test "${GITHUB_SHA}" = "${TARGET_SHA}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in text
    assert "BOOTSTRAP_PADIEM_LOCAL_AGENT_BROKER_PRIVATE" in text
    assert "environment: production" in text


def test_production_gate_packages_before_mutation_and_deploys_state_before_edge() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    tool = "py" + "wrangler deploy"
    dry_run = "--dry-run"
    assert text.count(tool) >= 4
    assert text.count(dry_run) >= 2
    assert "workers-py>=1.72,<2" in text
    assert "--strict" in text
    assert "--secrets-file" in text

    state_deploy = text.index("Deploy state Worker and SQLite Durable Object first")
    state_readback = text.index("Read back private state Worker boundary")
    edge_deploy = text.index("Deploy edge Worker second with private Service Binding")
    edge_readback = text.index("Read back edge as private-only and service-bound")
    assert state_deploy < state_readback < edge_deploy < edge_readback


def test_production_gate_never_configures_public_route_or_auto_deletes_durable_state() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "--route " not in lowered
    assert "--routes " not in lowered
    assert "--domain " not in lowered
    assert "delete worker" not in lowered
    assert "durable object delete" not in lowered
    assert "PUBLIC_ROUTE_CONFIGURED=NO" in text
    assert "LIVE_WINDOWS_CANARY=NO" in text
    assert "PRODUCTION_READY=NO" in text


def test_production_gate_does_not_embed_secret_or_account_values() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "LOCAL_AGENT_BROKER_PEPPER: ${{ secrets.LOCAL_AGENT_BROKER_PEPPER }}" not in text
    assert "BROKER_PEPPER: ${{ secrets.LOCAL_AGENT_BROKER_PEPPER }}" in text
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in text
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in text
    assert "5a305a04650f4ad419062f8d4a96a41d" not in text
