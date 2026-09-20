"""#2833 durable provider-neutral Claw automation scheduler tick runtime.

This module tests ``ClawAutomationTickRuntime``: the kernel that turns one
trusted scheduler trigger into zero or more durable, idempotent Claw runs for a
single explicit workspace.

Design boundaries pinned here:

* One tick processes exactly ONE workspace. There is no implicit "all
  workspaces" sweep, because background execution is never allowed without an
  explicit workspace plus an authoritative membership projection.
* ``membership`` is a REQUIRED argument. ``None`` is rejected, so the #2833
  acceptance rule "deleted/expired workspace membership prevents execution"
  cannot be bypassed by simply omitting the projection.
* Occurrence identity is the pre-existing ``occurrence_key(workspace_id,
  rule_id, scheduled_time)`` triple. This slice introduces no second dedup
  authority.
* Schedule evaluation reuses the pre-existing ``FakeClawScheduler`` candidate
  and dry-run semantics rather than duplicating cron/interval/daypart math.
* A tick materialises only bounded, non-sending results (WEB_ALERT_INBOX /
  draft / report / task proposals). No provider call, no outbound message.

The durable backend is a real SQLite adapter. In-memory runs are not accepted
as durability proof anywhere in this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import sqlite3
import tempfile
import unittest

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationStore,
    ClawAutomationTarget,
    ClawAutomationTickReceipt,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    occurrence_key,
)
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

try:  # match the pre-existing tz availability convention in this suite
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - requires-python>=3.11
    ZoneInfo = None  # type: ignore[assignment]


def _tz_available(name: str) -> bool:
    if ZoneInfo is None:
        return False
    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


UTC = timezone.utc
WHEN = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
WORKSPACE = "workspace_a"


def make_rule(
    rule_id: str,
    workspace_id: str = WORKSPACE,
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


def membership(
    workspace_id: str = WORKSPACE,
    *,
    at: datetime = WHEN,
    issued_offset_hours: int = -1,
    expires_offset_hours: int = 1,
    membership_id: str = "membership:owner",
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id=membership_id,
        workspace_id=workspace_id,
        principal_ref="principal:user",
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=at + timedelta(hours=issued_offset_hours),
        expires_at=at + timedelta(hours=expires_offset_hours),
    )


class SqliteStoreFactory:
    """Per-instance temp-file SQLite store, so every test uses a real file."""

    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self._paths: list[str] = []
        self.db_path = os.path.join(self._dir, "claw_tick.db")

    def __call__(self) -> SqliteClawAutomationStore:
        if self.db_path not in self._paths:
            self._paths.append(self.db_path)
        return SqliteClawAutomationStore(self.db_path)

    def reopen(self) -> SqliteClawAutomationStore:
        """A brand-new handle to the same file; simulates process restart."""

        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        for path in self._paths:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._dir)
        except OSError:
            pass


class FaultyConnection:
    """Delegating connection proxy with an overridable ``execute``.

    ``sqlite3.Connection.execute`` is a read-only C slot, so a test cannot
    monkeypatch it on a live connection. This proxy forwards every attribute
    to the wrapped connection while letting a test substitute ``execute``
    with an instance attribute, which is how store-failure injection is
    performed without touching production code.
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self.execute = self._delegate_execute

    def _delegate_execute(self, sql, *args):
        return self._inner.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _install_faulty_execute(store: SqliteClawAutomationStore, execute):
    """Swap the store's connection for a fault-injecting proxy."""

    proxy = FaultyConnection(store._db)
    proxy.execute = execute
    store._db = proxy  # type: ignore[assignment]
    return proxy


def _runtime_factories():
    """Yields (factory, is_durable). Only the durable factory proves restart."""

    yield (lambda: InMemoryClawAutomationStore(), False)
    yield (SqliteStoreFactory(), True)


class TickRuntimeContractTests(unittest.TestCase):
    """Core tick semantics, exercised against both stores."""

    def setUp(self) -> None:
        self._sqlite = SqliteStoreFactory()

    def tearDown(self) -> None:
        self._sqlite.cleanup()

    def _factories(self):
        yield (lambda: InMemoryClawAutomationStore(), False)
        yield (self._sqlite, True)

    # --- (1) due rule -> exactly one run ---

    def test_one_due_rule_creates_exactly_one_durable_run(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                runtime = ClawAutomationTickRuntime(store)

                receipt = runtime.tick(
                    workspace_id=WORKSPACE,
                    current_time=WHEN,
                    membership=membership(),
                )

                self.assertIsInstance(receipt, ClawAutomationTickReceipt)
                self.assertEqual(receipt.workspace_id, WORKSPACE)
                self.assertEqual(receipt.observed_at, WHEN)
                self.assertEqual(receipt.due_count, 1)
                self.assertEqual(len(receipt.created_run_ids), 1)
                self.assertEqual(receipt.deduplicated_count, 0)
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)
                self.assertEqual(store.list_runs(WORKSPACE)[0].rule_id, "due")

    # --- (2) not due ---

    def test_not_due_rule_creates_zero_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("not_due", expression="0 9 * * *"))
                runtime = ClawAutomationTickRuntime(store)
                # 09:01 is not a cron match for minute 0 hour 9.
                off_time = WHEN.replace(minute=1)
                receipt = runtime.tick(
                    workspace_id=WORKSPACE,
                    current_time=off_time,
                    membership=membership(at=off_time),
                )
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- (3) disabled ---

    def test_disabled_rule_creates_zero_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("disabled", enabled=False))
                runtime = ClawAutomationTickRuntime(store)
                receipt = runtime.tick(
                    workspace_id=WORKSPACE,
                    current_time=WHEN,
                    membership=membership(),
                )
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- (4) missing membership ---

    def test_missing_membership_fails_closed_with_zero_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                runtime = ClawAutomationTickRuntime(store)
                with self.assertRaises(ContractError):
                    runtime.tick(
                        workspace_id=WORKSPACE,
                        current_time=WHEN,
                        membership=None,
                    )
                self.assertEqual(store.list_runs(WORKSPACE), [])

    def test_none_membership_is_never_a_wildcard_background_grant(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("due"))
        runtime = ClawAutomationTickRuntime(store)
        for attempt in (None, {}, "workspace_a", 0, False):
            with self.subTest(membership=repr(attempt)):
                with self.assertRaises(ContractError):
                    runtime.tick(
                        workspace_id=WORKSPACE,
                        current_time=WHEN,
                        membership=attempt,
                    )
        self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- (5) expired membership ---

    def test_expired_membership_creates_zero_runs_even_with_due_rule(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                runtime = ClawAutomationTickRuntime(store)
                expired = TrustedWorkspaceMembershipProjection(
                    membership_id="membership:expired",
                    workspace_id=WORKSPACE,
                    principal_ref="principal:user",
                    role=WorkspaceRole.OWNER,
                    authority_ref="control-plane:membership",
                    issued_at=WHEN - timedelta(hours=2),
                    expires_at=WHEN - timedelta(hours=1),
                )
                self.assertFalse(expired.valid_at(WHEN))
                receipt = runtime.tick(
                    workspace_id=WORKSPACE,
                    current_time=WHEN,
                    membership=expired,
                )
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

    def test_not_yet_valid_membership_creates_zero_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                runtime = ClawAutomationTickRuntime(store)
                future = TrustedWorkspaceMembershipProjection(
                    membership_id="membership:future",
                    workspace_id=WORKSPACE,
                    principal_ref="principal:user",
                    role=WorkspaceRole.OWNER,
                    authority_ref="control-plane:membership",
                    issued_at=WHEN + timedelta(hours=1),
                    expires_at=WHEN + timedelta(hours=2),
                )
                receipt = runtime.tick(
                    workspace_id=WORKSPACE,
                    current_time=WHEN,
                    membership=future,
                )
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- (6) wrong workspace membership ---

    def test_wrong_workspace_membership_fails_closed(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due", WORKSPACE))
                runtime = ClawAutomationTickRuntime(store)
                with self.assertRaises(ContractError):
                    runtime.tick(
                        workspace_id=WORKSPACE,
                        current_time=WHEN,
                        membership=membership("workspace_other"),
                    )
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- (7) same tick retry ---

    def test_same_tick_retry_creates_no_duplicate(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
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

    # --- (10) two rules same instant ---

    def test_two_rules_same_instant_produce_two_distinct_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("alpha"))
                store.save_rule(make_rule("beta"))
                runtime = ClawAutomationTickRuntime(store)
                receipt = runtime.tick(
                    workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
                )
                self.assertEqual(receipt.due_count, 2)
                self.assertEqual(len(receipt.created_run_ids), 2)
                self.assertEqual(len(set(receipt.created_run_ids)), 2)
                runs = store.list_runs(WORKSPACE)
                self.assertEqual(len(runs), 2)
                self.assertEqual({r.rule_id for r in runs}, {"alpha", "beta"})

    # --- (11) two workspaces isolated ---

    def test_two_workspaces_same_rule_id_and_instant_stay_isolated(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        # rule_id is globally unique in this schema; use distinct ids, same instant.
        store.save_rule(make_rule("iso_a", "workspace_a"))
        store.save_rule(make_rule("iso_b", "workspace_b"))
        runtime = ClawAutomationTickRuntime(store)
        receipt_a = runtime.tick(
            workspace_id="workspace_a",
            current_time=WHEN,
            membership=membership("workspace_a"),
        )
        receipt_b = runtime.tick(
            workspace_id="workspace_b",
            current_time=WHEN,
            membership=membership("workspace_b"),
        )
        self.assertEqual(len(receipt_a.created_run_ids), 1)
        self.assertEqual(len(receipt_b.created_run_ids), 1)
        self.assertNotEqual(receipt_a.created_run_ids[0], receipt_b.created_run_ids[0])
        self.assertEqual(len(store.list_runs("workspace_a")), 1)
        self.assertEqual(len(store.list_runs("workspace_b")), 1)
        key_a = occurrence_key("workspace_a", "iso_a", WHEN)
        self.assertIsNone(store.get_run_for_occurrence(key_a, "workspace_b"))

    # --- (12)(13)(14) schedule kinds ---

    def test_cron_tick_creates_run_at_matching_minute(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("cron", expression="0 9 * * *"))
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(receipt.due_count, 1)
        run = store.list_runs(WORKSPACE)[0]
        self.assertEqual(run.scheduled_time, WHEN)

    def test_interval_tick_creates_run_only_on_boundary(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(
            make_rule("interval", kind=ClawScheduleKind.INTERVAL, expression="1h")
        )
        runtime = ClawAutomationTickRuntime(store)
        # 09:00 is an exact 1h boundary.
        on_boundary = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(on_boundary.due_count, 1)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)
        # 09:30 is not.
        off = WHEN.replace(minute=30)
        off_boundary = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=off,
            membership=membership(at=off),
        )
        self.assertEqual(off_boundary.due_count, 0)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    def test_daypart_tick_creates_run_at_slot(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(
            make_rule(
                "daypart",
                kind=ClawScheduleKind.DAYPART,
                expression="morning",
                schedule_timezone="UTC",
            )
        )
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(receipt.due_count, 1)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

    # --- (15) explicit timezone boundary ---

    def test_explicit_timezone_boundary_is_honoured(self) -> None:
        import kagent.claw_automation as module

        try:
            module.resolve_timezone("Asia/Seoul")
        except ContractError:
            self.skipTest("Asia/Seoul timezone data unavailable on this runner")
        store = SqliteClawAutomationStore(":memory:")
        # "0 0 * * *" in Asia/Seoul fires at 00:00 KST, which is 15:00 UTC the
        # previous day (KST is UTC+9). WHEN is 09:00 UTC == 18:00 KST, so the
        # rule is not due then.
        store.save_rule(make_rule("kst_morning", expression="0 0 * * *", schedule_timezone="Asia/Seoul"))
        runtime = ClawAutomationTickRuntime(store)

        not_due = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(not_due.due_count, 0)

        # 2026-09-07 15:00 UTC == 2026-09-08 00:00 KST, so the rule IS due.
        kst_midnight = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
        due = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=kst_midnight,
            membership=membership(at=kst_midnight),
        )
        self.assertEqual(due.due_count, 1)

    # --- (16) DST fold ---

    def test_dst_fold_semantics_preserved_and_deduped(self) -> None:
        """A DST fold must not silently double-run the same local wall-clock slot.

        ``America/New_York`` falls back 2026-11-01 02:00 EDT -> 01:00 EST, so
        01:30 occurs twice. The two instants are genuinely different absolute
        times and therefore distinct occurrences; the important guarantee is that
        each absolute instant is processed at most once and that both are
        durable and order-stable.
        """

        import kagent.claw_automation as module

        try:
            module.resolve_timezone("America/New_York")
        except ContractError:
            self.skipTest("America/New_York timezone data unavailable on this runner")
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(
            make_rule(
                "dst_fold",
                expression="30 1 * * *",
                schedule_timezone="America/New_York",
            )
        )
        runtime = ClawAutomationTickRuntime(store)
        # 05:30 UTC = 01:30 EDT (first pass), 06:30 UTC = 01:30 EST (second pass).
        first_pass = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
        second_pass = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)

        first = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=first_pass,
            membership=membership(at=first_pass),
        )
        self.assertEqual(first.due_count, 1)
        # Replaying the first instant is deduped.
        replay = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=first_pass,
            membership=membership(at=first_pass),
        )
        self.assertEqual(replay.created_run_ids, ())

        second = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=second_pass,
            membership=membership(at=second_pass),
        )
        self.assertEqual(second.due_count, 1)
        self.assertNotEqual(first.created_run_ids[0], second.created_run_ids[0])
        self.assertEqual(len(store.list_runs(WORKSPACE)), 2)
        # Both absolute instants remain distinct logical occurrences.
        keys = {
            occurrence_key(WORKSPACE, "dst_fold", first_pass.replace(second=0, microsecond=0)),
            occurrence_key(WORKSPACE, "dst_fold", second_pass.replace(second=0, microsecond=0)),
        }
        self.assertEqual(len(keys), 2)

    # --- (17) bounded output/proposal ---

    def test_output_and_proposal_are_bounded_and_inbox_scoped(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("bounded"))
        runtime = ClawAutomationTickRuntime(store)
        runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=membership())

        run = store.list_runs(WORKSPACE)[0]
        self.assertIsNotNone(run.output)
        output = run.output
        self.assertEqual(output.workspace_id, WORKSPACE)
        self.assertLessEqual(len(output.content), 16384)
        self.assertEqual(len(output.proposals), 1)
        proposal = output.proposals[0]
        self.assertEqual(proposal.workspace_id, WORKSPACE)
        self.assertEqual(proposal.rule_id, "bounded")
        self.assertEqual(proposal.channel.value, "web_alert_inbox")
        self.assertTrue(proposal.approval_gate.approval_required)
        safe = proposal.safe_dict()
        self.assertFalse(safe["auto_send"])
        self.assertFalse(safe["auto_order"])
        self.assertFalse(safe["auto_memory_confirm"])

    def test_proposal_is_persisted_to_the_durable_store(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("prop_persist"))
        runtime = ClawAutomationTickRuntime(store)
        runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=membership())
        proposals = store.list_proposals(WORKSPACE)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].rule_id, "prop_persist")
        self.assertTrue(proposals[0].approval_gate.approval_required)

    # --- (18) auto-send = 0 / (19) provider calls = 0 ---

    def test_no_auto_send_and_no_provider_or_dispatch_side_effects(self) -> None:
        """Boundary proof by source inspection, not by ambient process state.

        A test runner itself imports socket/subprocess, so asserting on
        ``sys.modules`` would be meaningless. What matters is that the tick
        module and runtime never reach for network, subprocess or provider
        machinery.
        """

        import inspect

        import kagent.claw_automation as module

        source = inspect.getsource(module)
        runtime_source = inspect.getsource(module.ClawAutomationTickRuntime)
        for forbidden in ("smtplib", "requests", "httpx", "urllib", "socket", "subprocess", "http.client"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(forbidden, runtime_source)

        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("no_side_effects"))
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertTrue(receipt.created_run_ids)
        run = store.list_runs(WORKSPACE)[0]
        for proposal in run.output.proposals:
            safe = proposal.safe_dict()
            self.assertFalse(safe["auto_send"])
            self.assertFalse(safe["auto_order"])
            self.assertFalse(safe["auto_memory_confirm"])

        self.assertFalse(module.EXTERNAL_SEND_ENABLED)
        self.assertFalse(module.AUTO_SEND_ENABLED)
        self.assertFalse(module.AUTO_ORDER_ENABLED)
        self.assertFalse(module.AUTO_MEMORY_CONFIRM_ENABLED)
        self.assertFalse(module.TICK_RUNTIME_PERFORMS_PROVIDER_CALLS)
        self.assertFalse(module.TICK_RUNTIME_REGISTERS_CLOUD_CRON)
        self.assertTrue(module.DURABLE_TICK_RUNTIME)
        self.assertFalse(module.REAL_BACKGROUND_TRIGGER)
        self.assertFalse(module.REAL_CLOUD_CRON_REGISTRATION)
        self.assertFalse(module.PRODUCTION_SCHEDULER_ACTIVATION)

    # --- (20) secret projection = 0 ---

    def test_receipt_projection_carries_no_secret_or_internal_evidence(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("secret_free"))
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        payload = receipt.safe_dict()
        for forbidden in (
            "token",
            "credential",
            "secret",
            "recipient_ref",
            "provider_response",
            "reasoning",
            "filesystem_path",
            "raw_output",
            "content",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(
            set(payload),
            {"workspace_id", "observed_at", "due_count", "created_run_ids", "deduplicated_count"},
        )

    # --- (21) store failure -> fail closed ---

    def test_store_failure_fails_closed_without_partial_receipt(self) -> None:
        class ExplodingStore:
            def list_rules(self, workspace_id: str):
                raise sqlite3.OperationalError("disk I/O error")

            def get_run_for_occurrence(self, key: str, workspace_id: str):
                raise sqlite3.OperationalError("disk I/O error")

            def record_run(self, run):
                raise sqlite3.OperationalError("disk I/O error")

        runtime = ClawAutomationTickRuntime(ExplodingStore())
        with self.assertRaises((ContractError, sqlite3.OperationalError)):
            runtime.tick(
                workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
            )

    def test_record_run_failure_fails_closed_after_membership_and_due_checks(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("record_fail"))
        runtime = ClawAutomationTickRuntime(store)

        def boom(run):
            raise sqlite3.OperationalError("database is locked")

        store.record_run = boom  # type: ignore[method-assign]
        with self.assertRaises((ContractError, sqlite3.OperationalError)):
            runtime.tick(
                workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
            )

    # --- (22) corrupted durable row -> fail closed ---

    def test_corrupted_rule_row_fails_closed_during_tick(self) -> None:
        factory = SqliteStoreFactory()
        try:
            store = factory()
            store.save_rule(make_rule("corrupt"))
            store._db.execute(
                "UPDATE claw_rules SET notification_channels = ? WHERE rule_id = ?",
                ("{not valid json", "corrupt"),
            )
            runtime = ClawAutomationTickRuntime(store)
            with self.assertRaises(ContractError):
                runtime.tick(
                    workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
                )
        finally:
            factory.cleanup()

    # --- (24) deterministic receipt ordering ---

    def test_receipt_ordering_is_deterministic_across_repeated_schedule_kinds(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("zeta"))
        store.save_rule(make_rule("alpha"))
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        order = tuple(sorted(receipt.created_run_ids))
        self.assertEqual(receipt.created_run_ids, order)

    def test_receipt_created_run_ids_is_a_tuple_and_immutable(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("immutable"))
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertIsInstance(receipt.created_run_ids, tuple)
        self.assertEqual(receipt.created_run_ids, tuple(sorted(receipt.created_run_ids)))

    # --- observed_at / input validation ---

    def test_naive_current_time_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("naive"))
        runtime = ClawAutomationTickRuntime(store)
        with self.assertRaises(ContractError):
            runtime.tick(
                workspace_id=WORKSPACE,
                current_time=datetime(2026, 9, 8, 9, 0),
                membership=membership(),
            )

    def test_invalid_workspace_id_fails_closed(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        runtime = ClawAutomationTickRuntime(store)
        for bad in ("", "  ", "bad workspace", "x" * 129, "workspace/../etc"):
            with self.subTest(workspace_id=repr(bad)):
                with self.assertRaises(ContractError):
                    runtime.tick(
                        workspace_id=bad, current_time=WHEN, membership=membership()
                    )

    def test_current_time_is_normalised_to_utc(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        store.save_rule(make_rule("tz_norm"))
        runtime = ClawAutomationTickRuntime(store)
        kst = timezone(timedelta(hours=9))
        receipt = runtime.tick(
            workspace_id=WORKSPACE,
            current_time=WHEN.astimezone(kst),
            membership=membership(),
        )
        self.assertEqual(receipt.observed_at, WHEN)
        self.assertEqual(receipt.observed_at.tzinfo, UTC)


class TickRuntimeRestartDurabilityTests(unittest.TestCase):
    """(8)(9) restart durability — only a real file-backed store can prove this."""

    def setUp(self) -> None:
        self._factory = SqliteStoreFactory()
        self.addCleanup(self._factory.cleanup)

    def test_restart_same_occurrence_is_not_duplicated(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("restart_once"))
        runtime = ClawAutomationTickRuntime(store)
        first = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(len(first.created_run_ids), 1)

        # --- process B (fresh handle, same file) ---
        reopened = self._factory.reopen()
        reopened_runtime = ClawAutomationTickRuntime(reopened)
        replay = reopened_runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(replay.created_run_ids, ())
        self.assertEqual(replay.due_count, 0)
        self.assertEqual(len(reopened.list_runs(WORKSPACE)), 1)
        self.assertEqual(reopened.list_runs(WORKSPACE)[0].run_id, first.created_run_ids[0])
        key = occurrence_key(WORKSPACE, "restart_once", WHEN)
        self.assertEqual(
            reopened.get_run_for_occurrence(key, WORKSPACE).run_id,
            first.created_run_ids[0],
        )

    def test_restart_next_occurrence_creates_exactly_one_new_run(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("restart_next", expression="0 9 * * *"))
        runtime = ClawAutomationTickRuntime(store)
        runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=membership())

        reopened = self._factory.reopen()
        reopened_runtime = ClawAutomationTickRuntime(reopened)
        next_day = WHEN + timedelta(days=1)
        receipt = reopened_runtime.tick(
            workspace_id=WORKSPACE,
            current_time=next_day,
            membership=membership(at=next_day),
        )
        self.assertEqual(len(receipt.created_run_ids), 1)
        self.assertEqual(len(reopened.list_runs(WORKSPACE)), 2)

    def test_receipt_after_restart_is_stable_and_bounded(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("stable_receipt"))
        ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        reopened = self._factory.reopen()
        replay = ClawAutomationTickRuntime(reopened).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(set(replay.safe_dict()), {
            "workspace_id", "observed_at", "due_count", "created_run_ids", "deduplicated_count"
        })
        self.assertEqual(replay.observed_at, WHEN)
        self.assertEqual(replay.created_run_ids, ())

    def test_restart_preserves_disabled_and_membership_semantics(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("off_after_restart", enabled=False))
        ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        reopened = self._factory.reopen()
        runtime = ClawAutomationTickRuntime(reopened)
        receipt = runtime.tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(receipt.created_run_ids, ())
        with self.assertRaises(ContractError):
            runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=None)
        self.assertEqual(reopened.list_runs(WORKSPACE), [])


class OccurrenceConcurrencyTests(unittest.TestCase):
    """(23) ONE_LOGICAL_OCCURRENCE => AT_MOST_ONE_CANONICAL_RUN.

    Two scheduler ticks racing on the same occurrence must not produce two
    canonical runs. ``record_run`` performs its occurrence pre-check OUTSIDE its
    transaction, so the guarantee has to come from the transaction body itself.
    """

    def setUp(self) -> None:
        self._factory = SqliteStoreFactory()
        self.addCleanup(self._factory.cleanup)

    def _run(self, run_id: str, workspace_id: str = WORKSPACE, rule_id: str = "race"):
        return ClawScheduledRun(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=WHEN,
            started_at=WHEN,
            completed_at=WHEN,
        )

    def test_two_connections_racing_one_occurrence_leave_one_canonical_run(self) -> None:
        path = self._factory.db_path
        SqliteClawAutomationStore(path)  # create schema
        conn_one = SqliteClawAutomationStore(path)
        conn_two = SqliteClawAutomationStore(path)

        first = conn_one.record_run(self._run("runA"))
        second = conn_two.record_run(self._run("runB"))

        # Both callers must observe the SAME canonical run.
        self.assertEqual(first.run_id, second.run_id)

        direct = sqlite3.connect(path)
        rows = direct.execute("SELECT run_id FROM claw_runs ORDER BY run_id").fetchall()
        occurrences = direct.execute(
            "SELECT occurrence_key, run_id FROM claw_occurrences"
        ).fetchall()
        self.assertEqual(len(occurrences), 1, "exactly one occurrence claim is allowed")
        self.assertEqual(
            [r[0] for r in rows],
            [occurrences[0][1]],
            "every persisted run must be the canonical run for the occurrence",
        )

    def test_interleaved_prechecks_do_not_orphan_a_second_run(self) -> None:
        """Reproduces the real race: both pre-checks see no run, then both write."""

        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        conn_one = SqliteClawAutomationStore(path)
        conn_two = SqliteClawAutomationStore(path)

        key = occurrence_key(WORKSPACE, "race", WHEN)
        # Both connections observe "no existing run" before either commits.
        self.assertIsNone(conn_one._get_occurrence_run_id(key, WORKSPACE))
        self.assertIsNone(conn_two._get_occurrence_run_id(key, WORKSPACE))

        conn_one.record_run(self._run("runA"))
        # conn_two still thinks it owns the occurrence, because its stale
        # pre-check already returned None before conn_one committed.
        conn_two.record_run(self._run("runB"))

        direct = sqlite3.connect(path)
        run_ids = direct.execute("SELECT run_id FROM claw_runs ORDER BY run_id").fetchall()
        occurrence_run = direct.execute(
            "SELECT run_id FROM claw_occurrences"
        ).fetchall()
        self.assertEqual(
            len(occurrence_run), 1, "a single occurrence may be claimed once"
        )
        self.assertEqual(
            [r[0] for r in run_ids],
            [occurrence_run[0][0]],
            "no orphaned run may survive an interleaved race",
        )

    def test_race_winner_is_the_occurrence_claim_holder(self) -> None:
        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        conn_one = SqliteClawAutomationStore(path)
        conn_two = SqliteClawAutomationStore(path)
        first = conn_one.record_run(self._run("runA"))
        second = conn_two.record_run(self._run("runB"))
        direct = sqlite3.connect(path)
        claimed = direct.execute("SELECT run_id FROM claw_occurrences").fetchone()[0]
        self.assertEqual(first.run_id, claimed)
        self.assertEqual(second.run_id, claimed)

    def test_distinct_occurrences_still_both_persist_under_race(self) -> None:
        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        conn_one = SqliteClawAutomationStore(path)
        conn_two = SqliteClawAutomationStore(path)
        first = conn_one.record_run(self._run("runA"))
        later = WHEN + timedelta(days=1)
        other = ClawScheduledRun(
            run_id="runB",
            workspace_id=WORKSPACE,
            rule_id="race",
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=later,
            started_at=later,
            completed_at=later,
        )
        second = conn_two.record_run(other)
        self.assertNotEqual(first.run_id, second.run_id)
        direct = sqlite3.connect(path)
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 2
        )
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 2
        )

    def test_concurrent_tick_runtime_returns_one_run_for_one_occurrence(self) -> None:
        """End-to-end: two runtimes racing one occurrence both report the winner."""

        path = self._factory.db_path
        store = SqliteClawAutomationStore(path)
        store.save_rule(make_rule("race_tick"))
        other = SqliteClawAutomationStore(path)

        receipt_one = ClawAutomationTickRuntime(store).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        # The second runtime's pre-check would see the existing run, so this is
        # the sequential manifestation of the same invariant.
        receipt_two = ClawAutomationTickRuntime(other).tick(
            workspace_id=WORKSPACE, current_time=WHEN, membership=membership()
        )
        self.assertEqual(len(receipt_one.created_run_ids), 1)
        self.assertEqual(receipt_two.created_run_ids, ())

        direct = sqlite3.connect(path)
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 1
        )
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 1
        )


class DeterministicRunIdRaceTests(unittest.TestCase):
    """(26) Real runtime semantics: one occurrence, one deterministic run_id.

    The pre-existing race tests use two arbitrary ids (``runA`` / ``runB``). The
    actual runtime does NOT do that: ``FakeClawScheduler.execute_rule_dry_run``
    derives ``run_id`` from ``occurrence_key(workspace_id, rule_id,
    scheduled_time)``, so two concurrent contenders for the SAME logical
    occurrence carry the SAME ``run_id``.

    That distinction is security relevant. A loser that blindly deletes
    ``run_id`` would delete the winner's canonical run, because both writers
    name the same row. The loser must therefore delete nothing at all: under
    claim-first ordering it never inserted a run row to begin with.
    """

    def setUp(self) -> None:
        self._factory = SqliteStoreFactory()
        self.addCleanup(self._factory.cleanup)

    def _stale_precheck_once(self, store: SqliteClawAutomationStore):
        """Force only the FIRST occurrence lookup to see a stale ``None``.

        ``record_run`` uses ``_get_occurrence_run_id`` twice: once for its
        untrustworthy pre-check and once to resolve the canonical winner after a
        lost claim. Stubbing the whole method would corrupt the second call too,
        so this stub is consumed after one invocation.
        """

        original = store._get_occurrence_run_id
        state = {"used": False}

        def stale(key, workspace_id):
            if not state["used"]:
                state["used"] = True
                return None
            return original(key, workspace_id)

        store._get_occurrence_run_id = stale  # type: ignore[method-assign]
        return original

    def _canonical_run(self, store: SqliteClawAutomationStore) -> ClawScheduledRun:
        """Mint the real derived run for the rule/instant under test."""

        rule = make_rule("deterministic")
        store.save_rule(rule)
        scheduler = FakeClawScheduler(store)
        return scheduler.execute_rule_dry_run(rule, WHEN, membership())

    def test_same_run_id_loser_never_deletes_the_canonical_run(self) -> None:
        """The winner's canonical row must survive the loser's write entirely."""

        path = self._factory.db_path
        SqliteClawAutomationStore(path)  # create schema
        writer = SqliteClawAutomationStore(path)
        winner = SqliteClawAutomationStore(path)

        canonical = self._canonical_run(winner)
        run_id = canonical.run_id
        key = occurrence_key(WORKSPACE, "deterministic", WHEN)

        # Force the loser's pre-check to observe the stale "no run yet" view,
        # exactly as it would in a real interleaving before the winner commits.
        original_precheck = self._stale_precheck_once(writer)

        # Same occurrence AND same deterministic run_id as the canonical run.
        contender = ClawScheduledRun(
            run_id=run_id,
            workspace_id=WORKSPACE,
            rule_id="deterministic",
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=WHEN,
            started_at=WHEN,
            completed_at=WHEN,
        )

        returned = writer.record_run(contender)
        writer._get_occurrence_run_id = original_precheck  # type: ignore[method-assign]

        # The loser must adopt the winner, wherever the race resolved.
        direct = sqlite3.connect(path)
        runs = direct.execute("SELECT run_id FROM claw_runs").fetchall()
        occurrences = direct.execute(
            "SELECT occurrence_key, run_id FROM claw_occurrences"
        ).fetchall()

        self.assertEqual(
            [r[0] for r in runs], [run_id], "the canonical run must not be deleted"
        )
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0],
            1,
            "exactly one canonical run may exist for one occurrence",
        )
        self.assertEqual(
            [(o[0], o[1]) for o in occurrences],
            [(key, run_id)],
            "the occurrence must still point at the canonical run",
        )
        # The canonical run row survived and is still readable.
        self.assertIsNotNone(winner.get_run(run_id, WORKSPACE))
        # Both callers resolve to the one canonical run.
        self.assertEqual(returned.run_id, run_id)
        # No dangling occurrence claim: the referenced run must exist.
        self.assertEqual(
            direct.execute(
                "SELECT COUNT(*) FROM claw_occurrences o "
                "LEFT JOIN claw_runs r ON r.run_id = o.run_id "
                "WHERE r.run_id IS NULL"
            ).fetchone()[0],
            0,
            "no occurrence may reference a missing run",
        )

    def test_same_run_id_loser_writes_no_run_and_no_proposal(self) -> None:
        """A losing writer must leave DELETE=0 / INSERT_RUN=0 / INSERT_PROPOSAL=0."""

        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        winner = SqliteClawAutomationStore(path)
        canonical = self._canonical_run(winner)

        writer = SqliteClawAutomationStore(path)
        before_runs = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM claw_runs"
        ).fetchone()[0]
        before_proposals = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM claw_proposals"
        ).fetchone()[0]

        # Make the claim fail deterministically, and record statement text so
        # the loser's write scope can be inspected precisely. The loser is
        # allowed exactly one INSERT (the occurrence claim attempt) and must
        # never DELETE, never insert a run row and never insert a proposal.
        statements: list[str] = []
        original_execute = writer._db.execute

        def recording(sql, *args):
            if isinstance(sql, str):
                statements.append(sql)
            return original_execute(sql, *args)

        _install_faulty_execute(writer, recording)
        self._stale_precheck_once(writer)

        contender = ClawScheduledRun(
            run_id=canonical.run_id,
            workspace_id=WORKSPACE,
            rule_id="deterministic",
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=WHEN,
            started_at=WHEN,
            completed_at=WHEN,
        )
        writer.record_run(contender)

        after_runs = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM claw_runs"
        ).fetchone()[0]
        after_proposals = sqlite3.connect(path).execute(
            "SELECT COUNT(*) FROM claw_proposals"
        ).fetchone()[0]

        self.assertEqual(
            [s for s in statements if s.strip().upper().startswith("DELETE")],
            [],
            "the loser must never issue a DELETE",
        )
        self.assertEqual(
            [s for s in statements if "INTO claw_runs" in s],
            [],
            "the loser must never insert a run row",
        )
        self.assertEqual(
            [s for s in statements if "INTO claw_proposals" in s],
            [],
            "the loser must never insert a proposal",
        )
        # Exactly one COMMIT: the transaction is closed exactly once.
        self.assertEqual(
            len([s for s in statements if s.strip().upper() == "COMMIT"]),
            1,
            "exactly one COMMIT must be issued",
        )
        self.assertEqual(
            [s for s in statements if s.strip().upper() == "ROLLBACK"],
            [],
            "the loser path must not need a ROLLBACK",
        )
        self.assertEqual(after_runs, before_runs, "loser must not change the run count")
        self.assertEqual(
            after_proposals,
            before_proposals,
            "loser must not persist any proposal",
        )
        self.assertIsNotNone(winner.get_run(canonical.run_id, WORKSPACE))

    def test_same_run_id_different_occurrence_fails_closed(self) -> None:
        """Reusing one run_id for an unrelated occurrence must not alias rows."""

        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        store = SqliteClawAutomationStore(path)

        canonical_rule = make_rule("alpha")
        store.save_rule(canonical_rule)
        scheduler = FakeClawScheduler(store)
        canonical = scheduler.execute_rule_dry_run(canonical_rule, WHEN, membership())

        # Same run_id, but a DIFFERENT logical occurrence (other rule + instant).
        other_instant = WHEN + timedelta(days=1)
        aliasing = ClawScheduledRun(
            run_id=canonical.run_id,
            workspace_id=WORKSPACE,
            rule_id="beta",
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=other_instant,
            started_at=other_instant,
            completed_at=other_instant,
        )

        with self.assertRaises(ContractError):
            store.record_run(aliasing)

        direct = sqlite3.connect(path)
        # The unrelated occurrence must never have been created.
        other_key = occurrence_key(WORKSPACE, "beta", other_instant)
        self.assertIsNone(
            direct.execute(
                "SELECT run_id FROM claw_occurrences WHERE occurrence_key = ?",
                (other_key,),
            ).fetchone(),
            "RUN_ID_ALIASING must be impossible",
        )
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 1
        )
        # The original canonical run is untouched.
        self.assertIsNotNone(store.get_run(canonical.run_id, WORKSPACE))

    def test_in_memory_store_enforces_the_same_aliasing_boundary(self) -> None:
        """The contract must not differ by backend: in-memory fails closed too."""

        store = InMemoryClawAutomationStore()
        rule = make_rule("alpha")
        store.save_rule(rule)
        canonical = FakeClawScheduler(store).execute_rule_dry_run(rule, WHEN, membership())

        other_instant = WHEN + timedelta(days=1)
        aliasing = ClawScheduledRun(
            run_id=canonical.run_id,
            workspace_id=WORKSPACE,
            rule_id="beta",
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=other_instant,
            started_at=other_instant,
            completed_at=other_instant,
        )
        with self.assertRaises(ContractError):
            store.record_run(aliasing)

        # Exactly one occurrence claim survives, and it points at the canonical run.
        self.assertEqual(len(store._occurrences), 1)
        self.assertEqual(list(store._occurrences.values()), [canonical.run_id])
        self.assertEqual(list(store._runs), [canonical.run_id])

    def test_one_occurrence_yields_exactly_one_canonical_run(self) -> None:
        """ONE_OCCURRENCE_MAX_RUNS must be exactly 1, with no orphans either side."""

        path = self._factory.db_path
        SqliteClawAutomationStore(path)
        winner = SqliteClawAutomationStore(path)
        rule = make_rule("deterministic")
        winner.save_rule(rule)
        canonical = FakeClawScheduler(winner).execute_rule_dry_run(rule, WHEN, membership())

        writer = SqliteClawAutomationStore(path)
        self._stale_precheck_once(writer)
        writer.record_run(
            ClawScheduledRun(
                run_id=canonical.run_id,
                workspace_id=WORKSPACE,
                rule_id="deterministic",
                status=ClawScheduledRunStatus.COMPLETED,
                scheduled_time=WHEN,
                started_at=WHEN,
                completed_at=WHEN,
            )
        )

        direct = sqlite3.connect(path)
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0],
            1,
            "ONE_OCCURRENCE_MAX_RUNS must be 1",
        )
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 1
        )
        # ORPHAN_RUNS = runs not referenced by any occurrence.
        self.assertEqual(
            direct.execute(
                "SELECT COUNT(*) FROM claw_runs r "
                "LEFT JOIN claw_occurrences o ON o.run_id = r.run_id "
                "WHERE o.run_id IS NULL"
            ).fetchone()[0],
            0,
            "ORPHAN_RUNS must be 0",
        )
        # ORPHAN_OCCURRENCES = occurrences not backed by a run.
        self.assertEqual(
            direct.execute(
                "SELECT COUNT(*) FROM claw_occurrences o "
                "LEFT JOIN claw_runs r ON r.run_id = o.run_id "
                "WHERE r.run_id IS NULL"
            ).fetchone()[0],
            0,
            "ORPHAN_OCCURRENCES must be 0",
        )


class StoreFailureInjectionTests(unittest.TestCase):
    """(21) A broken durable store must never yield a partial success receipt."""

    def setUp(self) -> None:
        self._factory = SqliteStoreFactory()
        self.addCleanup(self._factory.cleanup)

    def test_occurrence_write_failure_rolls_back_the_run(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("rollback"))
        original = store._db.execute
        calls = {"n": 0}

        def flaky(sql, *args):
            if "INSERT OR IGNORE INTO claw_occurrences" in sql:
                calls["n"] += 1
                raise sqlite3.OperationalError("injected occurrence failure")
            return original(sql, *args)

        _install_faulty_execute(store, flaky)
        runtime = ClawAutomationTickRuntime(store)
        with self.assertRaises((ContractError, sqlite3.OperationalError)):
            runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=membership())
        self.assertGreaterEqual(calls["n"], 1)

        _install_faulty_execute(store, original)
        # The failed tick must not have left a run behind.
        direct = sqlite3.connect(self._factory.db_path)
        self.assertEqual(direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 0)
        self.assertEqual(
            direct.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0], 0
        )

    def test_membership_check_precedes_any_store_write(self) -> None:
        store = self._factory()
        store.save_rule(make_rule("no_write_when_expired"))
        expired = TrustedWorkspaceMembershipProjection(
            membership_id="membership:expired",
            workspace_id=WORKSPACE,
            principal_ref="principal:user",
            role=WorkspaceRole.OWNER,
            authority_ref="control-plane:membership",
            issued_at=WHEN - timedelta(hours=3),
            expires_at=WHEN - timedelta(hours=2),
        )
        runtime = ClawAutomationTickRuntime(store)
        runtime.tick(workspace_id=WORKSPACE, current_time=WHEN, membership=expired)
        direct = sqlite3.connect(self._factory.db_path)
        self.assertEqual(direct.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0], 0)


class FakeClawSchedulerRegressionTests(unittest.TestCase):
    """(25) The pre-existing scheduler semantics must be untouched by this slice."""

    def setUp(self) -> None:
        self._factory = SqliteStoreFactory()
        self.addCleanup(self._factory.cleanup)

    def test_fake_scheduler_due_dry_run_and_next_occurrence_unchanged(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        scheduler = FakeClawScheduler(store)
        item = make_rule("regress")
        store.save_rule(item)

        due = scheduler.due_occurrences(WORKSPACE, WHEN, membership())
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0][0].rule_id, "regress")
        self.assertEqual(due[0][1], WHEN)

        run = scheduler.execute_rule_dry_run(item, WHEN, membership())
        self.assertEqual(run.status, ClawScheduledRunStatus.COMPLETED)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

        # Replay is deduped exactly as before.
        replayed = scheduler.execute_rule_dry_run(item, WHEN, membership())
        self.assertEqual(replayed.run_id, run.run_id)

        nxt = scheduler.compute_next_occurrence(item, WHEN)
        self.assertEqual(nxt, WHEN + timedelta(days=1))

    def test_fake_scheduler_membership_none_still_permitted_for_reference_use(self) -> None:
        """The reference scheduler keeps its optional-membership contract.

        Only the tick runtime makes membership mandatory; the pre-existing
        scheduler signature must not change.
        """

        store = InMemoryClawAutomationStore()
        scheduler = FakeClawScheduler(store)
        item = make_rule("optional_membership")
        store.save_rule(item)
        self.assertEqual(len(scheduler.due_occurrences(WORKSPACE, WHEN)), 1)
        self.assertEqual(len(scheduler.evaluate_due_rules(WORKSPACE, WHEN)), 1)

    def test_tick_runtime_reuses_scheduler_candidate_semantics(self) -> None:
        store = SqliteClawAutomationStore(":memory:")
        runtime = ClawAutomationTickRuntime(store)
        self.assertIsInstance(runtime.scheduler, FakeClawScheduler)

    def test_existing_occurrence_key_shape_is_unchanged(self) -> None:
        key = occurrence_key(WORKSPACE, "r", WHEN)
        self.assertTrue(key.startswith("claw_occurrence_v1_"))
        self.assertEqual(len(key.split("_")[-1]), 64)


if __name__ == "__main__":
    unittest.main()
