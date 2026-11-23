"""#8061: shared Broker device-directory test preparation.

The hub test and its consumers all build the same owner-scoped settings,
binding fake and ASGI client. Keeping the preparation here lets the tests
import from a common location instead of from another test file.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import CLAW_DEVICE_DIRECTORY_PATH, BrokerDeviceDirectorySource
from app.config import Settings
from app.main import create_app

OWNER = "usr_4139_test"
BASE = "https://chat.example.test"
WORKSPACE = "owner:" + OWNER


def fact(device: str, *, state="paired_offline", account=OWNER, workspace=WORKSPACE):
    now = datetime.now(timezone.utc)
    return {
        "canonical_state": state,
        "binding": {
            "binding_ref": "bind_" + device, "device_id": device,
            "account_ref": account, "workspace_ref": workspace,
            "credential_generation": 1,
            "issued_at": (now - timedelta(days=2)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
        },
        "session": None, "heartbeat_last_seen_at": None,
        "credential": "NEVER_RENDER_ME", "stdout": "PRIVATE",
    }


class Binding:
    def __init__(self, rows=None, *, fail=False, available=True, scoped=True):
        self.rows = list(rows or [])
        self.calls = []
        self.fail = fail
        self.available = available
        self.scoped = scoped

    async def device_directory(self, payload):
        self.calls.append(dict(payload))
        if self.fail:
            raise RuntimeError("SECRET_INTERNAL_STORAGE_PATH")
        if not self.available:
            return {"ok": True, "available": False, "reason": "no_device_binding"}
        return {
            "ok": True, "available": True,
            "owner_scoped": self.scoped,
            "device_count": len(self.rows),
            "devices": self.rows,
            "request_id": "DO_NOT_EXPOSE",
        }


def make_app(binding=None, selection_store=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="4139-device-list-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    source = BrokerDeviceDirectorySource(binding) if binding is not None else None
    app = create_app(
        settings, history_store=MagicMock(), claw_device_directory_source=source,
        claw_pc_device_selection_store=selection_store,
    )
    return app, settings


def get(app, settings, *, signed=True, query=None, user=OWNER):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if signed:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, user, canonical_session_id="session_test_a"))
            return await client.get(CLAW_DEVICE_DIRECTORY_PATH, params=query)
    return asyncio.run(perform())
