"""Read-only persisted Calendar READ grant state projection (#2952 follow-up).

The activation surface (``calendar_read_activation.py``) writes the single
canonical grant. This surface answers one bounded question with no write:

    does a READ grant exist for the Calendar binding the canonical session
    resolves to right now?

The selection is the activation's own: the same Control Plane identity
workspace resolution and the same private Google OAuth binding selection —
no second selector, no second grant store, no second OAuth authority. The
answer is a closed three-state vocabulary projected through the chat status
surface; nothing private (binding/actor/workspace refs, session ids, calendar
ids, credentials) ever leaves the Engine:

``active``
    the canonical current binding/actor resolves and the persisted canonical
    READ grant matches it exactly.
``inactive``
    the check itself succeeded — the workspace and its Calendar binding state
    were confirmed (including the definitive "Calendar is not connected for
    this workspace" answer) — and no matching READ grant exists. A persisted
    grant whose binding/actor no longer match the current resolution is also
    a confirmed inactive.
``unavailable``
    is never a 200 body here: an authority, binding-selection, or storage
    fault raises ``ServiceContractError`` and the caller projects it as
    ``unavailable``. A store answer that cannot be trusted — a non-dict
    result, or a row in the canonical slot that is not the canonical grant
    (wrong app_id, wrong canonical_agent_id, or capabilities other than
    exactly the reviewed READ) — fails closed the same way. It must never be
    misread as ``inactive``, and a non-canonical grant can never be
    projected as active.
"""

from __future__ import annotations

from typing import Protocol

from app.calendar_read_activation import (
    CALENDAR_ACTIVATION_CALLER_APP_ID,
    CloudflareCalendarBindingClient,
    CloudflareConnectorWorkspaceClient,
    ConnectorWorkspaceClient,
    CalendarBindingClient,
    parse_calendar_activation_request,
)
from app.connector_bindings import (
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    CalendarGrant,
)
from app.service import ServiceContractError, ServiceResponse
from padiem_ai_core.calendar_capability import CalendarCapability


CALENDAR_READ_STATE_PATH = "/internal/connectors/calendar/read/state"
# The state route answers for the same trusted caller as activation and
# accepts the same closed request body: {app_id, session_id} (the parse
# function is reused unchanged, so the caller id check travels with it).
CALENDAR_READ_STATE_REQUEST_APP_ID = CALENDAR_ACTIVATION_CALLER_APP_ID

CALENDAR_READ_GRANT_ACTIVE = "active"
CALENDAR_READ_GRANT_INACTIVE = "inactive"
# Only ever produced by the chat projection of a failed check — never by a
# 200 body from this service.
CALENDAR_READ_GRANT_UNAVAILABLE = "unavailable"
CALENDAR_READ_GRANT_STATES = (
    CALENDAR_READ_GRANT_ACTIVE,
    CALENDAR_READ_GRANT_INACTIVE,
)


def _store_answer_unavailable() -> ServiceContractError:
    return ServiceContractError(
        "calendar_read_state_unavailable",
        "Calendar READ grant storage returned an invalid record.",
        status_code=503,
    )


class CalendarGrantStateStore(Protocol):
    """The read half of the existing canonical grant store."""

    async def load_calendar_grants(self) -> dict[str, CalendarGrant]: ...


class CalendarReadStateService:
    """Answers the persisted READ-grant question without writing anything."""

    def __init__(
        self,
        *,
        workspace_client: ConnectorWorkspaceClient,
        binding_client: CalendarBindingClient,
        grant_store: CalendarGrantStateStore,
    ) -> None:
        self._workspace_client = workspace_client
        self._binding_client = binding_client
        self._grant_store = grant_store

    async def state(self, *, session_id: str) -> ServiceResponse:
        workspace_ref = await self._workspace_client.resolve_connector_workspace(
            session_id=session_id
        )
        try:
            binding_ref, actor_ref = await self._binding_client.select_calendar_binding(
                workspace_ref=workspace_ref
            )
        except ServiceContractError as exc:
            if exc.code != "calendar_not_connected":
                # An authority/selection fault is not a state: the check did
                # not reliably run, so it must never read as a missing grant.
                raise
            # The binding authority's definitive negative ("Calendar is not
            # connected for this workspace") is a confirmed check outcome:
            # no Calendar binding exists, so no READ grant can exist.
            binding_ref = None
            actor_ref = None
        if binding_ref is None or actor_ref is None:
            state = CALENDAR_READ_GRANT_INACTIVE
        else:
            is_active = await self._canonical_grant_active(
                binding_ref=binding_ref,
                actor_ref=actor_ref,
            )
            state = CALENDAR_READ_GRANT_ACTIVE if is_active else CALENDAR_READ_GRANT_INACTIVE
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "calendar_read_grant_state": state,
                "calendar_write_authorized": False,
                "binding_ref_projected": False,
                "actor_ref_projected": False,
                "workspace_ref_projected": False,
                "session_id_projected": False,
            },
        )

    async def _canonical_grant_active(self, *, binding_ref: str, actor_ref: str) -> bool:
        """Decide ``active`` against the full canonical grant identity.

        ``CONFIRMED_NO_GRANT=inactive; UNRELIABLE_STORE_RESULT=unavailable``:

        * a non-dict store answer is an unreliable store, not an empty one —
          fail closed (503), never ``inactive``;
        * a row sitting in the canonical slot that is not the canonical grant
          (a non-``CalendarGrant`` value, wrong app_id, wrong
          canonical_agent_id, or capabilities other than exactly the reviewed
          READ) means the store contract itself is broken — fail closed (503),
          so a non-canonical grant can never be projected as either state;
        * a canonical grant whose binding/actor no longer match the current
          resolution is a confirmed negative — ``inactive``.
        """

        grants = await self._grant_store.load_calendar_grants()
        if not isinstance(grants, dict):
            raise _store_answer_unavailable()
        grant = grants.get(CALENDAR_REFERENCE_APP_ID)
        if grant is None:
            return False
        if not isinstance(grant, CalendarGrant):
            raise _store_answer_unavailable()
        if (
            grant.app_id != CALENDAR_REFERENCE_APP_ID
            or grant.canonical_agent_id != CALENDAR_AGENT_ID
            or grant.granted_capabilities != (CalendarCapability.READ,)
        ):
            raise _store_answer_unavailable()
        return grant.binding_ref == binding_ref and grant.actor_ref == actor_ref


__all__ = [
    "CALENDAR_READ_GRANT_ACTIVE",
    "CALENDAR_READ_GRANT_INACTIVE",
    "CALENDAR_READ_GRANT_STATES",
    "CALENDAR_READ_GRANT_UNAVAILABLE",
    "CALENDAR_READ_STATE_PATH",
    "CALENDAR_READ_STATE_REQUEST_APP_ID",
    "CalendarGrantStateStore",
    "CalendarReadStateService",
    "CloudflareCalendarBindingClient",
    "CloudflareConnectorWorkspaceClient",
    "parse_calendar_activation_request",
]
