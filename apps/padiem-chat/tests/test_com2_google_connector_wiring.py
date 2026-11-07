"""#6460 3번 — COM2 host Google connector wiring.

The Worker reaches ``padiem-google-oauth-state`` and the P01 Engine over
Service Bindings. The CPython host is composed by ``app.local_cpython``; these
tests pin the two missing surfaces this lane wires:

1. a configured OAuth RPC pair composes the reviewed workspace-truth adapter,
   and ``/api/connectors/status`` projects the canonical state instead of
   ``unverified``. ``not_connected`` is the exact state the client
   ``driveConnectOffered(authenticated, workspaceState)`` predicate accepts, so
   the Drive connect button is offered.
2. a configured P01 pair composes the Calendar READ activation client, and the
   reviewed activation route answers 200 (never 503) against a 200 Engine.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx

import app.local_cpython as local_cpython
import app.calendar_read_activation_routes as activation_routes
from app.auth import SESSION_COOKIE, create_session_token
from app.calendar_read_activation_routes import activate_google_calendar_read
from app.config import Settings
from app.connector_status_projection import (
    WORKSPACE_STATE_NOT_CONNECTED,
    WORKSPACE_STATE_UNVERIFIED,
)
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.main import create_app

STATUS_PATH = "/api/connectors/status"
BASE_URL = "https://chat.example.test"
USER_ID = "usr_com2_wiring"
SESSION_ID = "authsession:b62:com2wiring"
WORKSPACE_REF = "workspace_com2_wiring"

GMAIL_ID = "connector:google:gmail@1"
DRIVE_ID = "connector:google:drive@1"
CALENDAR_ID = "connector:google:calendar@1"

GMAIL_CONNECTED = {
    "connector_id": "gmail",
    "state": "connected",
    "usable": True,
    "expires_present": True,
    "ambiguous": False,
}
DRIVE_NOT_CONNECTED = {
    "connector_id": "google-drive",
    "state": "not_connected",
    "usable": False,
    "expires_present": False,
    "ambiguous": False,
}
CALENDAR_NOT_CONNECTED = {
    "connector_id": "google-calendar",
    "state": "not_connected",
    "usable": False,
    "expires_present": False,
    "ambiguous": False,
}


class _Profile:
    def __init__(self, user_id: str = USER_ID) -> None:
        self.user_id = user_id

    def public_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id}


class _HistoryStore:
    async def get_user(self, user_id: str) -> Any:
        return _Profile() if user_id == USER_ID else None


class _ShadowStore:
    async def load_projection(self, product_user_id: str) -> IdentityShadowRecord | None:
        now = datetime.now(timezone.utc)
        return IdentityShadowRecord(
            product_user_id=USER_ID,
            canonical_subject_id="subject_com2_wiring",
            auth_session_id=SESSION_ID,
            session_revision=1,
            session_state="active",
            session_expires_at=now + timedelta(hours=1),
            observed_at=now,
        )


class _IdentityBinding:
    async def resolve_connector_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "workspace": {"present": True, "workspace_ref": WORKSPACE_REF},
        }


class _OAuthBinding:
    async def workspace_connector_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "connectors": [GMAIL_CONNECTED, DRIVE_NOT_CONNECTED]}

    async def workspace_calendar_connector_state(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"ok": True, "connectors": [CALENDAR_NOT_CONNECTED]}


class _EngineResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text


class _EngineFetch:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def fetch(self, request: dict[str, Any]) -> _EngineResponse:
        self.requests.append(dict(request))
        return _EngineResponse(
            200,
            json.dumps(
                {
                    "ok": True,
                    "calendar_read_grant": "active",
                    "calendar_write_authorized": False,
                    "binding_ref_projected": False,
                    "actor_ref_projected": False,
                    "workspace_ref_projected": False,
                    "session_id_projected": False,
                }
            ),
        )


class _ActivationRequest:
    def __init__(self, client: Any) -> None:
        self.headers = {
            "origin": BASE_URL,
            "content-type": "application/json",
        }
        self._body = b"{}"
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(public_base_url=BASE_URL),
                calendar_read_activation_client=client,
            )
        )

    async def body(self) -> bytes:
        return self._body


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE_URL,
        google_client_id="com2-wiring.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret="com2-wiring-session-secret-not-real",
        session_max_age_seconds=3600,
    )


def _app(workspace_truth: Any):
    settings = _settings()
    app = create_app(
        settings,
        history_store=_HistoryStore(),
        google_oauth_workspace_truth=workspace_truth,
    )
    app.state.control_plane_identity_authority = CloudflareControlPlaneIdentityAuthority(
        _IdentityBinding()
    )
    app.state.identity_shadow_store = _ShadowStore()
    return settings, app


def test_com2_workspace_truth_projects_connect_offered_state(monkeypatch):
    monkeypatch.setenv(
        local_cpython.LOCAL_GOOGLE_OAUTH_RPC_ORIGIN_ENV, "https://google-state.example"
    )
    monkeypatch.setenv(
        local_cpython.LOCAL_GOOGLE_OAUTH_RPC_SECRET_ENV, "s" * 40
    )
    monkeypatch.delenv("PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_LOCAL_P01_CALLER_ID", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL", raising=False)

    oauth_binding = _OAuthBinding()
    truth, _calendar = local_cpython._google_connector_authorities(
        os.environ,
        oauth_binding_factory=lambda origin, secret: oauth_binding,
    )
    assert truth is not None

    settings, app = _app(truth)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    )
    client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_ID))

    response = asyncio.run(client.get(STATUS_PATH))
    assert response.status_code == 200
    document = response.json()
    rows = {row["connector_id"]: row for row in document["connectors"]}

    assert document["workspace_state_authority"] is True
    assert rows[DRIVE_ID]["workspace_state"] == WORKSPACE_STATE_NOT_CONNECTED
    assert rows[DRIVE_ID]["workspace_state"] != WORKSPACE_STATE_UNVERIFIED
    assert rows[CALENDAR_ID]["workspace_state"] == WORKSPACE_STATE_NOT_CONNECTED
    assert rows[DRIVE_ID]["workspace_state"] == "not_connected"


def test_com2_calendar_activation_route_is_not_503(monkeypatch):
    monkeypatch.delenv(local_cpython.LOCAL_GOOGLE_OAUTH_RPC_ORIGIN_ENV, raising=False)
    monkeypatch.delenv(local_cpython.LOCAL_GOOGLE_OAUTH_RPC_SECRET_ENV, raising=False)
    monkeypatch.setenv(
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN", "http://127.0.0.1:8770"
    )
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_CALLER_ID", "b62-padiem-chat")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL", "c" * 40)

    engine = _EngineFetch()
    monkeypatch.setattr(
        local_cpython, "LocalEngineFetchBinding", lambda origin: engine
    )

    _truth, calendar_client = local_cpython._google_connector_authorities(os.environ)
    assert calendar_client is not None

    document = asyncio.run(calendar_client.activate(session_id=SESSION_ID))
    assert document["calendar_read_grant"] == "active"

    monkeypatch.setattr(
        activation_routes, "current_user_id", lambda request: USER_ID
    )

    async def _current(request):
        return SimpleNamespace(auth_session=SimpleNamespace(session_id=SESSION_ID))

    monkeypatch.setattr(
        activation_routes, "resolve_current_b54_canonical_session", _current
    )
    response = asyncio.run(
        activate_google_calendar_read(_ActivationRequest(calendar_client))
    )
    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8"))["calendar_read_grant"] == "active"
