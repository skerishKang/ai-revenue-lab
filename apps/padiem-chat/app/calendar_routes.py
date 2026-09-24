"""#2834 Phase A Native Padiem Calendar HTTP routes.

Provides bounded, owner/workspace-scoped calendar endpoints:
- GET /api/calendar/today — today view projection for explicit timezone
- GET /api/calendar/upcoming — upcoming appointments and deadlines
- GET /api/calendar/items — date range projection (Day/Week/Month backend reuse)
- GET /api/calendar/items/{calendar_item_id} — bounded item detail and trusted link-backs
- POST /api/calendar/work-logs — record native daily work log
- GET /api/calendar/work-logs — list native work logs
- POST /api/calendar/appointments — record native appointment (date-only, all-day, timed)
- GET /api/calendar/appointments — list native appointments

Authority invariants:
- Reuses existing B62 owner/workspace identity pattern (_require_owner, _resolve_memory_workspace).
- Caller-supplied owner/tenant fields are forbidden.
- Anonymous callers cannot access or mutate calendar data (401 unauthorized).
- Server-local timezone inference is strictly prohibited (400 if timezone missing/invalid).
- Zero raw user ids, provider accounts, credentials, or secrets in projections.
- Zero external calendar provider calls (EXTERNAL_PROVIDER_CALLS=0).
"""

from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .calendar_contracts import (
    AppointmentType,
    CalendarAppointment,
    CalendarContractError,
    CalendarWorkLog,
    parse_date,
    validate_timezone,
)
from .calendar_projection import (
    build_item_detail_projection,
    build_range_projection,
    build_today_projection,
    build_upcoming_projection,
    project_appointment,
    project_work_log,
)
from .calendar_store import CalendarStore
from .claw_memory_routes import _require_owner, _resolve_memory_workspace

MAX_CALENDAR_BODY_BYTES = 64 * 1024  # 64 KiB
_MAX_HTTP_LIMIT = 100

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_FORBIDDEN_OWNER_KEYS = frozenset(
    {
        "user_id",
        "owner",
        "owner_id",
        "tenant_id",
        "tenant",
        "workspace_id",
        "workspace",
    }
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _get_calendar_store(request: Request) -> CalendarStore | None:
    return getattr(request.app.state, "calendar_store", None)


def _bounded_limit(request: Request, default: int = 20) -> int | JSONResponse:
    raw = request.query_params.get("limit")
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit must be an integer")
    if val < 1:
        return _error(400, "invalid_limit", "limit must be at least 1")
    return min(val, _MAX_HTTP_LIMIT)


async def _read_json_body(request: Request) -> dict[str, Any] | JSONResponse:
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_CALENDAR_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    forbidden = _FORBIDDEN_OWNER_KEYS.intersection(data.keys())
    if forbidden:
        return _error(
            400,
            "forbidden_ownership_override",
            f"요청 본문에 소유권 필드를 지정할 수 없습니다: {', '.join(sorted(forbidden))}",
        )
    return data


async def calendar_today(request: Request) -> JSONResponse:
    """GET /api/calendar/today — returns today's items for explicit timezone."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    tz_param = request.query_params.get("timezone")
    if not tz_param:
        return _error(
            400,
            "timezone_required",
            "명시적 timezone 파라미터가 필요합니다. 서버 로컬 시간대 추론은 허용되지 않습니다.",
        )
    try:
        validate_timezone(tz_param)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    limit_val = _bounded_limit(request, default=100)
    if isinstance(limit_val, JSONResponse):
        return limit_val

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    task_alert_store = getattr(request.app.state, "claw_task_alert_store", None)
    history_store = getattr(request.app.state, "history_store", None)
    automation_store = getattr(request.app.state, "claw_automation_store", None)

    try:
        projection = await build_today_projection(
            workspace_id=workspace_id,
            tz_name=tz_param,
            calendar_store=store,
            task_alert_store=task_alert_store,
            history_store=history_store,
            automation_store=automation_store,
            user_id=uid,
            limit=limit_val,
        )
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "projection_failed", "오늘 캘린더를 생성하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "projection": projection},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_upcoming(request: Request) -> JSONResponse:
    """GET /api/calendar/upcoming — returns future appointments and deadlines."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    tz_param = request.query_params.get("timezone")
    if not tz_param:
        return _error(
            400,
            "timezone_required",
            "명시적 timezone 파라미터가 필요합니다. 서버 로컬 시간대 추론은 허용되지 않습니다.",
        )
    try:
        validate_timezone(tz_param)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    limit_val = _bounded_limit(request, default=20)
    if isinstance(limit_val, JSONResponse):
        return limit_val

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    task_alert_store = getattr(request.app.state, "claw_task_alert_store", None)

    try:
        projection = await build_upcoming_projection(
            workspace_id=workspace_id,
            tz_name=tz_param,
            calendar_store=store,
            task_alert_store=task_alert_store,
            user_id=uid,
            limit=limit_val,
        )
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "projection_failed", "다가오는 일정을 조회하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "projection": projection},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_items(request: Request) -> JSONResponse:
    """GET /api/calendar/items — returns items in date range for explicit timezone."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    tz_param = request.query_params.get("timezone")
    if not tz_param:
        return _error(
            400,
            "timezone_required",
            "명시적 timezone 파라미터가 필요합니다. 서버 로컬 시간대 추론은 허용되지 않습니다.",
        )
    try:
        validate_timezone(tz_param)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    start_param = request.query_params.get("start_date")
    end_param = request.query_params.get("end_date")
    if not start_param or not end_param:
        return _error(
            400, "date_range_required", "start_date와 end_date 파라미터가 필요합니다 (YYYY-MM-DD)."
        )

    try:
        start_d = parse_date(start_param, "start_date")
        end_d = parse_date(end_param, "end_date")
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    limit_val = _bounded_limit(request, default=100)
    if isinstance(limit_val, JSONResponse):
        return limit_val

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    task_alert_store = getattr(request.app.state, "claw_task_alert_store", None)
    history_store = getattr(request.app.state, "history_store", None)
    automation_store = getattr(request.app.state, "claw_automation_store", None)

    try:
        projection = await build_range_projection(
            workspace_id=workspace_id,
            start_date=start_d,
            end_date=end_d,
            tz_name=tz_param,
            calendar_store=store,
            task_alert_store=task_alert_store,
            history_store=history_store,
            automation_store=automation_store,
            user_id=uid,
            limit=limit_val,
        )
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "projection_failed", "캘린더 항목 범위를 조회하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "projection": projection},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_item_detail(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    tz_param = request.query_params.get("timezone")
    if not tz_param:
        return _error(
            400,
            "timezone_required",
            "명시적 timezone 파라미터가 필요합니다. 서버 로컬 시간대 추론은 허용되지 않습니다.",
        )
    try:
        validate_timezone(tz_param)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    calendar_item_id = request.path_params.get("calendar_item_id", "")
    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    task_alert_store = getattr(request.app.state, "claw_task_alert_store", None)
    history_store = getattr(request.app.state, "history_store", None)
    automation_store = getattr(request.app.state, "claw_automation_store", None)

    try:
        detail = await build_item_detail_projection(
            calendar_item_id=calendar_item_id,
            workspace_id=workspace_id,
            tz_name=tz_param,
            calendar_store=store,
            task_alert_store=task_alert_store,
            history_store=history_store,
            automation_store=automation_store,
            user_id=uid,
        )
    except CalendarContractError as exc:
        if exc.code == "calendar_item_not_found":
            return _error(404, "calendar_item_not_found", "캘린더 항목을 찾을 수 없습니다.")
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "detail_read_failed", "캘린더 항목 상세를 불러오지 못했습니다.")

    return JSONResponse(
        {"ok": True, "detail": detail},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_work_logs_create(request: Request) -> JSONResponse:
    """POST /api/calendar/work-logs — create a native daily work log entry."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    body = await _read_json_body(request)
    if isinstance(body, JSONResponse):
        return body

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)

    try:
        log = CalendarWorkLog.create(
            workspace_id=workspace_id,
            owner_id=uid,
            date_val=body.get("date"),
            title=body.get("title", ""),
            content=body.get("content"),
        )
        saved = await store.add_work_log(log)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "work_log_creation_failed", "업무 기록 생성에 실패했습니다.")

    return JSONResponse(
        {"ok": True, "work_log": project_work_log(saved).safe_dict()},
        status_code=201,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_work_logs_list(request: Request) -> JSONResponse:
    """GET /api/calendar/work-logs — list native work logs for current workspace."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)

    start_param = request.query_params.get("start_date")
    end_param = request.query_params.get("end_date")
    start_d: date | None = None
    end_d: date | None = None
    try:
        if start_param:
            start_d = parse_date(start_param, "start_date")
        if end_param:
            end_d = parse_date(end_param, "end_date")
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    limit_val = _bounded_limit(request, default=50)
    if isinstance(limit_val, JSONResponse):
        return limit_val

    try:
        logs = await store.list_work_logs(
            workspace_id, start_date=start_d, end_date=end_d, limit=limit_val
        )
    except Exception:
        return _error(500, "work_log_list_failed", "업무 기록 목록 조회에 실패했습니다.")

    return JSONResponse(
        {"ok": True, "items": [project_work_log(l).safe_dict() for l in logs]},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_appointments_create(request: Request) -> JSONResponse:
    """POST /api/calendar/appointments — create a native appointment."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    body = await _read_json_body(request)
    if isinstance(body, JSONResponse):
        return body

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)

    try:
        apt = CalendarAppointment.create(
            workspace_id=workspace_id,
            owner_id=uid,
            appointment_type=body.get("appointment_type", ""),
            title=body.get("title", ""),
            description=body.get("description"),
            date_val=body.get("date"),
            start_at=body.get("start_at"),
            end_at=body.get("end_at"),
            tz_name=body.get("timezone"),
            reminder_minutes=body.get("reminder_minutes"),
        )
        saved = await store.add_appointment(apt)
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        return _error(500, "appointment_creation_failed", "일정 생성에 실패했습니다.")

    return JSONResponse(
        {"ok": True, "appointment": project_appointment(saved).safe_dict()},
        status_code=201,
        headers=_NO_STORE_HEADERS,
    )


async def calendar_appointments_list(request: Request) -> JSONResponse:
    """GET /api/calendar/appointments — list native appointments for current workspace."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    store = _get_calendar_store(request)
    if store is None:
        return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)

    start_param = request.query_params.get("start_date")
    end_param = request.query_params.get("end_date")
    start_d: date | None = None
    end_d: date | None = None
    try:
        if start_param:
            start_d = parse_date(start_param, "start_date")
        if end_param:
            end_d = parse_date(end_param, "end_date")
    except CalendarContractError as exc:
        return _error(400, exc.code, exc.message)

    limit_val = _bounded_limit(request, default=50)
    if isinstance(limit_val, JSONResponse):
        return limit_val

    try:
        apts = await store.list_appointments(
            workspace_id, start_date=start_d, end_date=end_d, limit=limit_val
        )
    except Exception:
        return _error(500, "appointment_list_failed", "일정 목록 조회에 실패했습니다.")

    return JSONResponse(
        {"ok": True, "items": [project_appointment(a).safe_dict() for a in apts]},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )
