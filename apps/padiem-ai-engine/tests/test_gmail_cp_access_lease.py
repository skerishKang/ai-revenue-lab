from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from padiem_ai_core.connectors import GMAIL_BASE_URL, GMAIL_READONLY_SCOPE
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.gmail_port_cp_lease import (
    ACCESS_TOKEN_CACHED,
    GMAIL_CREATE_DRAFT,
    GMAIL_SEND,
    GMAIL_WRITE,
    RAW_REFRESH_TOKEN_ACCEPTED,
    ControlPlaneLeaseGmailReadPort,
)
from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


NOW = datetime(2026, 9, 19, 5, 0, tzinfo=timezone.utc)
BINDING_REF = "gmail-binding-1"
ACTOR_REF = "actor_1"
TOKEN = "short-lived-gmail-token"


def run(coro):
    return asyncio.run(coro)


def lease(*, token: str = TOKEN, actor_ref: str = ACTOR_REF) -> EngineGoogleOAuthAccessLease:
    return EngineGoogleOAuthAccessLease(
        access_token=token,
        binding_ref=BINDING_REF,
        connector_id="gmail",
        actor_ref=actor_ref,
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GMAIL_READONLY_SCOPE,),
        expires_at=NOW + timedelta(hours=1),
    )


class FakeServiceBinding:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {
            "ok": True,
            "lease": {
                "access_token": TOKEN,
                "binding_ref": BINDING_REF,
                "connector_id": "gmail",
                "actor_ref": ACTOR_REF,
                "account_ref": "account_1",
                "workspace_ref": "workspace_1",
                "scopes": [GMAIL_READONLY_SCOPE],
                "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        }
        self.error = error
        self.calls = []

    async def issue_access_lease(self, payload):
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error
        return self.result


class FakeLeaseClient:
    def __init__(self, leases=None, error: Exception | None = None) -> None:
        self.leases = list(leases or [lease()])
        self.error = error
        self.calls = []

    async def issue_access_lease(self, *, binding_ref: str, connector_id: str):
        self.calls.append({"binding_ref": binding_ref, "connector_id": connector_id})
        if self.error is not None:
            raise self.error
        if len(self.leases) > 1:
            return self.leases.pop(0)
        return self.leases[0]


def test_private_service_binding_client_accepts_exact_gmail_lease() -> None:
    binding = FakeServiceBinding()
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(binding, clock=lambda: NOW)
    result = run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="gmail"))

    assert result.access_token == TOKEN
    assert result.binding_ref == BINDING_REF
    assert result.connector_id == "gmail"
    assert result.actor_ref == ACTOR_REF
    assert result.scopes == (GMAIL_READONLY_SCOPE,)
    assert binding.calls == [{"binding_ref": BINDING_REF, "connector_id": "gmail"}]
    assert TOKEN not in repr(result)
    assert TOKEN not in repr(result.safe_dict())


def test_private_service_binding_client_rejects_gmail_scope_mismatch() -> None:
    wire = dict(FakeServiceBinding().result["lease"])
    wire["scopes"] = ["https://mail.google.com/"]
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(
        FakeServiceBinding(result={"ok": True, "lease": wire}),
        clock=lambda: NOW,
    )
    with pytest.raises(ServiceContractError) as caught:
        run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="gmail"))
    assert caught.value.code == "google_oauth_access_lease_unavailable"


def test_lease_backed_gmail_get_uses_server_binding_actor_and_bearer_only() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})

    lease_client = FakeLeaseClient()
    port = ControlPlaneLeaseGmailReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_json(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_BASE_URL,
            path="/users/me/messages",
            query={"maxResults": "1"},
            timeout_seconds=10,
            max_response_bytes=10000,
        )
    )

    assert result == {"messages": [{"id": "m1"}]}
    assert lease_client.calls == [{"binding_ref": BINDING_REF, "connector_id": "gmail"}]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_gmail_binding_or_actor_mismatch_blocks_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    port = ControlPlaneLeaseGmailReadPort(
        lease_client=FakeLeaseClient(leases=[lease(actor_ref="actor_other")]),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError) as caught:
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert caught.value.code == "gmail_access_lease_mismatch"
    assert provider_calls == 0


def test_gmail_lease_failure_fails_closed_without_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    port = ControlPlaneLeaseGmailReadPort(
        lease_client=FakeLeaseClient(
            error=ServiceContractError(
                "google_oauth_access_lease_unavailable",
                "lease unavailable",
                status_code=503,
            )
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError) as caught:
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url=GMAIL_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert caught.value.code == "google_oauth_access_lease_unavailable"
    assert provider_calls == 0


def test_gmail_provider_401_requests_one_fresh_cp_lease_and_retries_once() -> None:
    observed_tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_tokens.append(request.headers["Authorization"])
        if len(observed_tokens) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"messages": []})

    lease_client = FakeLeaseClient(
        leases=[lease(token="token-one"), lease(token="token-two")]
    )
    port = ControlPlaneLeaseGmailReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_json(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_BASE_URL,
            path="/users/me/messages",
            query={},
            timeout_seconds=10,
            max_response_bytes=10000,
        )
    )

    assert result == {"messages": []}
    assert observed_tokens == ["Bearer token-one", "Bearer token-two"]
    assert lease_client.calls == [
        {"binding_ref": BINDING_REF, "connector_id": "gmail"},
        {"binding_ref": BINDING_REF, "connector_id": "gmail"},
    ]


def test_gmail_write_scope_and_non_gmail_host_fail_before_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    port = ControlPlaneLeaseGmailReadPort(
        lease_client=FakeLeaseClient(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError) as scope_error:
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=("https://www.googleapis.com/auth/gmail.modify",),
                base_url=GMAIL_BASE_URL,
                path="/users/me/messages",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert scope_error.value.code == "gmail_access_lease_mismatch"

    with pytest.raises(ToolHandlerError) as host_error:
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(GMAIL_READONLY_SCOPE,),
                base_url="https://evil.example/gmail/v1",
                path="/users/me/messages",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert host_error.value.code == "gmail_provider_unavailable"
    assert provider_calls == 0


def test_canonical_gmail_port_has_no_refresh_secret_or_token_cache() -> None:
    assert RAW_REFRESH_TOKEN_ACCEPTED is False
    assert ACCESS_TOKEN_CACHED is False
    assert GMAIL_WRITE is False
    assert GMAIL_CREATE_DRAFT is False
    assert GMAIL_SEND is False

    app_root = Path(__file__).resolve().parents[1]
    worker_source = (app_root / "worker_identity.py").read_text(encoding="utf-8")
    gmail_block = worker_source.split("def _gmail_port_for_env", 1)[1].split(
        "async def _gmail_grants_for_env", 1
    )[0]
    assert "ControlPlaneLeaseGmailReadPort" in gmail_block
    assert "CONTROL_PLANE_GOOGLE_OAUTH_BINDING_NAME" in gmail_block
    assert "gmail_worker_transport" in gmail_block
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_ID_ENV" not in gmail_block
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET_ENV" not in gmail_block
    assert "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN_ENV" not in gmail_block
    assert "HttpxGmailReadPort" not in worker_source
