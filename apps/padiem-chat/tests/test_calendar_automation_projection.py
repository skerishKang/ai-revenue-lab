"""Focused regressions for #2846 durable Claw automation -> Padiem Calendar projection."""
from datetime import date, datetime, timezone
import sys
from pathlib import Path

CHAT_ROOT = Path(__file__).resolve().parents[1]
KAGENT_SRC = CHAT_ROOT.parent / "korean-ai-code-agent" / "src"
for candidate in (str(CHAT_ROOT), str(KAGENT_SRC)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import pytest

from app.calendar_projection import build_range_projection, build_today_projection
from app.calendar_store import InMemoryCalendarStore
from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
)


def _store_with_run(workspace_id: str, scheduled: datetime):
    store = InMemoryClawAutomationStore()
    rule = ClawAutomationRule(
        rule_id="rule_daily_quote",
        workspace_id=workspace_id,
        name="Daily supplier quote check",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.INTERVAL, expression="86400s", timezone="UTC"
        ),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
    )
    store.save_rule(rule)
    FakeClawScheduler(store).execute_rule_dry_run(rule, scheduled)
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
    scheduler = FakeClawScheduler(store)
    for idx in range(4):
        rule = ClawAutomationRule(
            rule_id=f"rule_{idx}",
            workspace_id="ws_alpha",
            name=f"Rule {idx}",
            schedule=ClawScheduleExpression(
                kind=ClawScheduleKind.INTERVAL, expression="daily", timezone="UTC"
            ),
            target_source=ClawAutomationTarget.INBOX,
            output_type=ClawAutomationOutputType.REPORT,
        )
        store.save_rule(rule)
        scheduler.execute_rule_dry_run(
            rule, datetime(2026, 9, 20, idx, 0, tzinfo=timezone.utc)
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
