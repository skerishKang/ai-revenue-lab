"""#7272: the browser-facing grade readiness never carries a model identity.

The authenticated Claw chooser answers with the PADIEM grade and opaque status
fields only. Registry model ids, display names, provider ids and upstream
addresses stay server-side even though the roster that decides availability is
loaded from B14's proven-caller authority.
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

from starlette.requests import Request

import app.auth_routes as auth_routes
import app.central_model_route_runtime as runtime
import app.member_grade_access as grade
from app.owner_model_preview_routes import claw_verified_model_choices

UID = "usr_" + "a" * 32
PROVIDER_ID = "vendor-acme"
MODEL_ID = "vendor-acme/model-x-9"
MODEL_NAME = "Vendor Acme Model X 9"
PROVIDER_ADDRESS = "upstream.vendor-acme.example"
RESPONSE_KEYS = {
    "ok",
    "scope",
    "complete_inventory",
    "automatic_default",
    "route_source",
    "route_revision",
    "tier",
    "available",
}
REGISTRY_ID_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*/[A-Za-z0-9]")


class _Roster:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        return [dict(row) for row in self.rows]


def _request(query: bytes = b"tier=free") -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({
        "type": "http", "method": "GET",
        "path": "/api/claw/verified-model-choices",
        "headers": [], "query_string": query, "app": app, "state": {},
    })


def _wire_models(monkeypatch, roster: _Roster) -> Request:
    request = _request()

    async def _denial(*_args, **_kwargs):
        return None

    async def _view(*_args, **_kwargs):
        return SimpleNamespace(
            ok=True, model_id=MODEL_ID, fallback_model_id=None, source="central",
        ), 7

    # The route imports these inside the call, so the source modules are patched.
    monkeypatch.setattr(auth_routes, "auth_ready", lambda _r: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda _r: UID)
    monkeypatch.setattr(grade, "selected_grade_denial", _denial)
    monkeypatch.setattr(grade, "selected_admin_denial", _denial)
    monkeypatch.setattr(runtime, "resolve_claw_tier_model_view", _view)
    request.app.state.b14_model_choice_resolver = roster
    return request


def test_the_browser_response_carries_no_registry_identity(monkeypatch):
    roster = _Roster([{"model_id": MODEL_ID, "name": MODEL_NAME}])

    response = asyncio.run(claw_verified_model_choices(_wire_models(monkeypatch, roster)))

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    payload = json.loads(body)
    assert set(payload) == RESPONSE_KEYS
    # Grade plus opaque status fields only: no id, name, provider or address.
    for identity in (MODEL_ID, MODEL_NAME, PROVIDER_ID, PROVIDER_ADDRESS):
        assert identity not in body, identity
    assert "://" not in body and "@" not in body
    assert REGISTRY_ID_SHAPE.search(body) is None
    # The closed value vocabularies stay grade/status-only.
    assert payload["tier"] == "free"
    assert payload["scope"] == "b14_tier_ready"
    assert payload["route_source"] in {"central", "static"}
    assert isinstance(payload["route_revision"], int)
    assert isinstance(payload["available"], bool)
    assert roster.calls == 1
