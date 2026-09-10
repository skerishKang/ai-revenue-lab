"""Slack worker composition tests (#2356).

Proves the Engine composition root wires the Slack port + grants into
``build_tool_binding_resolver`` alongside the existing Gmail/Drive/Telegram
wiring, with no Google OAuth dependency and no new connector framework.
Network-free: source-level assertions plus recording fakes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from padiem_ai_core.slack_capability import SlackCapability
from app.connector_bindings import (
    GMAIL_REFERENCE_APP_ID,
    SLACK_AGENT_ID,
    SLACK_REFERENCE_APP_ID,
    SlackGrant,
    build_tool_binding_resolver,
)

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

BINDING_REF = "bind:slack_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeSlackPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"ok": True, "team_id": "T0TEAM123", "user_id": "U0BOT1234"}


def slack_grant() -> SlackGrant:
    return SlackGrant(
        app_id=SLACK_REFERENCE_APP_ID,
        canonical_agent_id=SLACK_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=(SlackCapability.READ,),
    )


def test_worker_composes_slack_port_and_grants() -> None:
    assert "_slack_port_for_env" in WORKER_SRC
    assert "_slack_grants_for_env" in WORKER_SRC
    assert "HttpxSlackReadPort" in WORKER_SRC
    assert "parse_slack_channel_ids" in WORKER_SRC
    assert "load_slack_grants" in WORKER_SRC


def test_worker_slack_authorities_are_server_derived() -> None:
    assert "ENGINE_SLACK_BOT_TOKEN" in WORKER_SRC
    assert "ENGINE_SLACK_ALLOWED_CHANNELS" in WORKER_SRC
    assert "ENGINE_SLACK_PRIVATE_CHANNELS" in WORKER_SRC


def test_slack_has_no_google_oauth_dependency() -> None:
    start = WORKER_SRC.index("def _slack_port_for_env")
    end = WORKER_SRC.index("async def _slack_grants_for_env")
    slack_port_src = WORKER_SRC[start:end]
    assert "CONTROL_PLANE_GOOGLE_OAUTH" not in slack_port_src
    assert "OAUTH" not in slack_port_src


def test_resolver_gathers_four_connector_grant_sets() -> None:
    start = WORKER_SRC.index("async def _tool_binding_resolver_for_env")
    end = WORKER_SRC.index("def _gmail_port_for_env")
    resolver_src = WORKER_SRC[start:end]
    assert "slack_port = _slack_port_for_env(env)" in resolver_src
    assert "_slack_grants_for_env(env)" in resolver_src
    assert "slack_port=slack_port" in resolver_src
    assert "slack_grants=slack_grants or None" in resolver_src
    # Gmail/Drive/Telegram wiring lines stay present and unchanged in posture.
    assert "gmail_port = _gmail_port_for_env(env)" in resolver_src
    assert "drive_port = _drive_port_for_env(env)" in resolver_src
    assert "telegram_port = _telegram_port_for_env(env)" in resolver_src


def test_missing_slack_store_keeps_slack_tools_unavailable() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, slack_port=None)
    assert resolver is None


def test_slack_only_resolution_does_not_disturb_gmail_slot() -> None:
    port = FakeSlackPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        slack_port=port,
        slack_grants={SLACK_REFERENCE_APP_ID: slack_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is None
    binding = resolver(SLACK_REFERENCE_APP_ID)
    assert binding is not None
    assert set(binding.authorities) == {SLACK_AGENT_ID}


def test_caller_payload_cannot_mint_slack_write_or_binding_ref() -> None:
    grant = slack_grant()
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF
    with pytest.raises(ValueError):
        SlackGrant(
            app_id=SLACK_REFERENCE_APP_ID,
            canonical_agent_id=SLACK_AGENT_ID,
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            granted_capabilities=(SlackCapability.POST_MESSAGE,),
        )


def test_no_secret_value_in_slack_port_source() -> None:
    src = (APP_ROOT / "app" / "slack_port_httpx.py").read_text(encoding="utf-8")
    assert "ENGINE_SLACK_BOT_TOKEN" in src
    assert "ENGINE_SLACK_ALLOWED_CHANNELS" in src
    assert "ENGINE_SLACK_PRIVATE_CHANNELS" in src
    # Only secret NAMES appear; no token-shaped literal is embedded
    # (the bot-token shape regex alone is allowed; a fake token sentinel is not).
    assert "xoxb-fake" not in src
