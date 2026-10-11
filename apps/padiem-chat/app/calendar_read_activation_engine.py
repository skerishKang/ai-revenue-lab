"""Padiem Chat -> Engine client for Calendar READ activation (#2952).

#3434 follow-up — bounded rejection diagnostics. The Engine answers failures
with a closed ``{"ok": false, "error": {"code": ...}}`` body whose ``code``
values are fixed in the Engine's own source
(``apps/padiem-ai-engine/app/calendar_read_activation.py``,
``worker_identity.py``, ``worker.py``, ``app/connector_grants_d1.py``). This
client projects those codes onto a closed safe diagnostic vocabulary so the
Chat route can surface the real failure stage to the UI without ever
forwarding Engine prose or private references:

``service_authentication_failed`` / ``service_app_not_authorized``
    -> ``calendar_activation_engine_auth_failed``   (503; the browser user
       cannot repair the Chat->Engine service credential, and the Engine's own
       401/403 would misread as browser-auth failures)
``calendar_activation_workspace_unavailable`` /
``calendar_activation_identity_unavailable``
    -> ``calendar_activation_workspace_unavailable`` (Engine status preserved)
``calendar_binding_selection_unavailable``
    -> ``calendar_activation_binding_unavailable``   (Engine status preserved)
``calendar_not_connected``
    -> ``calendar_activation_not_connected``          (409 preserved)
``calendar_grant_activation_unavailable`` /
``calendar_grant_activation_invalid`` / ``connector_grants_unavailable``
    -> ``calendar_activation_grant_unavailable``     (Engine status preserved)
anything else, a malformed body, or a missing/unknown code
    -> ``calendar_read_activation_unavailable``      (503)

Only the Engine's ``error.code`` is read. The Engine's ``error.message`` and
any other body content are discarded here: the projection is the closed table
below, nothing else. Engine statuses 400/401/405 always flatten to 503 because
they describe Chat-side request/credential faults whose browser-facing
semantics would mislead.
"""

from __future__ import annotations

import json
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

CALENDAR_READ_ACTIVATION_PATH = "/internal/connectors/calendar/read/activate"
_MAX_RESPONSE_BYTES = 16 * 1024
_MAX_ENGINE_ERROR_CODE_CHARS = 96

GENERIC_CALENDAR_READ_ACTIVATION_CODE = "calendar_read_activation_unavailable"

# The closed projection. Keys are the exact error codes the Engine emits on
# this route (fresh-read from Engine source); values are the safe diagnostic
# code plus whether the Engine's own HTTP status carries user-actionable
# meaning and should be preserved (otherwise the diagnostic reports 503).
_ENGINE_ERROR_FAMILIES: dict[str, tuple[str, bool]] = {
    "service_authentication_failed": ("calendar_activation_engine_auth_failed", False),
    "service_app_not_authorized": ("calendar_activation_engine_auth_failed", False),
    "calendar_activation_workspace_unavailable": (
        "calendar_activation_workspace_unavailable",
        True,
    ),
    "calendar_activation_identity_unavailable": (
        "calendar_activation_workspace_unavailable",
        True,
    ),
    "calendar_binding_selection_unavailable": (
        "calendar_activation_binding_unavailable",
        True,
    ),
    "calendar_not_connected": ("calendar_activation_not_connected", True),
    "calendar_grant_activation_unavailable": (
        "calendar_activation_grant_unavailable",
        True,
    ),
    "calendar_grant_activation_invalid": ("calendar_activation_grant_unavailable", True),
    "connector_grants_unavailable": ("calendar_activation_grant_unavailable", True),
}
_FLATTENED_ENGINE_STATUSES = frozenset({400, 401, 405})


class CalendarReadActivationClientError(RuntimeError):
    """A bounded Chat-side failure of the Calendar READ activation call.

    ``diagnostic_code`` is always one of the closed safe codes below and
    ``status_code`` is always a bounded 4xx/5xx suitable for the Chat route;
    neither ever carries Engine prose or any private reference.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostic_code: str = GENERIC_CALENDAR_READ_ACTIVATION_CODE,
        status_code: int = 503,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.status_code = status_code


def _bounded_engine_status(status: int) -> int:
    if not isinstance(status, int) or isinstance(status, bool) or not 400 <= status <= 599:
        return 503
    return status


def project_engine_rejection_diagnostic(document: Any, engine_status: int) -> tuple[str, int]:
    """Project one Engine rejection onto the closed safe diagnostic pair.

    Reads at most the Engine body's ``error.code`` string, bounded and matched
    against the closed table above. A malformed body, a missing or non-string
    code, or a code outside the table all collapse to the generic unavailable
    diagnostic — never to Engine prose, and never to a second authority.
    """

    engine_code: Any = None
    if isinstance(document, dict):
        error = document.get("error")
        if isinstance(error, dict):
            candidate = error.get("code")
            if isinstance(candidate, str) and 0 < len(candidate) <= _MAX_ENGINE_ERROR_CODE_CHARS:
                engine_code = candidate
    family = _ENGINE_ERROR_FAMILIES.get(engine_code) if isinstance(engine_code, str) else None
    if family is None:
        return GENERIC_CALENDAR_READ_ACTIVATION_CODE, 503
    diagnostic_code, preserve_status = family
    if not preserve_status:
        return diagnostic_code, 503
    status = _bounded_engine_status(engine_status)
    if status in _FLATTENED_ENGINE_STATUSES:
        status = 503
    return diagnostic_code, status


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
            document = None

        try:
            status = int(getattr(response, "status", 0))
        except (TypeError, ValueError) as exc:
            raise CalendarReadActivationClientError(
                "Calendar READ activation transport failed"
            ) from exc
        if status != 200:
            diagnostic_code, safe_status = project_engine_rejection_diagnostic(document, status)
            raise CalendarReadActivationClientError(
                "Calendar READ activation was rejected",
                diagnostic_code=diagnostic_code,
                status_code=safe_status,
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
CALENDAR_ACTIVATION_CLIENT_RAW_ENGINE_MESSAGE_OUTPUT = False
CALENDAR_ACTIVATION_CLIENT_DIAGNOSTIC_CLOSED = True
CALENDAR_ACTIVATION_ENGINE_AUTH_CODES = frozenset(
    {"service_authentication_failed", "service_app_not_authorized"}
)
CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES = frozenset(
    {diagnostic for diagnostic, _ in _ENGINE_ERROR_FAMILIES.values()}
    | {GENERIC_CALENDAR_READ_ACTIVATION_CODE}
)
