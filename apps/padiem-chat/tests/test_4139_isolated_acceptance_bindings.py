"""#4139 source-controlled Cloudflare sandbox composition, never production."""
from __future__ import annotations

import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[3]
CHAT = ROOT / "apps/padiem-chat"
CP = ROOT / "packages/padiem-control-plane"

def test_nonproduction_owner_gateway_has_only_isolated_private_services():
    ordinary = tomllib.loads((CHAT / "wrangler.toml").read_text(encoding="utf-8"))
    isolated = tomllib.loads((CHAT / "wrangler.connector-acceptance-4139.toml").read_text(encoding="utf-8"))
    assert ordinary["name"] == "padiem-chat"
    assert "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED" not in ordinary.get("vars", {})
    assert "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED" not in ordinary.get("vars", {})
    assert "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE" not in {
        item["binding"] for item in ordinary.get("services", [])
    }
    assert isolated["name"] == "padiem-chat-connector-acceptance-4139"
    assert isolated["main"] == ordinary["main"]
    assert isolated["workers_dev"] is False
    assert isolated["preview_urls"] is False
    assert "routes" not in isolated
    assert isolated["vars"]["PADIEM_CHAT_LIVE_ENABLED"] == "false"
    assert isolated["vars"]["PADIEM_CHAT_RUNTIME_MODE"] == "mock"
    assert isolated["vars"]["PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"] == "isolated-operator-acceptance-4139"
    assert isolated["vars"]["PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED"] == "enabled"
    assert isolated["vars"]["PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED"] == "enabled"
    assert {item["binding"] for item in isolated["services"]} == {
        "IDENTITY_AUTHORITY_SERVICE", "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
    }
    assert {item["binding"]:item["service"] for item in isolated["services"] if item["binding"] in {
        "IDENTITY_AUTHORITY_SERVICE", "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
    }} == {
        "IDENTITY_AUTHORITY_SERVICE": "padiem-control-plane-identity-acceptance-4139",
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": "padiem-local-agent-broker-state-acceptance-4139",
    }


def test_nonprod_broker_and_identity_state_have_separate_durable_namespace():
    for name, live_file, stage_file in (
        ("padiem-local-agent-broker-state", "wrangler.local-agent-broker.jsonc",
         "wrangler.local-agent-broker-acceptance-4139.jsonc"),
        ("padiem-control-plane-identity", "wrangler.identity-authority.jsonc",
         "wrangler.identity-authority-acceptance-4139.jsonc"),
    ):
        live = json.loads((CP / live_file).read_text(encoding="utf-8"))
        stage = json.loads((CP / stage_file).read_text(encoding="utf-8"))
        assert live["name"] == name
        assert stage["name"] == name + "-acceptance-4139"
        assert stage["workers_dev"] is False and stage["preview_urls"] is False
        assert "routes" not in stage and "routes" not in live
        assert stage["main"] == live["main"]
        assert stage["durable_objects"] == live["durable_objects"]
    broker = json.loads((CP / "wrangler.local-agent-broker-acceptance-4139.jsonc").read_text())
    assert broker["vars"]["LOCAL_AGENT_BROKER_AUTHORITY_REF"] != json.loads(
        (CP / "wrangler.local-agent-broker.jsonc").read_text()
    )["vars"]["LOCAL_AGENT_BROKER_AUTHORITY_REF"]
