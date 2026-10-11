"""#2995 S2F6C — async tick/boundary persistence seam proofs.

NETWORK_FREE / SOURCE_ONLY: no cron registration, no Worker handler, no
provider call, no external send, no Production mutation. The awaited seam is
proven against a D1-shaped async store double whose reads and writes answer
ONLY through awaited statements (a forgotten ``await`` never executes the
statement, which the call log proves), and differentially against the
synchronous reference store so the two persistence applications cannot drift
into two scheduling authorities.
"""

from __future__ import annotations

import asyncio
import inspect
import unittest
from datetime import datetime, timedelta, timezone

from kagent.claw_automation import (
    DURABLE_TICK_RUNTIME,
    REAL_CLOUD_CRON_REGISTRATION,
    REAL_BACKGROUND_TRIGGER,
    TICK_RUNTIME_ASYNC_PERSISTENCE_SEAM,
    TICK_RUNTIME_REGISTERS_CLOUD_CRON,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickReceipt,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRunStatus,
    ContractError,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    _derived_occurrence_id,
    occurrence_key,
)
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
)
from kagent.workspace_visibility import (
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
)

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace_async"
OTHER_WORKSPACE = "workspace_other"


def _run(coro):
    return asyncio.run(coro)


def _rule(
    rule_id: str = "rule_async_1",
    *,
    enabled: bool = True,
    expression: str = "* * * * *",
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=WORKSPACE,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.CRON, expression=expression, timezone="UTC"
        ),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        owner_ref=f"own_{WORKSPACE}",
    )


def _membership(
    *,
    workspace_id: str = WORKSPACE,
    issued: timedelta = timedelta(hours=-1),
    expires: timedelta = timedelta(hours=1),
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id=f"mem_{workspace_id}",
        workspace_id=workspace_id,
        principal_ref="principal:user",
        role=WorkspaceRole.OWNER,
        authority_ref="authority:test",
        issued_at=NOW + issued,
        expires_at=NOW + expires,
    )


class AsyncD1ShapedStore:
    """D1-shaped async facade over the reference store.

    Every capability answers through a coroutine, and each coroutine body
    records its own execution in ``calls`` -- so a caller that forgets to await
    simply never runs the statement, which the log makes observable.
    """

    def __init__(self, inner: InMemoryClawAutomationStore) -> None:
        self.inner = inner
        self.calls: list[str] = []

    async def list_rules(self, workspace_id: str):
        self.calls.append("list_rules")
        return self.inner.list_rules(workspace_id)

    async def get_run_for_occurrence(self, key: str, workspace_id: str):
        self.calls.append("get_run_for_occurrence")
        return self.inner.get_run_for_occurrence(key, workspace_id)

    async def record_run(self, run):
        self.calls.append("record_run")
        return self.inner.record_run(run)


class RaisingListStore(AsyncD1ShapedStore):
    async def list_rules(self, workspace_id: str):
        self.calls.append("list_rules")
        raise RuntimeError("d1 unavailable")


class AsyncTickSeamTests(unittest.TestCase):
    # --- differential equivalence: ONE algorithm, two persistence shapes ----

    def test_atick_matches_tick_receipt_and_rows_exactly(self) -> None:
        sync_store = InMemoryClawAutomationStore()
        sync_store.save_rule(_rule())
        async_inner = InMemoryClawAutomationStore()
        async_inner.save_rule(_rule())
        async_store = AsyncD1ShapedStore(async_inner)

        sync_receipt = ClawAutomationTickRuntime(sync_store).tick(
            workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
        )
        async_receipt = _run(
            ClawAutomationTickRuntime(async_store).atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )

        self.assertEqual(sync_receipt, async_receipt)
        self.assertIsInstance(async_receipt, ClawAutomationTickReceipt)
        sync_rows = sync_store.list_runs(WORKSPACE)
        async_rows = async_inner.list_runs(WORKSPACE)
        self.assertEqual(len(sync_rows), 1)
        self.assertEqual(len(async_rows), 1)
        for field in (
            "run_id",
            "workspace_id",
            "rule_id",
            "status",
            "scheduled_time",
            "started_at",
            "completed_at",
            "output",
        ):
            self.assertEqual(
                getattr(sync_rows[0], field), getattr(async_rows[0], field), field
            )
        # Every async statement really executed: nothing was left un-awaited.
        self.assertIn("list_rules", async_store.calls)
        self.assertIn("record_run", async_store.calls)

    def test_atick_claim_is_occurrence_derived_and_pending(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule())
        receipt = _run(
            ClawAutomationTickRuntime(AsyncD1ShapedStore(inner)).atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )
        self.assertEqual(len(receipt.created_run_ids), 1)
        row = inner.list_runs(WORKSPACE)[0]
        self.assertEqual(
            row.run_id,
            _derived_occurrence_id("sched_run", WORKSPACE, _rule().rule_id, NOW),
        )
        self.assertEqual(row.status, ClawScheduledRunStatus.PENDING)
        self.assertIsNone(row.output)
        self.assertIsNone(row.completed_at)

    def test_atick_second_invocation_deduplicates_without_second_row(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule())
        store = AsyncD1ShapedStore(inner)
        runtime = ClawAutomationTickRuntime(store)
        first = _run(
            runtime.atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )
        second = _run(
            runtime.atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )
        self.assertEqual(len(first.created_run_ids), 1)
        self.assertEqual(second.created_run_ids, ())
        self.assertEqual(len(inner.list_runs(WORKSPACE)), 1)

        # Differential: the synchronous path reports the exact same second
        # invocation for the exact same store state (the existing occurrence is
        # filtered before the claim loop, so due_count and dedup both stay 0).
        sync_store = InMemoryClawAutomationStore()
        sync_store.save_rule(_rule())
        sync_runtime = ClawAutomationTickRuntime(sync_store)
        sync_first = sync_runtime.tick(
            workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
        )
        sync_second = sync_runtime.tick(
            workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
        )
        self.assertEqual(first, sync_first)
        self.assertEqual(second, sync_second)
        self.assertEqual(second.deduplicated_count, sync_second.deduplicated_count)
        self.assertEqual(len(sync_store.list_runs(WORKSPACE)), 1)

    # --- fail-closed membership and rule semantics --------------------------

    def test_atick_expired_membership_writes_nothing(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule())
        store = AsyncD1ShapedStore(inner)
        receipt = _run(
            ClawAutomationTickRuntime(store).atick(
                workspace_id=WORKSPACE,
                current_time=NOW,
                membership=_membership(
                    issued=timedelta(hours=-5), expires=timedelta(hours=-1)
                ),
            )
        )
        self.assertEqual(receipt.due_count, 0)
        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(store.calls, [])
        self.assertEqual(inner.list_runs(WORKSPACE), [])

    def test_atick_requires_a_trusted_matching_membership(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule())
        store = AsyncD1ShapedStore(inner)
        runtime = ClawAutomationTickRuntime(store)
        with self.assertRaises(ContractError):
            _run(
                runtime.atick(
                    workspace_id=WORKSPACE,
                    current_time=NOW,
                    membership=None,  # type: ignore[arg-type]
                )
            )
        with self.assertRaises(ContractError):
            _run(
                runtime.atick(
                    workspace_id=WORKSPACE,
                    current_time=NOW,
                    membership=_membership(workspace_id=OTHER_WORKSPACE),
                )
            )
        self.assertEqual(store.calls, [])

    def test_atick_disabled_rule_never_claims(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule(enabled=False))
        store = AsyncD1ShapedStore(inner)
        receipt = _run(
            ClawAutomationTickRuntime(store).atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )
        self.assertEqual(receipt.due_count, 0)
        self.assertNotIn("record_run", store.calls)
        self.assertEqual(inner.list_runs(WORKSPACE), [])

    def test_atick_non_due_rule_is_not_executed(self) -> None:
        inner = InMemoryClawAutomationStore()
        inner.save_rule(_rule(rule_id="rule_not_due", expression="30 8 * * *"))
        store = AsyncD1ShapedStore(inner)
        receipt = _run(
            ClawAutomationTickRuntime(store).atick(
                workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
            )
        )
        self.assertEqual(receipt.due_count, 0)
        self.assertNotIn("record_run", store.calls)
        self.assertEqual(inner.list_runs(WORKSPACE), [])

    def test_atick_fails_closed_when_the_store_is_unavailable(self) -> None:
        inner = InMemoryClawAutomationStore()
        store = RaisingListStore(inner)
        with self.assertRaises(RuntimeError):
            _run(
                ClawAutomationTickRuntime(store).atick(
                    workspace_id=WORKSPACE, current_time=NOW, membership=_membership()
                )
            )
        self.assertEqual(inner.list_runs(WORKSPACE), [])

    # --- boundary parity -----------------------------------------------------

    def test_ahandle_matches_handle_and_validates_identically(self) -> None:
        sync_store = InMemoryClawAutomationStore()
        sync_store.save_rule(_rule())
        async_inner = InMemoryClawAutomationStore()
        async_inner.save_rule(_rule())
        sync_boundary = ClawAutomationTriggerBoundary(
            ClawAutomationTickRuntime(sync_store)
        )
        async_boundary = ClawAutomationTriggerBoundary(
            ClawAutomationTickRuntime(AsyncD1ShapedStore(async_inner))
        )
        trigger = ClawAutomationTrigger(
            trigger_id="trigger:async_seam",
            correlation_id="corr:async_1",
            workspace_id=WORKSPACE,
            observed_at=NOW,
            membership=_membership(),
        )
        sync_receipt = sync_boundary.handle(trigger)
        async_receipt = _run(async_boundary.ahandle(trigger))
        self.assertEqual(sync_receipt, async_receipt)
        self.assertEqual(async_receipt.created_run_ids, sync_receipt.created_run_ids)

        with self.assertRaises(ContractError):
            _run(async_boundary.ahandle("not-a-trigger"))  # type: ignore[arg-type]
        foreign = ClawAutomationTrigger(
            trigger_id="trigger:async_seam",
            correlation_id="corr:async_2",
            workspace_id=WORKSPACE,
            observed_at=NOW,
            membership=_membership(workspace_id=OTHER_WORKSPACE),
        )
        with self.assertRaises(ContractError):
            _run(async_boundary.ahandle(foreign))
        # Parity: the synchronous path refuses exactly the same inputs.
        with self.assertRaises(ContractError):
            sync_boundary.handle(foreign)

    # --- shared pure selection and source locks ------------------------------

    def test_selection_step_is_pure_and_store_free(self) -> None:
        rules = [_rule(), _rule(rule_id="rule_disabled", enabled=False)]
        candidates = FakeClawScheduler.snapshot_due_candidates(rules, NOW)
        self.assertEqual(len(candidates), 1)
        rule, scheduled, key = candidates[0]
        self.assertEqual(rule.rule_id, "rule_async_1")
        self.assertEqual(scheduled, NOW)
        self.assertEqual(key, occurrence_key(WORKSPACE, rule.rule_id, NOW))

    def test_async_seam_keeps_every_activation_lock_closed(self) -> None:
        self.assertTrue(DURABLE_TICK_RUNTIME)
        self.assertTrue(TICK_RUNTIME_ASYNC_PERSISTENCE_SEAM)
        self.assertFalse(REAL_BACKGROUND_TRIGGER)
        self.assertFalse(REAL_CLOUD_CRON_REGISTRATION)
        self.assertFalse(TICK_RUNTIME_REGISTERS_CLOUD_CRON)

        runtime_source = inspect.getsource(ClawAutomationTickRuntime)
        # The awaited seam must never reach for a nested loop runner or sleep:
        # every store statement is awaited inline, so the event loop stays free.
        self.assertNotIn("asyncio.run", runtime_source)
        self.assertNotIn("time.sleep", runtime_source)
        for forbidden in (
            "smtplib",
            "requests",
            "httpx",
            "urllib",
            "socket",
            "subprocess",
        ):
            self.assertNotIn(forbidden, runtime_source)

        boundary = ClawAutomationTriggerBoundary(
            ClawAutomationTickRuntime(InMemoryClawAutomationStore())
        )
        contract = boundary.safe_dict()
        self.assertTrue(contract["async_persistence_seam"])
        self.assertFalse(contract["new_scheduler_algorithm"])
        self.assertFalse(contract["new_dedup_authority"])
        self.assertFalse(contract["production_scheduler_activation"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
