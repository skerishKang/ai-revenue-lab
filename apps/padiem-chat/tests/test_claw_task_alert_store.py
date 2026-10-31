"""NETWORK_FREE tests for the durable Claw task/alert D1 persistence seam (#2328).

No live D1 IO, no live model call, no background scheduler, no outbound send.
Uses an in-memory D1 double identical in shape to Cloudflare D1
(prepare / bind / async run, first, all).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from kagent.claw_memory import (
    CONTRACT_VERSION,
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawMemoryError,
    ClawTaskStatus,
)

from app.claw_task_alert_store import D1ClawTaskAlertStore
from app.workspace_storage import WorkspaceStorageError

_TABLE = "claw_task_alert"

COLUMNS = (
    "id", "workspace_id", "kind", "status", "title", "created_at", "updated_at",
    "member_id", "due_date", "source_id", "linked_ref", "severity", "kind_value",
    "visible_to_all",
)


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 9, 10, 8, 0, 0, tzinfo=_dt.timezone.utc)


def _T(
    task_id: str = "task-1",
    *,
    workspace_id: str = "ws-1",
    status: ClawTaskStatus = ClawTaskStatus.OPEN,
    title: str = "Follow up with supplier",
    member_id: str = "member-1",
    due_date: _dt.date | None = None,
    source_id: str | None = None,
    linked_ref: str | None = None,
    created_at: _dt.datetime | None = None,
) -> ClawFollowupTask:
    return ClawFollowupTask(
        task_id=task_id,
        workspace_id=workspace_id,
        member_id=member_id,
        title=title,
        status=status,
        created_at=created_at or _now(),
        due_date=due_date,
        source_id=source_id,
        linked_ref=linked_ref,
    )


def _A(
    alert_id: str = "alert-1",
    *,
    workspace_id: str = "ws-1",
    kind: ClawAlertKind = ClawAlertKind.FOLLOWUP_DUE,
    severity: ClawAlertSeverity = ClawAlertSeverity.WARN,
    title: str = "Due follow-up needed",
    status: ClawAlertStatus = ClawAlertStatus.ACTIVE,
    created_at: _dt.datetime | None = None,
    visible_to_members: tuple[str, ...] = (),
    linked_refs: tuple[str, ...] = (),
) -> ClawAlert:
    return ClawAlert(
        alert_id=alert_id,
        workspace_id=workspace_id,
        kind=kind,
        severity=severity,
        title=title,
        created_at=created_at or _now(),
        status=status,
        visible_to_members=visible_to_members,
        linked_refs=linked_refs,
    )


class _Statement:
    """Runs the store's own SQL through a D1-shaped surface over sqlite."""

    def __init__(self, conn: "sqlite3.Connection", sql: str) -> None:
        self._conn = conn
        self._sql = sql
        self._values: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> "_Statement":
        self._values = values
        return self

    async def run(self) -> dict[str, Any]:
        cur = self._conn.execute(self._sql, self._values)
        return {"success": True, "meta": {"changes": cur.rowcount}}

    async def first(self) -> dict[str, Any] | None:
        row = self._conn.execute(self._sql, self._values).fetchone()
        return dict(row) if row else None

    async def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(self._sql, self._values).fetchall()]


class _FakeD1:
    """sqlite with the migration-010 schema, so the real WHERE clauses are what
    the tests exercise — the owner predicate cannot drift from a hand-written fake."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            (
                Path(__file__).resolve().parents[1]
                / "migrations"
                / "010_claw_task_alert.sql"
            ).read_text(encoding="utf-8")
        )

    @property
    def rows(self) -> dict[str, dict[str, Any]]:
        return {
            row["id"]: dict(row)
            for row in self.conn.execute(f"SELECT * FROM {_TABLE}").fetchall()
        }

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self.conn, sql)


def _store() -> tuple[D1ClawTaskAlertStore, _FakeD1]:
    db = _FakeD1()
    return D1ClawTaskAlertStore(db), db


# ---- 1. task create/list/read ----
async def test_task_create_and_get_and_list():
    store, _ = _store()
    task = _T()
    saved = await store.add_task(task)
    assert saved.task_id == "task-1"
    got = await store.get_task("task-1", workspace_id="ws-1", member_id="member-1")
    assert got is not None
    assert got.task_id == "task-1"
    assert got.status == ClawTaskStatus.OPEN
    assert got.title == "Follow up with supplier"
    assert got.member_id == "member-1"
    listed = await store.list_tasks("ws-1", member_id="member-1")
    assert len(listed) == 1
    assert listed[0].task_id == "task-1"
    assert listed[0].title == "Follow up with supplier"


async def test_task_get_missing_returns_none():
    store, _ = _store()
    assert await store.get_task("task-1", workspace_id="ws-1", member_id="member-1") is None


# ---- 2. alert create/list/read ----
async def test_alert_create_and_get_and_list():
    store, _ = _store()
    alert = _A()
    await store.add_alert(alert)
    got = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-1")
    assert got is not None
    assert got.kind == ClawAlertKind.FOLLOWUP_DUE
    assert got.severity == ClawAlertSeverity.WARN
    assert got.title == "Due follow-up needed"
    listed = await store.list_alerts("ws-1", member_id="member-1")
    assert len(listed) == 1
    assert listed[0].alert_id == "alert-1"
    assert listed[0].is_visible_to(None)
    assert listed[0].is_visible_to("member-1")


async def test_alert_member_scoped_is_visible_to_only_listed_member():
    store, _ = _store()
    alert = _A(visible_to_members=("member-1",))
    await store.add_alert(alert)
    none_view = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-2")
    assert none_view is None
    own_view = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-1")
    assert own_view is not None


# ---- #5034: the alert result reference rides the existing ref columns ----
async def test_alert_result_reference_round_trips_in_order():
    store, db = _store()
    await store.add_alert(_A(
        kind=ClawAlertKind.AUTOMATION,
        linked_refs=("sched_run_" + "a" * 64, "rule-1"),
    ))
    row = db.rows["alert-1"]
    assert row["source_id"] == "sched_run_" + "a" * 64
    assert row["linked_ref"] == "rule-1"
    got = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-1")
    assert got is not None
    assert got.linked_refs == ("sched_run_" + "a" * 64, "rule-1")
    listed = await store.list_alerts("ws-1", member_id="member-1")
    assert listed[0].linked_refs == ("sched_run_" + "a" * 64, "rule-1")


async def test_alert_without_a_reference_keeps_the_empty_state():
    store, db = _store()
    await store.add_alert(_A())
    assert db.rows["alert-1"]["source_id"] is None
    assert db.rows["alert-1"]["linked_ref"] is None
    got = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-1")
    assert got is not None and got.linked_refs == ()


async def test_a_third_alert_reference_is_refused_not_dropped():
    store, db = _store()
    with pytest.raises(WorkspaceStorageError):
        await store.add_alert(_A(linked_refs=("a-1", "b-2", "c-3")))
    assert "alert-1" not in db.rows


# ---- 3. task status update ----
async def test_task_status_update():
    store, _ = _store()
    await store.add_task(_T())
    updated = await store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-1", member_id="member-1", at=_now())
    assert updated.status == ClawTaskStatus.DONE
    got = await store.get_task("task-1", workspace_id="ws-1", member_id="member-1")
    assert got.status == ClawTaskStatus.DONE


async def test_task_status_update_unknown_id_fails_closed():
    store, _ = _store()
    with pytest.raises(ClawMemoryError):
        await store.set_task_status("task-x", ClawTaskStatus.DONE, workspace_id="ws-1", member_id="member-1")


# ---- 4. alert status update ----
async def test_alert_status_update():
    store, _ = _store()
    await store.add_alert(_A())
    updated = await store.set_alert_status("alert-1", ClawAlertStatus.DISMISSED, workspace_id="ws-1", member_id="member-1", at=_now())
    assert updated.status == ClawAlertStatus.DISMISSED


async def test_alert_status_update_unknown_id_fails_closed():
    store, _ = _store()
    with pytest.raises(ClawMemoryError):
        await store.set_alert_status("alert-x", ClawAlertStatus.DISMISSED, workspace_id="ws-1", member_id="member-1")


# ---- 5. hard bounded list ----
async def test_list_is_hard_bounded():
    store, _ = _store()
    for i in range(300):
        await store.add_task(_T(f"task-{i}", title=f"title {i}", member_id="m-1"))
    assert len(await store.list_tasks("ws-1", member_id="m-1")) == 256
    assert len(await store.list_tasks("ws-1", member_id="m-1", limit=5)) == 5


# ---- 6. owner/workspace isolation ----
async def test_owner_workspace_isolation():
    store, _ = _store()
    await store.add_task(_T("task-1", workspace_id="ws-1", member_id="m-a"))
    await store.add_task(_T("task-2", workspace_id="ws-2", member_id="m-b"))
    t1 = await store.get_task("task-1", workspace_id="ws-1", member_id="m-a")
    t2 = await store.get_task("task-2", workspace_id="ws-2", member_id="m-b")
    assert t1 is not None and t1.member_id == "m-a"
    assert t2 is not None and t2.member_id == "m-b"
    listed_ws1 = await store.list_tasks("ws-1", member_id="m-a")
    listed_ws2 = await store.list_tasks("ws-2", member_id="m-b")
    assert len(listed_ws1) == 1 and listed_ws1[0].member_id == "m-a"
    assert len(listed_ws2) == 1 and listed_ws2[0].member_id == "m-b"
    # #2952 follow-up: inside ONE workspace a tenant-mate reads nothing.
    assert await store.list_tasks("ws-1", member_id="m-b") == ()
    assert await store.list_tasks("ws-2", member_id="m-a") == ()


# ---- 7. foreign/missing non-disclosure ----
async def test_foreign_get_returns_none_not_error():
    store, _ = _store()
    await store.add_task(_T("task-1", workspace_id="ws-1", member_id="m-1"))
    assert await store.get_task("task-1", workspace_id="ws-999", member_id="member-1") is None
    assert await store.get_alert("task-1", workspace_id="ws-999", member_id="member-1") is None
    with pytest.raises(ClawMemoryError):
        await store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-999", member_id="member-1")


# ---- 8. D1 failure fail-closed ----
class _AlwaysFailStatement:
    def bind(self, *values: Any) -> "_AlwaysFailStatement":
        return self

    async def run(self) -> dict[str, Any]:
        raise RuntimeError("simulated D1 failure")

    async def first(self) -> Any:
        raise RuntimeError("simulated D1 failure")

    async def all(self) -> list[Any]:
        raise RuntimeError("simulated D1 failure")


class _FailingD1:
    def prepare(self, sql: str) -> _AlwaysFailStatement:
        return _AlwaysFailStatement()


async def test_d1_write_failure_fail_closed():
    store = D1ClawTaskAlertStore(_FailingD1())
    with pytest.raises(WorkspaceStorageError):
        await store.add_task(_T())


async def test_d1_read_failure_fail_closed():
    store = D1ClawTaskAlertStore(_FailingD1())
    assert await store.get_task("task-1", workspace_id="ws-1", member_id="member-1") is None


# ---- 9. secret / raw-material persistence 0 ----
async def test_no_raw_prompt_secret_token_persisted_in_row():
    store, db = _store()
    task = _T(title="Review proposal")
    await store.add_task(task)
    row = db.rows["task-1"]
    assert row["source_id"] is None
    assert row["linked_ref"] is None
    assert row["severity"] is None
    assert row["kind_value"] is None
    assert row["created_at"] == task.created_at.isoformat()
    assert row["title"] == "Review proposal"


async def test_no_oauth_cookie_persisted_in_row():
    store, db = _store()
    alert = _A(kind=ClawAlertKind.MEMORY_PROPOSAL, severity=ClawAlertSeverity.INFO,
               title="Memory proposal awaiting approval")
    await store.add_alert(alert)
    row = db.rows["alert-1"]
    assert row["due_date"] is None
    assert row["source_id"] is None
    assert row["linked_ref"] is None
    assert row["severity"] == ClawAlertSeverity.INFO.value
    assert row["kind_value"] == ClawAlertKind.MEMORY_PROPOSAL.value
    assert row["visible_to_all"] == 1


async def test_projection_round_trip():
    store, _ = _store()
    await store.add_task(_T("task-1", member_id="m-1"))
    await store.add_alert(_A("alert-1", visible_to_members=("m-1",)))
    proj = await store.projection("ws-1", member_id="m-1")
    assert proj["contract_version"] == CONTRACT_VERSION
    assert proj["workspace_id"] == "ws-1"
    assert len(proj["tasks"]) == 1
    assert proj["tasks"][0]["task_id"] == "task-1"
    assert len(proj["alerts"]) == 1
    assert proj["alerts"][0]["alert_id"] == "alert-1"


async def test_projection_is_callable_with_the_contract_include_raw_switch():
    """#5360: the D1 adapter honours the shared contract's include_raw switch.

    The durable Task/Alert rows carry no inbound body, so the authorized and
    the diagnostic form of the same workspace are the same document here. What
    matters is that a caller may ask for either form through the contract.
    """
    store, _ = _store()
    await store.add_task(_T("task-1", member_id="m-1"))
    await store.add_alert(_A("alert-1", visible_to_members=("m-1",)))
    authorized = await store.projection("ws-1", member_id="m-1")
    diagnostic = await store.projection("ws-1", member_id="m-1", include_raw=False)
    assert diagnostic == authorized
    assert "raw_excerpt" not in repr(diagnostic)


def test_the_d1_store_projection_accepts_every_contract_keyword():
    """A contract keyword must never be missing from the durable adapter."""
    import inspect

    from kagent.claw_memory import ClawMemoryStore

    def keywords(function) -> set[str]:
        return {
            name
            for name, parameter in inspect.signature(function).parameters.items()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        }

    assert keywords(D1ClawTaskAlertStore.projection) == keywords(
        ClawMemoryStore.projection
    )



# ---- 6. due_date round trip (regression) ----
# add_task persists `due_date.isoformat()`, a *plain* date string. Reading it
# back through a tz-aware datetime parser raised WorkspaceStorageError, so a
# single due-dated task made list_tasks fail and get_task report "not found".
async def test_task_with_due_date_round_trips():
    store, _ = _store()
    await store.add_task(_T(due_date=_dt.date(2026, 9, 30)))
    got = await store.get_task("task-1", workspace_id="ws-1", member_id="member-1")
    assert got is not None
    assert got.due_date == _dt.date(2026, 9, 30)
    listed = await store.list_tasks("ws-1", member_id="member-1")
    assert [t.task_id for t in listed] == ["task-1"]
    assert listed[0].due_date == _dt.date(2026, 9, 30)


async def test_due_dated_task_status_update_round_trips():
    store, _ = _store()
    await store.add_task(_T(due_date=_dt.date(2026, 9, 30)))
    updated = await store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-1", member_id="member-1")
    assert updated.status == ClawTaskStatus.DONE
    assert updated.due_date == _dt.date(2026, 9, 30)
    assert (await store.get_task("task-1", workspace_id="ws-1", member_id="member-1")).status == ClawTaskStatus.DONE


async def test_due_date_parser_still_accepts_timestamp_rows():
    # Rows written as timestamps (not by add_task) must keep working.
    from app.claw_task_alert_store import _parse_date

    assert _parse_date("2026-09-30") == _dt.date(2026, 9, 30)
    assert _parse_date("2026-09-30T12:00:00+00:00") == _dt.date(2026, 9, 30)
    assert _parse_date(None) is None
    # A malformed value still fails; _task_row_to_record narrows it to
    # WorkspaceStorageError("claw task row is invalid").
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


# ---- 10. #2952 follow-up: one record read needs the member it belongs to ----
async def test_a_tenant_mate_cannot_read_another_members_task_row():
    """Same workspace, different member: the row is not there, at the store."""
    store, db = _store()
    await store.add_task(_T("task-a", member_id="member-a", title="A의 후속 작업"))

    assert await store.get_task("task-a", workspace_id="ws-1", member_id="member-b") is None
    own = await store.get_task("task-a", workspace_id="ws-1", member_id="member-a")
    assert own is not None and own.title == "A의 후속 작업"
    assert db.rows["task-a"]["member_id"] == "member-a"


async def test_a_tenant_mate_cannot_change_another_members_task_status():
    store, db = _store()
    await store.add_task(_T("task-a", member_id="member-a"))

    with pytest.raises(ClawMemoryError):
        await store.set_task_status(
            "task-a",
            ClawTaskStatus.DONE,
            workspace_id="ws-1",
            member_id="member-b",
        )
    assert db.rows["task-a"]["status"] == ClawTaskStatus.OPEN.value

    updated = await store.set_task_status(
        "task-a", ClawTaskStatus.DONE, workspace_id="ws-1", member_id="member-a"
    )
    assert updated.status == ClawTaskStatus.DONE
    assert db.rows["task-a"]["status"] == ClawTaskStatus.DONE.value


async def test_company_shared_alert_stays_visible_and_foreign_one_does_not():
    """``visible_to_all`` keeps its sharing meaning; a member-only row does not leak."""
    store, _db = _store()
    await store.add_alert(_A("alert-shared"))
    await store.add_alert(
        _A("alert-mine", visible_to_members=("member-a",))
    )

    for member in ("member-a", "member-b"):
        assert await store.get_alert("alert-shared", workspace_id="ws-1", member_id=member) is not None
    assert await store.get_alert("alert-mine", workspace_id="ws-1", member_id="member-a") is not None
    assert await store.get_alert("alert-mine", workspace_id="ws-1", member_id="member-b") is None


async def test_status_writes_follow_the_same_visibility_rule():
    store, db = _store()
    await store.add_alert(
        _A("alert-mine", visible_to_members=("member-a",))
    )
    with pytest.raises(ClawMemoryError):
        await store.set_alert_status(
            "alert-mine",
            ClawAlertStatus.DISMISSED,
            workspace_id="ws-1",
            member_id="member-b",
        )
    assert db.rows["alert-mine"]["status"] == ClawAlertStatus.ACTIVE.value
    await store.set_alert_status(
        "alert-mine", ClawAlertStatus.DISMISSED, workspace_id="ws-1", member_id="member-a"
    )
    assert db.rows["alert-mine"]["status"] == ClawAlertStatus.DISMISSED.value


def test_a_single_record_read_without_a_member_cannot_be_expressed():
    """No owner argument is a TypeError at the call, not a tenant-wide row."""
    import inspect

    for name in ("get_task", "get_alert", "set_task_status", "set_alert_status"):
        method = getattr(D1ClawTaskAlertStore, name)
        parameter = inspect.signature(method).parameters["member_id"]
        assert parameter.default is inspect.Parameter.empty, name
