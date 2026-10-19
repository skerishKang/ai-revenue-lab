"""Server-authoritative Calendar READ grant activation for #2952.

The request contributes only a canonical auth-session id. Workspace identity is
re-resolved through Control Plane identity, Calendar binding identity is selected
through the private Google OAuth authority, and the Engine writes only its fixed
READ grant. No browser/client workspace, binding, actor, scope or capability can
become authority here.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any, Protocol

from app.connector_bindings import CALENDAR_REFERENCE_APP_ID, CalendarGrant
from app.service import ServiceContractError, ServiceResponse


CALENDAR_READ_ACTIVATION_PATH = "/internal/connectors/calendar/read/activate"
CALENDAR_ACTIVATION_CALLER_APP_ID = "b54-padiem-claw-calendar"
CALENDAR_CP_CONNECTOR_ID = "google-calendar"
_REQUEST_KEYS = frozenset({"app_id", "session_id"})
_SAFE_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")


class ConnectorWorkspaceClient(Protocol):
    async def resolve_connector_workspace(self, *, session_id: str) -> str: ...


class CalendarBindingClient(Protocol):
    async def select_calendar_binding(
        self, *, workspace_ref: str
    ) -> tuple[str, str]: ...


class CalendarGrantActivationStore(Protocol):
    async def activate_calendar_read_grant(
        self, *, binding_ref: str, actor_ref: str
    ) -> CalendarGrant: ...


def _unavailable(code: str, message: str, *, status_code: int = 503) -> ServiceContractError:
    return ServiceContractError(code, message, status_code=status_code)


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise _unavailable(
            "calendar_activation_authority_unavailable",
            f"Calendar activation {field_name} is unavailable.",
        )
    return value


def parse_calendar_activation_request(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ServiceContractError(
            "invalid_request", "Calendar activation request is invalid."
        ) from None
    if not isinstance(payload, dict) or set(payload) != _REQUEST_KEYS:
        raise ServiceContractError(
            "invalid_request",
            "Calendar activation request must contain exactly app_id and session_id.",
        )
    if payload.get("app_id") != CALENDAR_ACTIVATION_CALLER_APP_ID:
        raise ServiceContractError(
            "invalid_request", "Calendar activation caller application is invalid."
        )
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or _SAFE_SESSION_RE.fullmatch(session_id) is None:
        raise ServiceContractError(
            "invalid_request", "Calendar activation session is invalid."
        )
    return session_id


class CloudflareConnectorWorkspaceClient:
    """Adapter over CONTROL_PLANE_IDENTITY.resolve_connector_workspace."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Control Plane identity Service Binding is required")
        self._binding = binding

    async def resolve_connector_workspace(self, *, session_id: str) -> str:
        method = getattr(self._binding, "resolve_connector_workspace", None)
        if not callable(method):
            raise _unavailable(
                "calendar_activation_identity_unavailable",
                "Calendar activation identity authority is unavailable.",
            )
        try:
            result = await method({"session_id": session_id})
        except Exception:
            raise _unavailable(
                "calendar_activation_identity_unavailable",
                "Calendar activation identity authority failed.",
            ) from None
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            raise _unavailable(
                "calendar_activation_workspace_unavailable",
                "Calendar activation workspace is unavailable.",
                status_code=403,
            )
        workspace = result.get("workspace")
        if not isinstance(workspace, Mapping):
            raise _unavailable(
                "calendar_activation_workspace_unavailable",
                "Calendar activation workspace is unavailable.",
                status_code=403,
            )
        if workspace.get("present") is not True:
            raise _unavailable(
                "calendar_activation_workspace_unavailable",
                "Calendar activation workspace is unavailable.",
                status_code=403,
            )
        if set(workspace) != {"present", "workspace_ref"}:
            raise _unavailable(
                "calendar_activation_authority_unavailable",
                "Calendar activation workspace projection is invalid.",
            )
        return _safe_ref(workspace.get("workspace_ref"), "workspace")


class CloudflareCalendarBindingClient:
    """Adapter over CONTROL_PLANE_GOOGLE_OAUTH.select_calendar_binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Control Plane Google OAuth Service Binding is required")
        self._binding = binding

    async def select_calendar_binding(
        self, *, workspace_ref: str
    ) -> tuple[str, str]:
        method = getattr(self._binding, "select_calendar_binding", None)
        if not callable(method):
            raise _unavailable(
                "calendar_binding_selection_unavailable",
                "Calendar binding selection is unavailable.",
            )
        try:
            result = await method({"workspace_ref": workspace_ref})
        except Exception:
            raise _unavailable(
                "calendar_binding_selection_unavailable",
                "Calendar binding selection failed.",
            ) from None
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            raise _unavailable(
                "calendar_binding_selection_unavailable",
                "Calendar binding is unavailable.",
                status_code=409,
            )
        selection = result.get("selection")
        if not isinstance(selection, Mapping):
            raise _unavailable(
                "calendar_binding_selection_unavailable",
                "Calendar binding selection returned invalid data.",
            )
        allowed = {
            "status",
            "connector_id",
            "workspace_ref",
            "binding_ref",
            "actor_ref",
        }
        if not set(selection).issubset(allowed):
            raise _unavailable(
                "calendar_binding_selection_unavailable",
                "Calendar binding selection widened private identity.",
            )
        if (
            selection.get("status") != "resolved"
            or selection.get("connector_id") != CALENDAR_CP_CONNECTOR_ID
            or selection.get("workspace_ref") != workspace_ref
        ):
            raise _unavailable(
                "calendar_not_connected",
                "Google Calendar is not connected for this workspace.",
                status_code=409,
            )
        return (
            _safe_ref(selection.get("binding_ref"), "binding"),
            _safe_ref(selection.get("actor_ref"), "actor"),
        )


class CalendarReadActivationService:
    def __init__(
        self,
        *,
        workspace_client: ConnectorWorkspaceClient,
        binding_client: CalendarBindingClient,
        grant_store: CalendarGrantActivationStore,
    ) -> None:
        self._workspace_client = workspace_client
        self._binding_client = binding_client
        self._grant_store = grant_store

    async def activate(self, *, session_id: str) -> ServiceResponse:
        workspace_ref = await self._workspace_client.resolve_connector_workspace(
            session_id=session_id
        )
        binding_ref, actor_ref = await self._binding_client.select_calendar_binding(
            workspace_ref=workspace_ref
        )
        grant = await self._grant_store.activate_calendar_read_grant(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
        )
        if grant.app_id != CALENDAR_REFERENCE_APP_ID:
            raise _unavailable(
                "calendar_grant_activation_unavailable",
                "Calendar READ grant activation did not reach canonical state.",
            )
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "calendar_read_grant": "active",
                "calendar_write_authorized": False,
                "binding_ref_projected": False,
                "actor_ref_projected": False,
                "workspace_ref_projected": False,
                "session_id_projected": False,
            },
        )
