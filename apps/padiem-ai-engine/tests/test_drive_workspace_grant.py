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
    RESOLVED_KEYS,
    CloudflareControlPlaneDriveBindingClient,
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


# --- 5. closed wire contract (status vocabulary + exact keyset) ------------


def test_unknown_or_malformed_status_is_denied() -> None:
    for status in ("ambiguous", "error", "resolved_v2", None, 123, "unknown"):
        payload = resolved_payload()
        payload["status"] = status
        provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
        with pytest.raises(DriveWorkspaceGrantError) as excinfo:
            run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
        assert excinfo.value.code == "drive_binding_response_invalid", status


def test_not_connected_exact_schema_yields_no_grant() -> None:
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(not_connected_payload()))
    assert run(provider.current_drive_grant(workspace_ref=WORKSPACE_A)) is None


def test_resolved_extra_field_is_denied() -> None:
    for extra in (
        {"account_ref": "acct_1"},
        {"scopes": ["https://www.googleapis.com/auth/drive.readonly"]},
        {"access_token": "ya29.raw"},
        {"refresh_token": "1//raw"},
        {"sealed_refresh_token": "sealed:v1:abc"},
        {"client_secret": "secret"},
        {"anything_else": 1},
    ):
        payload = resolved_payload()
        payload.update(extra)
        provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
        with pytest.raises(DriveWorkspaceGrantError) as excinfo:
            run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
        assert excinfo.value.code == "drive_binding_response_invalid", extra


def test_not_connected_extra_field_is_denied() -> None:
    payload = not_connected_payload()
    payload["binding_ref"] = BINDING_A
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_binding_response_invalid"


def test_resolved_missing_required_field_is_denied() -> None:
    payload = resolved_payload()
    del payload["actor_ref"]
    provider = WorkspaceScopedDriveGrantProvider(client=FakeControlPlaneClient(payload))
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_binding_response_invalid"


# --- 6. Control Plane Service Binding client + outer envelope -------------


class FakeCPServiceBinding:
    """Mirrors the real Service Binding call shape: ``binding.method({payload})``.

    The Control Plane side is emulated with the documented selector semantics
    (exact workspace + connector, usable-only, ambiguity fail-closed) so the
    cross-package contract is exercised network-free. See the PR notes for why
    the real CP store/RPC is not imported into this suite.
    """

    def __init__(self, rows=None, *, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.payloads: list[dict] = []

    async def select_drive_binding(self, payload: dict) -> dict:
        self.payloads.append(dict(payload))
        if self.error is not None:
            raise self.error
        workspace = payload.get("workspace_ref")
        usable = [
            row
            for row in self.rows
            if row["workspace_ref"] == workspace
            and row["connector_id"] == "google-drive"
            and row.get("revoked") is not True
        ]
        if len(usable) > 1:
            # ambiguous is a bounded Control Plane error, never a status payload
            return {"ok": False, "error": {"code": "ambiguous_google_oauth_binding", "message": "rejected"}}
        if not usable:
            return {
                "ok": True,
                "selection": {
                    "status": "not_connected",
                    "connector_id": "google-drive",
                    "workspace_ref": workspace,
                },
            }
        row = usable[0]
        return {
            "ok": True,
            "selection": {
                "status": "resolved",
                "connector_id": "google-drive",
                "workspace_ref": workspace,
                "binding_ref": row["binding_ref"],
                "actor_ref": row["actor_ref"],
            },
        }


def row(workspace_ref: str, binding_ref: str) -> dict:
    return {
        "workspace_ref": workspace_ref,
        "connector_id": "google-drive",
        "binding_ref": binding_ref,
        "actor_ref": f"actor.{binding_ref}",
    }


def test_real_binding_call_shape_round_trip() -> None:
    binding = FakeCPServiceBinding([row(WORKSPACE_A, BINDING_A)])
    provider = WorkspaceScopedDriveGrantProvider(
        client=CloudflareControlPlaneDriveBindingClient(binding)
    )
    grant = run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    # the real shape is binding.method({payload}), not keyword args
    assert binding.payloads == [{"workspace_ref": WORKSPACE_A}]
    assert grant is not None
    assert grant.binding_ref == BINDING_A
    assert grant.actor_ref == f"actor.{BINDING_A}"


def test_client_requires_a_real_binding() -> None:
    for bad in (None, object()):
        with pytest.raises(ValueError):
            CloudflareControlPlaneDriveBindingClient(bad)


def test_client_transport_failure_is_bounded() -> None:
    binding = FakeCPServiceBinding(error=RuntimeError("raw cp text"))
    provider = WorkspaceScopedDriveGrantProvider(
        client=CloudflareControlPlaneDriveBindingClient(binding)
    )
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_binding_selection_failed"
    assert "raw cp text" not in str(excinfo.value)


def test_outer_envelope_is_closed() -> None:
    for bad in (
        {"ok": False, "error": {"code": "ambiguous_google_oauth_binding"}},
        {"ok": True},
        {"ok": "true", "selection": resolved_payload()},
        {"ok": True, "selection": resolved_payload(), "extra": 1},
        {"selection": resolved_payload()},
        {"ok": False},
        {"ok": True, "selection": "not-an-object"},
    ):
        provider = WorkspaceScopedDriveGrantProvider(
            client=CloudflareControlPlaneDriveBindingClient(FakeCPServiceBinding([], error=None))
        )
        # emulate the binding returning the bad envelope directly
        async def select_drive_binding(_payload, _bad=bad):
            return _bad

        binding = FakeCPServiceBinding([row(WORKSPACE_A, BINDING_A)])
        binding.select_drive_binding = select_drive_binding  # type: ignore[assignment]
        provider = WorkspaceScopedDriveGrantProvider(
            client=CloudflareControlPlaneDriveBindingClient(binding)
        )
        with pytest.raises(DriveWorkspaceGrantError) as excinfo:
            run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
        assert excinfo.value.code == "drive_binding_response_invalid", bad


# --- 7. network-free CP -> Engine end-to-end -------------------------------


def test_end_to_end_workspace_a_resolves_its_own_grant() -> None:
    binding = FakeCPServiceBinding(
        [row(WORKSPACE_A, BINDING_A), row(WORKSPACE_B, BINDING_B)]
    )
    provider = WorkspaceScopedDriveGrantProvider(
        client=CloudflareControlPlaneDriveBindingClient(binding)
    )
    grant_a = run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    grant_b = run(provider.current_drive_grant(workspace_ref=WORKSPACE_B))
    assert grant_a is not None and grant_a.binding_ref == BINDING_A
    assert grant_b is not None and grant_b.binding_ref == BINDING_B


def test_end_to_end_workspace_b_never_receives_binding_a() -> None:
    binding = FakeCPServiceBinding([row(WORKSPACE_A, BINDING_A)])
    provider = WorkspaceScopedDriveGrantProvider(
        client=CloudflareControlPlaneDriveBindingClient(binding)
    )
    lease_b = run(provider.current_drive_grant(workspace_ref=WORKSPACE_B))
    assert lease_b is None, "workspace B must not receive workspace A's binding"


def test_end_to_end_ambiguous_workspace_fails_closed() -> None:
    binding = FakeCPServiceBinding(
        [row(WORKSPACE_A, BINDING_A), row(WORKSPACE_A, "binding.a.drive.2")]
    )
    provider = WorkspaceScopedDriveGrantProvider(
        client=CloudflareControlPlaneDriveBindingClient(binding)
    )
    with pytest.raises(DriveWorkspaceGrantError) as excinfo:
        run(provider.current_drive_grant(workspace_ref=WORKSPACE_A))
    assert excinfo.value.code == "drive_binding_response_invalid"
    assert "ambiguous" not in str(excinfo.value)
