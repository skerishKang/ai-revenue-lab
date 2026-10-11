"""#2833 S2F5A — the durable tick claims a PENDING occurrence.

This module pins the child slice that removed fake completion from the durable /
background-trigger source path:

```text
trusted trigger -> existing trigger boundary -> existing ClawAutomationTickRuntime
                 -> existing occurrence_key dedup/claim
                 -> one ClawScheduledRun(status=PENDING, output=None, completed_at=None)
                 -> STOP
```

What is asserted here:

* the tick CLAIMS an occurrence; it never completes one;
* the claimed row is ``PENDING`` with ``output=None``, ``completed_at=None``,
  no ``error_message`` and no proposal row on either store backend;
* the run id stays the pre-existing occurrence-derived ``sched_run_<digest>``,
  which is the SAME id the existing canonical helper derives — so a claimed row
  can later be consumed by the existing execution bridge without a second run id;
* ``record_run`` remains the only claim authority and is called exactly once per
  claimed occurrence;
* the tick never reaches the reference completion helper
  (``FakeClawScheduler.execute_rule_dry_run``), by call-spy AND by source
  inspection;
* duplicate ticks / restarts create no second run and never promote the claim to
  a terminal status;
* disabled rules and uncovered membership windows claim nothing;
* the explicit fake/reference path keeps its own COMPLETED + DRAFT/proposal
  behaviour for callers that ask for it.

Non-goals proven by absence, not by assertion order: no P01 dispatch, no owner
resolution, no History write, no Task/Alert write, no cloud cron registration,
no provider call, no sandbox allocation, no external send.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import os
import tempfile
import unittest

from kagent.claw_automation import (
    DURABLE_TICK_CLAIMS_PENDING_OCCURRENCE,
    DURABLE_TICK_REFERENCE_SCHEDULER_IS_COMPLETION_AUTHORITY,
    DURABLE_TICK_SYNTHETIC_COMPLETION,
    PRODUCTION_SCHEDULER_ACTIVATION,
    REAL_BACKGROUND_TRIGGER,
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRunStatus,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    _derived_occurrence_id,
    canonical_claw_run_for_occurrence,
    occurrence_key,
    project_canonical_status,
)
from kagent.contracts import ClawRunStatus
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

UTC = timezone.utc
WHEN = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
WORKSPACE = "workspace_a"
REVISION = "a" * 40


def make_rule(
    rule_id: str,
    workspace_id: str = WORKSPACE,
    *,
    expression: str = "0 9 * * *",
    enabled: bool = True,
    execution_intent: ClawAutomationExecutionIntent | None = None,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, expression, "UTC"),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        execution_intent=execution_intent,
    )


def membership(
    workspace_id: str = WORKSPACE,
    *,
    at: datetime = WHEN,
    issued_offset_hours: int = -1,
    expires_offset_hours: int = 1,
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id="membership:tick-claim",
        workspace_id=workspace_id,
        principal_ref="principal:user",
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=at + timedelta(hours=issued_offset_hours),
        expires_at=at + timedelta(hours=expires_offset_hours),
    )


class SqliteFileFactory:
    """Per-instance temp-file SQLite store, so durability is a real file."""

    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "claw_tick_claim.db")

    def __call__(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def reopen(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        try:
            os.remove(self.db_path)
        except OSError:  # pragma: no cover - best effort temp cleanup
            pass


class PendingClaimTests(unittest.TestCase):
    """The claim itself: PENDING, output-free, existing run id, one write."""

    def setUp(self) -> None:
        self._factory = SqliteFileFactory()
        self.addCleanup(self._factory.cleanup)

    def _factories(self):
        yield (lambda: InMemoryClawAutomationStore(), False)
        yield (self._factory, True)

    def test_tick_claims_pending_occurrence_with_no_output(self) -> None:
        for make_store, is_sqlite in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("claims"))
                receipt = ClawAutomationTickRuntime(store).tick(
                    workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
                )

                self.assertEqual(len(receipt.created_run_ids), 1)
                claimed = store.get_run(receipt.created_run_ids[0], WORKSPACE)
                self.assertIsNotNone(claimed)
                self.assertEqual(claimed.status, ClawScheduledRunStatus.PENDING)
                self.assertIsNone(claimed.output)
                self.assertIsNone(claimed.completed_at)
                self.assertIsNone(claimed.error_message)
                self.assertEqual(claimed.workspace_id, WORKSPACE)
                self.assertEqual(claimed.rule_id, "claims")
                self.assertEqual(claimed.scheduled_time, WHEN)
                # ``started_at`` records the CLAIM instant, never that execution
                # began: the row is PENDING and this kernel starts nothing.
                self.assertEqual(claimed.started_at, WHEN)
                self.assertNotEqual(claimed.status, ClawScheduledRunStatus.COMPLETED)
                self.assertEqual(store.list_proposals(WORKSPACE), [])
                if is_sqlite:
                    store._db.close()

    def test_claimed_run_id_is_the_existing_occurrence_derived_id(self) -> None:
        store = InMemoryClawAutomationStore()
        rule = make_rule("id_reuse")
        store.save_rule(rule)
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        claimed = store.get_run_for_occurrence(
            occurrence_key(WORKSPACE, "id_reuse", WHEN), WORKSPACE
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.run_id, receipt.created_run_ids[0])
        self.assertEqual(
            claimed.run_id,
            _derived_occurrence_id("sched_run", WORKSPACE, "id_reuse", WHEN),
        )
        self.assertTrue(claimed.run_id.startswith("sched_run_"))

    def test_claimed_run_id_is_the_existing_canonical_scheduled_run_id(self) -> None:
        """No second run id: the claim reuses the canonical S2F2 derivation.

        The existing canonical helper derives ``sched_run_<digest>`` from the
        occurrence identity; the claimed row must carry exactly that id so the
        existing execution bridge can consume it later without remapping.
        """

        store = InMemoryClawAutomationStore()
        rule = make_rule(
            "canonical_id",
            execution_intent=ClawAutomationExecutionIntent(
                task="정기 실행 결과를 보고해줘",
                repository_ref="skerishKang/ai-revenue-lab",
                exact_revision=REVISION,
            ),
        )
        store.save_rule(rule)
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        canonical, _intent = canonical_claw_run_for_occurrence(rule, WHEN)
        self.assertEqual(receipt.created_run_ids, (canonical.run_id,))

    def test_claim_goes_through_the_single_existing_record_run_authority(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("record_spy"))
        seen: list[object] = []
        original = store.record_run

        def spy(run):
            seen.append(run)
            return original(run)

        store.record_run = spy  # type: ignore[method-assign]
        ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        self.assertEqual(len(seen), 1, "exactly one claim write per occurrence")
        self.assertEqual(seen[0].status, ClawScheduledRunStatus.PENDING)
        self.assertIsNone(seen[0].output)
        self.assertIsNone(seen[0].completed_at)

    def test_sqlite_row_is_pending_with_null_output_and_zero_proposals(self) -> None:
        store = SqliteFileFactory()()
        self.addCleanup(store._db.close)
        store.save_rule(make_rule("raw_row"))
        ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        row = store._db.execute(
            "SELECT status, completed_at, output, error_message FROM claw_runs"
        ).fetchone()
        self.assertEqual(row[0], ClawScheduledRunStatus.PENDING.value)
        self.assertIsNone(row[1])
        self.assertIsNone(row[2])
        self.assertIsNone(row[3])
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_proposals").fetchone()[0], 0
        )
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 1
        )


class NoFakeCompletionTests(unittest.TestCase):
    """The reference completion helper must not be the durable runtime's authority."""

    def test_tick_never_calls_the_reference_dry_run_helper(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("dry_run_spy"))
        calls = {"n": 0}
        original = FakeClawScheduler.execute_rule_dry_run

        def spy(self, *args, **kwargs):  # pragma: no cover - must never run
            calls["n"] += 1
            raise AssertionError(
                "the durable tick must not use the reference completion helper"
            )

        FakeClawScheduler.execute_rule_dry_run = spy  # type: ignore[method-assign]
        try:
            receipt = ClawAutomationTickRuntime(store).tick(
                workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
            )
        finally:
            FakeClawScheduler.execute_rule_dry_run = original  # type: ignore[method-assign]

        self.assertEqual(calls["n"], 0)
        self.assertEqual(len(receipt.created_run_ids), 1)
        self.assertEqual(store.list_proposals(WORKSPACE), [])

    @staticmethod
    def _executing_source() -> str:
        """Source of the two functions that actually run a claim (no docstrings).

        The class docstring is allowed to *describe* the reference helper and the
        absent authorities; what must be code-free of them is the executable body.
        """

        import kagent.claw_automation as module

        runtime = module.ClawAutomationTickRuntime
        return inspect.getsource(runtime.tick) + inspect.getsource(
            runtime._claim_pending_occurrence
        )

    def test_tick_source_does_not_reference_the_reference_helper(self) -> None:
        executing_source = self._executing_source()
        self.assertNotIn("execute_rule_dry_run", executing_source)
        self.assertNotIn("FakeClawScheduler", executing_source)
        self.assertNotIn("COMPLETED", executing_source)

    def test_tick_source_names_no_later_authority(self) -> None:
        """No P01 / owner / History / Task-Alert authority is reached from here."""

        executing_source = self._executing_source().lower()
        for forbidden in (
            "p01",
            "owner_resolution",
            "history",
            "task_alert",
            "sandbox",
            "cron",
            "smtplib",
            "requests",
            "httpx",
            "urllib",
            "socket",
            "subprocess",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), executing_source)

    def test_reference_path_still_completes_explicitly_for_its_own_callers(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        item = make_rule("reference_kept")
        store.save_rule(item)
        run = FakeClawScheduler(store).execute_rule_dry_run(item, WHEN, membership())

        self.assertEqual(run.status, ClawScheduledRunStatus.COMPLETED)
        self.assertIsNotNone(run.output)
        self.assertIn("DRAFT", run.output.content)
        self.assertEqual(run.completed_at, WHEN)
        self.assertEqual(len(store.list_proposals(WORKSPACE)), 1)

    def test_module_flags_report_no_synthetic_completion(self) -> None:
        self.assertTrue(DURABLE_TICK_CLAIMS_PENDING_OCCURRENCE)
        self.assertFalse(DURABLE_TICK_SYNTHETIC_COMPLETION)
        self.assertFalse(DURABLE_TICK_REFERENCE_SCHEDULER_IS_COMPLETION_AUTHORITY)
        self.assertFalse(PRODUCTION_SCHEDULER_ACTIVATION)
        self.assertFalse(REAL_BACKGROUND_TRIGGER)


class DedupAndIdempotencyTests(unittest.TestCase):
    """One occurrence, one claim — a retry must not invent a second one."""

    def setUp(self) -> None:
        self._factory = SqliteFileFactory()
        self.addCleanup(self._factory.cleanup)

    def test_second_tick_creates_no_second_run_and_keeps_pending(self) -> None:
        store = self._factory()
        self.addCleanup(store._db.close)
        store.save_rule(make_rule("retry"))
        runtime = ClawAutomationTickRuntime(store)

        first = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        second = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        self.assertEqual(len(first.created_run_ids), 1)
        self.assertEqual(second.created_run_ids, ())
        self.assertEqual(second.due_count, 0)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 1
        )
        # The replay must not promote the claim to a terminal row either.
        claimed = store.get_run(first.created_run_ids[0], WORKSPACE)
        self.assertEqual(claimed.status, ClawScheduledRunStatus.PENDING)
        self.assertIsNone(claimed.output)
        self.assertIsNone(claimed.completed_at)

    def test_restart_keeps_the_pending_claim_and_creates_no_second_run(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("restart"))
        first = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(len(first.created_run_ids), 1)
        store._db.close()

        reopened = self._factory.reopen()
        self.addCleanup(reopened._db.close)
        replay = ClawAutomationTickRuntime(reopened).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        self.assertEqual(replay.created_run_ids, ())
        self.assertEqual(len(reopened.list_runs(WORKSPACE)), 1)
        survived = reopened.get_run(first.created_run_ids[0], WORKSPACE)
        self.assertEqual(survived.status, ClawScheduledRunStatus.PENDING)
        self.assertIsNone(survived.output)
        self.assertIsNone(survived.completed_at)
        self.assertEqual(reopened.list_proposals(WORKSPACE), [])

    def test_two_rules_same_instant_claim_two_distinct_pending_runs(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("alpha"))
        store.save_rule(make_rule("beta"))
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        self.assertEqual(len(receipt.created_run_ids), 2)
        self.assertEqual(len(set(receipt.created_run_ids)), 2)
        runs = store.list_runs(WORKSPACE)
        self.assertEqual({run.status for run in runs}, {ClawScheduledRunStatus.PENDING})
        self.assertEqual([run.output for run in runs], [None, None])

    def test_raw_occurrence_claim_points_at_the_pending_run(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("claim_row"))
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        key = occurrence_key(WORKSPACE, "claim_row", WHEN)
        claimed_id = store._db.execute(
            "SELECT run_id FROM claw_occurrences WHERE occurrence_key = ?", (key,)
        ).fetchone()[0]
        self.assertEqual(claimed_id, receipt.created_run_ids[0])
        self.assertEqual(
            store._db.execute(
                "SELECT COUNT(*) FROM claw_occurrences o "
                "LEFT JOIN claw_runs r ON r.run_id = o.run_id WHERE r.run_id IS NULL"
            ).fetchone()[0],
            0,
        )


class FailClosedClaimTests(unittest.TestCase):
    """Nothing is claimed without a rule that may run and a covering projection."""

    def test_disabled_rule_claims_nothing(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("disabled", enabled=False))
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(store.list_runs(WORKSPACE), [])
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 0
        )

    def test_expired_membership_claims_nothing(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("expired"))
        expired = membership(issued_offset_hours=-2, expires_offset_hours=-1)
        self.assertFalse(expired.valid_at(WHEN))

        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=expired
        )

        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(store.list_runs(WORKSPACE), [])
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 0
        )

    def test_not_yet_valid_membership_claims_nothing(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("future"))
        future = membership(issued_offset_hours=1, expires_offset_hours=2)
        self.assertFalse(future.valid_at(WHEN))

        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=future
        )

        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(
            store._db.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 0
        )

    def test_claimed_status_is_the_existing_queued_projection(self) -> None:
        """The claim invents no new status vocabulary: QUEUED projects to PENDING."""

        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("status_vocabulary"))
        receipt = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )

        claimed = store.get_run(receipt.created_run_ids[0], WORKSPACE)
        self.assertIs(claimed.status, ClawScheduledRunStatus.PENDING)
        self.assertIs(
            project_canonical_status(ClawRunStatus.QUEUED), claimed.status
        )


if __name__ == "__main__":
    unittest.main()
