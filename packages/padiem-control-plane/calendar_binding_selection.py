"""Private server-derived workspace callsite for Calendar binding selection.

The callsite accepts only a canonical Control Plane auth-session snapshot. It
resolves the existing connector context through the canonical read-only
resolver, then delegates identity selection to the merged Google OAuth store.
No caller workspace, public route, second session store, or credential
material is accepted or projected.
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


class TrustedCalendarBindingSelectionCallsite:
    """Resolve a trusted workspace, then invoke the existing private selector."""

    def __init__(
        self,
        *,
        context_store: CanonicalConnectorContextStore,
        oauth_store: CloudflareDurableGoogleOAuthStore,
    ) -> None:
        if not callable(getattr(context_store, "resolve_existing", None)):
            raise ValueError("context_store must expose resolve_existing")
        if not callable(getattr(oauth_store, "select_active_calendar_binding", None)):
            raise ValueError("oauth_store must expose select_active_calendar_binding")
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
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ControlPlaneContractError(
                "trusted_workspace_unavailable",
                "trusted workspace resolution time must be timezone-aware",
            )
        context = self._context_store.resolve_existing(
            auth_session=auth_session,
            now=now,
        )
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
        return self._oauth_store.select_active_calendar_binding(
            workspace_ref=context.workspace_ref,
            now=now.astimezone(timezone.utc),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "call_site": "private_server_derived_workspace",
            "caller_workspace_authority": False,
            "default_workspace_authority": False,
            "synthetic_workspace_ref": False,
            "public_route": False,
            "public_identity_projection": False,
            "second_session_store": False,
            "second_google_oauth_store": False,
            "raw_refresh_token_output": False,
            "sealed_refresh_token_output": False,
            "access_token_output": False,
            "client_secret_output": False,
        }


CalendarBindingSelectionCallsite = TrustedCalendarBindingSelectionCallsite

CALENDAR_BINDING_SELECTION_CALLSITE_SOURCE_ONLY = True
CALENDAR_BINDING_SELECTION_CALLSITE_REQUIRES_AUTH_SESSION = True
CALENDAR_BINDING_SELECTION_CALLSITE_PUBLIC_ROUTE = False
CALENDAR_BINDING_SELECTION_CALLSITE_WORKSPACE_MUTATION = 0

__all__ = [
    "CALENDAR_BINDING_SELECTION_CALLSITE_PUBLIC_ROUTE",
    "CALENDAR_BINDING_SELECTION_CALLSITE_REQUIRES_AUTH_SESSION",
    "CALENDAR_BINDING_SELECTION_CALLSITE_SOURCE_ONLY",
    "CALENDAR_BINDING_SELECTION_CALLSITE_WORKSPACE_MUTATION",
    "CalendarBindingSelectionCallsite",
    "TrustedCalendarBindingSelectionCallsite",
]
