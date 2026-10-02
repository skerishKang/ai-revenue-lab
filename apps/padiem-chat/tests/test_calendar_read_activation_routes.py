from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import app.calendar_read_activation_routes as routes
from app.calendar_read_activation_engine import CalendarReadActivationClientError


class _Request:
    def __init__(self, *, body: bytes = b"{}", origin: str = "https://chat.padiem.net", client=None):
        self.headers = {
            "origin": origin,
            "content-type": "application/json",
        }
        self._body = body
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(public_base_url="https://chat.padiem.net"),
                calendar_read_activation_client=client,
            )
        )

    async def body(self) -> bytes:
        return self._body


class _Client:
    def __init__(self):
        self.sessions: list[str] = []

    async def activate(self, *, session_id: str):
        self.sessions.append(session_id)
        return {
            "ok": True,
            "calendar_read_grant": "active",
            "calendar_write_authorized": False,
            "binding_ref_projected": False,
            "actor_ref_projected": False,
            "workspace_ref_projected": False,
            "session_id_projected": False,
        }


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def _patch_authenticated(monkeypatch, session_id: str = "sess_calendar_1"):
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product_user_1")

    async def _current(request):
        return SimpleNamespace(auth_session=SimpleNamespace(session_id=session_id))

    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", _current)


def test_activation_uses_only_server_resolved_session_and_projects_no_private_refs(monkeypatch):
    _patch_authenticated(monkeypatch)
    client = _Client()
    response = asyncio.run(routes.activate_google_calendar_read(_Request(client=client)))

    assert response.status_code == 200
    assert client.sessions == ["sess_calendar_1"]
    assert _json(response) == {
        "ok": True,
        "calendar_read_grant": "active",
        "calendar_write_authorized": False,
    }
    text = response.body.decode("utf-8")
    for forbidden in ("binding_ref", "actor_ref", "workspace_ref", "session_id"):
        assert forbidden not in text


def test_activation_rejects_client_supplied_authority_before_engine_call(monkeypatch):
    _patch_authenticated(monkeypatch)
    client = _Client()
    body = json.dumps({"workspace_ref": "workspace_attacker"}).encode("utf-8")
    response = asyncio.run(
        routes.activate_google_calendar_read(_Request(body=body, client=client))
    )

    assert response.status_code == 400
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "calendar_read_activation_body_invalid"


def test_activation_rejects_foreign_origin_before_engine_call(monkeypatch):
    _patch_authenticated(monkeypatch)
    client = _Client()
    response = asyncio.run(
        routes.activate_google_calendar_read(
            _Request(origin="https://evil.example", client=client)
        )
    )

    assert response.status_code == 403
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "calendar_read_activation_origin_rejected"


def test_activation_fails_closed_when_current_b54_session_is_missing(monkeypatch):
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product_user_1")

    async def _missing(request):
        return None

    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", _missing)
    client = _Client()
    response = asyncio.run(routes.activate_google_calendar_read(_Request(client=client)))

    assert response.status_code == 403
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "current_b54_session_unavailable"


def test_activation_maps_engine_failure_to_bounded_503(monkeypatch):
    _patch_authenticated(monkeypatch)

    class _FailingClient:
        async def activate(self, *, session_id: str):
            raise CalendarReadActivationClientError("private detail")

    response = asyncio.run(
        routes.activate_google_calendar_read(_Request(client=_FailingClient()))
    )

    assert response.status_code == 503
    payload = _json(response)
    assert payload["error"]["code"] == "calendar_read_activation_unavailable"
    assert "private detail" not in response.body.decode("utf-8")
