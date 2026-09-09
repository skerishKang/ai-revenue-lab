from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_ai_core.drive_capability import DRIVE_READONLY_SCOPE

from app.drive_port_cp_lease import ControlPlaneLeaseDriveReadPort
from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


NOW = datetime(2026, 9, 9, 5, 0, tzinfo=timezone.utc)
BINDING_REF = "google-drive-binding-1"
ACTOR_REF = "actor_1"
TOKEN = "short-lived-access-token"


def run(coro):
    return asyncio.run(coro)


def lease(*, token: str = TOKEN, actor_ref: str = ACTOR_REF) -> EngineGoogleOAuthAccessLease:
    return EngineGoogleOAuthAccessLease(
        access_token=token,
        binding_ref=BINDING_REF,
        connector_id="google-drive",
        actor_ref=actor_ref,
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(DRIVE_READONLY_SCOPE,),
        expires_at=NOW + timedelta(hours=1),
    )


class FakeServiceBinding:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {
            "ok": True,
            "lease": {
                "access_token": TOKEN,
                "binding_ref": BINDING_REF,
                "connector_id": "google-drive",
                "actor_ref": ACTOR_REF,
                "account_ref": "account_1",
                "workspace_ref": "workspace_1",
                "scopes": [DRIVE_READONLY_SCOPE],
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


def test_private_service_binding_client_accepts_exact_drive_lease() -> None:
    binding = FakeServiceBinding()
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(binding, clock=lambda: NOW)
    result = run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-drive"))

    assert result.access_token == TOKEN
    assert result.binding_ref == BINDING_REF
    assert result.actor_ref == ACTOR_REF
    assert result.scopes == (DRIVE_READONLY_SCOPE,)
    assert binding.calls == [{"binding_ref": BINDING_REF, "connector_id": "google-drive"}]
    assert TOKEN not in repr(result)
    assert TOKEN not in repr(result.safe_dict())
    assert result.safe_dict()["raw_access_token"] is False
    assert result.safe_dict()["raw_refresh_token"] is False


def test_private_client_rejects_refresh_token_or_extra_fields_in_rpc_response() -> None:
    bad = FakeServiceBinding(
        result={
            "ok": True,
            "lease": {
                "access_token": TOKEN,
                "refresh_token": "must-never-enter-engine",
                "binding_ref": BINDING_REF,
                "connector_id": "google-drive",
                "actor_ref": ACTOR_REF,
                "account_ref": "account_1",
                "workspace_ref": "workspace_1",
                "scopes": [DRIVE_READONLY_SCOPE],
                "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        }
    )
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(bad, clock=lambda: NOW)
    with pytest.raises(ServiceContractError) as caught:
        run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-drive"))
    assert caught.value.code == "google_oauth_access_lease_unavailable"


def test_private_client_rejects_wrong_scope_binding_and_expiry() -> None:
    variants = [
        {"scopes": ["https://www.googleapis.com/auth/drive"]},
        {"binding_ref": "different-binding"},
        {"expires_at": (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
        {"expires_at": (NOW + timedelta(seconds=7201)).isoformat().replace("+00:00", "Z")},
    ]
    for replacement in variants:
        wire = dict(FakeServiceBinding().result["lease"])
        wire.update(replacement)
        client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(
            FakeServiceBinding(result={"ok": True, "lease": wire}),
            clock=lambda: NOW,
        )
        with pytest.raises(ServiceContractError):
            run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-drive"))


def test_private_client_rejects_non_drive_connector_without_rpc_call() -> None:
    binding = FakeServiceBinding()
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(binding, clock=lambda: NOW)
    with pytest.raises(ServiceContractError):
        run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="gmail"))
    assert binding.calls == []


def test_lease_backed_drive_get_uses_server_binding_ref_actor_and_bearer_only() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"files": [{"id": "file_1"}]})

    lease_client = FakeLeaseClient()
    port = ControlPlaneLeaseDriveReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_json(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url="https://www.googleapis.com",
            path="/drive/v3/files",
            query={"pageSize": "1"},
            timeout_seconds=10,
            max_response_bytes=10000,
        )
    )

    assert result == {"files": [{"id": "file_1"}]}
    assert lease_client.calls == [{"binding_ref": BINDING_REF, "connector_id": "google-drive"}]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert "refresh" not in requests[0].headers["Authorization"].casefold()


def test_lease_binding_or_actor_mismatch_blocks_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    port = ControlPlaneLeaseDriveReadPort(
        lease_client=FakeLeaseClient(leases=[lease(actor_ref="actor_other")]),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceContractError):
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url="https://www.googleapis.com",
                path="/drive/v3/files",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert provider_calls == 0


def test_cp_lease_failure_fails_closed_without_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    lease_client = FakeLeaseClient(
        error=ServiceContractError(
            "google_oauth_access_lease_unavailable",
            "lease unavailable",
            status_code=503,
        )
    )
    port = ControlPlaneLeaseDriveReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceContractError):
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url="https://www.googleapis.com",
                path="/drive/v3/files",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert provider_calls == 0


def test_provider_401_requests_one_fresh_cp_lease_and_retries_once() -> None:
    observed_tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_tokens.append(request.headers["Authorization"])
        if len(observed_tokens) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"files": []})

    lease_client = FakeLeaseClient(
        leases=[lease(token="token-one"), lease(token="token-two")]
    )
    port = ControlPlaneLeaseDriveReadPort(
        lease_client=lease_client,
        transport=httpx.MockTransport(handler),
    )
    result = run(
        port.get_json(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url="https://www.googleapis.com",
            path="/drive/v3/files",
            query={},
            timeout_seconds=10,
            max_response_bytes=10000,
        )
    )
    assert result == {"files": []}
    assert observed_tokens == ["Bearer token-one", "Bearer token-two"]
    assert len(lease_client.calls) == 2


def test_write_scope_and_non_google_host_are_rejected_before_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    port = ControlPlaneLeaseDriveReadPort(
        lease_client=FakeLeaseClient(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ServiceContractError):
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=("https://www.googleapis.com/auth/drive",),
                base_url="https://www.googleapis.com",
                path="/drive/v3/files",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    with pytest.raises(ServiceContractError):
        run(
            port.get_json(
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                required_scopes=(DRIVE_READONLY_SCOPE,),
                base_url="https://evil.example",
                path="/drive/v3/files",
                query={},
                timeout_seconds=10,
                max_response_bytes=10000,
            )
        )
    assert provider_calls == 0


def test_lease_backed_port_has_no_refresh_or_client_secret_state() -> None:
    port = ControlPlaneLeaseDriveReadPort(lease_client=FakeLeaseClient())
    assert not hasattr(port, "_refresh_token")
    assert not hasattr(port, "_client_secret")
    assert not hasattr(port, "_client_id")
    assert not hasattr(port, "_access_token")
    assert not hasattr(port, "create")
    assert not hasattr(port, "update")
    assert not hasattr(port, "delete")
