"""The COM2 host assembly binds the Calendar READ activation client.

Before this wiring the CPython host set no ``calendar_read_activation_client``,
so ``POST /api/connectors/google/calendar/activate-read`` always answered 503
``calendar_read_activation_unavailable`` while the Worker path worked. These
regressions pin the assembly to the same client and caller surface the Worker
uses, over the host's loopback Engine binding.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.local_cpython import build_app
from app.local_p01_engine import build_local_calendar_read_activation_client

PUBLIC_BASE_URL = "http://127.0.0.1:8773"
SESSION_SECRET = "test-local-secret-0123456789abcdef"
ENGINE_ORIGIN = "http://127.0.0.1:8811"
USER_ID = "usr_" + "a" * 32
SESSION_ID = "sess_" + "b" * 32
ACTIVATION_ROUTE = "/api/connectors/google/calendar/activate-read"
ACTIVATION_PATH = "/internal/connectors/calendar/read/activate"

ENGINE_ENV = {
    "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": ENGINE_ORIGIN,
    "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b54-padiem-claw-calendar",
    "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "synthetic-engine-credential-value-0001",
}

# The closed activation document the Engine client accepts.
ACTIVATION_OK = {
    "ok": True,
    "calendar_read_grant": "active",
    "calendar_write_authorized": False,
    "binding_ref_projected": False,
    "actor_ref_projected": False,
    "workspace_ref_projected": False,
    "session_id_projected": False,
}


def _engine_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == ACTIVATION_PATH:
        return httpx.Response(200, json=ACTIVATION_OK)
    return httpx.Response(
        404, json={"ok": False, "error": {"code": "not_found", "message": "synthetic"}}
    )


def _assemble(tmp_path, monkeypatch, *, engine: bool = True):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "password")
    monkeypatch.setenv("PADIEM_CHAT_COOKIE_SECURE", "false")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_LIVE_ENABLED", "false")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", PUBLIC_BASE_URL)
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", SESSION_SECRET)
    for name in ENGINE_ENV:
        if engine:
            monkeypatch.setenv(name, ENGINE_ENV[name])
        else:
            monkeypatch.delenv(name, raising=False)
    engine_client = (
        httpx.AsyncClient(
            transport=httpx.MockTransport(_engine_handler), follow_redirects=False
        )
        if engine
        else None
    )
    return build_app(outbound_http_client=engine_client), engine_client


@pytest.mark.asyncio
async def test_the_com2_assembly_answers_the_activation_route_instead_of_503(
    tmp_path, monkeypatch
):
    app, engine_client = _assemble(tmp_path, monkeypatch)
    try:
        # The assembly, not the test, produced the client.
        assert app.state.calendar_read_activation_client is not None

        async def _current_session(request):
            return SimpleNamespace(
                auth_session=SimpleNamespace(session_id=SESSION_ID)
            )

        monkeypatch.setattr(
            "app.calendar_read_activation_routes.resolve_current_b54_canonical_session",
            _current_session,
        )
        token = create_session_token(app.state.settings, USER_ID)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE_URL
        ) as http:
            http.cookies.set(SESSION_COOKIE, token)
            response = await http.post(
                ACTIVATION_ROUTE, json={}, headers={"Origin": PUBLIC_BASE_URL}
            )
    finally:
        if engine_client is not None:
            await engine_client.aclose()

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "calendar_read_grant": "active",
        "calendar_write_authorized": False,
    }


def test_an_unconfigured_engine_surface_keeps_the_client_unbound(
    tmp_path, monkeypatch
):
    app, engine_client = _assemble(tmp_path, monkeypatch, engine=False)
    assert engine_client is None
    assert app.state.calendar_read_activation_client is None
    assert app.state.google_oauth_workspace_truth is None


def test_an_unconfigured_engine_surface_reports_no_diagnostic():
    client, diagnostic = build_local_calendar_read_activation_client({})
    assert client is None
    assert diagnostic is None
