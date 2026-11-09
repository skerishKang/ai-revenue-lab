from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.calendar_read_activation_routes as routes
from app.calendar_read_activation_engine import (
    GENERIC_CALENDAR_READ_ACTIVATION_CODE,
    CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES,
    CloudflareCalendarReadActivationEngineClient,
    CalendarReadActivationClientError,
)
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

_NOW = datetime.now(timezone.utc)
_SHADOW_SESSION_ID = "b62-shadow-session-1"
_SUBJECT_ID = "sub_calendar_owner"


class _Request:
    def __init__(self, *, body: bytes = b"{}", origin: str = "https://chat.padiem.net", client=None,
                 authority=None, shadow_store=None, cookies=None):
        self.headers = {
            "origin": origin,
            "content-type": "application/json",
        }
        self._body = body
        self.cookies = dict(cookies or {})
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    public_base_url="https://chat.padiem.net",
                    session_cookie_name="padiem_session",
                    session_cookie_secret="",
                ),
                calendar_read_activation_client=client,
                control_plane_identity_authority=authority,
                identity_shadow_store=shadow_store,
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


class _ShadowStore:
    """Pointer row the reviewed connector context is scoped to (B62)."""

    def __init__(self, session_id: str = _SHADOW_SESSION_ID, subject_id: str = _SUBJECT_ID) -> None:
        self.session_id = session_id
        self.subject_id = subject_id
        self.saved = 0

    async def load_projection(self, product_user_id: str):
        return IdentityShadowRecord(
            product_user_id=product_user_id,
            canonical_subject_id=self.subject_id,
            auth_session_id=self.session_id,
            session_revision=1,
            session_state="active",
            session_expires_at=_NOW + timedelta(hours=1),
            observed_at=_NOW,
        )

    async def save_projection(self, bridged) -> None:
        self.saved += 1


class _Authority:
    """Canonical authority: the shadow pointer resolves to a B62 session."""

    def __init__(self, *, product_id: str = "b62", subject_id: str = _SUBJECT_ID,
                 state: AuthSessionState = AuthSessionState.ACTIVE) -> None:
        self.product_id = product_id
        self.subject_id = subject_id
        self.state = state
        self.asked: list[str] = []

    async def resolve_auth_session(self, *, session_id: str):
        self.asked.append(session_id)
        return AuthSessionSnapshot(
            session_id=session_id,
            product_id=self.product_id,
            subject=CanonicalSubjectRef(SubjectType.USER, self.subject_id),
            issued_at=_NOW - timedelta(minutes=5),
            expires_at=_NOW + timedelta(hours=1),
            state=self.state,
            revision=1,
        )


def _patch_authenticated(monkeypatch, *, shadow_store=None, authority=None):
    monkeypatch.setattr(routes, "current_user_id", lambda request: "usr_product_user_1")
    return (
        shadow_store if shadow_store is not None else _ShadowStore(),
        authority if authority is not None else _Authority(),
    )


def _activate(client, *, shadow_store=None, authority=None, **kwargs):
    return asyncio.run(
        routes.activate_google_calendar_read(
            _Request(client=client, shadow_store=shadow_store, authority=authority, **kwargs)
        )
    )


def test_activation_uses_only_server_resolved_session_and_projects_no_private_refs(monkeypatch):
    shadow, authority = _patch_authenticated(monkeypatch)
    client = _Client()
    response = _activate(client, shadow_store=shadow, authority=authority)

    assert response.status_code == 200
    # #7247: the Engine receives the B62 session the connector context is
    # scoped to, never a B54 session.
    assert client.sessions == [_SHADOW_SESSION_ID]
    assert authority.asked == [_SHADOW_SESSION_ID]
    assert _json(response) == {
        "ok": True,
        "calendar_read_grant": "active",
        "calendar_write_authorized": False,
    }
    text = response.body.decode("utf-8")
    for forbidden in ("binding_ref", "actor_ref", "workspace_ref", "session_id"):
        assert forbidden not in text


def test_activation_refuses_when_only_the_b54_session_exists(monkeypatch):
    """No B62 shadow pointer means no reviewed connector context: refuse."""

    monkeypatch.setattr(routes, "current_user_id", lambda request: "usr_product_user_1")

    class _EmptyShadowStore:
        async def load_projection(self, product_user_id: str):
            return None

        async def save_projection(self, bridged) -> None:
            raise AssertionError("must not write")

    client = _Client()
    response = _activate(client, shadow_store=_EmptyShadowStore(), authority=_Authority())

    assert response.status_code == 403
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "current_b54_session_unavailable"


def test_activation_refuses_when_the_shadow_belongs_to_another_subject(monkeypatch):
    shadow, authority = _patch_authenticated(monkeypatch)
    shadow.subject_id = "sub_someone_else"
    client = _Client()
    response = _activate(client, shadow_store=shadow, authority=authority)

    assert response.status_code == 403
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "current_b54_session_unavailable"


def test_activation_refuses_a_foreign_product_session(monkeypatch):
    shadow, _ = _patch_authenticated(monkeypatch)
    client = _Client()
    response = _activate(
        client, shadow_store=shadow, authority=_Authority(product_id="b54-padiem-claw")
    )

    assert response.status_code == 403
    assert client.sessions == []


def test_activation_fails_closed_when_the_canonical_session_is_inactive(monkeypatch):
    shadow, _ = _patch_authenticated(monkeypatch)
    client = _Client()
    response = _activate(
        client, shadow_store=shadow, authority=_Authority(state=AuthSessionState.EXPIRED)
    )

    assert response.status_code == 403
    assert client.sessions == []


def test_activation_fails_closed_when_the_authority_is_unavailable(monkeypatch):
    monkeypatch.setattr(routes, "current_user_id", lambda request: "usr_product_user_1")

    class _BrokenAuthority:
        async def resolve_auth_session(self, *, session_id: str):
            raise RuntimeError("authority down")

    client = _Client()
    response = _activate(client, shadow_store=_ShadowStore(), authority=_BrokenAuthority())

    assert response.status_code == 503
    assert client.sessions == []


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
    monkeypatch.setattr(routes, "current_user_id", lambda request: "usr_product_user_1")
    client = _Client()
    response = _activate(client)

    # No authority/shadow wiring at all: the route refuses before the Engine.
    assert response.status_code == 503
    assert client.sessions == []
    assert _json(response)["error"]["code"] == "calendar_read_activation_unavailable"


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


# ---------------------------------------------------------------------------
# #3434 follow-up — bounded Engine rejection diagnostics
# ---------------------------------------------------------------------------

_ENGINE_REJECTION_BODY = (
    '{{"ok":false,"error":{{"code":"{code}","message":"{message}",'
    '"retryable":false,"metadata":null}}}}'
)


class _FakeEngineRequest:
    def __init__(self):
        self.js_object = {"url": "engine", "method": "POST", "headers": {}, "body": ""}


class _FakeEngineResponse:
    def __init__(self, *, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text


class _RecordingEngineBinding:
    def __init__(self, response: _FakeEngineResponse | None = None):
        self.response = response
        self.requests: list[dict] = []
        self.factory_requests: list[dict] = []

    async def fetch(self, js_object):
        self.requests.append(js_object)
        if self.response is None:
            raise RuntimeError("binding down")
        return self.response


def _make_client(binding: _RecordingEngineBinding) -> CloudflareCalendarReadActivationEngineClient:
    def _factory(url, *, method, headers, body):
        binding.factory_requests.append({"url": url, "method": method, "headers": dict(headers), "body": body})
        return _FakeEngineRequest()

    return CloudflareCalendarReadActivationEngineClient(
        binding,
        caller_id="chat-caller-unit-test",
        credential="unit-test-caller-value",
        request_factory=_factory,
    )


def _engine_rejection(code: str, message: str = "engine private detail") -> _FakeEngineResponse:
    body = _ENGINE_REJECTION_BODY.format(code=code, message=message)
    return _FakeEngineResponse(status=409, text=body)


def _raise_client_error(binding: _RecordingEngineBinding) -> CalendarReadActivationClientError:
    client = _make_client(binding)
    with pytest.raises(CalendarReadActivationClientError) as excinfo:
        asyncio.run(client.activate(session_id="sess_calendar_1"))
    return excinfo.value


@pytest.mark.parametrize(
    ("engine_code", "engine_status", "expected_code", "expected_status"),
    [
        ("service_authentication_failed", 401, "calendar_activation_engine_auth_failed", 503),
        ("service_app_not_authorized", 403, "calendar_activation_engine_auth_failed", 503),
        (
            "calendar_activation_workspace_unavailable",
            403,
            "calendar_activation_workspace_unavailable",
            403,
        ),
        (
            "calendar_activation_identity_unavailable",
            503,
            "calendar_activation_workspace_unavailable",
            503,
        ),
        ("calendar_binding_selection_unavailable", 409, "calendar_activation_binding_unavailable", 409),
        ("calendar_binding_selection_unavailable", 503, "calendar_activation_binding_unavailable", 503),
        ("calendar_not_connected", 409, "calendar_activation_not_connected", 409),
        ("calendar_grant_activation_unavailable", 503, "calendar_activation_grant_unavailable", 503),
        ("calendar_grant_activation_invalid", 503, "calendar_activation_grant_unavailable", 503),
        ("connector_grants_unavailable", 503, "calendar_activation_grant_unavailable", 503),
    ],
)
def test_engine_rejection_codes_project_onto_the_closed_safe_vocabulary(
    engine_code, engine_status, expected_code, expected_status
):
    body = _ENGINE_REJECTION_BODY.format(code=engine_code, message="engine private detail")
    error = _raise_client_error(
        _RecordingEngineBinding(_FakeEngineResponse(status=engine_status, text=body))
    )

    assert error.diagnostic_code == expected_code
    assert error.status_code == expected_status
    # The Engine's raw prose never becomes the exception text or the projection.
    assert "engine private detail" not in str(error)
    assert "engine private detail" not in error.diagnostic_code


@pytest.mark.parametrize(
    "rejection",
    [
        # Unknown Engine code.
        _engine_rejection("engine_went_sideways"),
        # Missing error object entirely.
        _FakeEngineResponse(status=503, text='{"ok":false}'),
        # Non-string code.
        _FakeEngineResponse(status=503, text='{"error":{"code":42}}'),
        # Malformed JSON on a non-200 response.
        _FakeEngineResponse(status=503, text="<html>gateway error</html>"),
        # Empty body.
        _FakeEngineResponse(status=502, text=""),
    ],
)
def test_unknown_or_malformed_engine_rejections_collapse_to_generic_unavailable(rejection):
    error = _raise_client_error(_RecordingEngineBinding(rejection))

    assert error.diagnostic_code == GENERIC_CALENDAR_READ_ACTIVATION_CODE
    assert error.status_code == 503


def test_transport_failure_and_size_bound_stay_generic_unavailable():
    transport = _raise_client_error(_RecordingEngineBinding())

    oversized = _raise_client_error(
        _RecordingEngineBinding(_FakeEngineResponse(status=200, text="x" * (16 * 1024 + 1)))
    )

    assert transport.diagnostic_code == GENERIC_CALENDAR_READ_ACTIVATION_CODE
    assert transport.status_code == 503
    assert oversized.diagnostic_code == GENERIC_CALENDAR_READ_ACTIVATION_CODE
    assert oversized.status_code == 503


def test_engine_success_200_contract_is_unchanged():
    document = {
        "ok": True,
        "calendar_read_grant": "active",
        "calendar_write_authorized": False,
        "binding_ref_projected": False,
        "actor_ref_projected": False,
        "workspace_ref_projected": False,
        "session_id_projected": False,
    }
    binding = _RecordingEngineBinding(
        _FakeEngineResponse(status=200, text=json.dumps(document))
    )

    result = asyncio.run(_make_client(binding).activate(session_id="sess_calendar_1"))

    assert result == document
    assert binding.factory_requests[0]["headers"]["x-padiem-engine-caller"] == "chat-caller-unit-test"


def test_safe_diagnostic_vocabulary_is_closed():
    assert GENERIC_CALENDAR_READ_ACTIVATION_CODE in CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES
    assert CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES == set(routes._ACTIVATION_FAILURE_MESSAGES)
    assert routes.SAFE_DIAGNOSTIC_CODES_CLOSED == CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES


def _patched_route_with_error(error: CalendarReadActivationClientError, monkeypatch):
    shadow, authority = _patch_authenticated(monkeypatch)

    class _ErroringClient:
        async def activate(self, *, session_id: str):
            raise error

    return _activate(_ErroringClient(), shadow_store=shadow, authority=authority)


@pytest.mark.parametrize(
    ("diagnostic_code", "status", "expected_status"),
    [
        ("calendar_activation_engine_auth_failed", 503, 503),
        ("calendar_activation_workspace_unavailable", 403, 403),
        ("calendar_activation_binding_unavailable", 409, 409),
        ("calendar_activation_not_connected", 409, 409),
        ("calendar_activation_grant_unavailable", 503, 503),
        (GENERIC_CALENDAR_READ_ACTIVATION_CODE, 503, 503),
    ],
)
def test_route_projects_engine_failure_stages_with_preserved_statuses(
    monkeypatch, diagnostic_code, status, expected_status
):
    response = _patched_route_with_error(
        CalendarReadActivationClientError(
            "Calendar READ activation was rejected",
            diagnostic_code=diagnostic_code,
            status_code=status,
        ),
        monkeypatch,
    )

    assert response.status_code == expected_status
    payload = _json(response)
    assert payload["error"]["code"] == diagnostic_code
    # The message is the route's own fixed text for the code, never engine prose.
    assert payload["error"]["message"] == routes._ACTIVATION_FAILURE_MESSAGES[diagnostic_code]


def test_route_refolds_a_misbehaving_client_diagnostic_fail_closed(monkeypatch):
    hostile = CalendarReadActivationClientError(
        "engine said: binding_ref=bind_calendar_1 actor_ref=act_1",
        diagnostic_code="not_in_the_closed_vocabulary",
        status_code=418,
    )

    response = _patched_route_with_error(hostile, monkeypatch)

    assert response.status_code == 503
    payload = _json(response)
    assert payload["error"]["code"] == GENERIC_CALENDAR_READ_ACTIVATION_CODE
    text = response.body.decode("utf-8")
    assert "bind_calendar_1" not in text
    assert "act_1" not in text
    assert "engine said" not in text


def test_route_failure_response_leaks_no_private_references_or_raw_prose(monkeypatch):
    hostile = CalendarReadActivationClientError(
        "engine body: binding_ref=bind_calendar_1 actor_ref=act_calendar_1 "
        "workspace_ref=ws_calendar_1 session_id=sess_calendar_1 token=ya29.secret",
        diagnostic_code="calendar_activation_not_connected",
        status_code=409,
    )

    response = _patched_route_with_error(hostile, monkeypatch)

    assert response.status_code == 409
    text = response.body.decode("utf-8")
    assert _json(response)["error"]["code"] == "calendar_activation_not_connected"
    for forbidden in (
        "bind_calendar_1",
        "act_calendar_1",
        "ws_calendar_1",
        "sess_calendar_1",
        "ya29.secret",
        "engine body",
        "binding_ref",
        "actor_ref",
        "workspace_ref",
        "session_id",
        "token",
    ):
        assert forbidden not in text


def test_route_write_authority_remains_zero(monkeypatch):
    shadow, authority = _patch_authenticated(monkeypatch)
    client = _Client()
    response = _activate(client, shadow_store=shadow, authority=authority)

    payload = _json(response)
    assert response.status_code == 200
    assert payload["calendar_write_authorized"] is False
    assert routes.CALENDAR_WRITE_AUTHORIZED is False
    assert routes.CALENDAR_WRITE_AUTHORITY_ADDED == 0
    assert routes.RAW_ENGINE_MESSAGE_OUTPUT == 0
    assert routes.BINDING_REF_OUTPUT == 0
    assert routes.ACTOR_REF_OUTPUT == 0
    assert routes.WORKSPACE_REF_OUTPUT == 0
    assert routes.SESSION_ID_OUTPUT == 0
    assert routes.OAUTH_TOKEN_OUTPUT == 0
