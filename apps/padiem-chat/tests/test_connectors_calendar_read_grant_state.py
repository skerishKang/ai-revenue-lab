"""Persisted Calendar READ grant state on /api/connectors/status (#2952).

The third, additive truth axis for the Calendar row:

    signed B62 product session (the workspace-truth gate, read once)
        -> existing canonical shadow auth_session_id
        -> existing P01 Engine service binding (read-only state route)
        -> closed ``calendar_read_grant_state`` on the calendar row only

Guarantees pinned here:

* anonymous / untrusted / unconfigured -> the field is absent and no Engine
  call happens (no inference); the rest of the response is unchanged.
* ``active`` / ``inactive`` come only from the Engine's closed 200 body.
* any client failure projects ``unavailable`` and never ``inactive``
  (UNAVAILABLE_AS_INACTIVE=0).
* the product profile and the shadow are still read exactly once per request
  (the pre-existing single-read contract is not disturbed).
* no private reference (session, workspace, binding, actor, token) ever
  appears in the response.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx

from app.calendar_read_state_engine import (
    CALENDAR_READ_GRANT_ACTIVE,
    CALENDAR_READ_GRANT_INACTIVE,
    CALENDAR_READ_GRANT_STATES,
    CALENDAR_READ_GRANT_UNAVAILABLE,
    CalendarReadStateUnavailableError,
    CloudflareCalendarReadStateEngineClient,
)
from app.connector_status_projection import (
    build_connector_status_projection,
)
from test_b62_connector_status_authenticated import (
    CALENDAR_ID,
    CANONICAL_SESSION_ID,
    STATUS_PATH,
    USER_ID,
    _HistoryStore,
    _assert_no_leak,
    _client,
    _rows,
    _wired,
)

ENGINE_STATE_PATH = "/internal/connectors/calendar/read/state"
ENGINE_ORIGIN_PREFIX = "https://engine.internal"


def run(coro):
    return asyncio.run(coro)


class _StateClient:
    def __init__(self, *, state: str | None = None, error: Exception | None = None):
        self.state = state
        self.error = error
        self.calls: list[str] = []

    async def read_state(self, *, session_id: str) -> str:
        self.calls.append(session_id)
        if self.error is not None:
            raise self.error
        return self.state  # type: ignore[return-value]


def _engine_body(state: str) -> dict[str, Any]:
    return {
        "ok": True,
        "calendar_read_grant_state": state,
        "calendar_write_authorized": False,
        "binding_ref_projected": False,
        "actor_ref_projected": False,
        "workspace_ref_projected": False,
        "session_id_projected": False,
    }


class _FakeEngineBinding:
    def __init__(self, *, status: int = 200, body: Any = None, fail: bool = False):
        self.status = status
        self.body = body
        self.fail = fail
        self.requests: list[dict[str, Any]] = []

    async def fetch(self, js_object: Any) -> Any:
        self.requests.append(dict(js_object))
        if self.fail:
            raise RuntimeError("binding down")
        body_text = json.dumps(self.body)

        class _Response:
            status = self.status

            async def text(self) -> str:
                return body_text

        return _Response()


class _FakeRequest:
    def __init__(self, url: str, method: str, headers: dict, body: str):
        self.url = url
        self.method = method
        self.headers = headers
        self.body = body
        self.js_object = {"url": url, "method": method, "headers": headers, "body": body}


# ── route-level: additive calendar-row projection ─────────────────────────


async def test_anonymous_response_carries_no_grant_field_and_no_engine_call():
    settings, app, identity_binding, oauth_binding, store = _wired()
    client_state = _StateClient(state=CALENDAR_READ_GRANT_ACTIVE)
    app.state.calendar_read_state_engine_client = client_state
    async with _client(settings, app, signed_in=False) as http:
        response = await http.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    rows = _rows(document)
    assert "calendar_read_grant_state" not in rows[CALENDAR_ID]
    # No inference for untrusted sessions: the client is never reached.
    assert client_state.calls == []
    _assert_no_leak(document)


async def test_authenticated_unconfigured_client_keeps_the_pre_feature_shape():
    settings, app, identity_binding, oauth_binding, store = _wired()
    # No calendar_read_state_engine_client on state at all.
    async with _client(settings, app) as http:
        response = await http.get(STATUS_PATH)
    document = response.json()
    assert "calendar_read_grant_state" not in _rows(document)[CALENDAR_ID]
    _assert_no_leak(document)


async def test_active_grant_projects_only_on_the_calendar_row():
    settings, app, identity_binding, oauth_binding, store = _wired()
    state_client = _StateClient(state=CALENDAR_READ_GRANT_ACTIVE)
    app.state.calendar_read_state_engine_client = state_client
    async with _client(settings, app) as http:
        response = await http.get(STATUS_PATH)
    document = response.json()
    rows = _rows(document)
    assert rows[CALENDAR_ID]["calendar_read_grant_state"] == "active"
    for connector_id, row in rows.items():
        if connector_id != CALENDAR_ID:
            assert "calendar_read_grant_state" not in row
    assert state_client.calls == [CANONICAL_SESSION_ID]
    _assert_no_leak(document)
    # The canonical session id itself must never travel.
    assert CANONICAL_SESSION_ID not in response.text


async def test_inactive_grant_projects_inactive():
    settings, app, identity_binding, oauth_binding, store = _wired()
    app.state.calendar_read_state_engine_client = _StateClient(
        state=CALENDAR_READ_GRANT_INACTIVE
    )
    async with _client(settings, app) as http:
        response = await http.get(STATUS_PATH)
    assert _rows(response.json())[CALENDAR_ID]["calendar_read_grant_state"] == "inactive"


async def test_engine_failure_projects_unavailable_never_inactive():
    settings, app, identity_binding, oauth_binding, store = _wired()
    app.state.calendar_read_state_engine_client = _StateClient(
        error=CalendarReadStateUnavailableError("rejected")
    )
    async with _client(settings, app) as http:
        response = await http.get(STATUS_PATH)
    rows = _rows(response.json())
    assert rows[CALENDAR_ID]["calendar_read_grant_state"] == "unavailable"
    # The two states are never merged.
    assert rows[CALENDAR_ID]["calendar_read_grant_state"] != "inactive"


async def test_malformed_client_answer_projects_unavailable():
    settings, app, identity_binding, oauth_binding, store = _wired()
    app.state.calendar_read_state_engine_client = _StateClient(state="bogus_state")
    async with _client(settings, app) as http:
        response = await http.get(STATUS_PATH)
    assert _rows(response.json())[CALENDAR_ID]["calendar_read_grant_state"] == "unavailable"


async def test_profile_and_shadow_are_still_read_exactly_once():
    history = _HistoryStore()
    settings, app, identity_binding, oauth_binding, store = _wired(history_store=history)
    app.state.calendar_read_state_engine_client = _StateClient(
        state=CALENDAR_READ_GRANT_ACTIVE
    )
    async with _client(settings, app) as http:
        await http.get(STATUS_PATH)
    # The workspace truth plus the grant state share one trust resolution:
    # the product profile and the shadow are each read exactly once.
    assert history.calls == [USER_ID]
    assert store.calls == [USER_ID]


# ── client-level: closed Engine contract ──────────────────────────────────


def _state_client(binding: _FakeEngineBinding) -> CloudflareCalendarReadStateEngineClient:
    return CloudflareCalendarReadStateEngineClient(
        binding,
        caller_id="b54-padiem-claw-calendar",
        credential="cred",
        request_factory=lambda url, method, headers, body: _FakeRequest(
            url, method, headers, body
        ),
    )


def test_client_returns_engine_active_state():
    binding = _FakeEngineBinding(body=_engine_body("active"))
    state = run(_state_client(binding).read_state(session_id=CANONICAL_SESSION_ID))
    assert state == "active"
    request = binding.requests[0]
    assert request["url"].endswith(ENGINE_STATE_PATH)
    assert request["method"] == "POST"
    assert json.loads(request["body"]) == {
        "app_id": "b54-padiem-claw-calendar",
        "session_id": CANONICAL_SESSION_ID,
    }


def test_client_returns_engine_inactive_state():
    binding = _FakeEngineBinding(body=_engine_body("inactive"))
    assert run(_state_client(binding).read_state(session_id=CANONICAL_SESSION_ID)) == "inactive"


def test_client_failure_responses_raise_unavailable_without_reading_the_body():
    # Non-200 (including Engine diagnostic bodies) never leaks prose or codes.
    for status, body in (
        (503, {"ok": False, "error": {"code": "calendar_activation_engine_auth_failed", "message": "internal prose"}}),
        (409, {"ok": False, "error": {"code": "calendar_not_connected", "message": "prose"}}),
        (401, {"error": {"code": "service_authentication_failed", "message": "prose"}}),
    ):
        binding = _FakeEngineBinding(status=status, body=body)
        try:
            run(_state_client(binding).read_state(session_id=CANONICAL_SESSION_ID))
            raised = False
        except CalendarReadStateUnavailableError:
            raised = True
        assert raised, status
        text = json.dumps(binding.requests[0])
        assert "prose" not in text


def test_client_rejects_widened_or_malformed_200_bodies():
    for body in (
        None,
        "prose",
        {"ok": True, "calendar_read_grant_state": "active"},
        _engine_body("bogus"),
        {**_engine_body("active"), "binding_ref": "binding:leak"},
        {**_engine_body("active"), "session_id": CANONICAL_SESSION_ID},
        {**_engine_body("active"), "calendar_write_authorized": True},
    ):
        binding = _FakeEngineBinding(body=body)
        try:
            run(_state_client(binding).read_state(session_id=CANONICAL_SESSION_ID))
            raised = False
        except CalendarReadStateUnavailableError:
            raised = True
        assert raised, body


def test_client_transport_failure_raises_unavailable():
    binding = _FakeEngineBinding(fail=True)
    try:
        run(_state_client(binding).read_state(session_id=CANONICAL_SESSION_ID))
        raised = False
    except CalendarReadStateUnavailableError:
        raised = True
    assert raised


def test_state_vocabulary_is_the_closed_triple() -> None:
    assert CALENDAR_READ_GRANT_STATES == ("active", "inactive", "unavailable")
