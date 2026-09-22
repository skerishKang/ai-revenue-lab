"""#2833 S2F2 lifecycle bridge foundation tests.

The bridge is the same-run-id identity between a scheduled occurrence and the
canonical ``ClawRun`` state machine, plus a bounded projection-update path that
never claims, never inserts, and never mutates the occurrence identity.

Nothing here dispatches: no P01 helper is called, owner resolution is not
wired, and History/Task/Alert stores are never written. The existing
dry-run/tick behaviour is asserted unchanged.

The KAgent suite runs under ``unittest`` discovery, so these tests deliberately
use no third-party test dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ClawScheduleExpression,
    ClawScheduleKind,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    canonical_claw_run_for_occurrence,
    canonical_task_intent_for_occurrence,
    occurrence_key,
    project_canonical_status,
    _derived_occurrence_id,
)
from kagent.contracts import ClawRunStatus, ContractError, ExecutionMode
from kagent.runs import ClawRun, InMemoryRunStore, RunStateError
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
SCHED = NOW.replace(second=0, microsecond=0)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_bridge_1"
REVISION = "a" * 40
INTENT_TASK = "Summarize the queued alerts for the on-call rotation"
REPO = "repo:padiem/ai-revenue-lab"
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")
MEMBERSHIP = TrustedWorkspaceMembershipProjection(
    membership_id="membership:owner",
    workspace_id=WORKSPACE,
    principal_ref="principal:user",
    role=WorkspaceRole.OWNER,
    authority_ref="control-plane:membership",
    issued_at=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
)
STATUS_MAP = (
    (ClawRunStatus.QUEUED, ClawScheduledRunStatus.PENDING),
    (ClawRunStatus.PREPARING, ClawScheduledRunStatus.RUNNING),
    (ClawRunStatus.RUNNING, ClawScheduledRunStatus.RUNNING),
    (ClawRunStatus.WAITING_APPROVAL, ClawScheduledRunStatus.RUNNING),
    (ClawRunStatus.COMPLETED, ClawScheduledRunStatus.COMPLETED),
    (ClawRunStatus.FAILED, ClawScheduledRunStatus.FAILED),
    (ClawRunStatus.CANCELLED, ClawScheduledRunStatus.CANCELLED),
)


def make_rule(*, rule_id=RULE_ID, workspace_id=WORKSPACE, execution_intent=None, enabled=True):
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Bridge rule display label",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
        execution_intent=execution_intent,
    )


def execution_intent() -> ClawAutomationExecutionIntent:
    return ClawAutomationExecutionIntent(
        task=INTENT_TASK,
        repository_ref=REPO,
        exact_revision=REVISION,
    )


def derived_run_id(*, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled=SCHED) -> str:
    return _derived_occurrence_id("sched_run", workspace_id, rule_id, scheduled)


def projection_row(
    *,
    run_id=None,
    workspace_id=WORKSPACE,
    rule_id=RULE_ID,
    scheduled=SCHED,
    status=ClawScheduledRunStatus.COMPLETED,
) -> ClawScheduledRun:
    return ClawScheduledRun(
        run_id=run_id or derived_run_id(workspace_id=workspace_id, rule_id=rule_id),
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=status,
        scheduled_time=scheduled,
        started_at=scheduled,  # STARTED_AT_LEGACY_SLOT_MARKER
        completed_at=scheduled if status is ClawScheduledRunStatus.COMPLETED else None,
    )


class SqliteFactory:
    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "lifecycle_bridge.db")

    def __call__(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def reopen(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        for path in (self.db_path, f"{self.db_path}-wal", f"{self.db_path}-shm"):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._dir)
        except OSError:
            pass


class BridgeTestBase(unittest.TestCase):
    """Provides both store backends without a third-party fixture library."""

    def stores(self):
        """Yield (label, store) for the in-memory and durable backends.

        The durable store's directory is cleaned up at test teardown (addCleanup),
        not while the store is still in use: on POSIX an early rmdir would break the
        open SQLite handle.
        """

        yield "inmemory", InMemoryClawAutomationStore()
        factory = SqliteFactory()
        self.addCleanup(factory.cleanup)
        yield "sqlite", factory()

    def each_store(self):
        return list(self.stores())


class CanonicalIntentTests(BridgeTestBase):
    def test_canonical_intent_maps_only_the_execution_intent(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        intent = canonical_task_intent_for_occurrence(rule, SCHED)

        self.assertEqual(intent.task, INTENT_TASK)
        self.assertEqual(intent.repository_ref, REPO)
        self.assertEqual(intent.execution_mode, ExecutionMode.CLOUD)
        self.assertEqual(intent.requested_revision, REVISION)
        self.assertEqual(intent.source_surface, "automation")
        # Display labels and closed enums are never reinterpreted as instructions.
        self.assertNotEqual(intent.task, rule.name)

    def test_canonical_task_id_is_deterministic_and_bounded(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        first = canonical_task_intent_for_occurrence(rule, SCHED)
        second = canonical_task_intent_for_occurrence(rule, SCHED)

        self.assertEqual(first.task_id, second.task_id)
        self.assertTrue(first.task_id.startswith("task_"))
        self.assertLessEqual(len(first.task_id), 128)
        other_instant = canonical_task_intent_for_occurrence(rule, SCHED + timedelta(minutes=1))
        self.assertNotEqual(other_instant.task_id, first.task_id)
        other_rule = make_rule(rule_id="rule_bridge_2", execution_intent=execution_intent())
        self.assertNotEqual(
            canonical_task_intent_for_occurrence(other_rule, SCHED).task_id, first.task_id
        )

    def test_canonical_task_id_is_not_a_dedup_authority(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        intent = canonical_task_intent_for_occurrence(rule, SCHED)

        self.assertNotEqual(intent.task_id, occurrence_key(WORKSPACE, RULE_ID, SCHED))
        self.assertNotEqual(intent.task_id, derived_run_id())

    def test_legacy_rule_without_intent_fails_closed(self) -> None:
        rule = make_rule(execution_intent=None)
        with self.assertRaises(ContractError) as raised:
            canonical_task_intent_for_occurrence(rule, SCHED)
        self.assertIn("execution intent", str(raised.exception))


class SameRunIdTests(BridgeTestBase):
    def test_canonical_run_reuses_the_scheduled_run_id(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        run, intent = canonical_claw_run_for_occurrence(rule, SCHED)

        self.assertEqual(run.run_id, derived_run_id())
        self.assertTrue(run.run_id.startswith("sched_run_"))
        self.assertNotEqual(intent.task_id, run.run_id)

    def test_canonical_run_container_is_queued_and_carries_the_intent(self) -> None:
        run, intent = canonical_claw_run_for_occurrence(
            make_rule(execution_intent=execution_intent()), SCHED
        )
        self.assertIsInstance(run, ClawRun)
        self.assertEqual(run.status, ClawRunStatus.QUEUED)
        self.assertEqual(run.intent.task_id, intent.task_id)
        self.assertEqual(run.intent.execution_mode, ExecutionMode.CLOUD)

    def test_two_calls_never_invent_a_second_run_id(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        first_run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
        second_run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
        self.assertEqual(first_run.run_id, second_run.run_id)
        self.assertEqual(first_run.run_id, derived_run_id())


class StatusProjectionTests(BridgeTestBase):
    def test_status_mapping_table(self) -> None:
        for canonical, projected in STATUS_MAP:
            with self.subTest(canonical=canonical):
                self.assertIs(project_canonical_status(canonical), projected)

    def test_status_mapping_refuses_unknown_values(self) -> None:
        with self.assertRaises(ContractError):
            project_canonical_status("not-a-status")


class ProjectionUpdateTests(BridgeTestBase):
    def test_non_terminal_update_clears_completed_at(self) -> None:
        for label, store in self.each_store():
            for status in (ClawScheduledRunStatus.PENDING, ClawScheduledRunStatus.RUNNING):
                with self.subTest(store=label, status=status):
                    store.record_run(projection_row())
                    updated = store.update_run_projection(
                        run_id=derived_run_id(),
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=SCHED,
                        status=status,
                        completed_at=None,
                    )
                    self.assertEqual(updated.status, status)
                    self.assertIsNone(updated.completed_at)

    def test_terminal_update_sets_completed_at(self) -> None:
        terminal_at = SCHED + timedelta(minutes=10)
        for label, store in self.each_store():
            for status in (
                ClawScheduledRunStatus.COMPLETED,
                ClawScheduledRunStatus.FAILED,
                ClawScheduledRunStatus.CANCELLED,
            ):
                with self.subTest(store=label, status=status):
                    store.record_run(projection_row())
                    updated = store.update_run_projection(
                        run_id=derived_run_id(),
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=SCHED,
                        status=status,
                        completed_at=terminal_at,
                    )
                    self.assertEqual(updated.status, status)
                    self.assertEqual(updated.completed_at, terminal_at)

    def test_failed_update_redacts_and_bounds_error_message(self) -> None:
        credential_laden = "boom: token=sk-liv…6789"
        store = InMemoryClawAutomationStore()
        store.record_run(projection_row())
        updated = store.update_run_projection(
            run_id=derived_run_id(),
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.FAILED,
            completed_at=SCHED + timedelta(minutes=5),
            error_message=credential_laden,
        )
        self.assertEqual(updated.status, ClawScheduledRunStatus.FAILED)
        self.assertLessEqual(len(updated.error_message), 1024)
        self.assertNotIn("sk-liv…6789", updated.error_message)

    def test_over_long_error_message_is_refused(self) -> None:
        store = InMemoryClawAutomationStore()
        store.record_run(projection_row())
        with self.assertRaises(ContractError) as raised:
            store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=ClawScheduledRunStatus.FAILED,
                completed_at=SCHED + timedelta(minutes=5),
                error_message="x" * 1200,
            )
        self.assertIn("exceeds", str(raised.exception))

    def test_error_message_on_non_failed_update_is_refused(self) -> None:
        store = InMemoryClawAutomationStore()
        store.record_run(projection_row())
        with self.assertRaises(ContractError) as raised:
            store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=ClawScheduledRunStatus.RUNNING,
                error_message="nope",
            )
        self.assertIn("error_message", str(raised.exception))

    def test_completed_at_on_non_terminal_update_is_refused(self) -> None:
        store = InMemoryClawAutomationStore()
        store.record_run(projection_row())
        with self.assertRaises(ContractError) as raised:
            store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=ClawScheduledRunStatus.PENDING,
                completed_at=SCHED + timedelta(minutes=3),
            )
        self.assertIn("completed_at", str(raised.exception))

    def test_update_missing_run_never_inserts(self) -> None:
        for label, store in self.each_store():
            with self.subTest(store=label):
                with self.assertRaises(ContractError) as raised:
                    store.update_run_projection(
                        run_id=derived_run_id(),
                        workspace_id=WORKSPACE,
                        rule_id=RULE_ID,
                        scheduled_time=SCHED,
                        status=ClawScheduledRunStatus.RUNNING,
                    )
                self.assertIn("existing scheduled run", str(raised.exception))
                self.assertEqual(store.list_runs(WORKSPACE), [])

    def test_update_cannot_mutate_identity(self) -> None:
        for label, store in self.each_store():
            with self.subTest(store=label):
                store.record_run(projection_row())
                original = store.get_run(derived_run_id(), WORKSPACE)
                cases = (
                    {"workspace_id": OTHER_WORKSPACE},
                    {"rule_id": "rule_bridge_2"},
                    {"scheduled_time": SCHED + timedelta(minutes=1)},
                )
                for case in cases:
                    with self.subTest(case=case):
                        with self.assertRaises(ContractError) as raised:
                            store.update_run_projection(
                                run_id=derived_run_id(),
                                workspace_id=case.get("workspace_id", WORKSPACE),
                                rule_id=case.get("rule_id", RULE_ID),
                                scheduled_time=case.get("scheduled_time", SCHED),
                                status=ClawScheduledRunStatus.RUNNING,
                            )
                        self.assertIn("projection update", str(raised.exception))
                # The stored row is byte-for-byte the original.
                self.assertEqual(store.get_run(derived_run_id(), WORKSPACE), original)

    def test_update_cannot_claim_a_new_occurrence(self) -> None:
        store = InMemoryClawAutomationStore()
        store.record_run(projection_row())
        before = dict(store._occurrences)
        with self.assertRaises(ContractError):
            store.update_run_projection(
                run_id=derived_run_id(workspace_id=OTHER_WORKSPACE, rule_id="rule_bridge_2"),
                workspace_id=OTHER_WORKSPACE,
                rule_id="rule_bridge_2",
                scheduled_time=SCHED,
                status=ClawScheduledRunStatus.RUNNING,
            )
        self.assertEqual(store._occurrences, before)

    def test_sqlite_reopen_keeps_the_updated_projection(self) -> None:
        factory = SqliteFactory()
        try:
            store = factory()
            store.record_run(projection_row())
            store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=ClawScheduledRunStatus.FAILED,
                completed_at=SCHED + timedelta(minutes=7),
                error_message="boom",
            )
            reopened_run = factory.reopen().get_run(derived_run_id(), WORKSPACE)
            self.assertEqual(reopened_run.status, ClawScheduledRunStatus.FAILED)
            self.assertEqual(reopened_run.completed_at, SCHED + timedelta(minutes=7))
            self.assertEqual(reopened_run.error_message, "boom")
        finally:
            factory.cleanup()


class OccurrenceClaimAuthorityTests(BridgeTestBase):
    def test_record_run_claims_once_and_never_clones(self) -> None:
        for label, store in self.each_store():
            with self.subTest(store=label):
                first = store.record_run(projection_row())
                again = store.record_run(
                    projection_row(status=ClawScheduledRunStatus.RUNNING)
                )
                self.assertEqual(first.run_id, derived_run_id())
                self.assertEqual(again.run_id, derived_run_id())
                # record_run stays the claim authority: re-recording the same
                # occurrence returns the stored row instead of overwriting it.
                self.assertEqual(again.status, ClawScheduledRunStatus.COMPLETED)
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)
                claimed = store.get_run_for_occurrence(
                    occurrence_key(WORKSPACE, RULE_ID, SCHED), WORKSPACE
                )
                self.assertEqual(claimed.run_id, derived_run_id())

    def test_duplicate_occurrence_creates_one_row_and_one_run_id(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        for label, store in self.each_store():
            with self.subTest(store=label):
                run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
                store.record_run(projection_row(run_id=run.run_id))
                again = store.record_run(
                    projection_row(run_id=run.run_id, status=ClawScheduledRunStatus.RUNNING)
                )
                self.assertEqual(again.run_id, run.run_id)
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    def test_inmemory_run_store_refuses_a_second_container_for_the_same_id(self) -> None:
        rule = make_rule(execution_intent=execution_intent())
        run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
        store = InMemoryRunStore()
        store.add(run)
        duplicate, _ = canonical_claw_run_for_occurrence(rule, SCHED)
        with self.assertRaises(RunStateError):
            store.add(duplicate)
        self.assertEqual(len(store), 1)
        self.assertEqual(store.get(run.run_id).run_id, run.run_id)


class LegacyBehaviourTests(BridgeTestBase):
    def test_legacy_dry_run_is_still_terminal_at_birth(self) -> None:
        scheduler = FakeClawScheduler(InMemoryClawAutomationStore())
        legacy = make_rule(execution_intent=None)
        run = scheduler.execute_rule_dry_run(legacy, SCHED, None)
        self.assertEqual(run.status, ClawScheduledRunStatus.COMPLETED)
        self.assertEqual(run.started_at, SCHED)
        self.assertEqual(run.scheduled_time, SCHED)
        self.assertEqual(run.completed_at, SCHED)

    def test_tick_behaviour_is_unchanged(self) -> None:
        scheduler_store = InMemoryClawAutomationStore()
        runtime = ClawAutomationTickRuntime(scheduler_store)
        scheduler_store.save_rule(make_rule(execution_intent=execution_intent()))

        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP
        )
        self.assertEqual(receipt.due_count, 1)
        self.assertEqual(len(receipt.created_run_ids), 1)
        recorded = scheduler_store.get_run(receipt.created_run_ids[0], WORKSPACE)
        self.assertEqual(recorded.run_id, receipt.created_run_ids[0])
        # A second tick for the same occurrence is deduplicated by the claim authority.
        second = runtime.tick(
            workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP
        )
        self.assertEqual(second.created_run_ids, ())
        self.assertEqual(len(scheduler_store.list_runs(WORKSPACE)), 1)


class DispatchSurfaceTests(BridgeTestBase):
    def test_s2f2_section_introduces_no_dispatch_or_owner_surface(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath(
            "src/kagent/claw_automation.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "create_claw_run(",
            "execute_p01_claw_task(",
            "run_p01_task(",
            "resolve_owner",
            "BackgroundDispatchRequest",
            "record_claw_run(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_bridge_contract_is_part_of_the_store_protocol(self) -> None:
        for store in (InMemoryClawAutomationStore(), SqliteClawAutomationStore(":memory:")):
            with self.subTest(store=type(store).__name__):
                self.assertTrue(hasattr(store, "update_run_projection"))
                self.assertTrue(callable(store.update_run_projection))
                self.assertTrue(hasattr(store, "record_run"))


if __name__ == "__main__":
    unittest.main()
