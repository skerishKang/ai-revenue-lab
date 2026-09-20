from __future__ import annotations

from datetime import datetime, timezone
import unittest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - supported Python versions provide zoneinfo
    ZoneInfo = None

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRunStatus,
    ContractError,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    occurrence_key,
    resolve_timezone,
)
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole


UTC = timezone.utc


def rule(
    rule_id: str,
    workspace_id: str = "workspace_a",
    *,
    kind: ClawScheduleKind = ClawScheduleKind.CRON,
    expression: str = "0 9 * * *",
    schedule_timezone: str = "UTC",
    enabled: bool = True,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(kind, expression, schedule_timezone),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
    )


class ClawAutomationPhaseATests(unittest.TestCase):
    def test_cron_due_and_not_yet_due(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        scheduled = rule("cron")
        store.save_rule(scheduled)
        self.assertEqual(
            [item.rule_id for item in scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 9, 0, tzinfo=UTC))],
            ["cron"],
        )
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 8, 59, tzinfo=UTC)), [])

    def test_interval_requires_explicit_grid_occurrence_and_compat_daily_alias(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("interval", kind=ClawScheduleKind.INTERVAL, expression="1h"))
        self.assertEqual(len(scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 10, 0, tzinfo=UTC))), 1)
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 10, 1, tzinfo=UTC)), [])
        self.assertEqual(rule("daily", kind=ClawScheduleKind.INTERVAL, expression="daily").schedule.expression, "daily")

    def test_daypart_honors_explicit_timezone(self) -> None:
        try:
            resolve_timezone("Asia/Seoul")
        except ContractError:
            self.skipTest("Asia/Seoul timezone data unavailable on this runner")
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("kst", kind=ClawScheduleKind.DAYPART, expression="morning", schedule_timezone="Asia/Seoul"))
        due = scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 0, 0, tzinfo=UTC))
        self.assertEqual([item.rule_id for item in due], ["kst"])
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), [])

    def test_naive_current_time_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            FakeClawScheduler(InMemoryClawAutomationStore()).evaluate_due_rules(
                "workspace_a", datetime(2026, 9, 8, 9, 0)
            )

    def test_invalid_schedule_and_timezone_fail_closed(self) -> None:
        with self.assertRaises(ContractError):
            rule("invalid", expression="@hourly")
        with self.assertRaises(ContractError):
            rule("invalid_interval", kind=ClawScheduleKind.INTERVAL, expression="0m")
        with self.assertRaises(ContractError):
            rule("invalid_tz", schedule_timezone="not a timezone")
        with self.assertRaises(ContractError):
            resolve_timezone("Not/AZone")

    def test_occurrence_identity_contains_workspace_rule_and_scheduled_at(self) -> None:
        when = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
        first = occurrence_key("workspace_a", "same", when)
        second = occurrence_key("workspace_b", "same", when)
        third = occurrence_key("workspace_a", "same", datetime(2026, 9, 8, 9, 1, tzinfo=UTC))
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_same_occurrence_retry_is_deduplicated(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        scheduled_rule = rule("retry")
        store.save_rule(scheduled_rule)
        when = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
        first = scheduler.execute_rule_dry_run(scheduled_rule, when)
        retry = scheduler.execute_rule_dry_run(scheduled_rule, when)
        self.assertEqual(first.run_id, retry.run_id)
        self.assertEqual(len(store.list_runs("workspace_a")), 1)
        self.assertEqual(first.status, ClawScheduledRunStatus.COMPLETED)

    def test_max_length_workspace_and_rule_ids_execute_with_bounded_derived_ids(self) -> None:
        long_workspace = "w" * 128
        long_rule = "r" * 128
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        item = rule(long_rule, long_workspace)
        store.save_rule(item)
        first_time = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
        run = scheduler.execute_rule_dry_run(item, first_time)
        self.assertLessEqual(len(run.run_id), 128)
        self.assertLessEqual(len(run.output.proposals[0].proposal_id), 128)
        self.assertLessEqual(len(run.output.output_id), 128)
        self.assertTrue(run.run_id.startswith("sched_run_"))
        self.assertTrue(run.output.proposals[0].proposal_id.startswith("prop_"))
        self.assertTrue(run.output.output_id.startswith("out_"))
        self.assertIs(run, scheduler.execute_rule_dry_run(item, first_time))

        different_rule = rule("q" * 128, long_workspace)
        different_workspace = rule("s" * 128, "x" * 128)
        store.save_rule(different_rule)
        store.save_rule(different_workspace)
        second = scheduler.execute_rule_dry_run(different_rule, first_time)
        third = scheduler.execute_rule_dry_run(different_workspace, first_time)
        fourth = scheduler.execute_rule_dry_run(item, datetime(2026, 9, 8, 9, 1, tzinfo=UTC))
        self.assertNotEqual(run.run_id, second.run_id)
        self.assertNotEqual(run.run_id, third.run_id)
        self.assertNotEqual(run.run_id, fourth.run_id)

    def test_different_occurrence_is_accepted(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        scheduled_rule = rule("two_runs")
        store.save_rule(scheduled_rule)
        first = scheduler.execute_rule_dry_run(scheduled_rule, datetime(2026, 9, 8, 9, 0, tzinfo=UTC))
        second = scheduler.execute_rule_dry_run(scheduled_rule, datetime(2026, 9, 9, 9, 0, tzinfo=UTC))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(len(store.list_runs("workspace_a")), 2)

    def test_disabled_rule_cannot_be_forced_to_execute(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        disabled = rule("disabled", enabled=False)
        store.save_rule(disabled)
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), [])
        with self.assertRaises(ContractError):
            scheduler.execute_rule_dry_run(disabled, datetime(2026, 9, 8, 9, 0, tzinfo=UTC))
        self.assertEqual(store.list_runs("workspace_a"), [])

    def test_workspace_isolation_and_update_enable_disable(self) -> None:
        store = InMemoryClawAutomationStore()
        item_a = rule("shared", "workspace_a")
        item_b = rule("other", "workspace_b")
        store.save_rule(item_a)
        store.save_rule(item_b)
        self.assertIsNone(store.get_rule("shared", "workspace_b"))
        with self.assertRaises(ContractError):
            store.save_rule(rule("shared", "workspace_b"))
        disabled = store.set_rule_enabled("workspace_a", "shared", False)
        self.assertFalse(disabled.enabled)
        enabled = store.set_rule_enabled("workspace_a", "shared", True)
        self.assertTrue(enabled.enabled)
        updated = rule("shared", "workspace_a", expression="30 9 * * *")
        store.update_rule(updated)
        self.assertEqual(store.get_rule("shared", "workspace_a").schedule.expression, "30 9 * * *")

    def test_existing_membership_projection_is_reused_and_expiry_fails_closed(self) -> None:
        now = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
        membership = TrustedWorkspaceMembershipProjection(
            membership_id="membership:owner",
            workspace_id="workspace_a",
            principal_ref="principal:user",
            role=WorkspaceRole.OWNER,
            authority_ref="control-plane:membership",
            issued_at=now.replace(hour=8),
            expires_at=now.replace(hour=10),
        )
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        item = rule("member")
        store.save_rule(item)
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", now, membership), [item])
        expired = TrustedWorkspaceMembershipProjection(
            membership_id="membership:expired",
            workspace_id="workspace_a",
            principal_ref="principal:user",
            role=WorkspaceRole.OWNER,
            authority_ref="control-plane:membership",
            issued_at=now.replace(hour=7),
            expires_at=now.replace(hour=8),
        )
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", now, expired), [])
        with self.assertRaises(ContractError):
            scheduler.evaluate_due_rules("workspace_b", now, membership)

    def test_next_occurrence_is_stable_and_timezone_aware(self) -> None:
        scheduler = FakeClawScheduler(InMemoryClawAutomationStore())
        item = rule("next", kind=ClawScheduleKind.CRON, expression="30 9 * * *")
        after = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
        first = scheduler.compute_next_occurrence(item, after)
        second = scheduler.compute_next_occurrence(item, after)
        self.assertEqual(first, second)
        self.assertEqual(first, datetime(2026, 9, 8, 9, 30, tzinfo=UTC))

    @unittest.skipUnless(ZoneInfo is not None, "zoneinfo unavailable on this runner")
    def test_cron_dst_fold_returns_both_distinct_instants(self) -> None:
        try:
            ZoneInfo("America/New_York")
        except Exception:
            self.skipTest("America/New_York timezone data unavailable on this runner")
        scheduler = FakeClawScheduler(InMemoryClawAutomationStore())
        item = rule("dst", expression="30 1 * * *", schedule_timezone="America/New_York")
        before_fold = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
        first = scheduler.compute_next_occurrence(item, before_fold)
        second = scheduler.compute_next_occurrence(item, first)
        self.assertEqual(first, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
        self.assertEqual(second, datetime(2026, 11, 1, 6, 30, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
