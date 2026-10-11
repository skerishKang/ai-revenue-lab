from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_ai_core.drive_capability import DRIVE_BASE_URL, DRIVE_READONLY_SCOPE
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.drive_port_cp_lease import (
    MAX_GOOGLE_API_RESPONSE_BYTES,
    ControlPlaneLeaseDriveReadPort,
)
from app.drive_port_httpx import HttpxDriveReadPort
from app.google_oauth_access_lease import EngineGoogleOAuthAccessLease

BINDING_REF = "bind:drive_binary"
ACTOR_REF = "actor_binary"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
PDF_BYTES = b"%PDF-1.7\x00\xffbinary\n%%EOF"


def run(coro):
    return asyncio.run(coro)


class FakeLeaseClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def issue_access_lease(self, *, binding_ref: str, connector_id: str):
        self.calls.append({"binding_ref": binding_ref, "connector_id": connector_id})
        return EngineGoogleOAuthAccessLease(
            access_token="ephemeral-access-token",
            binding_ref=BINDING_REF,
            connector_id="google-drive",
            actor_ref=ACTOR_REF,
            account_ref="account_binary",
            workspace_ref="workspace_binary",
            scopes=(DRIVE_READONLY_SCOPE,),
            expires_at=NOW + timedelta(minutes=30),
        )


def test_cp_lease_port_returns_opaque_bytes_with_readonly_lease() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=PDF_BYTES)

    lease_client = FakeLeaseClient()
    port = ControlPlaneLeaseDriveReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_bytes(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files/pdf_1",
            query={"alt": "media"},
            timeout_seconds=30,
            max_response_bytes=MAX_GOOGLE_API_RESPONSE_BYTES,
        )
    )
    assert result == PDF_BYTES
    assert lease_client.calls == [{"binding_ref": BINDING_REF, "connector_id": "google-drive"}]
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer ephemeral-access-token"


def test_cp_lease_binary_read_keeps_scope_and_size_gates() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, content=PDF_BYTES)

    port = ControlPlaneLeaseDriveReadPort(
        lease_client=FakeLeaseClient(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError):
        run(
            port.get_bytes(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=("https://www.googleapis.com/auth/drive",),
                base_url=DRIVE_BASE_URL,
                path="/files/pdf_1",
                query={"alt": "media"},
                timeout_seconds=30,
                max_response_bytes=MAX_GOOGLE_API_RESPONSE_BYTES,
            )
        )
    assert provider_calls == 0

    with pytest.raises(ToolHandlerError):
        run(
            port.get_bytes(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files/pdf_1",
                query={"alt": "media"},
                timeout_seconds=30,
                max_response_bytes=MAX_GOOGLE_API_RESPONSE_BYTES + 1,
            )
        )
    assert provider_calls == 0


def test_legacy_compatibility_port_returns_non_utf8_bytes_without_decoding() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "access_token": "access_binary",
                    "expires_in": 3600,
                    "scope": DRIVE_READONLY_SCOPE,
                },
            )
        return httpx.Response(200, content=PDF_BYTES)

    port = HttpxDriveReadPort(
        client_id="client_binary",
        client_secret="secret_binary",
        refresh_token="refresh_binary",
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_bytes(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files/pdf_1",
            query={"alt": "media"},
            timeout_seconds=30,
            max_response_bytes=1000,
        )
    )
    assert result == PDF_BYTES
    assert len(calls) == 2


def test_legacy_binary_read_still_rejects_write_scope_and_redirect() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "access_token": "access_binary",
                    "expires_in": 3600,
                    "scope": DRIVE_READONLY_SCOPE,
                },
            )
        provider_calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    port = HttpxDriveReadPort(
        client_id="client_binary",
        client_secret="secret_binary",
        refresh_token="refresh_binary",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError) as scope_error:
        run(
            port.get_bytes(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=("https://www.googleapis.com/auth/drive",),
                base_url=DRIVE_BASE_URL,
                path="/files/pdf_1",
                query={},
                timeout_seconds=30,
                max_response_bytes=1000,
            )
        )
    assert str(scope_error.value) == "scope_not_permitted"
    assert provider_calls == 0

    with pytest.raises(ValueError) as redirect_error:
        run(
            port.get_bytes(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url=DRIVE_BASE_URL,
                path="/files/pdf_1",
                query={},
                timeout_seconds=30,
                max_response_bytes=1000,
            )
        )
    assert str(redirect_error.value) == "provider_http_302"
    assert provider_calls == 1
