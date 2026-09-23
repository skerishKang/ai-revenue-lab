"""#2833 S2F5B — execution-claim store authority tests.

Proves the smallest additive conditional execution claim on the EXISTING
automation store: ``PENDING -> RUNNING`` for exactly one caller, ``NOT_CLAIMED``
for every other state, no second lock table / claim token / lease / dedup
authority, and no DELETE on the loser path.

NETWORK_FREE: no scheduler, no provider call, no external send, no Production
mutation. Every claim is measured against the real in-memory and real SQLite
store, and the SQLite statement stream is captured so "one bounded conditional
update" is read off the wire rather than asserted from prose.

Runner boundary: this suite is executed by ``python -m unittest discover -s tests``
in CI with no pytest installed, so it imports nothing beyond the standard library
and ``kagent``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
import unittest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    _derived_occurrence_id,
    occurrence_key,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace_a"
FOREIGN_WORKSPACE = "workspace_b"
RULE_ID = "rule_s2f5b_claim"
REVISION = "b" * 40
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily bounded check",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        owner_ref="owner:opaque:provenance:1",
        execution_intent=ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded report",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def run_for(
    *,
    rule: ClawAutomationRule | None = None,
    workspace_id: str | None = None,
    rule_id: str | None = None,
    scheduled_time: datetime = NOW,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
) -> ClawScheduledRun:
    rule = rule or make_rule()
    workspace = workspace_id if workspace_id is not None else rule.workspace_id
    owning_rule = rule_id if rule_id is not None else rule.rule_id
    return ClawScheduledRun(
        run_id=_derived_occurrence_id("sched_run", workspace, owning_rule, scheduled_time),
        workspace_id=workspace,
        rule_id=owning_rule,
        status=status,
        scheduled_time=scheduled_time,
        started_at=scheduled_time,
        completed_at=None if status is ClawScheduledRunStatus.PENDING else scheduled_time,
    )


def seed(store, *, rule=None, row=None) -> tuple[ClawAutomationRule, ClawScheduledRun]:
    rule = rule or make_rule()
    row = row or run_for(rule=rule)
    store.save_rule(rule)
    store.record_run(row)
    return rule, row


def drop_occurrence_claim(store, row: ClawScheduledRun) -> None:
    """Remove the occurrence mapping, leaving an orphaned run row."""

    key = occurrence_key(row.workspace_id, row.rule_id, row.scheduled_time)
    if isinstance(store, InMemoryClawAutomationStore):
        store._occurrences.pop(key)
        return
    store._db.execute("DELETE FROM claw_occurrences WHERE occurrence_key = ?", (key,))


def claim(store, row: ClawScheduledRun):
    return store.claim_execution(
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        rule_id=row.rule_id,
        scheduled_time=row.scheduled_time,
    )


class RecordingConnection:
    """Delegating proxy that records statements and can inject one competing write.

    ``sqlite3.Connection.execute`` is a read-only C slot, so the proxy is a plain
    object whose ``execute`` is an instance attribute.
    """

    def __init__(self, inner, *, on_statement=None, match=None) -> None:
        self._inner = inner
        self.statements: list[str] = []
        self._on_statement = on_statement
        self._match = match

    def execute(self, sql, parameters=()):
        normalised = " ".join(str(sql).split())
        self.statements.append(normalised)
        if self._on_statement is not None and self._match and self._match in normalised:
            hook = self._on_statement
            self._on_statement = None
            hook()
        return self._inner.execute(sql, parameters)

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        return self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


class SqliteFileFactory:
    """Per-call temp-file SQLite store, so durability is a real file.

    Each call allocates a NEW isolated file: a subTest matrix re-seeds the same
    derived ``run_id`` with a different status, so sharing one file would let the
    first seed win and mask the transition under test. ``reopen()`` re-opens the
    most recently created file so durability stays observable.
    """

    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self._counter = 0
        self._paths: list[str] = []
        self.db_path: str | None = None

    def __call__(self) -> SqliteClawAutomationStore:
        self._counter += 1
        path = os.path.join(self._dir, f"execution_claim_{self._counter}.db")
        self._paths.append(path)
        self.db_path = path
        return SqliteClawAutomationStore(path)

    def reopen(self) -> SqliteClawAutomationStore:
        assert self.db_path is not None
        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        # Windows keeps the file locked while a handle is open, so cleanup is
        # best-effort exactly like the pre-existing scheduler-runtime suite.
        for path in self._paths:
            try:
                os.remove(path)
            except OSError:  # pragma: no cover - best effort temp cleanup
                pass


def table_names(store) -> list[str]:
    rows = store._db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


# --- exactly one PENDING -> RUNNING transition ------------------------------


class ClaimTransitionTests(unittest.TestCase):
    """Both real stores: exactly one caller observes RUNNING, identity unchanged."""

    def setUp(self) -> None:
        self._factory = SqliteFileFactory()
        self.addCleanup(self._factory.cleanup)

    def _stores(self):
        yield ("memory", lambda: InMemoryClawAutomationStore())
        yield ("sqlite", self._factory)

    def test_pending_row_is_claimed_as_running_with_unchanged_identity(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                rule, row = seed(store)

                claimed = claim(store, row)

                self.assertIsNotNone(claimed)
                self.assertEqual(claimed.run_id, row.run_id)
                self.assertEqual(claimed.workspace_id, row.workspace_id)
                self.assertEqual(claimed.rule_id, rule.rule_id)
                self.assertIs(claimed.status, ClawScheduledRunStatus.RUNNING)
                self.assertEqual(claimed.scheduled_time, row.scheduled_time)
                self.assertEqual(claimed.started_at, row.started_at)
                self.assertIsNone(claimed.completed_at)
                self.assertIsNone(claimed.output)

    def test_second_claim_is_not_claimed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)

                first = claim(store, row)
                second = claim(store, row)

                self.assertIsNotNone(first)
                self.assertIsNone(second)
                self.assertIs(
                    store.get_run(row.run_id, WORKSPACE).status,
                    ClawScheduledRunStatus.RUNNING,
                )

    def test_non_pending_row_is_never_claimed(self) -> None:
        for label, make_store in self._stores():
            for status in (
                ClawScheduledRunStatus.RUNNING,
                ClawScheduledRunStatus.COMPLETED,
                ClawScheduledRunStatus.FAILED,
                ClawScheduledRunStatus.CANCELLED,
            ):
                with self.subTest(store=label, status=status.value):
                    store = make_store()
                    rule = make_rule()
                    row = run_for(rule=rule, status=status)
                    store.save_rule(rule)
                    store.record_run(row)

                    self.assertIsNone(claim(store, row))
                    self.assertIs(store.get_run(row.run_id, WORKSPACE).status, status)

    def test_claim_never_inserts_a_row_or_a_second_identity(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)
                before = [item.run_id for item in store.list_runs(WORKSPACE)]

                claim(store, row)

                after = [item.run_id for item in store.list_runs(WORKSPACE)]
                self.assertEqual(after, before)
                self.assertEqual(after, [row.run_id])

    def test_claim_does_not_mutate_started_at_or_scheduled_time(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)

                claim(store, row)
                stored = store.get_run(row.run_id, WORKSPACE)

                self.assertEqual(stored.started_at, row.started_at)
                self.assertEqual(stored.scheduled_time, row.scheduled_time)


# --- fail-closed refusals ---------------------------------------------------


class ClaimFailClosedTests(unittest.TestCase):
    """An authority violation is never silently reinterpreted as NOT_CLAIMED."""

    def setUp(self) -> None:
        self._factory = SqliteFileFactory()
        self.addCleanup(self._factory.cleanup)

    def _stores(self):
        yield ("memory", lambda: InMemoryClawAutomationStore())
        yield ("sqlite", self._factory)

    def test_missing_row_fails_closed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                rule = make_rule()
                store.save_rule(rule)
                row = run_for(rule=rule)

                with self.assertRaises(ContractError):
                    claim(store, row)

    def test_foreign_workspace_fails_closed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)

                with self.assertRaises(ContractError):
                    store.claim_execution(
                        run_id=row.run_id,
                        workspace_id=FOREIGN_WORKSPACE,
                        rule_id=row.rule_id,
                        scheduled_time=row.scheduled_time,
                    )
                self.assertIs(
                    store.get_run(row.run_id, WORKSPACE).status,
                    ClawScheduledRunStatus.PENDING,
                )

    def test_rule_identity_mismatch_fails_closed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)

                with self.assertRaises(ContractError):
                    store.claim_execution(
                        run_id=row.run_id,
                        workspace_id=WORKSPACE,
                        rule_id="rule_other",
                        scheduled_time=row.scheduled_time,
                    )
                self.assertIs(
                    store.get_run(row.run_id, WORKSPACE).status,
                    ClawScheduledRunStatus.PENDING,
                )

    def test_scheduled_time_mismatch_fails_closed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)

                with self.assertRaises(ContractError):
                    store.claim_execution(
                        run_id=row.run_id,
                        workspace_id=WORKSPACE,
                        rule_id=row.rule_id,
                        scheduled_time=datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc),
                    )
                self.assertIs(
                    store.get_run(row.run_id, WORKSPACE).status,
                    ClawScheduledRunStatus.PENDING,
                )

    def test_row_without_its_occurrence_claim_fails_closed(self) -> None:
        for label, make_store in self._stores():
            with self.subTest(store=label):
                store = make_store()
                _, row = seed(store)
                drop_occurrence_claim(store, row)

                with self.assertRaises(ContractError):
                    claim(store, row)
                self.assertIs(
                    store.get_run(row.run_id, WORKSPACE).status,
                    ClawScheduledRunStatus.PENDING,
                )


# --- durable semantics ------------------------------------------------------


class SqliteClaimDurabilityTests(unittest.TestCase):
    """Durability and the on-the-wire shape of the durable decision."""

    def setUp(self) -> None:
        self._factory = SqliteFileFactory()
        self.addCleanup(self._factory.cleanup)

    def test_sqlite_claim_is_durable_across_reopen(self) -> None:
        store = self._factory()
        _, row = seed(store)

        self.assertIsNotNone(claim(store, row))

        reopened = self._factory.reopen()
        self.assertIs(
            reopened.get_run(row.run_id, WORKSPACE).status,
            ClawScheduledRunStatus.RUNNING,
        )
        self.assertIsNone(claim(reopened, row))

    def test_sqlite_claim_statement_carries_the_pending_guard(self) -> None:
        store = self._factory()
        _, row = seed(store)
        proxy = RecordingConnection(store._db)
        store._db = proxy

        self.assertIsNotNone(claim(store, row))

        updates = [
            statement
            for statement in proxy.statements
            if statement.startswith("UPDATE claw_runs SET status=")
        ]
        self.assertEqual(len(updates), 1)
        self.assertTrue(
            updates[0].endswith("WHERE run_id=? AND status=? AND completed_at IS NULL"),
            updates[0],
        )
        keywords = [statement.split()[0].upper() for statement in proxy.statements]
        self.assertEqual(keywords.count("COMMIT"), 1)

    def test_concurrent_second_claimant_loses_without_deleting_the_winner(self) -> None:
        store = self._factory()
        _, row = seed(store)
        inner = store._db

        def competing_winner() -> None:
            inner.execute(
                "UPDATE claw_runs SET status=? WHERE run_id=?",
                (ClawScheduledRunStatus.RUNNING.value, row.run_id),
            )

        proxy = RecordingConnection(
            inner, on_statement=competing_winner, match="UPDATE claw_runs SET status="
        )
        store._db = proxy

        self.assertIsNone(claim(store, row))

        keywords = [statement.split()[0].upper() for statement in proxy.statements]
        self.assertNotIn("DELETE", keywords)
        self.assertEqual(keywords.count("COMMIT"), 1)
        self.assertEqual(keywords.count("ROLLBACK"), 0)
        self.assertIs(
            store.get_run(row.run_id, WORKSPACE).status,
            ClawScheduledRunStatus.RUNNING,
        )
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    def test_claim_introduces_no_new_table(self) -> None:
        store = self._factory()
        _, row = seed(store)
        before = table_names(store)

        self.assertIsNotNone(claim(store, row))

        self.assertEqual(table_names(store), before)
        self.assertIn("claw_runs", before)


# --- no second authority in source -----------------------------------------


class ExecutionClaimSourceAuthorityTests(unittest.TestCase):
    """The module declares reuse explicitly and adds no second authority."""

    def test_module_declares_no_second_execution_authority(self) -> None:
        from kagent import claw_automation as module

        self.assertIs(module.EXECUTION_CLAIM_AUTHORITY_REUSED, True)
        self.assertIs(module.EXECUTION_CLAIM_NEW_LOCK_TABLE, False)
        self.assertIs(module.EXECUTION_CLAIM_NEW_CLAIM_TOKEN, False)
        self.assertIs(module.EXECUTION_CLAIM_SECOND_DEDUP_AUTHORITY, False)
        self.assertIs(module.EXECUTION_CLAIM_SECOND_RUN_ID, False)
        self.assertIs(module.EXECUTION_CLAIM_REDISPATCHES_RUNNING, False)
        self.assertIs(module.EXECUTION_CLAIM_REDISPATCHES_TERMINAL, False)
        self.assertIs(module.EXECUTION_CLAIM_PERFORMS_PROVIDER_CALLS, False)
        self.assertIs(module.EXECUTION_CLAIM_ACTIVATES_PRODUCTION_SCHEDULER, False)


if __name__ == "__main__":
    unittest.main()
