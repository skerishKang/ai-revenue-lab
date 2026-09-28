"""Workspace-scoped Drive grant provider tests (#3193, blocks #3190).

Network-free. Proves the Engine resolves the canonical Drive grant per trusted
workspace, rejects cross-workspace / wrong-connector responses, and never falls
back to the global Engine connector-grant table.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from padiem_ai_core.drive_capability import DriveCapability

from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID
import app.drive_workspace_grant as grant_module
from app.drive_workspace_grant import (
    DriveWorkspaceGrantError,
    WorkspaceScopedDriveGrantProvider,
    drive_workspace_grant_snapshot,
)

WORKSPACE_A = "ws_alpha_001"
WORKSPACE_B = "ws_beta_002"
BINDING_A = "bind:drive_alpha"
BINDING_B = "bind:drive_beta"


def run(coro):
    return asyncio.run(coro)


class FakeControlPlaneClient:
    """Private Control Plane Google OAuth selector double."""

    def __init__(self, payload=None, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[str] = []

    async def select_drive_binding(self, *, workspace_ref: str):
        self.calls.append(workspace_ref)
        if self.error is not None:
            raise self.error
        return self.payload


def resolved_payload(workspace_ref: str = WORKSPACE_A, binding_ref: str = BINDING_A, actor_ref: str = "actor_a") -> dict:
    return {
        "status": "resolved",
        "connector_id": "google-drive",
        "workspace_ref": workspace_ref,
        "binding_ref": binding_ref,
        "actor_ref": actor_ref,
    }


def not_connected_payload(workspace_ref: str = WORKSPACE_A) -> dict:
    return {"status": "not_connected", "connector_id": "google-drive", "workspace_ref": workspace_ref}


# --- 1. workspace-scoped canonical grant ----------------------------------


def test_workspace_scoped_drive_grant_is_resolved() -> None:
    client = FakeControlPlaneClient(resolved_payload())
    provider = WorkspaceScopedDriveGrantProvider(client=client)
    grant = run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))

    assert grant is not None
    assert client.calls == [WORKSPACE_A], "the trusted workspace must be the selector input"
    assert grant.app_id == DRIVE_REFERENCE_APP_ID
    assert grant.canonical_agent_id == DRIVE_AGENT_ID
    assert grant.binding_ref == BINDING_A
    assert grant.actor_ref == "actor_a"
    assert grant.granted_capabilities == (DriveCapability.READ,)


def test_two_workspaces_resolve_their_own_binding() -> None:
    provider_a = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(resolved_payload(WORKSPACE_A, BINDING_A)))
    provider_b = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(resolved_payload(WORKSPACE_B, BINDING_B)))
    assert run(provider_a.current_drive_grant(workspace_ref=WORKSPACE_A)).binding_ref == BINDING_A
    assert run(provider_b.current_drive_grant(workspace_ref=WORKSPACE_B)).binding_ref == BINDING_B


# --- 2. equality proof + connector exactness -------------------------------


def test_workspace_rpc_mismatch_is_denied() -> None:
    client = FakeControlPlaneClient(resolved_payload(WORKSPACE_B, BINDING_B))
    provider = WorkspaceScopedDriveGrantProvider(client=client)
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_workspace_mismatch"


def test_wrong_connector_is_denied() -> None:
    payload = resolved_payload()
    payload["connector_id"] = "google-calendar"
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_connector_mismatch"


# --- 3. no binding / ambiguous / fail-closed -------------------------------


def test_no_binding_yields_no_grant() -> None:
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(not_connected_payload()))
    assert run(provider.current_drive_grant(workspace_ref=WORKSPACE_A)) is None


def test_ambiguous_binding_is_denied() -> None:
    class Ambiguous(Exception):
        pass

    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(error=Ambiguous("ambiguous")))
    with pytest.raises(Ambiguous):
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))


def test_missing_workspace_is_refused() -> None:
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(resolved_payload()))
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=""))
    assert excinfo.value.code == "invalid_workspace"


def test_missing_client_fails_closed() -> None:
    provider = WorkspaceScopedDriveGrantProvider(client=None)
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_authority_unavailable"


def test_resolved_without_identity_is_rejected() -> None:
    payload = resolved_payload()
    payload["actor_ref"] = None
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_binding_response_invalid"


# --- 4. no global fallback, no second authority ---------------------------


def test_no_global_grant_fallback_in_source() -> None:
    source = pathlib.Path(grant_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "connector_grants_d1",
        "CloudflareD1ConnectorGrantStore",
        "load_drive_grants",
        "CLOUDFLARE_D1",
        "import httpx",
        "import requests",
        "refresh_token",
        "client_secret",
        "access_token",
    ):
        assert forbidden not in source, f"provider must not contain: {forbidden}"


def test_snapshot_posture() -> None:
    snapshot = drive_workspace_grant_snapshot()
    assert snapshot["workspace_scoped"] is True
    assert snapshot["workspace_equality_required"] is True
    assert snapshot["connector_exactness_required"] is True
    assert snapshot["canonical_grant_constructed"] is True
    assert snapshot["global_grant_fallback"] is False
    assert snapshot["second_oauth_authority"] is False
    assert snapshot["public_route"] is False
    assert snapshot["token_unseal"] is False
    assert snapshot["access_lease_issue"] is False
