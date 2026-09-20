"""#2834 Phase A Native Padiem Calendar projections and builders.

Canonical calendar item projections:
- Projects native work_log, native appointment, existing task, existing alert,
  existing claw_run into a unified, bounded CalendarItemProjection.
- Reuses existing stores directly:
  DUPLICATE_TASK_STORAGE = NO
  DUPLICATE_ALERT_STORAGE = NO
  DUPLICATE_CLAW_RUN_STORAGE = NO
- Automation run projection is deferred pending #2833:
  AUTOMATION_PROJECTION = DEFERRED_PENDING_2833
- Today projection: calculates today's items according to explicit workspace/user timezone.
  SERVER_LOCAL_TIMEZONE_INFERENCE = NO
- Upcoming projection: returns future appointments and deadlines in stable ascending order.
  Past items are strictly excluded.
- Range projection: supports arbitrary date ranges for future Day/Week/Month UI reuse.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import inspect
from typing import Any
import zoneinfo

from .calendar_contracts import (
    AppointmentType,
    AUTOMATION_PROJECTION,
    CALENDAR_CONTRACT_VERSION,
    CalendarAppointment,
    CalendarContractError,
    CalendarItemProjection,
    CalendarItemType,
    CalendarSourceType,
    CalendarWorkLog,
    MAX_CALENDAR_LIST_LIMIT,
    _safe_identifier,
    parse_aware_datetime,
    validate_timezone,
)
from .calendar_store import CalendarStore


def project_work_log(log: CalendarWorkLog) -> CalendarItemProjection:
    """Project a native daily work log into a canonical calendar item."""
    return CalendarItemProjection(
        calendar_item_id=f"item_log_{log.log_id}",
        workspace_id=log.workspace_id,
        item_type=CalendarItemType.WORK_LOG.value,
        title=log.title,
        summary=log.content,
        date=log.date.isoformat(),
        start_at=None,
        end_at=None,
        timezone=None,
        all_day=False,
        source_type=CalendarSourceType.NATIVE_WORK_LOG.value,
        source_ref=f"work_log:{log.log_id}",
        created_at=log.created_at.isoformat(),
        updated_at=log.updated_at.isoformat(),
    )


def project_appointment(
    apt: CalendarAppointment, *, tz: zoneinfo.ZoneInfo | None = None
) -> CalendarItemProjection:
    """Project a native appointment into a canonical calendar item."""
    all_day = apt.appointment_type == AppointmentType.ALL_DAY
    if apt.appointment_type == AppointmentType.TIMED and apt.start_at is not None and tz is not None:
        item_date = apt.start_at.astimezone(tz).date().isoformat()
    else:
        item_date = apt.date.isoformat()

    return CalendarItemProjection(
        calendar_item_id=f"item_apt_{apt.appointment_id}",
        workspace_id=apt.workspace_id,
        item_type=CalendarItemType.APPOINTMENT.value,
        title=apt.title,
        summary=apt.description,
        date=item_date,
        start_at=apt.start_at.isoformat() if apt.start_at else None,
        end_at=apt.end_at.isoformat() if apt.end_at else None,
        timezone=apt.timezone,
        all_day=all_day,
        source_type=CalendarSourceType.NATIVE_APPOINTMENT.value,
        source_ref=f"appointment:{apt.appointment_id}",
        created_at=apt.created_at.isoformat(),
        updated_at=apt.updated_at.isoformat(),
    )


def project_task(
    task: Any, workspace_id: str, *, tz: zoneinfo.ZoneInfo | None = None
) -> CalendarItemProjection:
    """Project an existing Claw task into a canonical calendar item without duplication."""
    task_id = str(getattr(task, "task_id", task.get("task_id") if isinstance(task, dict) else ""))
    title = str(getattr(task, "title", task.get("title") if isinstance(task, dict) else ""))
    due_date = getattr(task, "due_date", task.get("due_date") if isinstance(task, dict) else None)
    created_at = getattr(task, "created_at", task.get("created_at") if isinstance(task, dict) else None)
    status = getattr(task, "status", task.get("status") if isinstance(task, dict) else "")
    status_val = status.value if hasattr(status, "value") else str(status)

    item_date: str
    if due_date is not None:
        item_date = due_date.isoformat() if hasattr(due_date, "isoformat") else str(due_date)
    elif created_at is not None:
        if isinstance(created_at, datetime) and tz is not None:
            item_date = created_at.astimezone(tz).date().isoformat()
        elif hasattr(created_at, "date"):
            item_date = created_at.date().isoformat()
        else:
            item_date = str(created_at)[:10]
    else:
        item_date = "1970-01-01"

    created_iso: str
    if created_at is not None:
        created_iso = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    else:
        created_iso = "1970-01-01T00:00:00Z"

    return CalendarItemProjection(
        calendar_item_id=f"item_task_{task_id}",
        workspace_id=workspace_id,
        item_type=CalendarItemType.TASK.value,
        title=title,
        summary=f"Status: {status_val}" if status_val else None,
        date=item_date,
        start_at=None,
        end_at=None,
        timezone=None,
        all_day=due_date is not None,
        source_type=CalendarSourceType.TASK.value,
        source_ref=f"task:{task_id}",
        created_at=created_iso,
        updated_at=created_iso,
    )


def project_alert(
    alert: Any, workspace_id: str, *, tz: zoneinfo.ZoneInfo | None = None
) -> CalendarItemProjection:
    """Project an existing Claw alert into a canonical calendar item without duplication."""
    alert_id = str(getattr(alert, "alert_id", alert.get("alert_id") if isinstance(alert, dict) else ""))
    title = str(getattr(alert, "title", alert.get("title") if isinstance(alert, dict) else ""))
    created_at = getattr(alert, "created_at", alert.get("created_at") if isinstance(alert, dict) else None)
    severity = getattr(alert, "severity", alert.get("severity") if isinstance(alert, dict) else "")
    severity_val = severity.value if hasattr(severity, "value") else str(severity)

    if created_at is not None:
        if isinstance(created_at, str):
            created_dt = parse_aware_datetime(created_at, "alert_created_at")
        else:
            created_dt = created_at
        created_iso = created_dt.astimezone(timezone.utc).isoformat()
        if tz is not None:
            item_date = created_dt.astimezone(tz).date().isoformat()
            tz_str = tz.key if hasattr(tz, "key") else str(tz)
        else:
            item_date = created_dt.date().isoformat()
            tz_str = "UTC"
    else:
        created_iso = "1970-01-01T00:00:00+00:00"
        item_date = "1970-01-01"
        tz_str = tz.key if tz is not None and hasattr(tz, "key") else "UTC"

    return CalendarItemProjection(
        calendar_item_id=f"item_alert_{alert_id}",
        workspace_id=workspace_id,
        item_type=CalendarItemType.ALERT.value,
        title=title,
        summary=f"Severity: {severity_val}" if severity_val else None,
        date=item_date,
        start_at=created_iso,
        end_at=None,
        timezone=tz_str,
        all_day=False,
        source_type=CalendarSourceType.ALERT.value,
        source_ref=f"alert:{alert_id}",
        created_at=created_iso,
        updated_at=created_iso,
    )


def project_claw_run(
    run: dict[str, Any], workspace_id: str, *, tz: zoneinfo.ZoneInfo | None = None
) -> CalendarItemProjection:
    """Project an existing Claw run history row into a canonical calendar item without duplication."""
    run_id = str(run.get("run_id", ""))
    title = str(run.get("title", ""))
    created_at_raw = run.get("created_at", "")
    updated_at_raw = run.get("updated_at") or created_at_raw
    summary = run.get("result_summary")
    status = run.get("status", "")

    if created_at_raw:
        try:
            dt = parse_aware_datetime(created_at_raw, "claw_run_created_at")
            start_at_iso = dt.astimezone(timezone.utc).isoformat()
            if tz is not None:
                item_date = dt.astimezone(tz).date().isoformat()
                tz_str = tz.key if hasattr(tz, "key") else str(tz)
            else:
                item_date = dt.date().isoformat()
                tz_str = "UTC"
        except Exception:
            start_at_iso = str(created_at_raw)
            item_date = str(created_at_raw)[:10]
            tz_str = "UTC"
    else:
        start_at_iso = "1970-01-01T00:00:00+00:00"
        item_date = "1970-01-01"
        tz_str = "UTC"

    clean_summary = f"[{status}] {summary}" if summary else f"Status: {status}"

    return CalendarItemProjection(
        calendar_item_id=f"item_run_{run_id}",
        workspace_id=workspace_id,
        item_type=CalendarItemType.CLAW_RUN.value,
        title=title,
        summary=clean_summary,
        date=item_date,
        start_at=start_at_iso,
        end_at=None,
        timezone=tz_str,
        all_day=False,
        source_type=CalendarSourceType.CLAW_RUN.value,
        source_ref=f"claw_run:{run_id}",
        created_at=str(created_at_raw),
        updated_at=str(updated_at_raw),
    )


async def _safe_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Invoke function whether sync or async, failing safely on error."""
    if not callable(fn):
        return None
    try:
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):
            return await res
        return res
    except Exception:
        return None


async def build_range_projection(
    workspace_id: str,
    start_date: date,
    end_date: date,
    tz_name: str,
    *,
    calendar_store: CalendarStore,
    task_alert_store: Any | None = None,
    history_store: Any | None = None,
    user_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Deterministic range projection over all canonical sources.

    Reusable for future Day, Week, and Month UI views.
    """
    _safe_identifier("workspace_id", workspace_id)
    tz = validate_timezone(tz_name)
    tz_key = tz.key if hasattr(tz, "key") else str(tz)

    if end_date < start_date:
        raise CalendarContractError(
            "invalid_date_range", "end_date cannot be earlier than start_date"
        )

    bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))
    items: list[CalendarItemProjection] = []

    # 1. Native work logs
    logs = await calendar_store.list_work_logs(
        workspace_id, start_date=start_date, end_date=end_date, limit=bounded_limit
    )
    for log in logs:
        items.append(project_work_log(log))

    # 2. Native appointments
    apts = await calendar_store.list_appointments(
        workspace_id, start_date=start_date, end_date=end_date, limit=bounded_limit
    )
    for apt in apts:
        items.append(project_appointment(apt, tz=tz))

    # 3. Existing Tasks (read-only projection, no duplicate storage)
    # Parity with claw_inbox_routes: only tasks owned by member_id/user_id are visible.
    # If user_id is None, fail closed (0 tasks projected).
    if task_alert_store is not None and user_id is not None:
        list_tasks = getattr(task_alert_store, "list_tasks", None)
        raw_tasks = await _safe_call(list_tasks, workspace_id, limit=bounded_limit)
        if raw_tasks:
            for t in raw_tasks:
                if getattr(t, "member_id", None) == user_id:
                    due = getattr(t, "due_date", None)
                    if due is not None and start_date <= due <= end_date:
                        items.append(project_task(t, workspace_id, tz=tz))

    # 4. Existing Alerts (read-only projection, no duplicate storage)
    # Parity with claw_inbox_routes: list_alerts(workspace_id, member_id=user_id)
    # If user_id is None, fail closed (0 alerts projected).
    if task_alert_store is not None and user_id is not None:
        list_alerts = getattr(task_alert_store, "list_alerts", None)
        raw_alerts = await _safe_call(
            list_alerts, workspace_id, member_id=user_id, limit=bounded_limit
        )
        if raw_alerts:
            for a in raw_alerts:
                is_vis = getattr(a, "is_visible_to", None)
                if callable(is_vis) and not is_vis(user_id):
                    continue
                c_at = getattr(a, "created_at", None)
                if c_at is not None:
                    # Determine date in user's requested timezone
                    if hasattr(c_at, "astimezone"):
                        a_date = c_at.astimezone(tz).date()
                    else:
                        a_date = c_at.date() if hasattr(c_at, "date") else None
                    if a_date and start_date <= a_date <= end_date:
                        items.append(project_alert(a, workspace_id, tz=tz))

    # 5. Existing Claw runs (read-only projection, no duplicate storage)
    # UNKNOWN_WORKSPACE_RUN_RELABELED_AS_CURRENT = NO
    # In HistoryStore, rows carry (user_id, run_id, ...) without workspace_id.
    # Only when the current workspace is provably the owner-derived personal scope
    # (workspace_id == f"owner:{user_id}") can user-scoped runs be projected.
    # For canonical tenant workspaces, run->workspace linkage is absent, so fail closed (omit runs).
    if (
        history_store is not None
        and user_id is not None
        and workspace_id == f"owner:{user_id}"
    ):
        list_runs = getattr(history_store, "list_recent_claw_runs", None)
        raw_runs = await _safe_call(list_runs, user_id, limit=bounded_limit)
        if raw_runs:
            for r in raw_runs:
                c_str = r.get("created_at")
                if c_str:
                    try:
                        dt = parse_aware_datetime(c_str, "claw_run_created_at")
                        r_date = dt.astimezone(tz).date()
                        if start_date <= r_date <= end_date:
                            items.append(project_claw_run(r, workspace_id, tz=tz))
                    except Exception:
                        pass

    # Deterministic sorting: date ascending, all_day events first, start_at ascending, tie-breaker id
    items.sort(
        key=lambda x: (
            x.date,
            not x.all_day,
            x.start_at or "",
            x.calendar_item_id,
        )
    )

    sliced = items[:bounded_limit]
    return {
        "contract_version": CALENDAR_CONTRACT_VERSION,
        "view": "range",
        "workspace_id": workspace_id,
        "timezone": tz_key,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "items": [item.safe_dict() for item in sliced],
        "total_count": len(sliced),
    }


async def build_today_projection(
    workspace_id: str,
    tz_name: str,
    *,
    calendar_store: CalendarStore,
    task_alert_store: Any | None = None,
    history_store: Any | None = None,
    user_id: str | None = None,
    now_utc: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Deterministic today projection for explicit timezone.

    SERVER_LOCAL_TIMEZONE_INFERENCE is NO.
    """
    _safe_identifier("workspace_id", workspace_id)
    tz = validate_timezone(tz_name)
    tz_key = tz.key if hasattr(tz, "key") else str(tz)

    ref_utc = now_utc or datetime.now(timezone.utc)
    if ref_utc.tzinfo is None or ref_utc.utcoffset() is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    # Compute today's date in the explicit timezone
    today_date = ref_utc.astimezone(tz).date()

    res = await build_range_projection(
        workspace_id=workspace_id,
        start_date=today_date,
        end_date=today_date,
        tz_name=tz_name,
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        history_store=history_store,
        user_id=user_id,
        limit=limit,
    )
    res["view"] = "today"
    res["date"] = today_date.isoformat()
    del res["start_date"]
    del res["end_date"]
    return res


async def build_upcoming_projection(
    workspace_id: str,
    tz_name: str,
    *,
    calendar_store: CalendarStore,
    task_alert_store: Any | None = None,
    user_id: str | None = None,
    now_utc: datetime | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Deterministic upcoming projection for future appointments and deadlines.

    Past events are strictly excluded.
    Ordered by start/date ascending with stable tie-breakers.
    """
    _safe_identifier("workspace_id", workspace_id)
    tz = validate_timezone(tz_name)
    tz_key = tz.key if hasattr(tz, "key") else str(tz)

    ref_utc = now_utc or datetime.now(timezone.utc)
    if ref_utc.tzinfo is None or ref_utc.utcoffset() is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    current_date_in_tz = ref_utc.astimezone(tz).date()
    bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))

    items: list[CalendarItemProjection] = []

    # 1. Native appointments starting on or after current_date
    raw_apts = await calendar_store.list_appointments(
        workspace_id, start_date=current_date_in_tz, limit=bounded_limit * 2
    )
    for apt in raw_apts:
        if apt.appointment_type == AppointmentType.TIMED:
            # Must be strictly in the future relative to ref_utc
            # (or ending in future if end_at is present)
            event_cutoff = apt.end_at or apt.start_at
            if event_cutoff and event_cutoff >= ref_utc:
                items.append(project_appointment(apt, tz=tz))
        else:
            # DATE_ONLY or ALL_DAY on or after current_date
            if apt.date >= current_date_in_tz:
                items.append(project_appointment(apt, tz=tz))

    # 2. Existing Tasks with future due dates
    # Parity with claw_inbox_routes: only tasks owned by member_id/user_id are visible.
    # If user_id is None, fail closed (0 tasks projected).
    if task_alert_store is not None and user_id is not None:
        list_tasks = getattr(task_alert_store, "list_tasks", None)
        raw_tasks = await _safe_call(list_tasks, workspace_id, limit=bounded_limit * 2)
        if raw_tasks:
            for t in raw_tasks:
                if getattr(t, "member_id", None) != user_id:
                    continue
                due = getattr(t, "due_date", None)
                status = getattr(t, "status", None)
                status_val = status.value if hasattr(status, "value") else str(status)
                # Omit completed/cancelled tasks from upcoming
                if status_val in {"completed", "cancelled"}:
                    continue
                if due is not None and due >= current_date_in_tz:
                    items.append(project_task(t, workspace_id, tz=tz))

    # Note: daily work logs, past alerts, and claw runs are historical records,
    # so they are NOT mixed into upcoming.

    # Stable ordering: date ascending, start_at ascending, tie-breaker calendar_item_id
    items.sort(
        key=lambda x: (
            x.date,
            x.start_at or "",
            x.calendar_item_id,
        )
    )

    sliced = items[:bounded_limit]
    return {
        "contract_version": CALENDAR_CONTRACT_VERSION,
        "view": "upcoming",
        "workspace_id": workspace_id,
        "timezone": tz_key,
        "from_timestamp": ref_utc.isoformat(),
        "items": [item.safe_dict() for item in sliced],
        "total_count": len(sliced),
    }
