"""#2833 B2A — rule owner provenance (opaque, authority-free).

Covers the bounded contract added to ``ClawAutomationRule``:

- ``owner_ref`` is an optional bounded opaque reference attached by trusted
  product composition at rule creation. It is NOT assumed to be a B62 usr_*
  product id, a canonical subject, or a membership principal_ref, and no
  semantic equivalence with any of those is enforced.
- It grants no authority: the tick runtime still requires a trusted
  workspace membership projection; owner_ref presence never bypasses
  membership, expiry, or workspace-match checks.
- Owner provenance is immutable after rule creation: generic saves/updates
  fail closed on any transfer, drop, or mint of the value.
- Durability rides inside the existing SQLite JSON payload (no new table,
  no new column); legacy payloads without the key read owner_ref=None.
- owner_ref never leaks into tick receipts, outputs, proposals, or error
  text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawNotificationChannel,
    ClawScheduleExpression,
    ClawScheduleKind,
    FakeClawScheduler,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
)
from kagent.contracts import ContractError
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
OWNER_A = "owner-alpha-001"
OWNER_B = "owner-beta-002"
OWNER_REF = "opaque-delivery-owner"


def rule(
    rule_id: str = "rule_owner",
    workspace_id: str = "ws_owner",
    *,
    owner_ref: str | None = OWNER_REF,
    enabled: bool = True,
    expression: str = "0 9 * * *",
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="정기 소유 규칙",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, expression),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        owner_ref=owner_ref,
    )


def membership(workspace_id: str = "ws_owner", *, expires_at: datetime | None = None) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id="membership:owner",
        workspace_id=workspace_id,
        principal_ref="principal:user",
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=NOW - timedelta(hours=1),
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def fresh_sqlite_store(path: str | None = None) -> SqliteClawAutomationStore:
    if path is None:
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        handle.close()
        path = handle.name
    return SqliteClawAutomationStore(path)


class RuleOwnerProvenanceCreationTests(unittest.TestCase):
    def test_01_legacy_rule_without_owner_ref_is_accepted(self) -> None:
        # Positional compatibility: seven positional args end at enabled.
        legacy = ClawAutomationRule(
            "rule_legacy",
            "ws_legacy",
            "레거시 규칙",
            ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
            ClawAutomationTarget.INBOX,
            ClawAutomationOutputType.REPORT,
            True,
        )
        self.assertIsNone(legacy.owner_ref)
        self.assertTrue(legacy.enabled)

    def test_02_safe_opaque_owner_ref_is_accepted(self) -> None:
        item = rule(owner_ref=OWNER_REF)
        self.assertEqual(item.owner_ref, OWNER_REF)

    def test_03_invalid_owner_ref_shape_fails_closed_without_echo(self) -> None:
        for bad in ("", "   ", "has space", 123, "x" * 200, "bad\nnewline"):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ContractError) as ctx:
                    rule(owner_ref=bad)  # type: ignore[arg-type]
                self.assertNotIn("owner-alpha", str(ctx.exception))
                if isinstance(bad, str) and bad.strip() and bad not in ("", "   "):
                    self.assertNotIn(bad, str(ctx.exception), "rejected owner_ref must not be echoed")

    def test_04_owner_ref_is_opaque_and_never_equated_to_principal_ref(self) -> None:
        # A principal_ref-shaped value is stored verbatim: no transform, no
        # hashing, no equality constraint against membership.principal_ref.
        item = rule(owner_ref="principal:user")
        self.assertEqual(item.owner_ref, "principal:user")
        store = InMemoryClawAutomationStore()
        store.save_rule(item)
        runtime = ClawAutomationTickRuntime(store)
        # A membership whose principal_ref differs from owner_ref still runs:
        # the contract enforces no semantic equivalence between the two, and
        # owner_ref presence neither adds nor removes tick authority.
        receipt = runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership())
        self.assertEqual(len(receipt.created_run_ids), 1)
        # A membership principal_ref is never read as, or into, owner_ref:
        # distinct opaque values stay distinct with no normalization.
        unrelated = TrustedWorkspaceMembershipProjection(
            membership_id="membership:other-principal",
            workspace_id="ws_owner",
            principal_ref="principal:someone-else",
            role=WorkspaceRole.OWNER,
            authority_ref="control-plane:membership",
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
        )
        self.assertNotEqual(item.owner_ref, unrelated.principal_ref)


class InMemoryOwnerProvenanceTests(unittest.TestCase):
    def test_05_inmemory_save_get_roundtrip_preserves_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        self.assertEqual(store.get_rule("rule_owner", "ws_owner").owner_ref, OWNER_REF)

    def test_06_inmemory_list_rules_preserves_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule("rule_a"))
        store.save_rule(rule("rule_b", owner_ref=None))
        owners = {item.rule_id: item.owner_ref for item in store.list_rules("ws_owner")}
        self.assertEqual(owners, {"rule_a": OWNER_REF, "rule_b": None})

    def test_07_inmemory_set_rule_enabled_preserves_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        updated = store.set_rule_enabled("ws_owner", "rule_owner", False)
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.owner_ref, OWNER_REF)
        self.assertEqual(store.get_rule("rule_owner", "ws_owner").owner_ref, OWNER_REF)


class SqliteOwnerProvenanceTests(unittest.TestCase):
    def test_08_sqlite_save_get_roundtrip_preserves_owner_ref(self) -> None:
        store = fresh_sqlite_store()
        try:
            store.save_rule(rule())
            self.assertEqual(store.get_rule("rule_owner", "ws_owner").owner_ref, OWNER_REF)
        finally:
            store._db.close()

    def test_09_sqlite_reopen_roundtrip_preserves_owner_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule())
            store._db.close()
            reopened = SqliteClawAutomationStore(path)
            try:
                self.assertEqual(reopened.get_rule("rule_owner", "ws_owner").owner_ref, OWNER_REF)
            finally:
                reopened._db.close()

    def test_10_legacy_payload_without_owner_ref_reads_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "legacy.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule("seed"))  # ensure schema exists
            store._db.close()
            # Simulate a pre-B2A writer: same columns, JSON payload without
            # any owner_ref key, exactly like rows written before this slice.
            legacy_payload = json.dumps(
                {
                    "rule_id": "rule_legacy_row",
                    "workspace_id": "ws_owner",
                    "name": "레거시 규칙",
                    "schedule": {"kind": "cron", "expression": "0 9 * * *", "timezone": "UTC"},
                    "target_source": "inbox",
                    "output_type": "report",
                    "enabled": True,
                    "notification_channels": [{"channel": "web_alert_inbox", "enabled": True, "recipient_ref": None}],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            raw = sqlite3.connect(path)
            try:
                raw.execute(
                    "INSERT INTO claw_rules(rule_id, workspace_id, name, schedule_kind, schedule_expression, "
                    "schedule_timezone, target_source, output_type, enabled, notification_channels, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "rule_legacy_row", "ws_owner", "레거시 규칙", "cron", "0 9 * * *", "UTC",
                        "inbox", "report", 1, legacy_payload.encode("utf-8"), NOW.isoformat(), NOW.isoformat(),
                    ),
                )
                raw.commit()
            finally:
                raw.close()
            reopened = SqliteClawAutomationStore(path)
            try:
                legacy = reopened.get_rule("rule_legacy_row", "ws_owner")
                self.assertIsNotNone(legacy)
                self.assertIsNone(legacy.owner_ref)  # type: ignore[union-attr]
                self.assertEqual(legacy.name, "레거시 규칙")  # type: ignore[union-attr]
            finally:
                reopened._db.close()


class OwnerImmutabilityTests(unittest.TestCase):
    def test_11_same_rule_same_owner_generic_update_passes(self) -> None:
        for make in (InMemoryClawAutomationStore, fresh_sqlite_store):
            with self.subTest(store=make.__name__):
                store = make()
                try:
                    store.save_rule(rule())
                    updated = rule(enabled=False)
                    store.update_rule(updated)
                    stored = store.get_rule("rule_owner", "ws_owner")
                    self.assertFalse(stored.enabled)  # type: ignore[union-attr]
                    self.assertEqual(stored.owner_ref, OWNER_REF)  # type: ignore[union-attr]
                finally:
                    if isinstance(store, SqliteClawAutomationStore):
                        store._db.close()

    def test_12_same_rule_different_owner_fails_closed(self) -> None:
        for make in (InMemoryClawAutomationStore, fresh_sqlite_store):
            with self.subTest(store=make.__name__):
                store = make()
                try:
                    store.save_rule(rule(owner_ref=OWNER_A))
                    with self.assertRaises(ContractError):
                        store.update_rule(rule(owner_ref=OWNER_B))
                    self.assertEqual(store.get_rule("rule_owner", "ws_owner").owner_ref, OWNER_A)
                finally:
                    if isinstance(store, SqliteClawAutomationStore):
                        store._db.close()

    def test_13_legacy_none_owner_cannot_be_claimed_by_generic_update(self) -> None:
        for make in (InMemoryClawAutomationStore, fresh_sqlite_store):
            with self.subTest(store=make.__name__):
                store = make()
                try:
                    store.save_rule(rule(owner_ref=None))
                    with self.assertRaises(ContractError):
                        store.update_rule(rule(owner_ref=OWNER_A))
                    self.assertIsNone(store.get_rule("rule_owner", "ws_owner").owner_ref)
                finally:
                    if isinstance(store, SqliteClawAutomationStore):
                        store._db.close()


class OwnerRefAuthorityIsolationTests(unittest.TestCase):
    def test_14_owner_ref_without_membership_grants_no_tick_authority(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        runtime = ClawAutomationTickRuntime(store)
        with self.assertRaises(ContractError):
            runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=None)

    def test_15_expired_membership_with_owner_ref_keeps_zero_run_semantics(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        runtime = ClawAutomationTickRuntime(store)
        expired = membership(expires_at=NOW - timedelta(minutes=1))
        receipt = runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=expired)
        self.assertEqual(receipt.due_count, 0)
        self.assertEqual(receipt.created_run_ids, ())
        self.assertEqual(receipt.deduplicated_count, 0)

    def test_16_foreign_workspace_membership_with_owner_ref_fails_closed(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        runtime = ClawAutomationTickRuntime(store)
        with self.assertRaises(ContractError):
            runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership("ws_other"))


class OwnerRefLeakPreventionTests(unittest.TestCase):
    def test_17_tick_receipt_leaks_no_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership())
        public = receipt.safe_dict()
        self.assertNotIn("owner_ref", public)
        self.assertNotIn(OWNER_REF, json.dumps(public, ensure_ascii=True))

    def test_18_output_and_proposal_leak_no_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        item = rule()
        store.save_rule(item)
        scheduler = FakeClawScheduler(store)
        run = scheduler.execute_rule_dry_run(item, NOW, membership())
        proposal_public = json.dumps(
            [proposal.safe_dict() for proposal in run.output.proposals], ensure_ascii=True
        )
        serialized_output = SqliteClawAutomationStore._serialize_output(run.output)
        self.assertNotIn("owner_ref", proposal_public)
        self.assertNotIn(OWNER_REF, proposal_public)
        self.assertIsNotNone(serialized_output)
        self.assertNotIn("owner_ref", serialized_output)  # type: ignore[arg-type]
        self.assertNotIn(OWNER_REF, serialized_output)  # type: ignore[arg-type]


class LegacyBehaviorPreservationTests(unittest.TestCase):
    def test_19_run_dedup_unchanged_with_owner_ref(self) -> None:
        store = InMemoryClawAutomationStore()
        item = rule()
        store.save_rule(item)
        runtime = ClawAutomationTickRuntime(store)
        first = runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership())
        self.assertEqual(len(first.created_run_ids), 1)
        # Canonical replay semantics (unchanged): the consumed occurrence is
        # no longer due, so the replayed tick is a zero-run no-op, and exactly
        # one durable run exists for the logical occurrence.
        second = runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership())
        self.assertEqual(second.created_run_ids, ())
        self.assertEqual(second.due_count, 0)
        self.assertEqual(second.deduplicated_count, 0)
        self.assertEqual(len(store.list_runs("ws_owner")), 1)
        # Same rule/occurrence without owner_ref behaves identically.
        legacy_store = InMemoryClawAutomationStore()
        legacy_store.save_rule(rule(owner_ref=None))
        legacy_runtime = ClawAutomationTickRuntime(legacy_store)
        legacy_first = legacy_runtime.tick(workspace_id="ws_owner", current_time=NOW, membership=membership())
        self.assertEqual(len(legacy_first.created_run_ids), 1)
        self.assertEqual(legacy_first.created_run_ids, first.created_run_ids)

    def test_20_run_ids_unchanged_regardless_of_owner_ref(self) -> None:
        scheduled = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
        without = FakeClawScheduler(InMemoryClawAutomationStore()).execute_rule_dry_run(
            rule(owner_ref=None), scheduled, membership()
        )
        with_ref = FakeClawScheduler(InMemoryClawAutomationStore()).execute_rule_dry_run(
            rule(owner_ref=OWNER_A), scheduled, membership()
        )
        self.assertEqual(without.run_id, with_ref.run_id)


if __name__ == "__main__":
    unittest.main()
