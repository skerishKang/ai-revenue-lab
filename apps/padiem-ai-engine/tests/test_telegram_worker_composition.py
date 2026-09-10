"""Telegram worker composition tests (#2353).

Proves the Engine composition root wires the Telegram port + grants into
``build_tool_binding_resolver`` alongside the existing Gmail/Drive wiring,
with no Google OAuth dependency and no new connector framework.
Network-free: source-level assertions plus recording fakes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from padiem_ai_core.telegram_capability import TelegramCapability
from app.connector_bindings import (
    GMAIL_REFERENCE_APP_ID,
    TELEGRAM_AGENT_ID,
    TELEGRAM_REFERENCE_APP_ID,
    TelegramGrant,
    build_tool_binding_resolver,
)

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

BINDING_REF = "bind:telegram_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeTelegramPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"ok": True, "result": {"id": 1, "username": "padiem_beta_bot", "first_name": "P", "is_bot": True}}


def telegram_grant() -> TelegramGrant:
    return TelegramGrant(
        app_id=TELEGRAM_REFERENCE_APP_ID,
        canonical_agent_id=TELEGRAM_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=(TelegramCapability.READ,),
    )


def test_worker_composes_telegram_port_and_grants() -> None:
    assert "_telegram_port_for_env" in WORKER_SRC
    assert "_telegram_grants_for_env" in WORKER_SRC
    assert "HttpxTelegramReadPort" in WORKER_SRC
    assert "parse_paired_chat_ids" in WORKER_SRC
    assert "load_telegram_grants" in WORKER_SRC


def test_worker_telegram_authorities_are_server_derived() -> None:
    assert "ENGINE_TELEGRAM_BOT_TOKEN" in WORKER_SRC
    assert "ENGINE_TELEGRAM_PAIRED_CHAT_IDS" in WORKER_SRC


def test_telegram_has_no_google_oauth_dependency() -> None:
    start = WORKER_SRC.index("def _telegram_port_for_env")
    end = WORKER_SRC.index("async def _telegram_grants_for_env")
    telegram_port_src = WORKER_SRC[start:end]
    assert "CONTROL_PLANE_GOOGLE_OAUTH" not in telegram_port_src
    assert "OAUTH" not in telegram_port_src


def test_resolver_gathers_three_connector_grant_sets() -> None:
    start = WORKER_SRC.index("async def _tool_binding_resolver_for_env")
    end = WORKER_SRC.index("def _gmail_port_for_env")
    resolver_src = WORKER_SRC[start:end]
    assert "telegram_port = _telegram_port_for_env(env)" in resolver_src
    assert "_telegram_grants_for_env(env)" in resolver_src
    assert "telegram_port=telegram_port" in resolver_src
    assert "telegram_grants=telegram_grants or None" in resolver_src
    # Gmail/Drive wiring lines stay present and unchanged in posture.
    assert "gmail_port = _gmail_port_for_env(env)" in resolver_src
    assert "drive_port = _drive_port_for_env(env)" in resolver_src


def test_missing_telegram_store_keeps_telegram_tools_unavailable() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, telegram_port=None)
    assert resolver is None


def test_telegram_only_resolution_does_not_disturb_gmail_slot() -> None:
    port = FakeTelegramPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        telegram_port=port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is None
    binding = resolver(TELEGRAM_REFERENCE_APP_ID)
    assert binding is not None
    assert set(binding.authorities) == {TELEGRAM_AGENT_ID}


def test_caller_payload_cannot_mint_telegram_write_or_binding_ref() -> None:
    grant = telegram_grant()
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF
    with pytest.raises(ValueError):
        TelegramGrant(
            app_id=TELEGRAM_REFERENCE_APP_ID,
            canonical_agent_id=TELEGRAM_AGENT_ID,
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            granted_capabilities=(TelegramCapability.SEND_MESSAGE,),
        )


def test_no_secret_value_in_telegram_port_source() -> None:
    src = (APP_ROOT / "app" / "telegram_port_httpx.py").read_text(encoding="utf-8")
    assert "ENGINE_TELEGRAM_BOT_TOKEN" in src
    assert "ENGINE_TELEGRAM_PAIRED_CHAT_IDS" in src
    # Only secret NAMES appear; no token-shaped literal is embedded.
    assert "123456:" not in src
