"""Padiem Chat -> Engine client for the read-only Calendar READ grant state.

Mirrors ``calendar_read_activation_engine.py`` but performs no write: it asks
the Engine's ``/internal/connectors/calendar/read/state`` whether the current
canonical session's Calendar binding carries the persisted READ grant. The
same P01 Engine Service Binding, caller id and credential travel on the call —
no second Engine authority.

The 200 body must be the Engine's exact closed projection:

    {ok, calendar_read_grant_state: "active"|"inactive",
     calendar_write_authorized: false,
     binding_ref_projected/actor_ref_projected/workspace_ref_projected/
     session_id_projected: false}

Any non-200 status, transport failure, malformed body or widened key set
raises ``CalendarReadStateUnavailableError`` — the status projection renders
that as the bounded ``unavailable`` state. It is never folded into
``inactive``, and no Engine prose, error code, or private reference is
read from any failure body.
"""

from __future__ import annotations

import json
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

CALENDAR_READ_STATE_PATH = "/internal/connectors/calendar/read/state"
_MAX_RESPONSE_BYTES = 16 * 1024

CALENDAR_READ_GRANT_ACTIVE = "active"
CALENDAR_READ_GRANT_INACTIVE = "inactive"
CALENDAR_READ_GRANT_UNAVAILABLE = "unavailable"
# The closed vocabulary the chat status projection publishes for the calendar
# row. ``unavailable`` is produced here for any failed check; a 200 body can
# only ever contribute the Engine's own active/inactive pair.
CALENDAR_READ_GRANT_STATES = (
    CALENDAR_READ_GRANT_ACTIVE,
    CALENDAR_READ_GRANT_INACTIVE,
    CALENDAR_READ_GRANT_UNAVAILABLE,
)


class CalendarReadStateUnavailableError(RuntimeError):
    """The persisted READ-grant check could not be reliably completed.

    This is the honest ``unavailable``: it is never converted into a
    ``missing``/``inactive`` answer and never carries Engine prose or any
    private reference.
    """


class CloudflareCalendarReadStateEngineClient:
    def __init__(
        self,
        binding: Any,
        *,
        caller_id: str,
        credential: str,
        request_factory: Any,
    ) -> None:
        if binding is None or not callable(request_factory):
            raise ValueError("Engine Service Binding and request factory are required")
        if not isinstance(caller_id, str) or not caller_id:
            raise ValueError("Engine caller id is required")
        if not isinstance(credential, str) or not credential:
            raise ValueError("Engine credential is required")
        self._binding = binding
        self._caller_id = caller_id
        self._credential = credential
        self._request_factory = request_factory

    async def read_state(self, *, session_id: str) -> str:
        """Return ``active`` or ``inactive``; raise on any unreliable check."""

        if not isinstance(session_id, str) or not session_id:
            raise CalendarReadStateUnavailableError("canonical session unavailable")
        body = json.dumps(
            {"app_id": "b54-padiem-claw-calendar", "session_id": session_id},
            separators=(",", ":"),
        )
        request = self._request_factory(
            f"{ENGINE_INTERNAL_ORIGIN}{CALENDAR_READ_STATE_PATH}",
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "x-padiem-engine-caller": self._caller_id,
                "x-padiem-engine-credential": self._credential,
            },
            body=body,
        )
        try:
            response = await self._binding.fetch(request.js_object)
            raw = str(await response.text()).encode("utf-8")
        except Exception:
            raise CalendarReadStateUnavailableError(
                "Calendar READ state transport failed"
            ) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CalendarReadStateUnavailableError(
                "Calendar READ state response exceeded the bound"
            )
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            document = None

        try:
            status = int(getattr(response, "status", 0))
        except (TypeError, ValueError) as exc:
            raise CalendarReadStateUnavailableError(
                "Calendar READ state transport failed"
            ) from exc
        if status != 200:
            # Only the fact of the failure is consumed; the body is discarded
            # unread so no Engine prose or private reference can travel.
            raise CalendarReadStateUnavailableError(
                "Calendar READ state check was rejected"
            )
        expected = {
            "ok",
            "calendar_read_grant_state",
            "calendar_write_authorized",
            "binding_ref_projected",
            "actor_ref_projected",
            "workspace_ref_projected",
            "session_id_projected",
        }
        state = document.get("calendar_read_grant_state") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or set(document) != expected
            or document.get("ok") is not True
            or state not in (CALENDAR_READ_GRANT_ACTIVE, CALENDAR_READ_GRANT_INACTIVE)
            or document.get("calendar_write_authorized") is not False
            or any(
                document.get(key) is not False
                for key in (
                    "binding_ref_projected",
                    "actor_ref_projected",
                    "workspace_ref_projected",
                    "session_id_projected",
                )
            )
        ):
            raise CalendarReadStateUnavailableError(
                "Calendar READ state response violated the bounded contract"
            )
        return str(state)


CALENDAR_READ_STATE_CLIENT_WRITE_AUTHORITY = False
CALENDAR_READ_STATE_CLIENT_RAW_ENGINE_MESSAGE_OUTPUT = False
CALENDAR_READ_STATE_CLIENT_PRIVATE_REF_OUTPUT = False
