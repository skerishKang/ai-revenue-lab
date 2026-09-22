"""#2833 S2F4A bounded terminal-output attachment contract tests.

This slice extends the existing scheduled-run projection update path only.
record_run remains the occurrence-claim authority; no new row, claim, table,
column, migration, scheduler, provider call, History write, or Task/Alert write
is introduced here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from kagent.claw_automation import (
    ClawApprovalGate,
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawNotificationChannel,
    ClawNotificationProposal,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
DONE = NOW + timedelta(minutes=1)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_output_attach"
RUN_ID = "sched_run_" + "a" * 64


def scheduled_run(
    *,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
    output: ClawAutomationOutput | None = None,
) -> ClawScheduledRun:
    terminal = status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
    return ClawScheduledRun(
        run_id=RUN_ID,
        workspace_id=WORKSPACE,
        rule_id=RULE_ID,
        status=status,
        scheduled_time=NOW,
        started_at=NOW,
        completed_at=DONE if terminal else None,
        output=output,
        error_message="failed" if status is ClawScheduledRunStatus.FAILED else None,
    )


def automation_output(
    *,
    output_id: str = "output_a",
    workspace_id: str = WORKSPACE,
    title: str = "Automation report",
    content: str = "bounded result",
) -> ClawAutomationOutput:
    return ClawAutomationOutput(
        output_id=output_id,
        workspace_id=workspace_id,
        output_type=ClawAutomationOutputType.REPORT,
        title=title,
        content=content,
    )


def notification_proposal(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
) -> ClawNotificationProposal:
    return ClawNotificationProposal(
        proposal_id="proposal_a",
        workspace_id=workspace_id,
        rule_id=rule_id,
        channel=ClawNotificationChannel.WEB_ALERT_INBOX,
        title="Proposal",
        summary="bounded proposal",
        approval_gate=ClawApprovalGate(
            approval_required=False,
            reason="",
            suggested_action="",
        ),
        created_at=NOW,
    )


class StoreMatrixMixin:
    def stores(self):
        return (
            ("memory", InMemoryClawAutomationStore()),
            ("sqlite", SqliteClawAutomationStore(":memory:")),
        )


class TerminalOutputAttachTests(StoreMatrixMixin, unittest.TestCase):
    def test_pending_row_can_complete_and_attach_output_once(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                updated = store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                    output=output,
                )
                self.assertEqual(updated.status, ClawScheduledRunStatus.COMPLETED)
                self.assertEqual(updated.completed_at, DONE)
                self.assertEqual(updated.output, output)
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    def test_exact_same_output_retry_is_idempotent(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                first = store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                    output=output,
                )
                second = store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                    output=output,
                )
                self.assertEqual(second, first)
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    def test_different_output_cannot_replace_attached_output(self) -> None:
        first_output = automation_output()
        replacement = automation_output(output_id="output_b", content="different")
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                    output=first_output,
                )
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.COMPLETED,
                        completed_at=DONE,
                        output=replacement,
                    )
                stored = store.get_run(RUN_ID, WORKSPACE)
                self.assertIsNotNone(stored)
                self.assertEqual(stored.output, first_output)

    def test_nonterminal_projection_cannot_attach_output(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.RUNNING,
                        completed_at=None,
                        output=output,
                    )
                stored = store.get_run(RUN_ID, WORKSPACE)
                self.assertEqual(stored.status, ClawScheduledRunStatus.PENDING)
                self.assertIsNone(stored.output)

    def test_foreign_workspace_output_is_rejected(self) -> None:
        output = automation_output(workspace_id=OTHER_WORKSPACE)
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.COMPLETED,
                        completed_at=DONE,
                        output=output,
                    )
                stored = store.get_run(RUN_ID, WORKSPACE)
                self.assertEqual(stored.status, ClawScheduledRunStatus.PENDING)
                self.assertIsNone(stored.output)

    def test_malformed_proposal_payload_is_rejected_before_mutation(self) -> None:
        output = ClawAutomationOutput(
            output_id="output_bad_proposal",
            workspace_id=WORKSPACE,
            output_type=ClawAutomationOutputType.REPORT,
            title="Automation report",
            content="bounded result",
            proposals=("not-a-proposal",),  # type: ignore[arg-type]
        )
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.COMPLETED,
                        completed_at=DONE,
                        output=output,
                    )
                stored = store.get_run(RUN_ID, WORKSPACE)
                self.assertEqual(stored.status, ClawScheduledRunStatus.PENDING)
                self.assertIsNone(stored.output)

    def test_foreign_proposal_scope_is_rejected_before_mutation(self) -> None:
        output = ClawAutomationOutput(
            output_id="output_foreign_proposal",
            workspace_id=WORKSPACE,
            output_type=ClawAutomationOutputType.REPORT,
            title="Automation report",
            content="bounded result",
            proposals=(notification_proposal(workspace_id=OTHER_WORKSPACE),),
        )
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run())
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.COMPLETED,
                        completed_at=DONE,
                        output=output,
                    )
                stored = store.get_run(RUN_ID, WORKSPACE)
                self.assertEqual(stored.status, ClawScheduledRunStatus.PENDING)
                self.assertIsNone(stored.output)

    def test_failed_and_cancelled_rows_cannot_resurrect_with_output(self) -> None:
        output = automation_output()
        for terminal in (
            ClawScheduledRunStatus.FAILED,
            ClawScheduledRunStatus.CANCELLED,
        ):
            for label, store in self.stores():
                with self.subTest(status=terminal, store=label):
                    store.record_run(scheduled_run(status=terminal))
                    with self.assertRaises(ContractError):
                        store.update_run_projection(
                            run_id=RUN_ID,
                            workspace_id=WORKSPACE,
                            rule_id=RULE_ID,
                            scheduled_time=NOW,
                            status=ClawScheduledRunStatus.COMPLETED,
                            completed_at=DONE,
                            output=output,
                        )
                    stored = store.get_run(RUN_ID, WORKSPACE)
                    self.assertEqual(stored.status, terminal)
                    self.assertIsNone(stored.output)

    def test_completed_row_without_output_allows_one_time_backfill(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(scheduled_run(status=ClawScheduledRunStatus.COMPLETED))
                updated = store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                    output=output,
                )
                self.assertEqual(updated.output, output)
                self.assertEqual(updated.status, ClawScheduledRunStatus.COMPLETED)

    def test_status_only_update_preserves_existing_output(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                store.record_run(
                    scheduled_run(
                        status=ClawScheduledRunStatus.COMPLETED,
                        output=output,
                    )
                )
                updated = store.update_run_projection(
                    run_id=RUN_ID,
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=NOW,
                    status=ClawScheduledRunStatus.COMPLETED,
                    completed_at=DONE,
                )
                self.assertEqual(updated.output, output)

    def test_missing_run_never_creates_or_claims_row(self) -> None:
        output = automation_output()
        for label, store in self.stores():
            with self.subTest(store=label):
                with self.assertRaises(ContractError):
                    store.update_run_projection(
                        run_id=RUN_ID,
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=NOW,
                        status=ClawScheduledRunStatus.COMPLETED,
                        completed_at=DONE,
                        output=output,
                    )
                self.assertEqual(store.list_runs(WORKSPACE), [])


class DurableOutputAttachTests(unittest.TestCase):
    def test_sqlite_reopen_preserves_attached_output(self) -> None:
        output = automation_output()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "automation-output.db")
            store = SqliteClawAutomationStore(path)
            store.record_run(scheduled_run())
            store.update_run_projection(
                run_id=RUN_ID,
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=NOW,
                status=ClawScheduledRunStatus.COMPLETED,
                completed_at=DONE,
                output=output,
            )

            reopened = SqliteClawAutomationStore(path)
            stored = reopened.get_run(RUN_ID, WORKSPACE)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, ClawScheduledRunStatus.COMPLETED)
            self.assertEqual(stored.completed_at, DONE)
            self.assertEqual(stored.output, output)


if __name__ == "__main__":
    unittest.main()
