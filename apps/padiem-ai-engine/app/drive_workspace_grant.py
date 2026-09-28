"""Workspace-scoped canonical Drive grant provider for B67 product reads (#3193).

Closes the Engine half of the #3192 CENTRAL blocker: the product path must not
reuse one global Drive grant. The grant is resolved per *server-derived*
workspace through a private Control Plane Google OAuth selector, and the Engine
only reconstructs the canonical grant after proving:

* the private response uses the closed status vocabulary
  (``resolved`` / ``not_connected``) and an exact keyset;
* the returned workspace equals the requested workspace (equality proof);
* the returned connector is exactly ``google-drive``.

There is deliberately **no fallback** to the global Engine connector-grant
table: a failed workspace selection yields no grant, never another workspace's
grant. The existing global Drive ToolRuntime authority is untouched.

No new OAuth authority, Service Binding, tool runtime or credential handling is
introduced here; the private response carries only binding/actor facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from padiem_ai_core.drive_capability import DriveCapability

from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID, DriveGrant

DRIVE_WORKSPACE_GRANT_VERSION = "engine-drive-workspace-grant.v1"

DRIVE_WORKSPACE_CONNECTOR = "google-drive"

# Closed status vocabulary: anything else is a contract failure, never a benign
# "not connected" (an ambiguous Control Plane result must not be softened).
STATUS_RESOLVED = "resolved"
STATUS_NOT_CONNECTED = "not_connected"
DRIVE_BINDING_STATUSES = frozenset({STATUS_RESOLVED, STATUS_NOT_CONNECTED})

# Exact private response keysets (blacklist-free): extra fields, including any
# credential-like field the Control Plane might mistakenly add, are rejected.
NOT_CONNECTED_KEYS = frozenset({"status", "connector_id", "workspace_ref"})
RESOLVED_KEYS = frozenset({"status", "connector_id", "workspace_ref", "binding_ref", "actor_ref"})

# Hard locks for this slice.
GLOBAL_GRANT_FALLBACK_FOR_B67 = False
SECOND_OAUTH_AUTHORITY = False
PUBLIC_ROUTE = False
TOKEN_UNSEAL = False
ACCESS_LEASE_ISSUE = False

_MAX_ERROR_CODE_CHARS = 64
_MAX_REF_CHARS = 200


class DriveWorkspaceGrantError(ValueError):
    """Fail-closed workspace grant resolution error safe for products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if (
            not isinstance(code, str)
            or not code
            or len(code) > _MAX_ERROR_CODE_CHARS
            or not code[0].islower()
        ):
            raise ValueError("workspace grant error code must be a bounded lowercase token")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


class ControlPlaneDriveBindingClient(Protocol):
    """Private Control Plane Google OAuth RPC (existing Service Binding)."""

    async def select_drive_binding(self, *, workspace_ref: str) -> Mapping[str, Any]: ...


def _bounded_ref(value: object, limit: int = _MAX_REF_CHARS) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


class WorkspaceScopedDriveGrantProvider:
    """Resolve the current canonical Drive grant for one trusted workspace."""

    def __init__(self, *, client: ControlPlaneDriveBindingClient | None = None) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "WorkspaceScopedDriveGrantProvider(configured)"

    async def current_drive_grant(self, *, workspace_ref: str) -> DriveGrant | None:
        """Return the workspace's canonical READ-only Drive grant, or ``None``.

        ``workspace_ref`` is mandatory authority input: without it the provider
        refuses rather than falling back to any global grant.
        """

        workspace = _bounded_ref(workspace_ref)
        if workspace is None:
            raise DriveWorkspaceGrantError(
                "invalid_workspace", "A trusted workspace reference is required."
            )
        if self._client is None:
            raise DriveWorkspaceGrantError(
                "drive_authority_unavailable",
                "Control Plane Drive authority is unavailable.",
                status_code=503,
            )
        payload = await self._client.select_drive_binding(workspace_ref=workspace)
        return self.grant_from_private_payload(payload, workspace_ref=workspace)

    def grant_from_private_payload(
        self, payload: object, *, workspace_ref: str
    ) -> DriveGrant | None:
        """Validate one private Control Plane selection payload, fail closed.

        Split out so an adapter (and tests) can validate a payload without a
        live client. The status vocabulary and the keyset are both closed.
        """

        workspace = _bounded_ref(workspace_ref)
        if workspace is None:
            raise DriveWorkspaceGrantError(
                "invalid_workspace", "A trusted workspace reference is required."
            )
        if not isinstance(payload, Mapping):
            raise DriveWorkspaceGrantError(
                "drive_binding_response_invalid",
                "Drive binding selection response is invalid.",
                status_code=502,
            )

        status = payload.get("status")
        if not isinstance(status, str) or status not in DRIVE_BINDING_STATUSES:
            # unknown/malformed status (ambiguous, error, null, 123, ...) is a
            # contract failure, never "no binding".
            raise DriveWorkspaceGrantError(
                "drive_binding_response_invalid",
                "Drive binding selection response is invalid.",
                status_code=502,
            )
        expected_keys = RESOLVED_KEYS if status == STATUS_RESOLVED else NOT_CONNECTED_KEYS
        if set(payload) != expected_keys:
            raise DriveWorkspaceGrantError(
                "drive_binding_response_invalid",
                "Drive binding selection response is invalid.",
                status_code=502,
            )

        returned_workspace = _bounded_ref(payload.get("workspace_ref"))
        if returned_workspace != workspace:
            # Never use a binding that belongs to another workspace.
            raise DriveWorkspaceGrantError(
                "drive_workspace_mismatch",
                "Drive binding selection returned a different workspace.",
                status_code=403,
            )
        if payload.get("connector_id") != DRIVE_WORKSPACE_CONNECTOR:
            raise DriveWorkspaceGrantError(
                "drive_connector_mismatch",
                "Drive binding selection returned a different connector.",
                status_code=403,
            )
        if status != STATUS_RESOLVED:
            return None

        binding_ref = _bounded_ref(payload.get("binding_ref"))
        actor_ref = _bounded_ref(payload.get("actor_ref"))
        if binding_ref is None or actor_ref is None:
            raise DriveWorkspaceGrantError(
                "drive_binding_response_invalid",
                "Drive binding selection response is invalid.",
                status_code=502,
            )
        return DriveGrant(
            app_id=DRIVE_REFERENCE_APP_ID,
            canonical_agent_id=DRIVE_AGENT_ID,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            granted_capabilities=(DriveCapability.READ,),
        )


class ControlPlaneDriveBindingAdapter:
    """Engine adapter over the existing ``CONTROL_PLANE_GOOGLE_OAUTH`` binding.

    The transport is injected (the Worker composition supplies the real service
    binding); this adapter only enforces the closed private request/response
    contract and maps Control Plane failures to bounded Engine errors. It never
    unseals a credential, issues an access lease or falls back to a global
    grant.
    """

    def __init__(self, *, transport: object | None = None) -> None:
        self._transport = transport

    def __repr__(self) -> str:
        return "ControlPlaneDriveBindingAdapter(configured)"

    async def select_drive_binding(self, *, workspace_ref: str) -> Mapping[str, Any]:
        workspace = _bounded_ref(workspace_ref)
        if workspace is None:
            raise DriveWorkspaceGrantError(
                "invalid_workspace", "A trusted workspace reference is required."
            )
        if self._transport is None or not callable(getattr(self._transport, "select_drive_binding", None)):
            raise DriveWorkspaceGrantError(
                "drive_authority_unavailable",
                "Control Plane Drive authority is unavailable.",
                status_code=503,
            )
        try:
            payload = await self._transport.select_drive_binding(workspace_ref=workspace)
        except DriveWorkspaceGrantError:
            raise
        except Exception:
            # Control Plane ambiguity/failure stays fail closed and never leaks
            # raw transport text to a product.
            raise DriveWorkspaceGrantError(
                "drive_binding_selection_failed",
                "Drive binding selection failed.",
                status_code=502,
            ) from None
        if not isinstance(payload, Mapping):
            raise DriveWorkspaceGrantError(
                "drive_binding_response_invalid",
                "Drive binding selection response is invalid.",
                status_code=502,
            )
        return payload


def drive_workspace_grant_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this provider's posture."""

    return {
        "provider_version": DRIVE_WORKSPACE_GRANT_VERSION,
        "connector_id": DRIVE_WORKSPACE_CONNECTOR,
        "workspace_scoped": True,
        "workspace_equality_required": True,
        "connector_exactness_required": True,
        "closed_status_vocabulary": sorted(DRIVE_BINDING_STATUSES),
        "exact_private_keysets": True,
        "canonical_grant_constructed": True,
        "global_grant_fallback": GLOBAL_GRANT_FALLBACK_FOR_B67,
        "second_oauth_authority": SECOND_OAUTH_AUTHORITY,
        "public_route": PUBLIC_ROUTE,
        "token_unseal": TOKEN_UNSEAL,
        "access_lease_issue": ACCESS_LEASE_ISSUE,
        "live_provider_calls": 0,
    }


__all__ = [
    "DRIVE_WORKSPACE_GRANT_VERSION",
    "DRIVE_WORKSPACE_CONNECTOR",
    "STATUS_RESOLVED",
    "STATUS_NOT_CONNECTED",
    "DRIVE_BINDING_STATUSES",
    "NOT_CONNECTED_KEYS",
    "RESOLVED_KEYS",
    "GLOBAL_GRANT_FALLBACK_FOR_B67",
    "DriveWorkspaceGrantError",
    "ControlPlaneDriveBindingClient",
    "ControlPlaneDriveBindingAdapter",
    "WorkspaceScopedDriveGrantProvider",
    "drive_workspace_grant_snapshot",
]
