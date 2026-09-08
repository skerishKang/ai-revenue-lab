from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.claw_automation import (
    ClawApprovalGate,
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawDaypart,
    ClawNotificationChannel,
    ClawNotificationPreference,
    ClawNotificationProposal,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
)
from kagent.contracts import ContractError


class ClawAutomationTests(unittest.TestCase):
    def test_workspace_scoped_rule_creation(self) -> None:
        rule = ClawAutomationRule(
            rule_id="rule_001",
            workspace_id="ws_main",
            name="미처리 견적서 일일 점검",
            schedule=ClawScheduleExpression(
                kind=ClawScheduleKind.DAYPART,
                expression="morning",
            ),
            target_source=ClawAutomationTarget.TASKS,
            output_type=ClawAutomationOutputType.ALERT,
            enabled=True,
        )
        self.assertEqual(rule.workspace_id, "ws_main")
        self.assertEqual(rule.schedule.expression, "morning")
        self.assertTrue(rule.enabled)

    def test_disabled_rules_are_excluded_by_scheduler(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        now = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)

        enabled_rule = ClawAutomationRule(
            rule_id="rule_enabled",
            workspace_id="ws_1",
            name="활성 규칙",
            schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
            target_source=ClawAutomationTarget.INBOX,
            output_type=ClawAutomationOutputType.REPORT,
            enabled=True,
        )
        disabled_rule = ClawAutomationRule(
            rule_id="rule_disabled",
            workspace_id="ws_1",
            name="비활성 규칙",
            schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
            target_source=ClawAutomationTarget.INBOX,
            output_type=ClawAutomationOutputType.REPORT,
            enabled=False,
        )
        store.save_rule(enabled_rule)
        store.save_rule(disabled_rule)

        due = scheduler.evaluate_due_rules("ws_1", now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].rule_id, "rule_enabled")

    def test_schedule_expression_validation(self) -> None:
        # Valid daypart
        expr = ClawScheduleExpression(ClawScheduleKind.DAYPART, "evening")
        self.assertEqual(expr.expression, "evening")

        # Invalid daypart fails closed
        with self.assertRaises(ContractError):
            ClawScheduleExpression(ClawScheduleKind.DAYPART, "midnight_snack")

    def test_notification_channel_tiers_and_availability(self) -> None:
        self.assertEqual(ClawNotificationChannel.WEB_ALERT_INBOX.availability_tier, "tier1_active")
        self.assertEqual(ClawNotificationChannel.EMAIL.availability_tier, "tier2_deferred_or_gated")
        self.assertEqual(ClawNotificationChannel.TELEGRAM.availability_tier, "tier3_later")
        self.assertEqual(ClawNotificationChannel.DISCORD.availability_tier, "tier3_later")
        self.assertEqual(ClawNotificationChannel.KAKAO.availability_tier, "tier4_later_policy_gated")
        self.assertEqual(ClawNotificationChannel.SMS.availability_tier, "tier4_later_policy_gated")

    def test_fake_scheduler_execution_and_approval_gate(self) -> None:
        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        now = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)

        rule = ClawAutomationRule(
            rule_id="rule_quote_check",
            workspace_id="ws_auto",
            name="견적서 납기 점검",
            schedule=ClawScheduleExpression(ClawScheduleKind.INTERVAL, "daily"),
            target_source=ClawAutomationTarget.TASKS,
            output_type=ClawAutomationOutputType.ALERT,
        )
        store.save_rule(rule)

        run = scheduler.execute_rule_dry_run(rule, now)
        self.assertEqual(run.status, ClawScheduledRunStatus.COMPLETED)
        self.assertIsNotNone(run.output)
        self.assertEqual(run.output.output_type, ClawAutomationOutputType.ALERT)

        # Verify proposal requires approval
        self.assertTrue(len(run.output.proposals) > 0)
        proposal = run.output.proposals[0]
        self.assertTrue(proposal.approval_gate.approval_required)
        self.assertIn("수동 승인", proposal.approval_gate.suggested_action)

        # Verify safe projection asserts zero automatic side-effects
        safe = proposal.safe_dict()
        self.assertFalse(safe["auto_send"])
        self.assertFalse(safe["auto_order"])
        self.assertFalse(safe["auto_memory_confirm"])
        self.assertTrue(safe["approval_required"])

    def test_output_types_strictly_confined(self) -> None:
        allowed = {ot.value for ot in ClawAutomationOutputType}
        self.assertEqual(allowed, {"alert", "draft", "report", "task_proposal"})

    def test_recipient_ref_rejects_credential_leak(self) -> None:
        with self.assertRaises(ContractError):
            ClawNotificationPreference(
                channel=ClawNotificationChannel.EMAIL,
                recipient_ref="user-api-key: gho_secrettoken1234567890abcdef1234567890",
            )


if __name__ == "__main__":
    unittest.main()
