"""#2833 durable automation store/runtime foundation — adversarial tests.

Phase A tests are preserved in ``test_claw_automation_phase_a.py``. This module
adds the durability slice: every contract is exercised against BOTH the
in-memory reference store and the real durable SQLite adapter, so the durable
backend itself is the thing under test (in-memory runs are not durable proof).
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
import unittest

from kagent.claw_automation import (
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawApprovalGate,
    ClawNotificationChannel,
    ClawNotificationProposal,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    occurrence_key,
    SqliteClawAutomationStore,
)


UTC = timezone.utc
WHEN = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)


def rule(
    rule_id: str,
    workspace_id: str = "workspace_a",
    *,
    expression: str = "0 9 * * *",
    enabled: bool = True,
    kind: ClawScheduleKind = ClawScheduleKind.CRON,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(kind, expression),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
    )


def _store_factories():
    """Yields (factory, is_durable). The durable backend is a real adapter target."""
    yield (lambda: InMemoryClawAutomationStore(), False)
    yield (SqliteClawAutomationStoreFactory(), True)


class SqliteClawAutomationStoreFactory:
    """Creates a SQLite store backed by a per-instance temp file."""

    def __init__(self) -> None:
        self._paths: list[str] = []

    def __call__(self) -> SqliteClawAutomationStore:
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self._paths.append(path)
        return SqliteClawAutomationStore(path)

    def cleanup(self) -> None:
        for path in self._paths:
            try:
                os.remove(path)
            except OSError:
                pass


class DurableStoreAdversarialTests(unittest.TestCase):
    """Contracts that must hold for ANY ClawAutomationStore, durable included."""

    def setUp(self) -> None:
        self._sqlite_factory = SqliteClawAutomationStoreFactory()

    def tearDown(self) -> None:
        self._sqlite_factory.cleanup()

    # --- workspace isolation ---

    def test_cross_workspace_rule_get_returns_none(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("shared", "workspace_a"))
                self.assertIsNone(store.get_rule("shared", "workspace_b"))

    def test_cross_workspace_rule_save_is_rejected(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("shared", "workspace_a"))
                with self.assertRaises(ContractError):
                    store.save_rule(rule("shared", "workspace_b"))

    def test_cross_workspace_list_rules_returns_nothing(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("only_a", "workspace_a"))
                self.assertEqual(store.list_rules("workspace_b"), [])

    def test_cross_workspace_run_get_returns_none(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                store.save_rule(rule("r", "workspace_a"))
                run = scheduler.execute_rule_dry_run(rule("r", "workspace_a"), WHEN)
                self.assertIsNone(store.get_run(run.run_id, "workspace_b"))

    def test_cross_workspace_list_runs_returns_nothing(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                store.save_rule(rule("r", "workspace_a"))
                scheduler.execute_rule_dry_run(rule("r", "workspace_a"), WHEN)
                self.assertEqual(store.list_runs("workspace_b"), [])

    def test_cross_workspace_list_proposals_returns_nothing(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                store.save_rule(rule("r", "workspace_a"))
                scheduler.execute_rule_dry_run(rule("r", "workspace_a"), WHEN)
                self.assertEqual(store.list_proposals("workspace_b"), [])

    def test_cross_workspace_occurrence_lookup_returns_none(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                store.save_rule(rule("r", "workspace_a"))
                scheduler.execute_rule_dry_run(rule("r", "workspace_a"), WHEN)
                key = occurrence_key("workspace_a", "r", WHEN)
                self.assertIsNone(store.get_run_for_occurrence(key, "workspace_b"))

    def test_workspace_a_b_same_rule_ids_stay_isolated(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                # rule_id is globally unique: reuse in a second workspace fails closed.
                store.save_rule(rule("same_id", "workspace_a"))
                with self.assertRaises(ContractError):
                    store.save_rule(rule("same_id", "workspace_b"))
                # Distinct rules firing at the same instant stay fully isolated.
                store.save_rule(rule("other", "workspace_b"))
                run_a = scheduler.execute_rule_dry_run(rule("same_id", "workspace_a"), WHEN)
                run_b = scheduler.execute_rule_dry_run(rule("other", "workspace_b"), WHEN)
                self.assertEqual(run_a.workspace_id, "workspace_a")
                self.assertEqual(run_b.workspace_id, "workspace_b")
                self.assertNotEqual(run_a.run_id, run_b.run_id)
                self.assertNotEqual(run_a.output.output_id, run_b.output.output_id)
                self.assertNotEqual(
                    run_a.output.proposals[0].proposal_id,
                    run_b.output.proposals[0].proposal_id,
                )
                self.assertEqual({r.workspace_id for r in store.list_rules("workspace_a")}, {"workspace_a"})
                self.assertEqual({r.workspace_id for r in store.list_rules("workspace_b")}, {"workspace_b"})
                self.assertEqual(len(store.list_runs("workspace_a")), 1)
                self.assertEqual(len(store.list_runs("workspace_b")), 1)
                self.assertEqual(len(store.list_proposals("workspace_a")), 1)
                self.assertEqual(len(store.list_proposals("workspace_b")), 1)

    # --- same-occurrence dedupe ---

    def test_same_occurrence_dedupe_across_retries(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                item = rule("retry")
                store.save_rule(item)
                first = scheduler.execute_rule_dry_run(item, WHEN)
                retry = scheduler.execute_rule_dry_run(item, WHEN)
                self.assertEqual(first.run_id, retry.run_id)
                self.assertEqual(len(store.list_runs("workspace_a")), 1)
                self.assertEqual(
                    store.get_run_for_occurrence(occurrence_key("workspace_a", "retry", WHEN), "workspace_a").run_id,
                    first.run_id,
                )

    def test_different_occurrence_is_not_deduped(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                item = rule("two")
                store.save_rule(item)
                first = scheduler.execute_rule_dry_run(item, WHEN)
                second = scheduler.execute_rule_dry_run(item, WHEN.replace(minute=1))
                self.assertNotEqual(first.run_id, second.run_id)
                self.assertEqual(len(store.list_runs("workspace_a")), 2)

    # --- disabled rule semantics ---

    def test_disabled_rule_never_executes_or_appears_due(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                disabled = rule("disabled", enabled=False)
                store.save_rule(disabled)
                self.assertEqual(scheduler.evaluate_due_rules("workspace_a", WHEN), [])
                with self.assertRaises(ContractError):
                    scheduler.execute_rule_dry_run(disabled, WHEN)
                self.assertEqual(store.list_runs("workspace_a"), [])
                self.assertEqual(store.list_proposals("workspace_a"), [])

    def test_enable_disable_roundtrip_preserves_rule_body(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                item = rule("toggle", expression="30 9 * * *")
                store.save_rule(item)
                off = store.set_rule_enabled("workspace_a", "toggle", False)
                self.assertFalse(off.enabled)
                self.assertEqual(off.schedule.expression, "30 9 * * *")
                self.assertEqual(off.name, "rule toggle")
                on = store.set_rule_enabled("workspace_a", "toggle", True)
                self.assertTrue(on.enabled)
                self.assertEqual(on.schedule.expression, "30 9 * * *")

    def test_set_rule_enabled_cross_workspace_fails_closed(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("owned_a", "workspace_a"))
                with self.assertRaises(ContractError):
                    store.set_rule_enabled("workspace_b", "owned_a", False)

    # --- conflicting rule update ---

    def test_conflicting_rule_update_cross_workspace_fails_closed(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("owned_a", "workspace_a"))
                with self.assertRaises(ContractError):
                    store.update_rule(rule("owned_a", "workspace_b"))
                # The original rule is untouched.
                self.assertEqual(store.get_rule("owned_a", "workspace_a").workspace_id, "workspace_a")

    def test_update_rule_unknown_id_fails_closed(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                with self.assertRaises(ContractError):
                    store.update_rule(rule("ghost", "workspace_a"))

    def test_rule_update_replaces_schedule_and_output(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(rule("evolve", expression="0 9 * * *"))
                store.update_rule(rule("evolve", expression="15 10 * * *"))
                updated = store.get_rule("evolve", "workspace_a")
                self.assertEqual(updated.schedule.expression, "15 10 * * *")

    # --- max-length IDs ---

    def test_max_length_ids_roundtrip_and_stay_bounded(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                long_workspace = "w" * 128
                long_rule = "r" * 128
                item = rule(long_rule, long_workspace)
                store.save_rule(item)
                self.assertEqual(store.get_rule(long_rule, long_workspace).rule_id, long_rule)
                run = scheduler.execute_rule_dry_run(item, WHEN)
                self.assertLessEqual(len(run.run_id), 128)
                self.assertLessEqual(len(run.output.output_id), 128)
                self.assertLessEqual(len(run.output.proposals[0].proposal_id), 128)
                # Reopen-class lookup still resolves.
                self.assertEqual(store.get_run(run.run_id, long_workspace).run_id, run.run_id)

    def test_max_length_ids_isolate_across_workspaces(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                scheduler = FakeClawScheduler(store)
                long_rule = "r" * 128
                store.save_rule(rule(long_rule, "a" * 128))
                store.save_rule(rule("s" * 128, "b" * 128))
                run_a = scheduler.execute_rule_dry_run(rule(long_rule, "a" * 128), WHEN)
                run_b = scheduler.execute_rule_dry_run(rule("s" * 128, "b" * 128), WHEN)
                self.assertNotEqual(run_a.run_id, run_b.run_id)
                self.assertEqual(len(store.list_runs("a" * 128)), 1)
                self.assertEqual(len(store.list_runs("b" * 128)), 1)
                self.assertIsNone(store.get_run(run_a.run_id, "b" * 128))
                self.assertIsNone(store.get_run(run_b.run_id, "a" * 128))

    # --- explicit run recording ---

    def test_record_run_cross_workspace_collision_fails_closed(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                output = ClawAutomationOutput(
                    output_id="out1", workspace_id="workspace_a",
                    output_type=ClawAutomationOutputType.ALERT, title="t", content="c",
                )
                first = ClawScheduledRun(
                    run_id="run1", workspace_id="workspace_a", rule_id="r",
                    status=ClawScheduledRunStatus.COMPLETED, scheduled_time=WHEN,
                    started_at=WHEN, completed_at=WHEN, output=output,
                )
                store.record_run(first)
                stolen = ClawScheduledRun(
                    run_id="run1", workspace_id="workspace_b", rule_id="r",
                    status=ClawScheduledRunStatus.COMPLETED, scheduled_time=WHEN,
                    started_at=WHEN, completed_at=WHEN,
                )
                with self.assertRaises(ContractError):
                    store.record_run(stolen)
                self.assertIsNone(store.get_run("run1", "workspace_b"))

    def test_record_run_persists_proposals(self) -> None:
        for make_store, _ in _store_factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                proposal = ClawNotificationProposal(
                    proposal_id="prop1", workspace_id="workspace_a", rule_id="r",
                    channel=ClawNotificationChannel.WEB_ALERT_INBOX, title="t", summary="s",
                    approval_gate=ClawApprovalGate(
                        approval_required=True, reason="r", suggested_action="a",
                    ),
                    created_at=WHEN,
                )
                output = ClawAutomationOutput(
                    output_id="out1", workspace_id="workspace_a",
                    output_type=ClawAutomationOutputType.ALERT, title="t", content="c",
                    proposals=(proposal,),
                )
                run = ClawScheduledRun(
                    run_id="run1", workspace_id="workspace_a", rule_id="r",
                    status=ClawScheduledRunStatus.COMPLETED, scheduled_time=WHEN,
                    started_at=WHEN, completed_at=WHEN, output=output,
                )
                store.record_run(run)
                proposals = store.list_proposals("workspace_a")
                self.assertEqual(len(proposals), 1)
                self.assertEqual(proposals[0].proposal_id, "prop1")
                self.assertTrue(proposals[0].approval_gate.approval_required)


class SqliteDurabilityTests(unittest.TestCase):
    """Restart/reopen semantics that only a real durable backend can prove."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, "claw_automation.db")

    def tearDown(self) -> None:
        try:
            os.remove(self._path)
        except OSError:
            pass
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def _reopen(self) -> SqliteClawAutomationStore:
        # A brand-new process-level handle to the same file simulates restart.
        return SqliteClawAutomationStore(self._path)

    def test_restart_preserves_rules_runs_and_proposals(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        item = rule("persist", "workspace_a", expression="0 9 * * *")
        store.save_rule(item)
        run = scheduler.execute_rule_dry_run(item, WHEN)
        self.assertEqual(len(store.list_runs("workspace_a")), 1)

        reopened = self._reopen()
        rules = reopened.list_rules("workspace_a")
        self.assertEqual([r.rule_id for r in rules], ["persist"])
        self.assertEqual(rules[0].schedule.expression, "0 9 * * *")
        runs = reopened.list_runs("workspace_a")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, run.run_id)
        self.assertEqual(runs[0].status, ClawScheduledRunStatus.COMPLETED)
        self.assertEqual(runs[0].scheduled_time, WHEN)
        proposals = reopened.list_proposals("workspace_a")
        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0].approval_gate.approval_required)

    def test_duplicate_occurrence_after_restart_is_deduplicated(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        item = rule("once", "workspace_a")
        store.save_rule(item)
        first = scheduler.execute_rule_dry_run(item, WHEN)

        reopened_store = self._reopen()
        reopened_scheduler = FakeClawScheduler(reopened_store)
        replayed = reopened_scheduler.execute_rule_dry_run(item, WHEN)
        self.assertEqual(first.run_id, replayed.run_id)
        self.assertEqual(len(reopened_store.list_runs("workspace_a")), 1)

        # The reopened store also reports the occurrence as already consumed.
        key = occurrence_key("workspace_a", "once", WHEN)
        self.assertEqual(
            reopened_store.get_run_for_occurrence(key, "workspace_a").run_id,
            first.run_id,
        )

    def test_restart_scheduler_reports_no_duplicate_due_occurrence(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        item = rule("due_after_restart", "workspace_a")
        store.save_rule(item)
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", WHEN), [item])
        scheduler.execute_rule_dry_run(item, WHEN)

        reopened_store = self._reopen()
        reopened_scheduler = FakeClawScheduler(reopened_store)
        # After restart the same instant must not be reported due again.
        self.assertEqual(reopened_scheduler.evaluate_due_rules("workspace_a", WHEN), [])
        self.assertEqual(reopened_scheduler.due_occurrences("workspace_a", WHEN), [])

    def test_restart_preserves_disabled_rule_semantics(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        item = rule("stays_off", "workspace_a", enabled=False)
        store.save_rule(item)
        off = store.set_rule_enabled("workspace_a", "stays_off", False)
        self.assertFalse(off.enabled)

        reopened = self._reopen()
        persisted = reopened.get_rule("stays_off", "workspace_a")
        self.assertIsNotNone(persisted)
        self.assertFalse(persisted.enabled)
        scheduler = FakeClawScheduler(reopened)
        # Disabled state survives restart: still not due, still not executable.
        self.assertEqual(scheduler.evaluate_due_rules("workspace_a", WHEN), [])
        with self.assertRaises(ContractError):
            scheduler.execute_rule_dry_run(persisted, WHEN)
        self.assertEqual(reopened.list_runs("workspace_a"), [])

    def test_restart_preserves_workspace_isolation(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("iso_a", "workspace_a"))
        store.save_rule(rule("iso_b", "workspace_b"))
        run_a = scheduler.execute_rule_dry_run(rule("iso_a", "workspace_a"), WHEN)
        run_b = scheduler.execute_rule_dry_run(rule("iso_b", "workspace_b"), WHEN)

        reopened = self._reopen()
        self.assertIsNone(reopened.get_rule("iso_a", "workspace_b"))
        self.assertIsNone(reopened.get_rule("iso_b", "workspace_a"))
        self.assertEqual(len(reopened.list_rules("workspace_a")), 1)
        self.assertEqual(len(reopened.list_rules("workspace_b")), 1)
        self.assertEqual(reopened.get_run(run_a.run_id, "workspace_b"), None)
        self.assertEqual(reopened.get_run(run_b.run_id, "workspace_a"), None)
        key_a = occurrence_key("workspace_a", "iso_a", WHEN)
        self.assertIsNone(reopened.get_run_for_occurrence(key_a, "workspace_b"))
        self.assertEqual(
            reopened.get_run_for_occurrence(key_a, "workspace_a").run_id,
            run_a.run_id,
        )
        # rule_id global uniqueness also survives restart.
        with self.assertRaises(ContractError):
            reopened.save_rule(rule("iso_a", "workspace_b"))

    def test_in_memory_database_is_not_durable_and_fails_closed_on_reuse(self) -> None:
        # ``:memory:`` is a valid bounded adapter target but never durable proof.
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(rule("ephemeral", "workspace_a"))
        reopened = SqliteClawAutomationStore(":memory:")
        self.assertEqual(reopened.list_rules("workspace_a"), [])

    def test_corrupt_rule_record_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        store.save_rule(rule("corrupt_rule", "workspace_a"))
        # White-box corruption of the serialized rule payload.
        store._db.execute(
            "UPDATE claw_rules SET notification_channels = ? WHERE rule_id = ?",
            ("{this is not valid rule json", "corrupt_rule"),
        )
        with self.assertRaises(ContractError):
            store.get_rule("corrupt_rule", "workspace_a")
        with self.assertRaises(ContractError):
            store.list_rules("workspace_a")

    def test_corrupt_run_timestamp_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("corrupt_run", "workspace_a"))
        run = scheduler.execute_rule_dry_run(rule("corrupt_run", "workspace_a"), WHEN)
        store._db.execute(
            "UPDATE claw_runs SET scheduled_time = ? WHERE run_id = ?",
            ("not-a-timestamp", run.run_id),
        )
        with self.assertRaises(ContractError):
            store.get_run(run.run_id, "workspace_a")
        with self.assertRaises(ContractError):
            store.list_runs("workspace_a")

    def test_corrupt_output_record_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("corrupt_out", "workspace_a"))
        run = scheduler.execute_rule_dry_run(rule("corrupt_out", "workspace_a"), WHEN)
        store._db.execute(
            "UPDATE claw_runs SET output = ? WHERE run_id = ?",
            ("{broken output payload", run.run_id),
        )
        with self.assertRaises(ContractError):
            store.get_run(run.run_id, "workspace_a")

    def test_corrupt_proposal_record_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(self._path)
        scheduler = FakeClawScheduler(store)
        store.save_rule(rule("corrupt_prop", "workspace_a"))
        scheduler.execute_rule_dry_run(rule("corrupt_prop", "workspace_a"), WHEN)
        store._db.execute(
            "UPDATE claw_proposals SET created_at = ? WHERE workspace_id = ?",
            ("not-a-timestamp", "workspace_a"),
        )
        with self.assertRaises(ContractError):
            store.list_proposals("workspace_a")

    def test_empty_database_path_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            SqliteClawAutomationStore("")
        with self.assertRaises(ContractError):
            SqliteClawAutomationStore("   ")

    def test_secret_bearing_rule_name_is_rejected_before_persistence(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        with self.assertRaises(ContractError):
            rule(
                "secret_rule", "workspace_a",
            ).__class__(
                rule_id="secret_rule", workspace_id="workspace_a",
                name="gho_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
                target_source=ClawAutomationTarget.TASKS,
                output_type=ClawAutomationOutputType.ALERT,
            )
        self.assertEqual(store.list_rules("workspace_a"), [])


if __name__ == "__main__":
    unittest.main()
