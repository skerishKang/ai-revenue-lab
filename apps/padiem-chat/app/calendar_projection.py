"""#2834 Phase A Native Padiem Calendar projections and builders.

Canonical calendar item projections:
- Projects native work_log, native appointment, existing task, existing alert,
  existing claw_run into a unified, bounded CalendarItemProjection.
- Reuses existing stores directly:
  DUPLICATE_TASK_STORAGE = NO
  DUPLICATE_ALERT_STORAGE = NO
  DUPLICATE_CLAW_RUN_STORAGE = NO
- Durable automation runs are projected read-only from the existing automation store:
  DUPLICATE_AUTOMATION_STORAGE = NO
- Today projection: calculates today's items according to explicit workspace/user timezone.
  SERVER_LOCAL_TIMEZONE_INFERENCE = NO
- Upcoming projection: returns future appointments and deadlines in stable ascending order.
  Past items are strictly excluded.
- Range projection: supports arbitrary date ranges for future Day/Week/Month UI reuse.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import inspect
import re
from typing import Any
import zoneinfo

from .calendar_contracts import (
    AppointmentType,
    AUTOMATION_PROJECTION,
    CALENDAR_CONTRACT_VERSION,
    CalendarAppointment,
    CalendarContractError,
    CalendarItemDetail,
    CalendarItemProjection,
    CalendarItemType,
    CalendarLinkBack,
    CalendarSourceType,
    CalendarWorkLog,
    MAX_CALENDAR_LIST_LIMIT,
    MAX_CONTENT_CHARS,
    MAX_TITLE_CHARS,
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
        artifact=_project_claw_run_artifact(run),
    )


_DOCUMENT_ID_PATTERN = re.compile(r"^doc_[A-Za-z0-9]{32}$")
_ARTIFACT_KEYS = ("document_id", "filename", "media_type")


def _project_claw_run_artifact(run: dict[str, Any]) -> dict[str, str] | None:
    """Pass through the bounded HistoryStore artifact reference, fail closed.

    Reuses the canonical document_id grammar from claw_routes.claw_manual_intake_artifact
    (HISTORY_STORE_ARTIFACT_AUTHORITY=REUSE, NEW_DOCUMENT_ID_GRAMMAR=NO).
    Projects only {document_id, filename, media_type}; never credentials, tokens,
    storage keys, filesystem paths, provider identifiers, or D1 row ids.
    Any malformed or missing artifact yields None while the run itself still projects.
    """
    artifact = run.get("artifact")
    if not isinstance(artifact, dict) or not artifact:
        return None
    out: dict[str, str] = {}
    for key in _ARTIFACT_KEYS:
        value = artifact.get(key)
        if not isinstance(value, str) or not value:
            return None
        out[key] = value
    if not _DOCUMENT_ID_PATTERN.match(out["document_id"]):
        return None
    if set(artifact) != set(_ARTIFACT_KEYS):
        return None
    return out


def project_automation_run(
    run: Any, workspace_id: str, *, tz: zoneinfo.ZoneInfo
) -> CalendarItemProjection:
    """Project a durable Claw automation run without exposing output/proposal payloads."""
    run_workspace_id = str(getattr(run, "workspace_id", ""))
    if run_workspace_id != workspace_id:
        raise CalendarContractError("automation_workspace_mismatch", "automation run workspace mismatch")
    run_id = str(getattr(run, "run_id", ""))
    rule_id = str(getattr(run, "rule_id", ""))
    _safe_identifier("automation_run_id", run_id)
    _safe_identifier("automation_rule_id", rule_id)
    status = getattr(run, "status", "")
    status_val = status.value if hasattr(status, "value") else str(status)
    scheduled = getattr(run, "scheduled_time", None)
    if not isinstance(scheduled, datetime) or scheduled.tzinfo is None or scheduled.utcoffset() is None:
        raise CalendarContractError("invalid_automation_run", "scheduled_time must be timezone-aware")
    scheduled_utc = scheduled.astimezone(timezone.utc)
    local_date = scheduled_utc.astimezone(tz).date().isoformat()
    tz_key = tz.key if hasattr(tz, "key") else str(tz)
    completed = getattr(run, "completed_at", None)
    updated = completed if isinstance(completed, datetime) else getattr(run, "started_at", scheduled_utc)
    if not isinstance(updated, datetime) or updated.tzinfo is None or updated.utcoffset() is None:
        raise CalendarContractError("invalid_automation_run", "updated automation timestamp must be timezone-aware")
    return CalendarItemProjection(
        calendar_item_id=f"automation_{run_id}",
        workspace_id=workspace_id,
        item_type=CalendarItemType.AUTOMATION_RUN.value,
        title=f"Claw automation · {rule_id}",
        summary=f"Status: {status_val}",
        date=local_date,
        start_at=scheduled_utc.isoformat(),
        end_at=None,
        timezone=tz_key,
        all_day=False,
        source_type=CalendarSourceType.AUTOMATION_RUN.value,
        source_ref=f"automation_run:{run_id}",
        created_at=scheduled_utc.isoformat(),
        updated_at=updated.astimezone(timezone.utc).isoformat(),
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


_CALENDAR_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_LOG_CALENDAR_ITEM_ID_RE = re.compile(r"^item_log_(log_[0-9a-f]{16,32})$")
_APPOINTMENT_CALENDAR_ITEM_ID_RE = re.compile(r"^item_apt_(apt_[0-9a-f]{16,32})$")
_TASK_CALENDAR_ITEM_ID_RE = re.compile(
    r"^item_task_([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
)
_ALERT_CALENDAR_ITEM_ID_RE = re.compile(
    r"^item_alert_([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
)
_RUN_CALENDAR_ITEM_ID_RE = re.compile(
    r"^item_run_([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
)
_AUTOMATION_CALENDAR_ITEM_ID_RE = re.compile(
    r"^automation_([A-Za-z0-9][A-Za-z0-9._:-]{0,127})$"
)


def _detail_not_found() -> CalendarContractError:
    return CalendarContractError(
        "calendar_item_not_found", "Calendar item was not found"
    )


def _bounded_detail_item(item: CalendarItemProjection) -> CalendarItemProjection:
    title = item.title.strip()
    if not title:
        raise _detail_not_found()
    summary = item.summary.strip() if isinstance(item.summary, str) else None
    return replace(
        item,
        calendar_item_id=item.calendar_item_id[:256],
        title=title[:MAX_TITLE_CHARS],
        summary=summary[:MAX_CONTENT_CHARS] if summary else None,
        date=item.date[:64],
        start_at=item.start_at[:128] if item.start_at else None,
        end_at=item.end_at[:128] if item.end_at else None,
        timezone=item.timezone[:128] if item.timezone else None,
        source_type=item.source_type[:64],
        created_at=item.created_at[:128],
        updated_at=item.updated_at[:128],
    )


def _run_session_link(run: dict[str, Any]) -> CalendarLinkBack | None:
    session = run.get("session")
    if not isinstance(session, dict):
        return None
    target_id = session.get("conversation_id")
    if not isinstance(target_id, str):
        return None
    try:
        return CalendarLinkBack(kind="claw_session", target_id=target_id)
    except CalendarContractError:
        return None


def _run_artifact_link(item: CalendarItemProjection) -> CalendarLinkBack | None:
    artifact = item.artifact
    if not isinstance(artifact, dict):
        return None
    target_id = artifact.get("document_id")
    if not isinstance(target_id, str):
        return None
    try:
        return CalendarLinkBack(kind="artifact", target_id=target_id)
    except CalendarContractError:
        return None


async def build_item_detail_projection(
    calendar_item_id: str,
    workspace_id: str,
    tz_name: str,
    *,
    calendar_store: CalendarStore,
    task_alert_store: Any | None = None,
    history_store: Any | None = None,
    automation_store: Any | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    _safe_identifier("workspace_id", workspace_id)
    if user_id is not None:
        _safe_identifier("user_id", user_id)
    tz = validate_timezone(tz_name)
    if not isinstance(calendar_item_id, str) or not _CALENDAR_ITEM_ID_RE.fullmatch(
        calendar_item_id
    ):
        raise _detail_not_found()

    link_backs: tuple[CalendarLinkBack, ...] = ()
    item: CalendarItemProjection | None = None

    match = _LOG_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
    if match:
        record = await _safe_call(
            getattr(calendar_store, "get_work_log", None), workspace_id, match.group(1)
        )
        if isinstance(record, CalendarWorkLog) and record.workspace_id == workspace_id:
            item = project_work_log(record)

    if item is None:
        match = _APPOINTMENT_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
        if match:
            record = await _safe_call(
                getattr(calendar_store, "get_appointment", None),
                workspace_id,
                match.group(1),
            )
            if (
                isinstance(record, CalendarAppointment)
                and record.workspace_id == workspace_id
            ):
                item = project_appointment(record, tz=tz)

    if item is None:
        match = _TASK_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
        if match and task_alert_store is not None and user_id is not None:
            task_id = match.group(1)
            record = await _safe_call(
                getattr(task_alert_store, "get_task", None),
                task_id,
                workspace_id=workspace_id,
            )
            if record is not None and getattr(record, "member_id", None) == user_id:
                try:
                    item = project_task(record, workspace_id, tz=tz)
                    link_backs = (CalendarLinkBack(kind="task", target_id=task_id),)
                except Exception:
                    item = None

    if item is None:
        match = _ALERT_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
        if match and task_alert_store is not None and user_id is not None:
            alert_id = match.group(1)
            record = await _safe_call(
                getattr(task_alert_store, "get_alert", None),
                alert_id,
                workspace_id=workspace_id,
                member_id=user_id,
            )
            is_visible = getattr(record, "is_visible_to", None)
            if record is not None and (not callable(is_visible) or is_visible(user_id)):
                try:
                    item = project_alert(record, workspace_id, tz=tz)
                except Exception:
                    item = None

    if item is None:
        match = _RUN_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
        if (
            match
            and history_store is not None
            and user_id is not None
            and workspace_id == f"owner:{user_id}"
        ):
            run_id = match.group(1)
            runs = await _safe_call(
                getattr(history_store, "list_recent_claw_runs", None),
                user_id,
                limit=MAX_CALENDAR_LIST_LIMIT,
            )
            if isinstance(runs, (list, tuple)):
                for run in runs:
                    if (
                        not isinstance(run, dict)
                        or str(run.get("run_id", "")) != run_id
                    ):
                        continue
                    try:
                        item = project_claw_run(run, workspace_id, tz=tz)
                        links = [CalendarLinkBack(kind="run", target_id=run_id)]
                        session_link = _run_session_link(run)
                        if session_link is not None:
                            links.append(session_link)
                        artifact_link = _run_artifact_link(item)
                        if artifact_link is not None:
                            links.append(artifact_link)
                        link_backs = tuple(links)
                    except Exception:
                        item = None
                    break

    if item is None:
        match = _AUTOMATION_CALENDAR_ITEM_ID_RE.fullmatch(calendar_item_id)
        if match and automation_store is not None:
            run_id = match.group(1)
            record = await _safe_call(
                getattr(automation_store, "get_run", None),
                run_id,
                workspace_id=workspace_id,
            )
            if (
                record is not None
                and getattr(record, "workspace_id", None) == workspace_id
            ):
                try:
                    item = project_automation_run(record, workspace_id, tz=tz)
                except Exception:
                    item = None

    if item is None:
        raise _detail_not_found()
    return CalendarItemDetail(
        item=_bounded_detail_item(item), link_backs=link_backs
    ).safe_dict()


async def build_range_projection(
    workspace_id: str,
    start_date: date,
    end_date: date,
    tz_name: str,
    *,
    calendar_store: CalendarStore,
    task_alert_store: Any | None = None,
    history_store: Any | None = None,
    automation_store: Any | None = None,
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


    # 6. Durable automation runs (read-only; store already enforces workspace isolation).
    if automation_store is not None:
        list_automation_runs = getattr(automation_store, "list_runs", None)
        raw_automation_runs = await _safe_call(list_automation_runs, workspace_id)
        if raw_automation_runs:
            for run in raw_automation_runs:
                try:
                    scheduled = getattr(run, "scheduled_time", None)
                    if not isinstance(scheduled, datetime):
                        continue
                    run_date = scheduled.astimezone(tz).date()
                    if start_date <= run_date <= end_date:
                        items.append(project_automation_run(run, workspace_id, tz=tz))
                except Exception:
                    continue

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
    automation_store: Any | None = None,
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
        automation_store=automation_store,
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
