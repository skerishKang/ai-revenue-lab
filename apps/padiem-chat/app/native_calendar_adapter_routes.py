"""Native Calendar adapter routes for signed owner actions."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .calendar_routes import _NO_STORE_HEADERS, _error, _get_calendar_store, _require_owner, _resolve_memory_workspace
from .native_calendar_adapter import (
    FORBIDDEN_AUTHORITY_KEYS,
    NativeCalendarAdapterError,
    execute_native_calendar_plan,
    parse_native_calendar_plan,
)


async def native_calendar_adapter_read(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    timezone_name = request.query_params.get("timezone")
    limit = request.query_params.get("limit", "100")
    plan = {
        "version": "native-calendar-tool.v1",
        "op": "read",
        "args": {
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone_name,
            "limit": int(limit) if str(limit or "").isdigit() else limit,
        },
    }
    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")
    try:
        result = await execute_native_calendar_plan(request, store, uid, plan)
    except NativeCalendarAdapterError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    return JSONResponse({"ok": True, **result}, status_code=200, headers=_NO_STORE_HEADERS)


async def native_calendar_adapter_create(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(body, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    forbidden = FORBIDDEN_AUTHORITY_KEYS.intersection(body.keys())
    if forbidden:
        return _error(400, "forbidden_ownership_override", "요청 본문에 소유권 필드를 지정할 수 없습니다.")
    plan_payload = body.get("plan")
    if plan_payload is None:
        try:
            plan_payload = parse_native_calendar_plan(
                {
                    "version": "native-calendar-tool.v1",
                    "op": "create_appointment",
                    "args": body.get("args") or {k: v for k, v in body.items() if k != "turn_key"},
                }
            ).safe_dict()
        except NativeCalendarAdapterError as exc:
            return _error(exc.status_code, exc.code, exc.message)
    turn_key = body.get("turn_key")
    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")
    try:
        result = await execute_native_calendar_plan(request, store, uid, plan_payload, turn_key=turn_key)
    except NativeCalendarAdapterError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    except Exception:
        return _error(500, "create_failed", "일정 생성에 실패했습니다.")
    return JSONResponse({"ok": True, **result}, status_code=201 if result.get("operation") == "create_appointment" else 200, headers=_NO_STORE_HEADERS)


__all__ = ["native_calendar_adapter_create", "native_calendar_adapter_read"]
