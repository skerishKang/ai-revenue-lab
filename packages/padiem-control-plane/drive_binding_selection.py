"""Private server-derived workspace callsite for Drive binding selection (#3193).

Mirrors ``calendar_binding_selection.py``: the callsite accepts only a canonical
Control Plane auth-session snapshot, resolves the existing connector context
through the canonical read-only resolver, then delegates identity selection to
the shared Google OAuth store. No caller workspace, public route, second session
store, or credential material is accepted or projected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google_oauth_durable_store import (
    CloudflareDurableGoogleOAuthStore,
    GoogleOAuthBindingSelection,
)
from identity_connector_ticket import (
    CanonicalConnectorContext,
    CanonicalConnectorContextStore,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import ControlPlaneContractError


class TrustedDriveBindingSelectionCallsite:
    """Resolve a trusted workspace, then invoke the existing private selector.

    ``workspace_ref`` is deliberately **not** a caller parameter: it can only
    come from the canonical connector context of the authenticated session.
    """

    def __init__(
        self,
        *,
        context_store: CanonicalConnectorContextStore,
        oauth_store: CloudflareDurableGoogleOAuthStore,
    ) -> None:
        if not callable(getattr(context_store, "resolve_existing", None)):
            raise ValueError("context_store must expose resolve_existing")
        if not callable(getattr(oauth_store, "select_active_drive_binding", None)):
            raise ValueError("oauth_store must expose select_active_drive_binding")
        self._context_store = context_store
        self._oauth_store = oauth_store

    def select_for_auth_session(
        self,
        *,
        auth_session: AuthSessionSnapshot,
        now: datetime,
    ) -> GoogleOAuthBindingSelection:
        if not isinstance(auth_session, AuthSessionSnapshot):
            raise ControlPlaneContractError(
                "trusted_workspace_unavailable",
                "canonical auth session is required",
            )
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ControlPlaneContractError(
                "trusted_workspace_unavailable",
                "trusted workspace resolution time must be timezone-aware",
            )
        context = self._context_store.resolve_existing(auth_session=auth_session, now=now)
        if context is None:
            raise ControlPlaneContractError(
                "trusted_workspace_unavailable",
                "canonical connector workspace is unavailable",
            )
        if not isinstance(context, CanonicalConnectorContext):
            raise ControlPlaneContractError(
                "trusted_workspace_unavailable",
                "canonical connector workspace result is invalid",
            )
        return self._oauth_store.select_active_drive_binding(
            workspace_ref=context.workspace_ref,
            now=now.astimezone(timezone.utc),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "call_site": "private_server_derived_workspace",
            "caller_workspace_authority": False,
            "default_workspace_authority": False,
            "synthetic_workspace_ref": False,
            "creates_connector_context": False,
            "public_route": False,
            "public_identity_projection": False,
            "second_session_store": False,
            "second_google_oauth_store": False,
            "raw_refresh_token_output": False,
            "sealed_refresh_token_output": False,
            "access_token_output": False,
            "client_secret_output": False,
        }


DriveBindingSelectionCallsite = TrustedDriveBindingSelectionCallsite

DRIVE_BINDING_SELECTION_CALLSITE_SOURCE_ONLY = True
DRIVE_BINDING_SELECTION_CALLSITE_REQUIRES_AUTH_SESSION = True
DRIVE_BINDING_SELECTION_CALLSITE_PUBLIC_ROUTE = False
DRIVE_BINDING_SELECTION_CALLSITE_CALLER_WORKSPACE_AUTHORITY = False

__all__ = [
    "DRIVE_BINDING_SELECTION_CALLSITE_CALLER_WORKSPACE_AUTHORITY",
    "DRIVE_BINDING_SELECTION_CALLSITE_PUBLIC_ROUTE",
    "DRIVE_BINDING_SELECTION_CALLSITE_REQUIRES_AUTH_SESSION",
    "DRIVE_BINDING_SELECTION_CALLSITE_SOURCE_ONLY",
    "DriveBindingSelectionCallsite",
    "TrustedDriveBindingSelectionCallsite",
]
