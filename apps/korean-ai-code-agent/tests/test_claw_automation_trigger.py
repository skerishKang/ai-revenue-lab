"""#2833 S-1 trusted background scheduler trigger boundary tests.

This module tests ``ClawAutomationTriggerBoundary``: the trusted source boundary
that turns one scheduler trigger into exactly one durable tick for one explicit
workspace, by delegating to the pre-existing ``ClawAutomationTickRuntime``.

Design boundaries pinned here:

* ONE_TRIGGER_ONE_WORKSPACE. A trigger names exactly one workspace and there is
  no enumeration path, so a trigger can never sweep every workspace.
* Membership is REQUIRED and must be the authoritative projection. ``None``, a
  dict, a bare id, ``0`` and ``False`` all fail closed, so an absent projection
  can never become a wildcard background grant.
* A foreign projection is refused; an expired or not-yet-valid projection yields
  zero runs without an error.
* The boundary adds no scheduling algorithm, no second dedup authority and no
  store. Duplicate delivery is absorbed by the existing ``occurrence_key`` claim.
* Only the exact observed instant is evaluated: no backfill, no catch-up.
* No provider call, no external send, no connector write, no canonical dispatch
  and no sandbox allocation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ContractError,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
)
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
    ClawAutomationTriggerReceipt,
)
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

UTC = timezone.utc
WHEN = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RECEIPT_KEYS = {
    "trigger_id",
    "correlation_id",
    "workspace_id",
    "observed_at",
    "due_count",
    "created_run_ids",
    "deduplicated_count",
    "provider_calls",
    "external_sends",
    "connector_writes",
    "canonical_dispatches",
    "sandbox_allocations",
    "catch_up_occurrences",
    "background_trigger_source",
    "production_scheduler",
    "canonical_dispatch",
    "client_asserted_authority",
}
FORBIDDEN_MARKERS = (
    "secret",
    "token",
    "credential",
    "api_key",
    "provider_response",
    "authority_ref",
    "principal_ref",
    "claim_token",
)


def make_rule(
    rule_id: str,
    workspace_id: str = WORKSPACE,
    *,
    expression: str = "0 9 * * *",
    enabled: bool = True,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, expression, "UTC"),
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
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id="membership:owner",
        workspace_id=workspace_id,
        principal_ref="principal:user",
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=at + timedelta(hours=issued_offset_hours),
        expires_at=at + timedelta(hours=expires_offset_hours),
    )


def make_trigger(
    *,
    workspace_id: str = WORKSPACE,
    observed_at: datetime = WHEN,
    membership_projection: object = None,
    trigger_id: str = "trigger:cloud_cron",
    correlation_id: str = "corr:0001",
) -> ClawAutomationTrigger:
    if membership_projection is None:
        membership_projection = membership(workspace_id, at=observed_at)
    return ClawAutomationTrigger(
        trigger_id=trigger_id,
        correlation_id=correlation_id,
        workspace_id=workspace_id,
        observed_at=observed_at,
        membership=membership_projection,
    )


class SqliteFileFactory:
    """A real temp-file SQLite store, so a reopen simulates process restart."""

    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "claw_trigger.db")

    def __call__(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def reopen(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        # Windows keeps the file locked while a handle is open, so cleanup is
        # best-effort exactly like the pre-existing scheduler-runtime suite.
        for path in (self.db_path, f"{self.db_path}-wal", f"{self.db_path}-shm"):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._dir)
        except OSError:
            pass


class _CountingStore(InMemoryClawAutomationStore):
    """Records the mutating calls the boundary indirectly causes."""

    def __init__(self) -> None:
        super().__init__()
        self.record_run_calls = 0

    def record_run(self, run):  # type: ignore[override]
        self.record_run_calls += 1
        return super().record_run(run)


class TrustedTriggerTests(unittest.TestCase):
    def _factories(self):
        yield (lambda: InMemoryClawAutomationStore(), False)
        yield (self._sqlite, True)

    def setUp(self) -> None:
        self._sqlite = SqliteFileFactory()

    def tearDown(self) -> None:
        self._sqlite.cleanup()

    # --- TRUSTED_TRIGGER_ACCEPTED -----------------------------------------

    def test_trusted_trigger_accepted_creates_exactly_one_durable_run(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

                receipt = boundary.handle(make_trigger())

                self.assertIsInstance(receipt, ClawAutomationTriggerReceipt)
                self.assertEqual(receipt.workspace_id, WORKSPACE)
                self.assertEqual(receipt.observed_at, WHEN)
                self.assertEqual(receipt.trigger_id, "trigger:cloud_cron")
                self.assertEqual(receipt.correlation_id, "corr:0001")
                self.assertEqual(receipt.due_count, 1)
                self.assertEqual(len(receipt.created_run_ids), 1)
                self.assertEqual(receipt.deduplicated_count, 0)
                runs = store.list_runs(WORKSPACE)
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0].rule_id, "due")

    # --- MISSING_MEMBERSHIP_FAIL_CLOSED -----------------------------------

    def test_missing_or_caller_minted_membership_fails_closed(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("due"))
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

        for attempt in (None, {}, "workspace_a", 0, False, "membership:owner"):
            with self.subTest(membership=repr(attempt)):
                with self.assertRaises(ContractError):
                    ClawAutomationTrigger(
                        trigger_id="trigger:cloud_cron",
                        correlation_id="corr:0001",
                        workspace_id=WORKSPACE,
                        observed_at=WHEN,
                        membership=attempt,  # type: ignore[arg-type]
                    )
        self.assertEqual(store.list_runs(WORKSPACE), [])

        # The boundary is not a second door for a non-trigger payload.
        with self.assertRaises(ContractError):
            boundary.handle("trigger:cloud_cron")  # type: ignore[arg-type]
        self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- FOREIGN_MEMBERSHIP_FAIL_CLOSED -----------------------------------

    def test_foreign_membership_fails_closed(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

                foreign = make_trigger(
                    membership_projection=membership(OTHER_WORKSPACE)
                )
                with self.assertRaises(ContractError):
                    boundary.handle(foreign)
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- EXPIRED_MEMBERSHIP_ZERO_RUNS -------------------------------------

    def test_expired_and_not_yet_valid_membership_produce_zero_runs(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

                expired = make_trigger(
                    membership_projection=membership(
                        issued_offset_hours=-3, expires_offset_hours=-1
                    )
                )
                receipt = boundary.handle(expired)
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

                future = make_trigger(
                    membership_projection=membership(
                        issued_offset_hours=1, expires_offset_hours=2
                    )
                )
                receipt = boundary.handle(future)
                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- ONE_TRIGGER_ONE_WORKSPACE ----------------------------------------

    def test_one_trigger_one_workspace(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("due_a", WORKSPACE))
        store.save_rule(make_rule("due_b", OTHER_WORKSPACE))
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

        receipt = boundary.handle(make_trigger(workspace_id=WORKSPACE))

        self.assertEqual(receipt.workspace_id, WORKSPACE)
        self.assertEqual(len(store.list_runs(WORKSPACE)), 1)
        # The other workspace was never swept.
        self.assertEqual(store.list_runs(OTHER_WORKSPACE), [])

    # --- DUPLICATE_TRIGGER_DEDUP / DUPLICATE_CANONICAL_RUN = 0 ------------

    def test_duplicate_trigger_creates_no_second_canonical_run(self) -> None:
        for make_store, durable in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("due"))
                boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

                first = boundary.handle(make_trigger(correlation_id="corr:first"))
                second = boundary.handle(make_trigger(correlation_id="corr:second"))

                self.assertEqual(len(first.created_run_ids), 1)
                self.assertEqual(second.created_run_ids, ())
                self.assertEqual(len(store.list_runs(WORKSPACE)), 1)

                if durable:
                    # A brand-new handle on the same file proves restart safety.
                    reopened = self._sqlite.reopen()
                    again = ClawAutomationTriggerBoundary(
                        ClawAutomationTickRuntime(reopened)
                    ).handle(make_trigger(correlation_id="corr:third"))
                    self.assertEqual(again.created_run_ids, ())
                    self.assertEqual(len(reopened.list_runs(WORKSPACE)), 1)

    # --- DISABLED_RULE_EXECUTION = 0 --------------------------------------

    def test_disabled_rule_creates_zero_runs_via_trigger(self) -> None:
        for make_store, _ in self._factories():
            with self.subTest(store=type(make_store()).__name__):
                store = make_store()
                store.save_rule(make_rule("disabled", enabled=False))
                boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

                receipt = boundary.handle(make_trigger())

                self.assertEqual(receipt.due_count, 0)
                self.assertEqual(receipt.created_run_ids, ())
                self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- UNBOUNDED_CATCHUP = 0 --------------------------------------------

    def test_late_trigger_does_not_backfill_past_occurrences(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("daily_9am", expression="0 9 * * *"))
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

        # Three days late and NOT on an occurrence instant: nothing is due, and
        # the three missed 09:00 occurrences are never materialised.
        late_off_instant = make_trigger(
            observed_at=WHEN + timedelta(days=3, minutes=30),
            membership_projection=membership(
                at=WHEN + timedelta(days=3, minutes=30),
                issued_offset_hours=-1,
                expires_offset_hours=1,
            ),
        )
        receipt = boundary.handle(late_off_instant)

        self.assertEqual(receipt.due_count, 0)
        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(receipt.safe_dict()["catch_up_occurrences"], 0)
        self.assertEqual(store.list_runs(WORKSPACE), [])

    # --- side effects ------------------------------------------------------

    def test_side_effects_are_zero(self) -> None:
        store = _CountingStore()
        store.save_rule(make_rule("due"))
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

        receipt = boundary.handle(make_trigger())

        # The only store mutation is the durable occurrence claim made by the
        # reused tick runtime; the boundary itself writes nothing extra.
        self.assertEqual(store.record_run_calls, 1)
        self.assertEqual(len(receipt.created_run_ids), 1)

        payload = receipt.safe_dict()
        for marker in (
            "provider_calls",
            "external_sends",
            "connector_writes",
            "canonical_dispatches",
            "sandbox_allocations",
            "catch_up_occurrences",
        ):
            self.assertEqual(payload[marker], 0, marker)
        self.assertFalse(payload["production_scheduler"])
        self.assertFalse(payload["canonical_dispatch"])
        self.assertFalse(payload["client_asserted_authority"])

        contract = boundary.safe_dict()
        for marker in (
            "new_scheduler_algorithm",
            "new_dedup_authority",
            "automatic_backfill",
            "unbounded_catch_up",
            "workspace_enumeration",
            "production_scheduler_activation",
            "canonical_dispatch",
        ):
            self.assertFalse(contract[marker], marker)
        self.assertTrue(contract["one_trigger_one_workspace"])
        self.assertTrue(contract["reuses_tick_runtime"])
        self.assertFalse(contract["membership_may_be_omitted"])
        self.assertEqual(contract["catch_up_policy"], "none")

    def test_trigger_module_has_no_provider_network_or_shell_surface(self) -> None:
        import kagent.claw_automation_trigger as module

        with open(module.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in (
            "import httpx",
            "import requests",
            "import urllib",
            "import socket",
            "import subprocess",
            "os.system",
            "asyncio.sleep",
            "while True",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    # --- bounded, non-secret receipt --------------------------------------

    def test_receipt_is_bounded_and_carries_no_secret(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(make_rule("due"))
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))

        receipt = boundary.handle(make_trigger())

        self.assertEqual(set(receipt.safe_dict()), RECEIPT_KEYS)
        serialized = json.dumps(receipt.safe_dict()).lower()
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, serialized, marker)
        # The delegate tick receipt is embedded as plain counts, never as text.
        self.assertNotIn("output", serialized)
        self.assertNotIn("proposal", serialized)

    # --- trigger/contract validation --------------------------------------

    def test_trigger_and_boundary_validation(self) -> None:
        with self.assertRaises(ContractError):
            # naive instant
            ClawAutomationTrigger(
                trigger_id="trigger:cloud_cron",
                correlation_id="corr:0001",
                workspace_id=WORKSPACE,
                observed_at=datetime(2026, 9, 8, 9, 0),
                membership=membership(),
            )
        for bad in ("", "x" * 200, "bad id!", "bad@id", "-lead"):
            with self.subTest(value=bad):
                with self.assertRaises(ContractError):
                    make_trigger(trigger_id=bad)
        # Bounded ids are normalised, not silently widened: surrounding
        # whitespace is stripped by the shared id authority.
        self.assertEqual(make_trigger(trigger_id="  cloud_cron  ").trigger_id, "cloud_cron")

        store = InMemoryClawAutomationStore()
        with self.assertRaises(ContractError):
            ClawAutomationTriggerBoundary(store)  # type: ignore[arg-type]
