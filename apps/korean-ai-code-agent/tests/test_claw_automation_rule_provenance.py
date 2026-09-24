from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationRuleAuthority,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    classify_rule_background_authority,
)
from kagent.contracts import ContractError

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
TENANT = "tenant_0123456789abcdef0123456789abcdef"
SUBJECT = "sub_0123456789abcdef0123456789abcdef"


def rule(
    *,
    workspace_id: str = TENANT,
    canonical_subject_id: str | None = SUBJECT,
    enabled: bool = True,
    rule_id: str = "rule_provenance",
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="canonical rule",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC"),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        owner_ref="owner:opaque",
        canonical_subject_id=canonical_subject_id,
    )


class CanonicalRuleProvenanceTests(unittest.TestCase):
    def test_canonical_rule_is_background_eligible(self) -> None:
        self.assertIs(
            classify_rule_background_authority(rule()),
            ClawAutomationRuleAuthority.CANONICAL_BACKGROUND_ELIGIBLE,
        )

    def test_legacy_workspace_is_noncanonical(self) -> None:
        result = classify_rule_background_authority(
            rule(workspace_id="owner:usr_legacy", canonical_subject_id=None)
        )
        self.assertIs(result, ClawAutomationRuleAuthority.LEGACY_NONCANONICAL_WORKSPACE)

    def test_legacy_tenant_shaped_rule_without_subject_is_quarantined(self) -> None:
        result = classify_rule_background_authority(rule(canonical_subject_id=None))
        self.assertIs(result, ClawAutomationRuleAuthority.LEGACY_MISSING_SUBJECT)

    def test_invalid_canonical_subject_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            rule(canonical_subject_id="subject:legacy")

    def test_new_subject_provenance_is_keyword_only_and_preserves_execution_intent_slot(self) -> None:
        intent = ClawAutomationExecutionIntent(
            task="Preserve the prior positional contract",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision="a" * 40,
        )
        positional = ClawAutomationRule(
            "rule_positional",
            TENANT,
            "positional compatibility",
            ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC"),
            ClawAutomationTarget.INBOX,
            ClawAutomationOutputType.REPORT,
            True,
            (),
            "owner:opaque",
            intent,
        )
        self.assertIs(positional.execution_intent, intent)
        self.assertIsNone(positional.canonical_subject_id)

    def test_inmemory_provenance_is_immutable_and_preserved(self) -> None:
        store = InMemoryClawAutomationStore()
        store.save_rule(rule())
        with self.assertRaises(ContractError):
            store.update_rule(rule(canonical_subject_id="sub_ffffffffffffffffffffffffffffffff"))
        toggled = store.set_rule_enabled(TENANT, "rule_provenance", False)
        self.assertFalse(toggled.enabled)
        self.assertEqual(toggled.canonical_subject_id, SUBJECT)

    def test_sqlite_provenance_roundtrips_without_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "rules.sqlite")
            store = SqliteClawAutomationStore(path)
            try:
                columns = {
                    str(row[1]): row[4]
                    for row in store._db.execute("PRAGMA table_info(claw_rules)")
                }
                self.assertIn("canonical_subject_id", columns)
                self.assertIsNone(columns["canonical_subject_id"])
                store.save_rule(rule())
                loaded = store.get_rule("rule_provenance", TENANT)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.canonical_subject_id, SUBJECT)  # type: ignore[union-attr]
            finally:
                store._db.close()

    def test_sqlite_existing_rule_schema_adds_nullable_column_without_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.sqlite")
            raw = sqlite3.connect(path)
            raw.execute(
                "CREATE TABLE claw_rules ("
                "rule_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, "
                "schedule_kind TEXT NOT NULL, schedule_expression TEXT NOT NULL, "
                "schedule_timezone TEXT NOT NULL, target_source TEXT NOT NULL, "
                "output_type TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
                "notification_channels TEXT NOT NULL DEFAULT '[]', "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            raw.commit()
            raw.close()
            store = SqliteClawAutomationStore(path)
            try:
                columns = {
                    str(row[1]): row[4]
                    for row in store._db.execute("PRAGMA table_info(claw_rules)")
                }
                self.assertIn("canonical_subject_id", columns)
                self.assertIsNone(columns["canonical_subject_id"])
            finally:
                store._db.close()


if __name__ == "__main__":
    unittest.main()
