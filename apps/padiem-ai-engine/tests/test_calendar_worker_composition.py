"""Calendar worker composition tests (#2358).

Proves the Engine composition root wires the Calendar port + grants into
``build_tool_binding_resolver`` alongside the existing Gmail/Drive/Telegram/
Slack wiring, reuses the single existing Google OAuth authority (no second
OAuth stack, no new secret name), and stays READ-only. Network-free:
source-level assertions plus recording fakes.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest

from padiem_ai_core.calendar_capability import CalendarCapability, CalendarContractError
from app.connector_bindings import (
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    GMAIL_REFERENCE_APP_ID,
    CalendarGrant,
    build_tool_binding_resolver,
)

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

BINDING_REF = "bind:calendar_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, body=None, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class FakeWorkerEntrypoint:
    def __init__(self, ctx=None, env=None):
        self.ctx = ctx
        self.env = env


class FakeCalendarPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"items": []}


def calendar_grant() -> CalendarGrant:
    return CalendarGrant(
        app_id=CALENDAR_REFERENCE_APP_ID,
        canonical_agent_id=CALENDAR_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=(CalendarCapability.READ,),
    )


def _import_worker_identity():
    stub = types.ModuleType("workers")
    stub.Request = lambda *args, **kwargs: None
    stub.Response = FakeResponse
    stub.WorkerEntrypoint = FakeWorkerEntrypoint

    saved = {n: sys.modules.get(n) for n in ("workers", "worker", "worker_identity")}
    sys.modules["workers"] = stub
    for n in ("worker", "worker_identity"):
        sys.modules.pop(n, None)
    try:
        return importlib.import_module("worker_identity"), saved
    except BaseException:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod
        raise


def _restore(saved: dict) -> None:
    for n, mod in saved.items():
        if mod is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = mod


def test_worker_composes_calendar_port_and_grants() -> None:
    assert "_calendar_port_for_env" in WORKER_SRC
    assert "_calendar_grants_for_env" in WORKER_SRC
    assert "HttpxGoogleCalendarReadPort" in WORKER_SRC
    assert "parse_calendar_ids" in WORKER_SRC
    assert "load_calendar_grants" in WORKER_SRC


def test_worker_calendar_reuses_the_existing_google_oauth_authority() -> None:
    start = WORKER_SRC.index("def _calendar_port_for_env")
    end = WORKER_SRC.index("async def _calendar_grants_for_env")
    calendar_src = WORKER_SRC[start:end]
    # Same existing Gmail/Drive secret names — no second OAuth stack.
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_ID_ENV" in calendar_src
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET_ENV" in calendar_src
    assert "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN_ENV" in calendar_src
    # No new OAuth/Calendar secret name is invented by this promotion.
    for forbidden in (
        "CALENDAR_CLIENT_SECRET",
        "CALENDAR_REFRESH_TOKEN",
        "CALENDAR_ACCESS_TOKEN",
        "CALENDAR_OAUTH",
    ):
        assert forbidden not in WORKER_SRC


def test_worker_calendar_allowlist_is_server_derived() -> None:
    assert "ENGINE_CALENDAR_ALLOWED_CALENDARS_ENV" in WORKER_SRC
    assert 'ENGINE_CALENDAR_ALLOWED_CALENDARS_ENV = "ENGINE_CALENDAR_ALLOWED_CALENDARS"' in WORKER_SRC


def test_resolver_gathers_five_connector_grant_sets() -> None:
    start = WORKER_SRC.index("async def _tool_binding_resolver_for_env")
    end = WORKER_SRC.index("def _gmail_port_for_env")
    resolver_src = WORKER_SRC[start:end]
    assert "calendar_port = _calendar_port_for_env(env)" in resolver_src
    assert "_calendar_grants_for_env(env)" in resolver_src
    assert "calendar_port=calendar_port" in resolver_src
    assert "calendar_grants=calendar_grants or None" in resolver_src
    # Gmail/Drive/Telegram/Slack wiring lines stay present and unchanged.
    assert "gmail_port = _gmail_port_for_env(env)" in resolver_src
    assert "drive_port = _drive_port_for_env(env)" in resolver_src
    assert "telegram_port = _telegram_port_for_env(env)" in resolver_src
    assert "slack_port = _slack_port_for_env(env)" in resolver_src


def test_calendar_port_fail_closed_on_missing_authorities() -> None:
    identity, saved = _import_worker_identity()
    try:
        base = types.SimpleNamespace(
            ENGINE_GOOGLE_OAUTH_CLIENT_ID="client-id",
            ENGINE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
            ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
            ENGINE_CALENDAR_ALLOWED_CALENDARS="primary",
        )
        assert identity._calendar_port_for_env(base) is not None

        missing_oauth = types.SimpleNamespace(
            ENGINE_CALENDAR_ALLOWED_CALENDARS="primary",
        )
        assert identity._calendar_port_for_env(missing_oauth) is None

        missing_allowlist = types.SimpleNamespace(
            ENGINE_GOOGLE_OAUTH_CLIENT_ID="client-id",
            ENGINE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
            ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
        )
        assert identity._calendar_port_for_env(missing_allowlist) is None

        empty_allowlist = types.SimpleNamespace(
            ENGINE_GOOGLE_OAUTH_CLIENT_ID="client-id",
            ENGINE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
            ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
            ENGINE_CALENDAR_ALLOWED_CALENDARS="  ",
        )
        assert identity._calendar_port_for_env(empty_allowlist) is None

        malformed_allowlist = types.SimpleNamespace(
            ENGINE_GOOGLE_OAUTH_CLIENT_ID="client-id",
            ENGINE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
            ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
            ENGINE_CALENDAR_ALLOWED_CALENDARS="bad/id",
        )
        assert identity._calendar_port_for_env(malformed_allowlist) is None
    finally:
        _restore(saved)


def test_missing_calendar_store_keeps_calendar_tools_unavailable() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, calendar_port=None)
    assert resolver is None


def test_calendar_only_resolution_does_not_disturb_gmail_slot() -> None:
    port = FakeCalendarPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        calendar_port=port,
        calendar_grants={CALENDAR_REFERENCE_APP_ID: calendar_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is None
    binding = resolver(CALENDAR_REFERENCE_APP_ID)
    assert binding is not None
    assert set(binding.authorities) == {CALENDAR_AGENT_ID}


def test_caller_payload_cannot_mint_calendar_write_or_binding_ref() -> None:
    grant = calendar_grant()
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF
    with pytest.raises(CalendarContractError):
        CalendarGrant(
            app_id=CALENDAR_REFERENCE_APP_ID,
            canonical_agent_id=CALENDAR_AGENT_ID,
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            granted_capabilities=(CalendarCapability.CREATE_EVENT,),
        )


def test_no_secret_value_in_calendar_port_source() -> None:
    src = (APP_ROOT / "app" / "calendar_port_httpx.py").read_text(encoding="utf-8")
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_ID" in src
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET" in src
    assert "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN" in src
    assert "ENGINE_CALENDAR_ALLOWED_CALENDARS" in src
    # Only secret NAMES appear; no token-shaped or client-shaped literal.
    assert "ya29." not in src
    assert "apps.googleusercontent.com" not in src
    assert "1//" not in src
