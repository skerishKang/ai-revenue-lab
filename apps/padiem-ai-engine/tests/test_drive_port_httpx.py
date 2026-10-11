"""HttpxDriveReadPort contract tests (#2206 S4-ACT1).

All tests use ``httpx.MockTransport`` so no real network call is ever made.
The mock handler distinguishes the token endpoint (oauth2.googleapis.com)
from the provider endpoint (www.googleapis.com) and returns canned
responses from pre-loaded queues.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.drive_port_httpx import (
    ENGINE_GOOGLE_OAUTH_CLIENT_ID,
    ENGINE_GOOGLE_OAUTH_CLIENT_SECRET,
    ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN,
    DRIVE_API_HOST,
    GOOGLE_TOKEN_URL,
    HttpxDriveReadPort,
)
from padiem_ai_core.drive_capability import DRIVE_BASE_URL, DRIVE_READONLY_SCOPE

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
        "scope": DRIVE_READONLY_SCOPE,
        "token_type": "Bearer",
    },
)
PROVIDER_JSON_RESPONSE = httpx.Response(
    200,
    json={"files": [{"id": "file_1", "name": "doc.txt"}]},
)
PROVIDER_TEXT_RESPONSE = httpx.Response(200, content="hello world")


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
        provider_responses=[PROVIDER_JSON_RESPONSE, PROVIDER_JSON_RESPONSE],
        recorded=calls,
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    _run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 1
    _run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 1


def test_token_rerefreshs_after_expiry() -> None:
    calls: list = []
    ticks = [0.0, 3601.0, 3602.0]
    transport = _handler(
        token_responses=[TOKEN_RESPONSE, TOKEN_RESPONSE],
        provider_responses=[PROVIDER_JSON_RESPONSE, PROVIDER_JSON_RESPONSE],
        recorded=calls,
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport, clock=lambda: ticks.pop(0))
    _run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    _run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    token_calls = [c for c in calls if c[0] == "token"]
    assert len(token_calls) == 2


def test_401_triggers_token_drop_and_retry() -> None:
    calls: list = []
    transport = _handler(
        token_responses=[TOKEN_RESPONSE, TOKEN_RESPONSE],
        provider_responses=[
            httpx.Response(401, content=b"unauthorized"),
            PROVIDER_JSON_RESPONSE,
        ],
        recorded=calls,
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    body = _run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    assert body["files"][0]["id"] == "file_1"
    provider_calls = [c for c in calls if c[0] == "provider"]
    assert len(provider_calls) == 2
    assert "Bearer access_1" in provider_calls[-1][3]


def test_scope_not_permitted_rejected() -> None:
    transport = _handler(token_responses=[], provider_responses=[], recorded=[])
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE, "drive.full"),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "scope_not_permitted"


def test_host_not_permitted_rejected() -> None:
    transport = _handler(token_responses=[], provider_responses=[], recorded=[])
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url="https://evil.example.com/drive/v3",
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "host_not_permitted"


def test_response_too_large_aborts_stream() -> None:
    big = b"x" * (1_000_001)
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[httpx.Response(200, content=big)],
        recorded=[],
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "response_too_large"


def test_provider_http_5xx_mapped_without_body() -> None:
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[httpx.Response(500, content=b"internal")],
        recorded=[],
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
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
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    text = str(exc_info.value)
    assert PORT_KWARGS["client_secret"] not in text
    assert PORT_KWARGS["refresh_token"] not in text
    assert PORT_KWARGS["client_id"] not in text


def test_get_text_returns_string() -> None:
    calls: list = []
    transport = _handler(
        token_responses=[TOKEN_RESPONSE],
        provider_responses=[PROVIDER_TEXT_RESPONSE],
        recorded=calls,
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    result = _run(
        port.get_text(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files/file_1/content",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )
    assert result == "hello world"
    provider_calls = [c for c in calls if c[0] == "provider"]
    assert len(provider_calls) == 1


def test_get_text_scope_gate() -> None:
    transport = _handler(token_responses=[], provider_responses=[], recorded=[])
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_text(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE, "drive.full"),
                base_url=DRIVE_BASE_URL,
                path="/files/file_1/content",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "scope_not_permitted"


def test_refresh_response_too_large_rejected() -> None:
    big = b"x" * (65_001)
    transport = _handler(
        token_responses=[httpx.Response(200, content=big)],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "provider_token_response_too_large"


def test_refresh_non_200_mapped() -> None:
    transport = _handler(
        token_responses=[httpx.Response(400, content=b"bad_request")],
        provider_responses=[],
        recorded=[],
    )
    port = HttpxDriveReadPort(**PORT_KWARGS, transport=transport)
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "provider_token_http_400"


def test_provider_redirect_not_followed() -> None:
    """A 3xx from the Drive provider must never forward the Bearer token."""
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "oauth2.googleapis.com":
            return TOKEN_RESPONSE
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    port = HttpxDriveReadPort(**PORT_KWARGS, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "provider_http_302"
    assert len(calls) == 2
    assert all("evil.example" not in url for url in calls)


def test_token_redirect_not_followed() -> None:
    """A 3xx from the token endpoint is a distinct provider_token_http_302."""
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    port = HttpxDriveReadPort(**PORT_KWARGS, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError) as exc_info:
        _run(
            port.get_json(
                binding_ref="bind:1",
                actor_ref="actor:1",
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files",
                query={},
                timeout_seconds=30,
                max_response_bytes=1_000_000,
            )
        )
    assert str(exc_info.value) == "provider_token_http_302"
    assert len(calls) == 1
    assert "evil.example" not in calls[0]
