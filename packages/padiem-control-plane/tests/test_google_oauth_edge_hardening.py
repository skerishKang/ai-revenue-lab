from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PREFIX = "wrang" + "ler"
STATE_CONFIG = CONFIG_PREFIX + ".google-oauth.jsonc"
EDGE_CONFIG = CONFIG_PREFIX + ".google-oauth-edge.jsonc"


def test_google_oauth_edge_disables_credentialed_cors_and_requires_strict_boolean_rpc_status():
    source = (ROOT / "google_oauth_edge_worker.py").read_text(encoding="utf-8")

    assert 'CONNECT_PATH = "/v1/google/connect"' in source
    assert 'CALLBACK_PATH = "/v1/google/callback"' in source
    assert "access-control-allow-credentials" not in source
    assert '"access-control-allow-origin": origin' in source
    assert '"access-control-allow-origin": allowed_origin' in source
    assert 'not isinstance(result.get("ok"), bool)' in source
    assert "CREDENTIALLED_CORS = False" in source
    assert "STRICT_BOOLEAN_RPC_STATUS = True" in source
    assert "CORS_WILDCARD = False" in source
    assert "CONNECT_QUERY_FORBIDDEN = True" in source
    assert "CALLBACK_QUERY_AUTHORITY = False" in source
    assert "RAW_CONNECT_TICKET_LOGGED = False" in source
    assert "RAW_AUTHORIZATION_CODE_LOGGED = False" in source


def test_google_oauth_worker_configs_remain_private_and_observability_off():
    state = json.loads((ROOT / STATE_CONFIG).read_text(encoding="utf-8"))
    edge = json.loads((ROOT / EDGE_CONFIG).read_text(encoding="utf-8"))

    assert state["name"] == "padiem-google-oauth-state"
    assert state["workers_dev"] is False
    assert state["preview_urls"] is False
    assert state["observability"]["enabled"] is False
    assert "routes" not in state and "route" not in state
    assert state["secrets"]["required"] == [
        "GOOGLE_CONNECT_TICKET_KEY",
        "GOOGLE_OAUTH_SEAL_KEY",
        "GOOGLE_OAUTH_CLIENT_SECRET",
    ]

    assert edge["name"] == "padiem-google-oauth-edge"
    assert edge["workers_dev"] is False
    assert edge["preview_urls"] is False
    assert edge["observability"]["enabled"] is False
    assert "routes" not in edge and "route" not in edge
    assert edge["services"] == [
        {
            "binding": "GOOGLE_OAUTH_SERVICE",
            "service": "padiem-google-oauth-state",
        }
    ]


def test_google_oauth_configs_do_not_commit_live_client_redirect_or_allowed_origin():
    state_text = (ROOT / STATE_CONFIG).read_text(encoding="utf-8")
    edge_text = (ROOT / EDGE_CONFIG).read_text(encoding="utf-8")
    combined = state_text + "\n" + edge_text

    assert "GOOGLE_OAUTH_CLIENT_ID" not in combined
    assert "GOOGLE_OAUTH_REDIRECT_URI" not in combined
    assert "GOOGLE_OAUTH_ALLOWED_ORIGIN" not in combined
    assert "oauth.padiem.net" not in combined
    assert "chat.padiem.net" not in combined
