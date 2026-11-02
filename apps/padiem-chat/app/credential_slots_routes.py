"""Owner-only read of the B14 credential-slot board.

The browser never talks to B14. This route reuses the existing global-model
administrator authority (the same ``_central_admin`` check every Chat admin
model endpoint uses) and then asks B14 for slot metadata through the deployment
lane. What the browser receives is rebuilt here from a strict field allowlist,
so a regression on the B14 side still cannot turn this route into a path for a
key value.

No write, rotate, create or delete action exists in this slice.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .b14_slot_status_source import SlotStatusUnavailable
from .central_model_control_routes import _central_admin, _error

SLOT_STATUS_ROUTE = "/api/admin/credential-slots"

MAX_SLOTS = 14
MAX_PROVIDERS_PER_SLOT = 8
MAX_ERROR_CODES = 10

_SLOT = re.compile(r"\APADIEM_B14_CREDENTIAL_\d{2}\Z")
_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}\Z")
_TIMESTAMP = re.compile(r"\A\d{4}-\d{2}-\d{2}T[0-9:.+-]{1,32}\Z")
_STATES = frozenset({
    "configured", "empty", "placeholder", "unresolved", "rejected_mode",
})
_MODIFIED_SOURCES = frozenset({"secret_file", "env_file", "none"})
_LEDGER_STATES = frozenset({"bound", "not_configured", "unavailable"})
_REGISTRY_STATES = frozenset({"loaded", "unavailable"})


def _safe_slot(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    slot = row.get("slot")
    number = row.get("slot_number")
    providers = row.get("provider_ids")
    configured = row.get("configured")
    state = row.get("state")
    detail = row.get("state_detail", "")
    length = row.get("length")
    last4 = row.get("last4")
    modified_at = row.get("file_modified_at")
    modified_source = row.get("file_modified_source")
    last_success = row.get("last_success_at")
    errors = row.get("recent_error_codes")

    if not isinstance(slot, str) or _SLOT.fullmatch(slot) is None:
        return None
    if type(number) is not int or not 1 <= number <= MAX_SLOTS:
        return None
    if not isinstance(providers, list) or len(providers) > MAX_PROVIDERS_PER_SLOT:
        return None
    if any(not isinstance(p, str) or _IDENTIFIER.fullmatch(p) is None for p in providers):
        return None
    if type(configured) is not bool or state not in _STATES:
        return None
    if not isinstance(detail, str) or len(detail) > 64:
        return None
    if length is not None and (type(length) is not int or not 0 <= length <= 4096):
        return None
    if last4 is not None and (not isinstance(last4, str) or len(last4) > 4):
        return None
    if modified_source not in _MODIFIED_SOURCES:
        return None
    if modified_at is not None and (
        not isinstance(modified_at, str) or _TIMESTAMP.fullmatch(modified_at) is None
    ):
        return None
    if last_success is not None and (
        not isinstance(last_success, str) or _TIMESTAMP.fullmatch(last_success) is None
    ):
        return None
    if not isinstance(errors, list) or len(errors) > MAX_ERROR_CODES:
        return None
    safe_errors: list[dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            return None
        code, count = item.get("code"), item.get("count")
        if not isinstance(code, str) or _IDENTIFIER.fullmatch(code) is None:
            return None
        if type(count) is not int or count < 0:
            return None
        safe_errors.append({"code": code, "count": count})

    return {
        "slot": slot,
        "slot_number": number,
        "provider_ids": list(providers),
        "configured": configured,
        "state": state,
        "state_detail": detail,
        "length": length,
        "last4": last4,
        "file_modified_at": modified_at,
        "file_modified_source": modified_source,
        "last_success_at": last_success,
        "recent_error_codes": safe_errors,
    }


def _safe_slots(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    rows = payload.get("slots")
    if not isinstance(rows, list) or len(rows) != MAX_SLOTS:
        return None
    safe = [_safe_slot(row) for row in rows]
    if any(row is None for row in safe):
        return None
    return [row for row in safe if row is not None]


def _safe_ledger(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("state") not in _LEDGER_STATES:
        return None
    hours = value.get("error_window_hours")
    if type(hours) is not int or not 0 < hours <= 24 * 90:
        return None
    return {"state": value["state"], "error_window_hours": hours}


async def credential_slots_status(request: Request):
    denial = await _central_admin(request)
    if denial is not None:
        return denial

    source = getattr(request.app.state, "b14_slot_status_source", None)
    fetch = getattr(source, "fetch", None)
    if not callable(fetch):
        return _error(503, "credential_slots_unavailable")

    try:
        payload = await fetch()
    except SlotStatusUnavailable as exc:
        return _error(502, exc.code)
    except Exception:
        return _error(502, "credential_slots_unavailable")

    slots = _safe_slots(payload)
    ledger = _safe_ledger(payload.get("ledger") if isinstance(payload, dict) else None)
    registry = payload.get("registry") if isinstance(payload, dict) else None
    if slots is None or ledger is None:
        return _error(502, "credential_slots_invalid_response")
    if registry not in _REGISTRY_STATES:
        registry = "unavailable"

    generated_at = payload.get("generated_at")
    return JSONResponse(
        {
            "ok": True,
            "slots": slots,
            "ledger": ledger,
            "registry": registry,
            "generated_at": generated_at if isinstance(generated_at, str) else None,
        },
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )
