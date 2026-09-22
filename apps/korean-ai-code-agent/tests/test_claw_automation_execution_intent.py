"""#2833 S2F1 — immutable scheduled execution-intent foundation.

A rule created by a scheduler could not reach canonical execution because
``ClawTaskIntent`` requires a non-empty ``task`` and a ``repository_ref``, and
neither is derivable from any rule field. These tests pin the contract that
supplies those three values explicitly, and nothing more:

- ``ClawAutomationExecutionIntent`` is bounded, opaque to no credential material,
  and binds an exact 40-hex revision through the canonical contract predicate.
- ``intent_sha256`` is a deterministic digest of the versioned material.
- The safe projection carries digests, never the task body.
- ``ClawAutomationRule.execution_intent`` is optional and last, so legacy rules
  read ``None`` and legacy positional construction keeps working.
- The intent is immutable after creation on both backends: no swap, no drop, and
  no promotion of a legacy rule through a generic save/update.
- Persistence rides inside the existing rule JSON document: no table, column or
  migration.
- Tick and dry-run behaviour is unchanged; no dispatch, no P01 call, no owner
  resolution.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kagent.claw_automation import (
    EXECUTION_INTENT_VERSION,
    ONE_OCCURRENCE_MAX_CANONICAL_RUNS,
    PRODUCTION_SCHEDULER_ACTIVATION,
    REAL_BACKGROUND_TRIGGER,
    ClawAutomationExecutionIntent as Intent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    FakeClawScheduler,
    occurrence_key,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
)
from kagent.contracts import ContractError, ClawTaskIntent, ExecutionMode
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
TASK = "어제 완료된 작업을 요약해서 보고해줘"
REPOSITORY_REF = "skerishKang/ai-revenue-lab"
REVISION = "abcdef1234567890abcdef1234567890abcdef12"
OTHER_REVISION = "dddddd1234567890abcdef1234567890abcdef12"
UPPER_REVISION = REVISION.upper()
INTENT_A = {"task": TASK, "repository_ref": REPOSITORY_REF, "exact_revision": REVISION}
INTENT_B = {"task": "오늘 예정된 작업을 점검해줘", "repository_ref": REPOSITORY_REF, "exact_revision": REVISION}


def intent(**overrides: str) -> Intent:
    values = dict(INTENT_A)
    values.update(overrides)
    return Intent(**values)  # type: ignore[arg-type]


def rule(
    rule_id: str = "rule_intent",
    workspace_id: str = "ws_intent",
    *,
    owner_ref: str | None = None,
    execution_intent: Intent | None = None,
    enabled: bool = True,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="정기 실행 규칙",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        owner_ref=owner_ref,
        execution_intent=execution_intent,
    )


def membership(workspace_id: str = "ws_intent") -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id="membership:intent",
        workspace_id=workspace_id,
        principal_ref="principal:intent",
        role=WorkspaceRole.OWNER,
        authority_ref="control-plane:membership",
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )


class ExecutionIntentContractTests(unittest.TestCase):
    def test_valid_intent_is_accepted_and_fields_are_preserved(self):
        subject = intent()
        self.assertEqual(subject.task, TASK)
        self.assertEqual(subject.repository_ref, REPOSITORY_REF)

    def test_uppercase_revision_is_normalized_by_the_canonical_predicate(self):
        self.assertEqual(intent(exact_revision=UPPER_REVISION).exact_revision, REVISION)

    def test_mutable_ref_and_abbreviated_revision_are_rejected(self):
        for bad in ("main", "refs/heads/main", "v1.2.3", REVISION[:12], "", "  ", REVISION + "0"):
            with self.subTest(revision=bad):
                with self.assertRaises(ContractError):
                    intent(exact_revision=bad)

    def test_task_bounds_reject_empty_oversize_and_control_characters(self):
        for bad in ("", "   ", "x" * 12_001, "line\x00break", "bell\x07ring"):
            with self.subTest(task=repr(bad)[:24]):
                with self.assertRaises(ContractError):
                    intent(task=bad)

    def test_task_limit_matches_the_canonical_input_requirement(self):
        self.assertEqual(len(intent(task="y" * 12_000).task), 12_000)

    def test_repository_ref_bounds_are_enforced(self):
        for bad in ("", "   ", "r" * 1_025):
            with self.subTest(repository_ref=repr(bad)[:12]):
                with self.assertRaises(ContractError):
                    intent(repository_ref=bad)

    def test_credential_material_fails_closed_in_either_field(self):
        for kwargs in (
            {"task": "token=ghp_16C7e4YNym5ZnqD1sPnRz3gT4mEoqr3xKL7"},
            {"task": "run password=hunter22here"},
            {"repository_ref": "org/repo?key=AKIAIOSFODNN7EXAMPLE"},
        ):
            with self.subTest(**{k: v[:18] for k, v in kwargs.items()}):
                with self.assertRaises(ContractError):
                    intent(**kwargs)  # type: ignore[arg-type]

    def test_non_string_inputs_are_rejected(self):
        for kwargs in ({"task": None}, {"repository_ref": 5}, {"exact_revision": ["a"]}):
            with self.subTest(fields=list(kwargs)):
                with self.assertRaises(ContractError):
                    intent(**kwargs)  # type: ignore[arg-type]


class CanonicalDigestTests(unittest.TestCase):
    def test_digest_is_deterministic_for_identical_material(self):
        self.assertEqual(intent().intent_sha256, intent().intent_sha256)
        self.assertEqual(intent().intent_sha256, intent(exact_revision=UPPER_REVISION).intent_sha256)

    def test_digest_changes_when_any_single_field_changes(self):
        base = intent().intent_sha256
        self.assertNotEqual(base, intent(**INTENT_B).intent_sha256)
        self.assertNotEqual(base, intent(repository_ref="other/repository").intent_sha256)
        self.assertNotEqual(base, intent(exact_revision=OTHER_REVISION).intent_sha256)

    def test_digest_is_stable_against_key_ordering_and_is_a_sha256(self):
        material = intent().material_document
        self.assertEqual(sorted(material), ["exact_revision", "repository_ref", "task", "version"])
        manually = json.dumps(material, sort_keys=True, separators=(",", ":"))
        import hashlib

        self.assertEqual(intent().intent_sha256, hashlib.sha256(manually.encode("utf-8")).hexdigest())
        self.assertRegex(intent().intent_sha256, r"^[a-f0-9]{64}$")
        self.assertEqual(material["version"], EXECUTION_INTENT_VERSION)


class SafeProjectionTests(unittest.TestCase):
    def test_projection_carries_digests_and_no_task_body(self):
        subject = intent()
        projected = subject.safe_dict()
        self.assertEqual(projected["task_sha256"], subject.task_sha256)
        self.assertEqual(projected["intent_sha256"], subject.intent_sha256)
        self.assertIs(projected["raw_task_in_projection"], False)
        self.assertNotIn("task", projected)
        serialized = json.dumps(projected, sort_keys=True)
        self.assertNotIn(TASK, serialized)
        self.assertNotIn(INTENT_B["task"], serialized)

    def test_projection_never_leaks_credential_shaped_text(self):
        # The ref itself is credential-free by construction, so the projection of a
        # stored intent cannot carry a secret either.
        projected = json.dumps(intent().safe_dict(), sort_keys=True)
        self.assertNotIn("ghp_", projected)
        self.assertNotIn("hunter22", projected)


class RuleIntegrationTests(unittest.TestCase):
    def test_legacy_rule_reads_none(self):
        self.assertIsNone(rule().execution_intent)
        self.assertIsNone(rule(owner_ref="opaque-owner").execution_intent)

    def test_rule_still_supports_legacy_positional_construction(self):
        positional = ClawAutomationRule(
            "rule_pos",
            "ws_pos",
            "position label",
            ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *"),
            ClawAutomationTarget.INBOX,
            ClawAutomationOutputType.REPORT,
        )
        self.assertIsNone(positional.execution_intent)
        self.assertIsNone(positional.owner_ref)

    def test_rule_order_places_execution_intent_last_and_optional(self):
        fields = list(ClawAutomationRule.__dataclass_fields__)
        self.assertEqual(fields[-1], "execution_intent")
        self.assertLess(fields.index("owner_ref"), fields.index("execution_intent"))

    def test_rule_rejects_a_non_intent_execution_intent(self):
        with self.assertRaises(ContractError):
            rule(execution_intent={"task": TASK, "repository_ref": REPOSITORY_REF, "exact_revision": REVISION})  # type: ignore[arg-type]

    def test_rule_carries_owner_ref_and_intent_independently(self):
        carried = rule(owner_ref="opaque-owner", execution_intent=intent())
        self.assertEqual(carried.owner_ref, "opaque-owner")
        self.assertEqual(carried.execution_intent.intent_sha256, intent().intent_sha256)


class InMemoryPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryClawAutomationStore()

    def test_roundtrip_preserves_intent_and_digest(self):
        self.store.save_rule(rule(execution_intent=intent()))
        stored = self.store.get_rule("rule_intent", "ws_intent")
        self.assertEqual(stored.execution_intent.intent_sha256, intent().intent_sha256)
        self.assertEqual(stored.execution_intent.task, TASK)

    def test_list_rules_preserves_intent(self):
        self.store.save_rule(rule(execution_intent=intent()))
        listed = self.store.list_rules("ws_intent")
        self.assertEqual(listed[0].execution_intent.intent_sha256, intent().intent_sha256)

    def test_set_rule_enabled_preserves_intent_and_owner_ref(self):
        self.store.save_rule(rule(owner_ref="opaque-owner", execution_intent=intent()))
        toggled = self.store.set_rule_enabled("ws_intent", "rule_intent", False)
        self.assertFalse(toggled.enabled)
        self.assertEqual(toggled.execution_intent.intent_sha256, intent().intent_sha256)
        self.assertEqual(toggled.owner_ref, "opaque-owner")
        stored = self.store.get_rule("rule_intent", "ws_intent")
        self.assertEqual(stored.execution_intent.intent_sha256, intent().intent_sha256)

    def test_intent_is_immutable_across_generic_save(self):
        self.store.save_rule(rule(execution_intent=intent()))
        with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
            self.store.save_rule(rule(execution_intent=intent(**INTENT_B)))
        with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
            self.store.save_rule(rule(execution_intent=None))

    def test_legacy_rule_cannot_be_promoted_by_generic_save(self):
        self.store.save_rule(rule())
        with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
            self.store.save_rule(rule(execution_intent=intent()))
        # The original stays exactly as legacy as it was.
        self.assertIsNone(self.store.get_rule("rule_intent", "ws_intent").execution_intent)

    def test_a_rejected_save_leaves_the_stored_rule_untouched(self):
        self.store.save_rule(rule(execution_intent=intent()))
        attempted = replace(
            rule(execution_intent=intent(**INTENT_B)), name="renamed while swapping intent"
        )
        with self.assertRaises(ContractError):
            self.store.save_rule(attempted)
        stored = self.store.get_rule("rule_intent", "ws_intent")
        self.assertEqual(stored.name, "정기 실행 규칙")
        self.assertEqual(stored.execution_intent.intent_sha256, intent().intent_sha256)

    def test_owner_ref_immutability_still_enforced(self):
        self.store.save_rule(rule(owner_ref="opaque-owner", execution_intent=intent()))
        with self.assertRaisesRegex(ContractError, "owner provenance is immutable"):
            self.store.save_rule(rule(owner_ref="other-owner", execution_intent=intent()))


class SqlitePersistenceTests(unittest.TestCase):
    def test_roundtrip_and_reopen_preserve_intent_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule(execution_intent=intent()))
            self.assertEqual(store.get_rule("rule_intent", "ws_intent").execution_intent.intent_sha256, intent().intent_sha256)
            store._db.close()
            reopened = SqliteClawAutomationStore(path)
            try:
                restored = reopened.get_rule("rule_intent", "ws_intent")
                self.assertEqual(restored.execution_intent.task, TASK)
                self.assertEqual(restored.execution_intent.repository_ref, REPOSITORY_REF)
                self.assertEqual(restored.execution_intent.exact_revision, REVISION)
                self.assertEqual(restored.execution_intent.intent_sha256, intent().intent_sha256)
            finally:
                reopened._db.close()

    def test_intent_rides_in_the_existing_json_document_without_schema_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule(execution_intent=intent()))
            row = store._get_rule_row("rule_intent")
            document = json.loads(row[9])
            self.assertEqual(document["execution_intent"]["task"], TASK)
            self.assertEqual(document["execution_intent"]["version"], EXECUTION_INTENT_VERSION)
            columns = {
                r[1] for r in store._db.execute("PRAGMA table_info(claw_rules)").fetchall()
            }
            self.assertNotIn("execution_intent", columns)
            self.assertNotIn("task", columns)
            store._db.close()

    def test_legacy_document_without_the_key_reads_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule())
            row = store._get_rule_row("rule_intent")
            document = json.loads(row[9])
            self.assertNotIn("execution_intent", document)
            self.assertIsNone(store.get_rule("rule_intent", "ws_intent").execution_intent)
            store._db.close()

    def test_reopening_a_legacy_database_after_upgrade_still_reads_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule())
            store._db.close()
            reopened = SqliteClawAutomationStore(path)
            try:
                self.assertIsNone(reopened.get_rule("rule_intent", "ws_intent").execution_intent)
            finally:
                reopened._db.close()

    def test_sqlite_generic_update_cannot_swap_or_drop_the_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule(execution_intent=intent()))
            with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
                store.save_rule(rule(execution_intent=intent(**INTENT_B)))
            with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
                store.save_rule(rule(execution_intent=None))
            self.assertEqual(store.get_rule("rule_intent", "ws_intent").execution_intent.intent_sha256, intent().intent_sha256)
            store._db.close()

    def test_sqlite_legacy_rule_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule())
            with self.assertRaisesRegex(ContractError, "execution intent is immutable"):
                store.save_rule(rule(execution_intent=intent()))
            store._db.close()

    def test_sqlite_set_rule_enabled_preserves_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule(execution_intent=intent()))
            toggled = store.set_rule_enabled("ws_intent", "rule_intent", False)
            self.assertFalse(toggled.enabled)
            self.assertEqual(toggled.execution_intent.intent_sha256, intent().intent_sha256)
            reopened = store.get_rule("rule_intent", "ws_intent")
            self.assertEqual(reopened.execution_intent.intent_sha256, intent().intent_sha256)
            store._db.close()

    def test_corrupt_intent_document_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            store.save_rule(rule(execution_intent=intent()))
            row = store._get_rule_row("rule_intent")
            document = json.loads(row[9])
            document["execution_intent"] = "not-an-object"
            store._db.execute(
                "UPDATE claw_rules SET notification_channels=? WHERE rule_id=?",
                (json.dumps(document, sort_keys=True), "rule_intent"),
            )
            store._db.commit()
            with self.assertRaisesRegex(ContractError, "corrupt"):
                store.get_rule("rule_intent", "ws_intent")
            store._db.close()


class FutureDispatchMaterialTests(unittest.TestCase):
    """S2F1 only has to prove the material is sufficient — not that anything runs."""

    def test_intent_supplies_every_required_canonical_input_without_inference(self):
        subject = intent()
        # The canonical input object's required fields, built from the intent alone.
        # No ClawRun, no adapter, no P01 call happens here or anywhere in this file.
        candidate = ClawTaskIntent(
            task_id="task_scheduled_placeholder",
            task=subject.task,
            repository_ref=subject.repository_ref,
            execution_mode=ExecutionMode.CLOUD,
            requested_revision=subject.exact_revision,
            source_surface="automation",
        )
        self.assertEqual(candidate.task, subject.task)
        self.assertEqual(candidate.repository_ref, subject.repository_ref)
        self.assertEqual(candidate.requested_revision, subject.exact_revision)
        self.assertEqual(candidate.execution_mode, ExecutionMode.CLOUD)
        self.assertEqual(candidate.source_surface, "automation")

    def test_rule_fields_still_cannot_supply_that_material(self):
        # Guards the reason this contract exists: nothing may be inferred from the
        # label or the closed enums if a future slice ever loses the intent.
        legacy = rule()
        self.assertIsNone(legacy.execution_intent)
        self.assertTrue(legacy.name)
        self.assertIsInstance(legacy.target_source, ClawAutomationTarget)
        self.assertIsInstance(legacy.output_type, ClawAutomationOutputType)


class UnchangedBehaviourTests(unittest.TestCase):
    def test_tick_dry_run_is_unchanged_for_a_rule_holding_an_intent(self):
        store = InMemoryClawAutomationStore()
        held = rule(execution_intent=intent())
        store.save_rule(held)
        runtime = ClawAutomationTickRuntime(store)
        receipt = runtime.tick(workspace_id="ws_intent", current_time=NOW, membership=membership())
        self.assertEqual(len(receipt.created_run_ids), 1)
        run = store.get_run(receipt.created_run_ids[0], "ws_intent")
        self.assertEqual(run.status.value, "completed")
        self.assertIn("DRAFT", run.output.content)
        self.assertTrue(run.output.proposals[0].approval_gate.approval_required)
        # The intent never rides into the receipt, the stored output blob, or a
        # proposal projection — the same three surfaces the B2A leak tests use.
        surfaces = [json.dumps(receipt.safe_dict(), sort_keys=True, default=str)]
        serialized_output = SqliteClawAutomationStore._serialize_output(run.output)
        if serialized_output is not None:
            surfaces.append(serialized_output)
        surfaces.append(json.dumps([p.safe_dict() for p in run.output.proposals], sort_keys=True, default=str))
        for blob in surfaces:
            self.assertNotIn(TASK, blob)
            self.assertNotIn("execution_intent", blob)

    def test_dedup_and_run_identity_are_unchanged(self):
        store = InMemoryClawAutomationStore()
        store.save_rule(rule(execution_intent=intent()))
        runtime = ClawAutomationTickRuntime(store)
        first = runtime.tick(workspace_id="ws_intent", current_time=NOW, membership=membership())
        self.assertEqual(len(first.created_run_ids), 1)
        # Canonical replay semantics, unchanged by S2F1: the consumed occurrence is
        # no longer due, so the replayed tick is a zero-run no-op and exactly one
        # durable run exists for the logical occurrence.
        second = runtime.tick(workspace_id="ws_intent", current_time=NOW, membership=membership())
        self.assertEqual(second.created_run_ids, ())
        self.assertEqual(second.due_count, 0)
        self.assertEqual(second.deduplicated_count, 0)
        self.assertEqual(len(store.list_runs("ws_intent")), 1)
        claimed = store.get_run_for_occurrence(
            occurrence_key("ws_intent", "rule_intent", NOW), "ws_intent"
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.run_id, first.created_run_ids[0])
        self.assertEqual(ONE_OCCURRENCE_MAX_CANONICAL_RUNS, 1)

    def test_intent_presence_does_not_perturb_run_identity(self):
        # Dedup is the existing authority; an intent must not fork a second run id.
        with_intent = InMemoryClawAutomationStore()
        with_intent.save_rule(rule(execution_intent=intent()))
        plain = InMemoryClawAutomationStore()
        plain.save_rule(rule(execution_intent=None))
        first = ClawAutomationTickRuntime(with_intent).tick(
            workspace_id="ws_intent", current_time=NOW, membership=membership()
        )
        second = ClawAutomationTickRuntime(plain).tick(
            workspace_id="ws_intent", current_time=NOW, membership=membership()
        )
        self.assertEqual(first.created_run_ids, second.created_run_ids)

    def test_nothing_is_activated_by_this_slice(self):
        self.assertIs(REAL_BACKGROUND_TRIGGER, False)
        self.assertIs(PRODUCTION_SCHEDULER_ACTIVATION, False)


if __name__ == "__main__":
    unittest.main()
