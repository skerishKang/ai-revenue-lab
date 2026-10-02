"""Padiem Chat -> Engine client for Calendar READ activation (#2952)."""

from __future__ import annotations

import json
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

CALENDAR_READ_ACTIVATION_PATH = "/internal/connectors/calendar/read/activate"
_MAX_RESPONSE_BYTES = 16 * 1024


class CalendarReadActivationClientError(RuntimeError):
    pass


class CloudflareCalendarReadActivationEngineClient:
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


    async def activate(self, *, session_id: str) -> dict[str, Any]:
        if not isinstance(session_id, str) or not session_id:
            raise CalendarReadActivationClientError("canonical session unavailable")
        body = json.dumps(
            {"app_id": "b54-padiem-claw-calendar", "session_id": session_id},
            separators=(",", ":"),
        )
        request = self._request_factory(
            f"{ENGINE_INTERNAL_ORIGIN}{CALENDAR_READ_ACTIVATION_PATH}",
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
            raise CalendarReadActivationClientError(
                "Calendar READ activation transport failed"
            ) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CalendarReadActivationClientError(
                "Calendar READ activation response exceeded the bound"
            )
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CalendarReadActivationClientError(
                "Calendar READ activation response was invalid"
            ) from None

        if int(getattr(response, "status", 0)) != 200:
            raise CalendarReadActivationClientError(
                "Calendar READ activation was rejected"
            )
        expected = {
            "ok",
            "calendar_read_grant",
            "calendar_write_authorized",
            "binding_ref_projected",
            "actor_ref_projected",
            "workspace_ref_projected",
            "session_id_projected",
        }
        if not isinstance(document, dict) or set(document) != expected:
            raise CalendarReadActivationClientError(
                "Calendar READ activation response was not closed"
            )
        if (
            document.get("ok") is not True
            or document.get("calendar_read_grant") != "active"
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
            raise CalendarReadActivationClientError(
                "Calendar READ activation response violated the bounded contract"
            )
        return dict(document)


CALENDAR_ACTIVATION_CLIENT_RAW_REF_OUTPUT = False
CALENDAR_ACTIVATION_CLIENT_RAW_SESSION_OUTPUT = False
CALENDAR_ACTIVATION_CLIENT_WRITE_AUTHORITY = False
