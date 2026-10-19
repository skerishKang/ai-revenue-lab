"""#4072: source-only checks for guarded Production D1 014/015 repair."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
WORKFLOW = ROOT / ".github/workflows/b54-claw-history-014-015-apply-gate.yml"
EXPECTED = {
    "014_claw_run_history_conversation.sql":
        "ALTER TABLE claw_run_history ADD COLUMN conversation_id TEXT;",
    "015_claw_run_history_workspace.sql":
        "ALTER TABLE claw_run_history ADD COLUMN workspace_id TEXT;",
}


def statement(name: str) -> str:
    sql = (MIGRATIONS / name).read_text(encoding="utf-8")
    return "\n".join(line.strip() for line in sql.splitlines()
                     if line.strip() and not line.lstrip().startswith("--"))


class GuardedRepairContract(unittest.TestCase):
    def test_exact_additive_source_only(self):
        for name, expected in EXPECTED.items():
            self.assertEqual(statement(name), expected)
            for forbidden in ("DROP", "DELETE", "UPDATE"):
                self.assertNotIn(forbidden, expected.upper())

    def test_requires_confirmation_and_exact_current_main(self):
        wf = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "workflow_dispatch:", "environment: production",
            "APPLY_B54_CLAW_D1_014_015_ONCE",
            'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"',
            'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"',
            "::add-mask::${DB_ID}",
            "B54_CLAW_HISTORY_D1_SCHEMA=READY_015",
            "PROVIDER_POST_COUNT=0",
        ):
            self.assertIn(marker, wf)
        for forbidden in ("force-push", "wrangler deploy"):
            self.assertNotIn(forbidden, wf.lower())

    def test_no_unreviewed_schema_mutation(self):
        wf = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "014_claw_run_history_conversation.sql",
            "015_claw_run_history_workspace.sql",
            '"BASE_009"', '"CONVERSATION_014"', '"READY_015"',
        ):
            self.assertIn(marker, wf)
        self.assertNotIn("migration_009.sql", wf)


if __name__ == "__main__":
    unittest.main()
