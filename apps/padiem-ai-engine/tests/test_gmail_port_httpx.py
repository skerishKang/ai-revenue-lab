"""WO-10 PR-C2 commit 1: HttpxGmailReadPort contract tests (D28).

All tests use ``httpx.MockTransport`` so no real network call is ever made.
The mock handler distinguishes the token endpoint (oauth2.googleapis.com)
from the provider endpoint (gmail.googleapis.com) and returns canned
responses from pre-loaded queues.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.gmail_port_httpx import (
    ENGINE_GOOGLE_OAUTH_CLIENT_ID,
    ENGINE_GOOGLE_OAUTH_CLIENT_SECRET,
    ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN,
    GMAIL_API_HOST,
    GOOGLE_TOKEN_URL,
    HttpxGmailReadPort,
)
from padiem_ai_core.connectors import GMAIL_BASE_URL, GMAIL_READONLY_SCOPE

PORT_KWARGS = {
    "client_id": "client_1",
    "client_secret": "secret_1",
    "refresh_token": "refresh_1",
}
TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "access_1",
        "expires_in": 3600,
        "scope": GMAIL_READONLY_SCOPE,
        "token_type": "Bearer",
    },
)
PROVIDER_RESPONSE = httpx.Response(
    200,
    json={"messages": [{"id": "msg_1", "threadId": "thread_1"}]},
)


def _handler(
    token_responses: list[httpx.Response],
    provider_responses: list[httpx.Response],
    recorded: list,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            recorded.append(("token", str(request.url), request.method, request.headers.get("authorization")))
            return token_responses.pop(0)
        recorded.append(("provider", str(request.url), request.method, request.headers.get("authorization")))
        return provider_responses.pop(0)

    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


def test_token_refresh_once_then_cached_reuse() -> None:
    calls: list = []
    transport = _handler(
        token_responses=[TOKEN_RESPONSE, TOKEN_RESPONSE],
        provider_responses=[PROVIDER_RESPONSE, PROVIDER_RESPONSE],
        recorded=calls,
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    # First call: refresh token + provider GET.
    _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 1
    # Second call within TTL: cached token reused, no second refresh.
    _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 1


def test_token_rerefreshs_after_expiry() -> None:
    calls: list = []
    ticks = [0.0, 3601.0, 3602.0]  # 3rd tick funds _access_token_for cache-check clock() call.
    transport = _handler(
        token_responses=[TOKEN_RESPONSE, TOKEN_RESPONSE],
        provider_responses=[PROVIDER_RESPONSE, PROVIDER_RESPONSE],
        recorded=calls,
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport, clock=lambda: ticks.pop(0))
    _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 2


def test_401_triggers_token_drop_and_retry() -> None:
    calls: list = []
    transport = _handler(
        token_responses=[TOKEN_RESPONSE, TOKEN_RESPONSE],
        provider_responses=[
            httpx.Response(401, content=b"unauthorized"),
            PROVIDER_RESPONSE,
        ],
        recorded=calls,
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    body = _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    assert body["messages"][0]["id"] == "msg_1"
    provider_calls = [c for c in calls if c[0] == "provider"]
    assert len(provider_calls) == 2  # 401 then retry.
    assert "Bearer access_1" in provider_calls[-1][3]


def test_scope_not_permitted_rejected() -> None:
    transport = _handler(token_responses=[], provider_responses=[], recorded=[])
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE, "gmail.send"),
            base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "scope_not_permitted"


def test_host_not_permitted_rejected() -> None:
    transport = _handler(token_responses=[], provider_responses=[], recorded=[])
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url="https://evil.example.com/gmail/v1",
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "host_not_permitted"


def test_response_too_large_aborts_stream() -> None:
    big = b"x" * (1_000_001)
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[httpx.Response(200, content=big)],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "response_too_large"


def test_provider_http_5xx_mapped_without_body() -> None:
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[httpx.Response(500, content=b"internal")],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "provider_http_500"


def test_exception_strings_never_contain_secrets() -> None:
    transport = _handler(
        token_responses=[
            httpx.Response(400, content=(
                f"client_id={PORT_KWARGS['client_id']}"
                f"&client_secret={PORT_KWARGS['client_secret']}"
                f"&refresh_token={PORT_KWARGS['refresh_token']}"
            )),
        ],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    text = str(exc_info.value)
    assert PORT_KWARGS["client_secret"] not in text
    assert PORT_KWARGS["refresh_token"] not in text
    assert PORT_KWARGS["client_id"] not in text


def test_authorization_header_reaches_mock() -> None:
    calls: list = []
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[PROVIDER_RESPONSE],
        recorded=calls,
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    _run(port.get_json(
        binding_ref="bind:1", actor_ref="actor:1",
        required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
        path="/users/me/messages", query={}, timeout_seconds=30,
        max_response_bytes=1_000_000,
    ))
    provider_calls = [c for c in calls if c[0] == "provider"]
    assert len(provider_calls) == 1
    assert provider_calls[0][3] == "Bearer access_1"


def test_refresh_scope_validation_requires_granted_scope() -> None:
    transport = _handler(
        token_responses=[
            httpx.Response(200, json={"access_token": "tok", "expires_in": 3600, "token_type": "Bearer"}),
        ],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "scope_not_granted"


def test_refresh_response_too_large_rejected() -> None:
    big = b"x" * (65_001)
    transport = _handler(
        token_responses=[httpx.Response(200, content=big)],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "provider_token_response_too_large"


def test_refresh_non_200_mapped() -> None:
    transport = _handler(
        token_responses=[httpx.Response(400, content=b"bad_request")],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxGmailReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "provider_token_http_400"


def test_provider_redirect_not_followed() -> None:
    """A 3xx from the Gmail provider must never forward the Bearer token.

    With ``follow_redirects=False`` the 302 (Location: evil.example) is
    reported as ``provider_http_302`` and no second request is issued, so the
    Authorization header can never be replayed to another host.
    """
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "oauth2.googleapis.com":
            return TOKEN_RESPONSE
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    port = HttpxGmailReadPort(**PORT_KWARGS, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "provider_http_302"
    # Exactly one token refresh + one provider GET; the provider 302 was not
    # followed to evil.example.
    assert len(calls) == 2
    assert all("evil.example" not in url for url in calls)


def test_token_redirect_not_followed() -> None:
    """A 3xx from the token endpoint is a distinct ``provider_token_http_302``.

    The redirect must not be followed (the client secret/refresh token POST is
    never replayed elsewhere) and the handler is called exactly once.
    """
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    port = HttpxGmailReadPort(**PORT_KWARGS, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError) as exc_info:
        _run(port.get_json(
            binding_ref="bind:1", actor_ref="actor:1",
            required_scopes=(GMAIL_READONLY_SCOPE,), base_url=GMAIL_BASE_URL,
            path="/users/me/messages", query={}, timeout_seconds=30,
            max_response_bytes=1_000_000,
        ))
    assert str(exc_info.value) == "provider_token_http_302"
    # Only the token request happened; the 302 was not followed.
    assert len(calls) == 1
    assert "evil.example" not in calls[0]