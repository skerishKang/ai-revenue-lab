"""#3099 the device directory projects the diagnostic hint as display only.

The hint must reach the web surface without touching anything the product
decides with: the canonical state, the online projection, the executable
flag and the selectable flag stay exactly as the Broker proved them.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH,
    BrokerDeviceDirectorySource,
)
from app.config import Settings
from app.main import create_app

OWNER = "usr_3099_test"
WORKSPACE = "owner:" + OWNER
BASE = "https://chat.example.test"
DEVICE = "device-1"

REPORTED = {
    "status": "reported",
    "device_id": DEVICE,
    "checks": {"agent_source": "not_installed", "autostart": "disabled", "resident": "stopped"},
    "fixes": {
        "agent_source": "install_agent",
        "autostart": "enable_autostart",
        "resident": "start_connector",
    },
}


def fact(device: str, *, diagnostics=None, state="paired_offline"):
    now = datetime.now(timezone.utc)
    row = {
        "canonical_state": state,
        "binding": {
            "binding_ref": "bind_" + device, "device_id": device,
            "account_ref": OWNER, "workspace_ref": WORKSPACE,
            "credential_generation": 1,
            "issued_at": (now - timedelta(days=2)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
        },
        "session": None, "heartbeat_last_seen_at": None,
        "credential": "NEVER_RENDER_ME", "stdout": "PRIVATE",
    }
    if diagnostics is not None:
        row["device_diagnostics"] = diagnostics
    return row


class Binding:
    def __init__(self, rows):
        self.rows = list(rows)

    async def device_directory(self, payload):
        del payload
        return {
            "ok": True, "available": True, "owner_scoped": True,
            "device_count": len(self.rows), "devices": self.rows,
            "request_id": "DO_NOT_EXPOSE",
        }


def make_app(binding):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="3099-device-list-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings, history_store=MagicMock(),
        claw_device_directory_source=BrokerDeviceDirectorySource(binding),
    )
    return app, settings


def get(app, settings):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            client.cookies.set(
                SESSION_COOKIE, create_session_token(settings, OWNER),
                domain="chat.example.test", path="/",
            )
            return await client.get(CLAW_DEVICE_DIRECTORY_PATH)
    return asyncio.run(perform())


def test_the_hint_reaches_the_directory_without_changing_the_device_state():
    app, settings = make_app(Binding([fact(DEVICE, diagnostics=REPORTED)]))
    with patch("app.claw_device_directory_routes._resolve_memory_workspace",
               new=AsyncMock(return_value=WORKSPACE)):
        data = get(app, settings).json()
    assert data["available"] is True
    row = data["devices"][0]
    # The canonical, online and selection judgments are untouched.
    assert row["state"] == "OFFLINE"
    assert row["usable"] is False
    assert row["revoked"] is False
    assert row["expired"] is False
    # The hint is present and bounded.
    assert row["diagnostic"]["status"] == "reported"
    assert row["diagnostic"]["checks"]["agent_source"] == "not_installed"
    assert row["diagnostic"]["fixes"]["autostart"] == "enable_autostart"


def test_a_device_without_a_hint_has_no_diagnostic_field():
    app, settings = make_app(Binding([fact(DEVICE)]))
    with patch("app.claw_device_directory_routes._resolve_memory_workspace",
               new=AsyncMock(return_value=WORKSPACE)):
        data = get(app, settings).json()
    assert "diagnostic" not in data["devices"][0]


def test_a_hint_for_another_device_is_not_projected():
    other = {**REPORTED, "device_id": "device-2"}
    app, settings = make_app(Binding([fact(DEVICE, diagnostics=other)]))
    with patch("app.claw_device_directory_routes._resolve_memory_workspace",
               new=AsyncMock(return_value=WORKSPACE)):
        data = get(app, settings).json()
    assert "diagnostic" not in data["devices"][0]


def test_a_stale_hint_is_shown_as_unavailable_not_as_a_fact():
    stale = {
        "status": "stale", "device_id": DEVICE,
        "checks": {"agent_source": "not_installed", "autostart": "enabled",
                    "resident": "running"},
    }
    app, settings = make_app(Binding([fact(DEVICE, diagnostics=stale)]))
    with patch("app.claw_device_directory_routes._resolve_memory_workspace",
               new=AsyncMock(return_value=WORKSPACE)):
        data = get(app, settings).json()
    row = data["devices"][0]
    assert row["diagnostic"]["status"] == "stale"
    assert row["diagnostic"]["checks"] == {}
    assert row["diagnostic"]["fixes"] == {}
