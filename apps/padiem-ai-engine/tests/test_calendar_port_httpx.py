"""HttpxGoogleCalendarReadPort contract tests (#2358).

All tests use ``httpx.MockTransport`` so no real network call is ever made.
The OAuth material is a fake sentinel; assertions prove it never leaks
through exception strings, causes or contexts — including via the bearer
header — and that the port reuses the single existing Google OAuth authority
(token endpoint + readonly scope check) with no second OAuth stack.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from padiem_ai_core.calendar_capability import (
    CALENDAR_READONLY_AUTH_SCOPE,
    GOOGLE_CALENDAR_BASE_URL,
    GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
)
from app.calendar_port_httpx import (
    CALENDAR_LIST_PATH,
    ENGINE_CALENDAR_ALLOWED_CALENDARS,
    ENGINE_GOOGLE_OAUTH_CLIENT_ID,
    ENGINE_GOOGLE_OAUTH_CLIENT_SECRET,
    ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN,
    MAX_CALENDAR_RESPONSE_BYTES,
    HttpxGoogleCalendarReadPort,
    parse_calendar_ids,
)

FAKE_CLIENT_ID = "fake-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "fake-client-secret-value"
FAKE_REFRESH_TOKEN = "1//fake-refresh-token-secret"
FAKE_ACCESS_TOKEN = "ya29.FAKE-ACCESS-TOKEN-SENTINEL"
PRIMARY = "primary"
WORK_CAL = "work@example.com"
ALLOWED_IDS = frozenset({PRIMARY, WORK_CAL})

PORT_KWARGS = {
    "client_id": FAKE_CLIENT_ID,
    "client_secret": FAKE_CLIENT_SECRET,
    "refresh_token": FAKE_REFRESH_TOKEN,
    "allowed_calendar_ids": ALLOWED_IDS,
}

TOKEN_OK = httpx.Response(
    200,
    json={
        "access_token": FAKE_ACCESS_TOKEN,
        "expires_in": 3600,
        "scope": GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
    },
)
CALENDAR_LIST_RESPONSE = httpx.Response(
    200,
    json={
        "kind": "calendar#calendarList",
        "etag": "E1",
        "items": [
            {"id": PRIMARY, "summary": "Primary", "timeZone": "Asia/Seoul", "primary": True},
            {"id": WORK_CAL, "summary": "Work", "timeZone": "Asia/Seoul"},
        ],
    },
)
CALENDAR_GET_RESPONSE = httpx.Response(
    200,
    json={"id": PRIMARY, "summary": "Primary", "timeZone": "Asia/Seoul", "etag": "E2"},
)
EVENTS_RESPONSE = httpx.Response(
    200,
    json={
        "items": [
            {
                "id": "evt1",
                "summary": "Standup",
                "status": "confirmed",
                "start": {"dateTime": "2026-09-14T09:00:00+09:00"},
                "end": {"dateTime": "2026-09-14T09:30:00+09:00"},
            }
        ]
    },
)


def _handler(
    provider_responses: list[httpx.Response],
    recorded: list,
    *,
    token_response: httpx.Response = TOKEN_OK,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((str(request.url), request.method, dict(request.headers)))
        if str(request.url).startswith("https://oauth2.googleapis.com/token"):
            return token_response
        return provider_responses.pop(0)

    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


def _get(
    port,
    *,
    path=CALENDAR_LIST_PATH,
    query=None,
    scopes=(CALENDAR_READONLY_AUTH_SCOPE,),
    base_url=GOOGLE_CALENDAR_BASE_URL,
    max_response_bytes=128_000,
):
    return _run(port.get_json(
        binding_ref="bind:calendar", actor_ref="actor:1",
        required_scopes=scopes, base_url=base_url,
        path=path, query=query or {}, timeout_seconds=30,
        max_response_bytes=max_response_bytes,
    ))


def _token_calls(calls: list) -> list:
    return [c for c in calls if c[0].startswith("https://oauth2.googleapis.com/token")]


def _provider_calls(calls: list) -> list:
    return [c for c in calls if not c[0].startswith("https://oauth2.googleapis.com/token")]


def test_secret_names_declared_not_values() -> None:
    assert ENGINE_GOOGLE_OAUTH_CLIENT_ID == "ENGINE_GOOGLE_OAUTH_CLIENT_ID"
    assert ENGINE_GOOGLE_OAUTH_CLIENT_SECRET == "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET"
    assert ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN == "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN"
    assert ENGINE_CALENDAR_ALLOWED_CALENDARS == "ENGINE_CALENDAR_ALLOWED_CALENDARS"


def test_calendar_list_uses_single_existing_oauth_stack_official_get() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS, transport=_handler([CALENDAR_LIST_RESPONSE], calls)
    )
    body = _get(port)
    assert body["items"][0]["id"] == PRIMARY
    token = _token_calls(calls)
    provider = _provider_calls(calls)
    # Exactly one token refresh on the existing Google token endpoint, then
    # exactly one bounded GET on the official Calendar API host.
    assert len(token) == 1
    assert token[0][0] == "https://oauth2.googleapis.com/token"
    assert token[0][1] == "POST"
    assert len(provider) == 1
    assert provider[0][0] == f"https://www.googleapis.com/calendar/v3{CALENDAR_LIST_PATH}"
    assert provider[0][1] == "GET"
    assert provider[0][2]["authorization"] == f"Bearer {FAKE_ACCESS_TOKEN}"


def test_calendar_get_and_events_window_pass_through() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS, transport=_handler([CALENDAR_GET_RESPONSE, EVENTS_RESPONSE], calls)
    )
    assert _get(port, path=f"{CALENDAR_LIST_PATH}/{PRIMARY}")["id"] == PRIMARY
    events = _get(
        port,
        path=f"/calendars/{WORK_CAL}/events",
        query={"timeMin": "2026-09-14T00:00:00Z", "timeMax": "2026-09-15T00:00:00Z"},
    )
    assert events["items"][0]["id"] == "evt1"
    provider = _provider_calls(calls)
    assert provider[1][0].startswith(f"https://www.googleapis.com/calendar/v3/calendars/{WORK_CAL}/events?")
    assert "timeMin=" in provider[1][0]
    assert "timeMax=" in provider[1][0]


def test_unallowlisted_calendar_fails_closed_without_network() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([], calls))
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/calendars/other@example.com/events")
    assert str(exc_info.value) == "calendar_not_allowed"
    assert calls == []


def test_mutation_and_unknown_paths_rejected() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([], calls))
    for path in (
        "/users/me/calendarList/primary/events",
        "/calendars/primary/events/evt1/send",
        "/calendars/primary/acl",
        "/calendars/primary",
        "/users/me",
        "/calendars/primary/events/ev*bad",
        "/calendars/bad id/events",
    ):
        with pytest.raises(ValueError) as exc_info:
            _get(port, path=path)
        assert str(exc_info.value) == "method_not_permitted"
    assert calls == []


def test_malformed_window_query_rejected_before_token() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([], calls))
    with pytest.raises(ValueError) as exc_info:
        _get(port, path=f"/calendars/{PRIMARY}/events", query={"timeMin": "yesterday"})
    assert str(exc_info.value) == "method_not_permitted"
    assert calls == []


def test_scope_not_permitted_rejected() -> None:
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, scopes=(CALENDAR_READONLY_AUTH_SCOPE, "calendar.write"))
    assert str(exc_info.value) == "scope_not_permitted"


def test_host_not_permitted_rejected() -> None:
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, base_url="https://evil.example.com")
    assert str(exc_info.value) == "host_not_permitted"


def test_granted_scope_must_include_calendar_readonly() -> None:
    calls: list = []
    wrong_scope = httpx.Response(
        200,
        json={
            "access_token": FAKE_ACCESS_TOKEN,
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        },
    )
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS, transport=_handler([], calls, token_response=wrong_scope)
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "scope_not_granted"
    assert _provider_calls(calls) == []


def test_401_refreshes_once_and_retries_once() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS,
        transport=_handler([httpx.Response(401, content=b"expired"), CALENDAR_GET_RESPONSE], calls),
    )
    body = _get(port, path=f"{CALENDAR_LIST_PATH}/{PRIMARY}")
    assert body["id"] == PRIMARY
    assert len(_token_calls(calls)) == 2
    assert len(_provider_calls(calls)) == 2


def test_401_twice_fails_closed() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS,
        transport=_handler(
            [httpx.Response(401, content=b"a"), httpx.Response(401, content=b"b")], calls
        ),
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_http_401"
    assert len(_provider_calls(calls)) == 2


def test_response_too_large_aborts_stream() -> None:
    big = httpx.Response(200, content=b"x" * 128_001)
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([big], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "response_too_large"


def test_hard_cap_applies_even_when_caller_asks_for_more() -> None:
    big = httpx.Response(200, content=b"x" * (MAX_CALENDAR_RESPONSE_BYTES + 1))
    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=_handler([big], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, max_response_bytes=MAX_CALENDAR_RESPONSE_BYTES + 5_000_000)
    assert str(exc_info.value) == "response_too_large"


def test_provider_http_5xx_mapped_without_body() -> None:
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS, transport=_handler([httpx.Response(500, content=b"internal")], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_http_500"


def test_non_json_provider_response_mapped_to_safe_code() -> None:
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS, transport=_handler([httpx.Response(200, content=b"<html>")], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_response_invalid"


def test_network_exception_never_leaks_oauth_material() -> None:
    class ExplodingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                f"connect failed for {request.url} auth={request.headers.get('authorization')}"
            )

    port = HttpxGoogleCalendarReadPort(**PORT_KWARGS, transport=ExplodingTransport())
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    message = str(exc_info.value)
    assert message == "calendar_provider_request_failed"
    for secret in (FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, FAKE_CLIENT_SECRET, FAKE_CLIENT_ID):
        assert secret not in message
    assert "Bearer" not in message
    assert "googleapis.com" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_token_failure_codes_are_safe() -> None:
    calls: list = []
    port = HttpxGoogleCalendarReadPort(
        **PORT_KWARGS,
        transport=_handler([], calls, token_response=httpx.Response(400, content=b"invalid_grant")),
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_token_http_400"


def test_malformed_allowlist_or_empty_rejected_at_construction() -> None:
    for bad in (frozenset(), frozenset({"bad/id"}), frozenset({"has space"})):
        with pytest.raises(ValueError) as exc_info:
            HttpxGoogleCalendarReadPort(**{**PORT_KWARGS, "allowed_calendar_ids": bad})
        assert str(exc_info.value) == "calendar_id_invalid"
    with pytest.raises(ValueError) as exc_info:
        HttpxGoogleCalendarReadPort(**{**PORT_KWARGS, "client_id": ""})
    assert str(exc_info.value) == "calendar_id_invalid"


def test_parse_calendar_ids_is_bounded_and_fail_closed() -> None:
    assert parse_calendar_ids(None) == frozenset()
    assert parse_calendar_ids("  ") == frozenset()
    assert parse_calendar_ids(f"{PRIMARY}, {WORK_CAL} ,") == ALLOWED_IDS
    with pytest.raises(ValueError) as exc_info:
        parse_calendar_ids("bad/id")
    assert str(exc_info.value) == "calendar_id_invalid"
    with pytest.raises(ValueError) as exc_info:
        parse_calendar_ids(",".join(f"cal-{i}.example.com" for i in range(129)))
    assert str(exc_info.value) == "calendar_id_invalid"
