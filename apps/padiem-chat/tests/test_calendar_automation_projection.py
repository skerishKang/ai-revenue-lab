"""Focused regressions for #2846 durable Claw automation -> Padiem Calendar projection."""
from datetime import date, datetime, timedelta, timezone
import json
import sys
import zoneinfo
from pathlib import Path
from typing import Any

CHAT_ROOT = Path(__file__).resolve().parents[1]
KAGENT_SRC = CHAT_ROOT.parent / "korean-ai-code-agent" / "src"
for candidate in (str(CHAT_ROOT), str(KAGENT_SRC)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import pytest
from starlette.testclient import TestClient

from app.auth import create_session_token
from app.calendar_contracts import CalendarWorkLog
from app.calendar_projection import (
    build_range_projection,
    build_today_projection,
    build_upcoming_projection,
)
from app.calendar_store import InMemoryCalendarStore
from app.config import Settings
from app.history import UserProfile
from app.main import create_app
from kagent.claw_automation import (
    ClawApprovalGate,
    ClawAutomationOutputType,
    ClawAutomationOutput,
    ClawNotificationChannel,
    ClawNotificationProposal,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    InMemoryClawAutomationStore,
)

SESSION_COOKIE = "padiem_session"


def _record_run(
    store,
    workspace_id: str,
    rule_id: str,
    scheduled: datetime,
    *,
    proposals: tuple = (),
):
    run = ClawScheduledRun(
        run_id=f"run_{rule_id}_{int(scheduled.timestamp())}",
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=ClawScheduledRunStatus.COMPLETED,
        scheduled_time=scheduled,
        started_at=scheduled,
        completed_at=scheduled,
        output=ClawAutomationOutput(
            output_id=f"out_{rule_id}_{int(scheduled.timestamp())}",
            workspace_id=workspace_id,
            output_type=ClawAutomationOutputType.REPORT,
            title="Sensitive automation output",
            content="결과 보고서 (DRAFT) — must not be projected.",
            evidence_refs=("credential://must-not-project",),
            proposals=proposals,
        ),
    )
    store.record_run(run)
    return run


def _store_with_run(workspace_id: str, scheduled: datetime):
    store = InMemoryClawAutomationStore()
    _record_run(store, workspace_id, "rule_daily_quote", scheduled)
    return store

@pytest.mark.asyncio
async def test_range_projects_durable_run_read_only_and_minimal():
    store = _store_with_run("ws_alpha", datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc))
    result = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        tz_name="Asia/Seoul",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
    )
    assert result["total_count"] == 1
    item = result["items"][0]
    assert item["item_type"] == "automation_run"
    assert item["source_type"] == "automation_run"
    assert item["date"] == "2026-09-21"
    assert item["timezone"] == "Asia/Seoul"
    serialized = str(item).lower()
    assert "recipient" not in serialized
    assert "evidence" not in serialized
    assert "결과 보고서" not in serialized


@pytest.mark.asyncio
async def test_cross_workspace_automation_run_is_not_disclosed():
    store = _store_with_run("ws_secret", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc))
    result = await build_range_projection(
        workspace_id="ws_other",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
    )
    assert result["items"] == []


@pytest.mark.asyncio
async def test_missing_automation_store_fails_closed_to_zero_projection():
    result = await build_today_projection(
        workspace_id="ws_alpha",
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=None,
        now_utc=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert result["items"] == []


@pytest.mark.asyncio
async def test_automation_projection_respects_calendar_limit():
    store = InMemoryClawAutomationStore()
    for idx in range(4):
        _record_run(
            store,
            "ws_alpha",
            f"rule_{idx}",
            datetime(2026, 9, 20, idx, 0, tzinfo=timezone.utc),
        )
    result = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
        limit=2,
    )
    assert result["total_count"] == 2
    assert len(result["items"]) == 2


# ==============================================================================
# #2846 acceptance: today / timezone boundary / ordering / fail-closed stores
# ==============================================================================


@pytest.mark.asyncio
async def test_today_projects_durable_run_in_explicit_timezone():
    store = _store_with_run("ws_alpha", datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc))
    result = await build_today_projection(
        workspace_id="ws_alpha",
        tz_name="Asia/Seoul",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
        now_utc=datetime(2026, 9, 20, 15, 30, tzinfo=timezone.utc),
    )
    assert result["view"] == "today"
    assert result["date"] == "2026-09-21"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["item_type"] == "automation_run"
    assert item["date"] == "2026-09-21"
    assert item["timezone"] == "Asia/Seoul"
    assert item["start_at"] == "2026-09-20T15:00:00+00:00"


@pytest.mark.asyncio
async def test_timezone_boundary_utc_vs_seoul_date_split():
    """UTC date and Asia/Seoul date diverge at the 15:00Z boundary."""
    # 14:59:59Z = 2026-09-20 23:59:59+09:00 -> Seoul date stays 09-20
    before = _store_with_run("ws_alpha", datetime(2026, 9, 20, 14, 59, 59, tzinfo=timezone.utc))
    res_before = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        tz_name="Asia/Seoul",
        calendar_store=InMemoryCalendarStore(),
        automation_store=before,
    )
    assert res_before["items"] == []

    # 15:00:00Z = 2026-09-21 00:00:00+09:00 -> Seoul date flips to 09-21
    after = _store_with_run("ws_alpha", datetime(2026, 9, 20, 15, 0, 0, tzinfo=timezone.utc))
    res_after = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        tz_name="Asia/Seoul",
        calendar_store=InMemoryCalendarStore(),
        automation_store=after,
    )
    assert len(res_after["items"]) == 1
    assert res_after["items"][0]["date"] == "2026-09-21"

    # Same run is on 09-20 under UTC projection
    res_utc = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=after,
    )
    assert len(res_utc["items"]) == 1
    assert res_utc["items"][0]["date"] == "2026-09-20"


class _HostileAutomationStore:
    """Store that violates workspace filtering (defense-in-depth target)."""

    def __init__(self, runs: list):
        self._runs = runs

    def list_runs(self, workspace_id: str):
        return list(self._runs)


class _BrokenAutomationStore:
    """Store whose read path raises (must fail closed, not kill calendar)."""

    def list_runs(self, workspace_id: str):
        raise RuntimeError("automation store unavailable")


@pytest.mark.asyncio
async def test_hostile_store_foreign_workspace_run_not_disclosed():
    foreign_run = ClawScheduledRun(
        run_id="run_foreign_1",
        workspace_id="ws_secret",
        rule_id="rule_foreign",
        status=ClawScheduledRunStatus.COMPLETED,
        scheduled_time=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
    )
    result = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=_HostileAutomationStore([foreign_run]),
    )
    assert result["items"] == []


@pytest.mark.asyncio
async def test_unavailable_automation_store_fails_closed_without_killing_calendar():
    cal_store = InMemoryCalendarStore()
    await cal_store.add_work_log(
        CalendarWorkLog.create(
            workspace_id="ws_alpha",
            owner_id="usr_1",
            date_val="2026-09-20",
            title="기존 업무 기록",
        )
    )
    result = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=cal_store,
        automation_store=_BrokenAutomationStore(),
    )
    types = {i["item_type"] for i in result["items"]}
    assert "work_log" in types
    assert "automation_run" not in types


@pytest.mark.asyncio
async def test_automation_projection_stable_ordering():
    store = InMemoryClawAutomationStore()
    for idx, hour in enumerate((12, 0, 6)):
        _record_run(
            store,
            "ws_alpha",
            f"rule_{idx}",
            datetime(2026, 9, 20, hour, 0, tzinfo=timezone.utc),
        )
    kwargs = dict(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 20),
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
    )
    first = await build_range_projection(**kwargs)
    second = await build_range_projection(**kwargs)
    first_starts = [i["start_at"] for i in first["items"]]
    second_starts = [i["start_at"] for i in second["items"]]
    assert first_starts == sorted(first_starts)
    assert first_starts == second_starts
    assert len(first_starts) == 3


@pytest.mark.asyncio
async def test_proposal_text_and_credential_material_not_projected():
    gate = ClawApprovalGate(
        approval_required=True,
        reason="",
        suggested_action="",
    )
    proposal = ClawNotificationProposal(
        proposal_id="prop_secret_1",
        workspace_id="ws_alpha",
        rule_id="rule_daily_quote",
        channel=ClawNotificationChannel.WEB_ALERT_INBOX,
        title="PROPOSAL_TITLE_SECRET",
        summary="PROPOSAL_SUMMARY_SECRET must not leak",
        approval_gate=gate,
    )
    store = _store_with_run("ws_alpha", datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc))
    # attach proposal to the recorded run's output
    runs = store.list_runs("ws_alpha")
    base = runs[0]
    with_proposal = ClawScheduledRun(
        run_id=base.run_id,
        workspace_id=base.workspace_id,
        rule_id=base.rule_id,
        status=base.status,
        scheduled_time=base.scheduled_time,
        started_at=base.started_at,
        completed_at=base.completed_at,
        output=ClawAutomationOutput(
            output_id=base.output.output_id,
            workspace_id=base.workspace_id,
            output_type=base.output.output_type,
            title=base.output.title,
            content=base.output.content,
            evidence_refs=base.output.evidence_refs,
            proposals=(proposal,),
        ),
    )
    store = InMemoryClawAutomationStore()
    store.record_run(with_proposal)

    result = await build_range_projection(
        workspace_id="ws_alpha",
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        tz_name="Asia/Seoul",
        calendar_store=InMemoryCalendarStore(),
        automation_store=store,
    )
    assert len(result["items"]) == 1
    serialized = json.dumps(result["items"][0], ensure_ascii=False).lower()
    assert "proposal_summary_secret" not in serialized
    assert "proposal_title_secret" not in serialized
    assert "credential://" not in serialized
    assert "evidence" not in serialized
    assert "recipient" not in serialized
    assert "결과 보고서" not in serialized
    assert "must not be projected" not in serialized
    # minimal allowed metadata present
    item = result["items"][0]
    assert item["source_ref"].startswith("automation_run:")
    assert item["item_type"] == "automation_run"


# ==============================================================================
# #2846 HTTP route composition (items / today include; upcoming excludes)
# ==============================================================================


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.users: dict[str, Any] = {}

    async def get_user(self, user_id: str):
        return self.users.get(user_id)

    async def list_recent_claw_runs(self, user_id: str, limit: int = 30):
        return []


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="calendar-client.apps.googleusercontent.com",
        google_client_secret="calendar-google-secret",
        session_secret="calendar-session-secret-not-a-real-credential-0",
        session_max_age_seconds=3600,
    )


def _http_client(automation_store=None):
    settings = _settings()
    user_id = "usr_cal_auto"
    history_store = _FakeHistoryStore()
    history_store.users[user_id] = UserProfile(
        id=user_id,
        email="cal-auto@example.test",
        display_name="Calendar Automation Tester",
        picture_url="",
    )
    token = create_session_token(settings, user_id)
    app = create_app(
        settings=settings,
        history_store=history_store,
        calendar_store=InMemoryCalendarStore(),
        claw_automation_store=automation_store,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, token)
    return client, user_id


def test_http_calendar_items_includes_automation_run():
    workspace_id = "owner:usr_cal_auto"
    store = _store_with_run(workspace_id, datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc))
    client, _ = _http_client(automation_store=store)
    res = client.get(
        "/api/calendar/items?start_date=2026-09-21&end_date=2026-09-21&timezone=Asia/Seoul"
    )
    assert res.status_code == 200
    items = res.json()["projection"]["items"]
    auto_items = [i for i in items if i["item_type"] == "automation_run"]
    assert len(auto_items) == 1
    assert auto_items[0]["date"] == "2026-09-21"
    blob = json.dumps(items, ensure_ascii=False).lower()
    assert "결과 보고서" not in blob
    assert "credential://" not in blob


def test_http_calendar_today_includes_automation_run():
    workspace_id = "owner:usr_cal_auto"
    now = datetime.now(timezone.utc)
    store = _store_with_run(workspace_id, now)
    client, _ = _http_client(automation_store=store)
    res = client.get("/api/calendar/today?timezone=Asia/Seoul")
    assert res.status_code == 200
    items = res.json()["projection"]["items"]
    auto_items = [i for i in items if i["item_type"] == "automation_run"]
    assert len(auto_items) == 1
    expected_date = now.astimezone(zoneinfo.ZoneInfo("Asia/Seoul")).date().isoformat()
    assert auto_items[0]["date"] == expected_date


def test_http_calendar_items_missing_automation_store_keeps_other_items():
    client, _ = _http_client(automation_store=None)
    # create a work log so non-automation source is present
    create_res = client.post(
        "/api/calendar/work-logs",
        json={"date": "2026-09-21", "title": "일반 업무 기록"},
    )
    assert create_res.status_code == 201
    res = client.get(
        "/api/calendar/items?start_date=2026-09-21&end_date=2026-09-21&timezone=Asia/Seoul"
    )
    assert res.status_code == 200
    items = res.json()["projection"]["items"]
    types = {i["item_type"] for i in items}
    assert "work_log" in types
    assert "automation_run" not in types


def test_http_calendar_upcoming_does_not_promote_completed_historical_runs():
    workspace_id = "owner:usr_cal_auto"
    future = datetime.now(timezone.utc) + timedelta(days=7)
    store = _store_with_run(workspace_id, future)
    client, _ = _http_client(automation_store=store)
    res = client.get("/api/calendar/upcoming?timezone=Asia/Seoul")
    assert res.status_code == 200
    items = res.json()["projection"]["items"]
    assert all(i["item_type"] != "automation_run" for i in items)


@pytest.mark.asyncio
async def test_upcoming_projection_excludes_automation_runs():
    store = _store_with_run("ws_alpha", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    # upcoming builder reads only appointments/tasks — automation runs never enter
    result = await build_upcoming_projection(
        workspace_id="ws_alpha",
        tz_name="UTC",
        calendar_store=InMemoryCalendarStore(),
        now_utc=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert all(i["item_type"] != "automation_run" for i in result["items"])
    assert store.list_runs("ws_alpha")  # store itself still holds the run (no promotion)
