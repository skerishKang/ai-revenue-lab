"""Shared product-local native PADIEM Calendar execution adapter (#4745).

This module owns the bounded Chat/Claw execution boundary for
``native_calendar.read`` and ``native_calendar.create_appointment``.  It reuses
the existing workspace-scoped CalendarStore and validation rules and keeps model
output as a proposal/planner payload rather than execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .calendar_contracts import (
    CalendarAppointment,
    CalendarContractError,
    _safe_identifier,
)
from .calendar_projection import project_appointment
from .claw_memory_routes import _require_owner, _resolve_memory_workspace


NATIVE_CALENDAR_TOOL_VERSION = "native-calendar-tool.v1"
VALID_OPS = ("read", "create_appointment", "clarify", "none")
FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "user_id",
        "owner_id",
        "tenant_id",
        "tenant",
        "workspace_id",
        "workspace",
        "account_ref",
        "binding_ref",
        "actor_ref",
    }
)


class NativeCalendarAdapterError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class NativeCalendarPlan:
    version: str
    op: str
    args: dict[str, Any]
    question: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "op": self.op,
            "args": dict(self.args),
            "question": self.question,
        }


def parse_native_calendar_plan(payload: Any) -> NativeCalendarPlan:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar plan is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar plan must be an object")
    version = payload.get("version")
    if version != NATIVE_CALENDAR_TOOL_VERSION:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar plan has an unsupported version")
    op = payload.get("op")
    if op not in VALID_OPS:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar plan has an unsupported operation")
    args = payload.get("args", {})
    if not isinstance(args, Mapping):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar args must be an object")
    if len(json.dumps(dict(args), ensure_ascii=False, separators=(",", ":"))) > 8192:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar args are too large")
    question = payload.get("question")
    if question is not None and not isinstance(question, str):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar question must be text")
    return NativeCalendarPlan(version=version, op=str(op), args=dict(args), question=str(question) if question is not None else None)


def _read_args(args: Mapping[str, Any]) -> tuple[str, str, str, int]:
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    timezone_name = args.get("timezone")
    limit = int(args.get("limit", 100) or 100)
    from .calendar_contracts import parse_date, validate_timezone

    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar read requires explicit date bounds")
    if not isinstance(timezone_name, str):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar read requires explicit timezone")
    try:
        start = parse_date(start_date, "start_date")
        end = parse_date(end_date, "end_date")
        validate_timezone(timezone_name)
    except (CalendarContractError, ValueError) as exc:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", str(exc)) from exc
    if start > end:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar read range is inverted")
    return str(start), str(end), timezone_name.strip(), max(1, min(limit, 100))


def _appointment_payload(appointment: CalendarAppointment) -> dict[str, Any]:
    return {
        "appointment_type": appointment.appointment_type.value,
        "title": appointment.title,
        "description": appointment.description,
        "date": appointment.date.isoformat(),
        "start_at": appointment.start_at.isoformat() if appointment.start_at else None,
        "end_at": appointment.end_at.isoformat() if appointment.end_at else None,
        "timezone": appointment.timezone,
    }


def _payloads_match(existing: CalendarAppointment, desired: CalendarAppointment) -> bool:
    return (
        existing.owner_id == desired.owner_id
        and existing.workspace_id == desired.workspace_id
        and existing.appointment_type == desired.appointment_type
        and existing.title == desired.title
        and existing.description == desired.description
        and existing.date == desired.date
        and existing.start_at == desired.start_at
        and existing.end_at == desired.end_at
        and existing.timezone == desired.timezone
    )


def _canonical_id(owner_id: str, workspace_id: str, turn_key: str, payload: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256("|".join(("native_calendar", owner_id, workspace_id, turn_key, blob)).encode("utf-8")).hexdigest()[:16]


async def execute_native_calendar_plan(
    request: Any,
    store: Any,
    owner_id: str | None,
    plan: NativeCalendarPlan | Mapping[str, Any] | str,
    *,
    turn_key: str | None = None,
) -> dict[str, Any]:
    uid = owner_id or _require_owner(request)
    if uid is None:
        raise NativeCalendarAdapterError("unauthorized", "native calendar requires authentication", status_code=401)
    workspace_id = await _resolve_memory_workspace(request, uid)
    parsed = plan if isinstance(plan, NativeCalendarPlan) else parse_native_calendar_plan(plan)

    if parsed.op == "none":
        return {"ok": True, "operation": "none"}
    if parsed.op == "clarify":
        return {"ok": True, "operation": "clarify", "question": parsed.question}

    if parsed.op == "read":
        start_date, end_date, timezone_name, limit = _read_args(parsed.args)
        appointments = await store.list_appointments(
            workspace_id,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            limit=limit,
        )
        items = [project_appointment(item).safe_dict() for item in appointments]
        return {
            "ok": True,
            "operation": "read",
            "items": items,
            "timezone": timezone_name,
            "range": {"start_date": start_date, "end_date": end_date},
            "empty_native_calendar": not bool(items),
        }

    if set(parsed.args).intersection(FORBIDDEN_AUTHORITY_KEYS):
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar plan must not supply authority identifiers")

    title = parsed.args.get("title")
    appointment_type = str(parsed.args.get("appointment_type", "date_only"))
    if not isinstance(title, str) or not title.strip():
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar create requires a title")
    if turn_key is None and parsed.args.get("turn_key") is None:
        raise NativeCalendarAdapterError("invalid_or_ambiguous", "native calendar create requires a server turn key")
    effective_turn_key = turn_key or str(parsed.args["turn_key"])

    payload = {
        "appointment_type": appointment_type,
        "title": title.strip(),
        "description": parsed.args.get("description"),
        "date": parsed.args.get("date"),
        "start_at": parsed.args.get("start_at"),
        "end_at": parsed.args.get("end_at"),
        "timezone": parsed.args.get("timezone"),
    }

    from .calendar_contracts import CalendarAppointment

    desired = CalendarAppointment.create(
        workspace_id=workspace_id,
        owner_id=uid,
        appointment_type=appointment_type,
        title=title.strip(),
        description=payload["description"],
        date_val=payload["date"],
        start_at=payload["start_at"],
        end_at=payload["end_at"],
        tz_name=payload["timezone"],
        appointment_id="apt_" + _canonical_id(uid, workspace_id, effective_turn_key, {}),
    )

    appointment_id = desired.appointment_id
    existing = await store.get_appointment(workspace_id, appointment_id)
    if existing is not None:
        if existing.owner_id != uid or not _payloads_match(existing, desired):
            raise NativeCalendarAdapterError("conflict", "native calendar create duplicate payload mismatch", status_code=409)
        return {
            "ok": True,
            "operation": "create_appointment",
            "appointment": project_appointment(existing).safe_dict(),
            "replayed": True,
        }

    try:
        saved = await store.add_appointment(desired)
    except Exception as exc:
        existing = await store.get_appointment(workspace_id, appointment_id)
        if existing is not None:
            if existing.owner_id != uid or not _payloads_match(existing, desired):
                raise NativeCalendarAdapterError("conflict", "native calendar create duplicate payload mismatch", status_code=409) from exc
            return {"ok": True, "operation": "create_appointment", "appointment": project_appointment(existing).safe_dict(), "replayed": True}
        raise NativeCalendarAdapterError("unavailable", "native calendar create could not be stored", status_code=503) from exc

    return {"ok": True, "operation": "create_appointment", "appointment": project_appointment(saved).safe_dict(), "replayed": False}


__all__ = [
    "FORBIDDEN_AUTHORITY_KEYS",
    "NATIVE_CALENDAR_TOOL_VERSION",
    "NativeCalendarAdapterError",
    "NativeCalendarPlan",
    "execute_native_calendar_plan",
    "parse_native_calendar_plan",
]
