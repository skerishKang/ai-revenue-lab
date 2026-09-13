"""HttpxSlackReadPort contract tests (#2356).

All tests use ``httpx.MockTransport`` so no real network call is ever made.
The bot token is a fake sentinel; assertions prove it never leaks through
exception strings, causes or contexts — including via the bearer header.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from padiem_ai_core.slack_capability import (
    SLACK_BASE_URL,
    SLACK_READONLY_AUTH_SCOPE,
)
from app.slack_port_httpx import (
    ALLOWED_SLACK_METHOD_PATHS,
    CHANNEL_GATED_SLACK_PATHS,
    ENGINE_SLACK_ALLOWED_CHANNELS,
    ENGINE_SLACK_BOT_TOKEN,
    ENGINE_SLACK_PRIVATE_CHANNELS,
    HttpxSlackReadPort,
    parse_slack_channel_ids,
)

FAKE_TOKEN = "xoxb-fake-1234567890123-abcdefghijklmnop"
ALLOWED_CHANNEL_ID = "C0AAAAAAA"
PRIVATE_CHANNEL_ID = "D0BBBBBBB"
PORT_KWARGS = {
    "bot_token": FAKE_TOKEN,
    "allowed_channel_ids": frozenset({ALLOWED_CHANNEL_ID, PRIVATE_CHANNEL_ID}),
}

AUTH_TEST_RESPONSE = httpx.Response(
    200,
    json={"ok": True, "url": "https://acme.slack.com/", "team": "Acme", "team_id": "T0TEAM123"},
)
LIST_RESPONSE = httpx.Response(
    200,
    json={
        "ok": True,
        "channels": [
            {"id": ALLOWED_CHANNEL_ID, "name": "ops", "is_private": False},
            {"id": PRIVATE_CHANNEL_ID, "name": "secrets", "is_private": True},
            {"id": "C0NOTLISTD", "name": "general", "is_private": False},
        ],
    },
)
HISTORY_RESPONSE = httpx.Response(
    200,
    json={"ok": True, "messages": [{"ts": "1700000000.000100", "text": "hello", "user": "U0USER1"}]},
)


def _handler(provider_responses: list[httpx.Response], recorded: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((str(request.url), request.method, dict(request.headers)))
        return provider_responses.pop(0)

    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


def _get(
    port,
    *,
    path="/api/auth.test",
    query=None,
    scopes=(SLACK_READONLY_AUTH_SCOPE,),
    base_url=SLACK_BASE_URL,
):
    return _run(port.get_json(
        binding_ref="bind:slack", actor_ref="actor:1",
        required_scopes=scopes, base_url=base_url,
        path=path, query=query or {}, timeout_seconds=30,
        max_response_bytes=128_000,
    ))


def test_secret_names_declared_not_values() -> None:
    assert ENGINE_SLACK_BOT_TOKEN == "ENGINE_SLACK_BOT_TOKEN"
    assert ENGINE_SLACK_ALLOWED_CHANNELS == "ENGINE_SLACK_ALLOWED_CHANNELS"
    assert ENGINE_SLACK_PRIVATE_CHANNELS == "ENGINE_SLACK_PRIVATE_CHANNELS"


def test_auth_test_projects_bounded_official_api_call() -> None:
    calls: list = []
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([AUTH_TEST_RESPONSE], calls))
    body = _get(port)
    assert body["team_id"] == "T0TEAM123"
    assert calls[0][0] == "https://slack.com/api/auth.test"
    assert calls[0][1] == "POST"
    assert calls[0][2]["authorization"] == f"Bearer {FAKE_TOKEN}"


def test_channel_history_allowed_for_allowlisted_channel_only() -> None:
    calls: list = []
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([HISTORY_RESPONSE], calls))
    body = _get(
        port,
        path="/api/conversations.history",
        query={"channel": ALLOWED_CHANNEL_ID},
    )
    assert body["messages"][0]["text"] == "hello"
    assert len(calls) == 1


def test_unallowlisted_channel_fails_closed_without_network() -> None:
    calls: list = []
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([], calls))
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/api/conversations.history", query={"channel": "C0ZZZZZZZZ"})
    assert str(exc_info.value) == "channel_not_allowed"
    assert calls == []


def test_malformed_channel_id_rejected_before_allowlist_check() -> None:
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/api/conversations.replies", query={"channel": "lowercase1"})
    assert str(exc_info.value) == "channel_id_invalid"
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/api/conversations.replies", query={})
    assert str(exc_info.value) == "channel_id_invalid"


def test_conversations_list_output_filtered_to_server_allowlist() -> None:
    calls: list = []
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([LIST_RESPONSE], calls))
    body = _get(port, path="/api/conversations.list")
    ids = [channel["id"] for channel in body["channels"]]
    # private stays hidden until explicitly enumerated
    assert ids == [ALLOWED_CHANNEL_ID]


def test_private_channel_returned_only_when_explicitly_enumerated() -> None:
    calls: list = []
    port = HttpxSlackReadPort(
        bot_token=FAKE_TOKEN,
        allowed_channel_ids=frozenset({ALLOWED_CHANNEL_ID, PRIVATE_CHANNEL_ID}),
        explicitly_private_channel_ids=frozenset({PRIVATE_CHANNEL_ID}),
        transport=_handler([LIST_RESPONSE], calls),
    )
    body = _get(port, path="/api/conversations.list")
    ids = [channel["id"] for channel in body["channels"]]
    assert sorted(ids) == sorted([ALLOWED_CHANNEL_ID, PRIVATE_CHANNEL_ID])


def test_private_subset_outside_allowlist_rejected_at_construction() -> None:
    with pytest.raises(ValueError) as exc_info:
        HttpxSlackReadPort(
            bot_token=FAKE_TOKEN,
            allowed_channel_ids=frozenset({ALLOWED_CHANNEL_ID}),
            explicitly_private_channel_ids=frozenset({PRIVATE_CHANNEL_ID}),
        )
    assert str(exc_info.value) == "channel_id_invalid"


def test_scope_not_permitted_rejected() -> None:
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, scopes=(SLACK_READONLY_AUTH_SCOPE, "slack.send"))
    assert str(exc_info.value) == "scope_not_permitted"


def test_method_not_permitted_rejected() -> None:
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([], []))
    assert ALLOWED_SLACK_METHOD_PATHS == frozenset(
        {
            "/api/auth.test",
            "/api/conversations.list",
            "/api/conversations.history",
            "/api/conversations.replies",
            "/api/users.info",
            "/api/files.info",
        }
    )
    assert CHANNEL_GATED_SLACK_PATHS == frozenset(
        {"/api/conversations.history", "/api/conversations.replies"}
    )
    for path in (
        "/api/chat.postMessage",
        "/api/chat.update",
        "/api/conversations.join",
        "/api/files.upload",
        "/api/users.setPresence",
    ):
        with pytest.raises(ValueError) as exc_info:
            _get(port, path=path)
        assert str(exc_info.value) == "method_not_permitted"


def test_host_not_permitted_rejected() -> None:
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, base_url="https://evil.example.com")
    assert str(exc_info.value) == "host_not_permitted"


def test_response_too_large_aborts_stream() -> None:
    big = httpx.Response(200, content=b"x" * (128_001))
    port = HttpxSlackReadPort(**PORT_KWARGS, transport=_handler([big], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "response_too_large"


def test_provider_http_5xx_mapped_without_body() -> None:
    port = HttpxSlackReadPort(
        **PORT_KWARGS, transport=_handler([httpx.Response(500, content=b"internal")], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_http_500"


def test_non_json_provider_response_mapped_to_safe_code() -> None:
    port = HttpxSlackReadPort(
        **PORT_KWARGS, transport=_handler([httpx.Response(200, content=b"<html>")], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_response_invalid"


def test_network_exception_never_leaks_bearer_token() -> None:
    class ExplodingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"connect failed for {request.url}")

    port = HttpxSlackReadPort(**PORT_KWARGS, transport=ExplodingTransport())
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    message = str(exc_info.value)
    assert FAKE_TOKEN not in message
    assert "Bearer" not in message
    assert "slack.com" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_invalid_token_shape_rejected_at_construction() -> None:
    for bad in ("", "nocolon", "xoxp-fake-1234567890123-abcdefghijklmnop", "xoxb-short"):
        with pytest.raises(ValueError) as exc_info:
            HttpxSlackReadPort(bot_token=bad, allowed_channel_ids=frozenset({ALLOWED_CHANNEL_ID}))
        assert str(exc_info.value) == "bot_token_invalid"


def test_empty_allowlist_rejected_at_construction() -> None:
    with pytest.raises(ValueError) as exc_info:
        HttpxSlackReadPort(bot_token=FAKE_TOKEN, allowed_channel_ids=frozenset())
    assert str(exc_info.value) == "channel_id_invalid"


def test_parse_slack_channel_ids_is_bounded_and_fail_closed() -> None:
    assert parse_slack_channel_ids(None) == frozenset()
    assert parse_slack_channel_ids("  ") == frozenset()
    assert parse_slack_channel_ids(f"{ALLOWED_CHANNEL_ID}, {PRIVATE_CHANNEL_ID} ,") == frozenset(
        {ALLOWED_CHANNEL_ID, PRIVATE_CHANNEL_ID}
    )
    with pytest.raises(ValueError) as exc_info:
        parse_slack_channel_ids("lowercase-id")
    assert str(exc_info.value) == "channel_id_invalid"
    with pytest.raises(ValueError) as exc_info:
        parse_slack_channel_ids("C01")
    assert str(exc_info.value) == "channel_id_invalid"
    with pytest.raises(ValueError) as exc_info:
        parse_slack_channel_ids(",".join(f"C{i:010d}" for i in range(129)))
    assert str(exc_info.value) == "channel_id_invalid"
