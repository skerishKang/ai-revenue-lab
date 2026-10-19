"""#3989 exact Claw manual-field CSS ownership, with fail-open CSS scope.

Five original browser lanes remain required. Full B62 Chat/static security
checks and Claw's source-owned browser/Node tests are never suppressed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
CHAT = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
AUDITS = ROOT / ".github/workflows/b62-static-audits.yml"
CLAW_CSS = "apps/padiem-chat/static/claw-manual-intake.css"
spec = importlib.util.spec_from_file_location("b62_claw_manual_css_scope_3989", SCRIPT)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

KEEP = {
    "accessibility-browser-qa",
    "auth-history-browser-qa",
    "browser-qa",
    "document-browser-qa",
    "project-files-browser-qa",
}


def chosen(*paths: str) -> set[str]:
    return {
        name for name, enabled in planner.choose_lanes(set(paths), planner.load_paths()).items()
        if enabled
    }


class ClawManualCSSScopeContract(unittest.TestCase):
    def test_exact_claw_css_preserves_relevant_five_browser_lanes(self):
        self.assertEqual(planner.CLAW_MANUAL_INTAKE_CSS, CLAW_CSS)
        self.assertEqual(planner.CLAW_MANUAL_QA_OWNERS, KEEP)
        self.assertEqual(len(planner.load_paths()), 16)
        self.assertTrue(planner.claw_manual_css_is_isolated())
        self.assertEqual(chosen(CLAW_CSS), KEEP)
        self.assertNotIn(CLAW_CSS, planner.GLASS_TAIL_UNCHANGED_LEAVES)
        html = (ROOT / "apps/padiem-chat/static/index.html").read_text(encoding="utf-8")
        self.assertIn('href="./claw-manual-intake.css"', html)
        self.assertIn('class="claw-field"', html)

    def test_shared_mixed_and_other_claw_changes_keep_full_original_ownership(self):
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/app.js"),
                         chosen("apps/padiem-chat/static/app.js") | KEEP)
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/padiem-first-use.css"),
                         set(planner.load_paths()))
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/app/app_factory.py"),
                         chosen("apps/padiem-chat/app/app_factory.py") | KEEP)
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/claw-workspace.css"),
                         chosen("apps/padiem-chat/static/claw-workspace.css") | KEEP)
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/claw-local-handoff.js"),
                         chosen("apps/padiem-chat/static/claw-local-handoff.js") | KEEP)
        self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/b66-quote-runtime.js"),
                         KEEP)
        self.assertEqual(chosen(CLAW_CSS, ".github/scripts/b62_browser_qa_path_plan.py"),
                         set(planner.load_paths()))
        self.assertEqual(chosen(CLAW_CSS, ".github/tests/test_3989_claw_manual_css_scope.py"),
                         set(planner.load_paths()))

    def test_unknown_or_global_css_selector_never_skips_any_lane(self):
        valid = """.claw-field { gap: 4px; }
.claw-field input, .claw-field select { color: inherit; }
"""
        self.assertTrue(planner.claw_manual_css_is_isolated(valid))
        for unsafe in (
            "",
            ":root { --shared-color: red; }",
            "body { background: black; }",
            ".claw-field, .assistant-message { color: red; }",
            ".claw-field ~ .conversation { display: none; }",
            ".claw-workspace { display: none; }",
            "@media (min-width: 400px) { .claw-field { gap: 8px; } }",
            '@import url("https://example.test/global.css");',
            "@font-face { font-family: X; }",
            ".claw-field { color: inherit;",
            "/* incomplete .claw-field { color: inherit; }",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertFalse(planner.claw_manual_css_is_isolated(unsafe))

    def test_unreadable_css_and_uncertain_pr_file_scope_are_fail_open(self):
        with patch.object(planner, "claw_manual_css_is_isolated", return_value=False):
            self.assertEqual(chosen(CLAW_CSS), set(planner.load_paths()))
            self.assertEqual(chosen(CLAW_CSS, "apps/padiem-chat/static/app.js"),
                             set(planner.load_paths()))
        with patch.object(Path, "read_text", side_effect=OSError("unreadable")):
            self.assertFalse(planner.claw_manual_css_is_isolated())
        self.assertTrue(all(planner.choose_lanes(None, planner.load_paths()).values()))
        self.assertEqual(planner.choose_lanes({CLAW_CSS}, planner.load_paths())["browser-qa"], True)

    def test_existing_safety_and_claw_owned_checks_remain_triggered(self):
        master = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("test_3989_claw_manual_css_scope.py", master)
        self.assertIn('".github/tests/test_3989_claw_manual_css_scope.py"', SCRIPT.read_text(encoding="utf-8"))
        self.assertIn('      - "apps/padiem-chat/**"', CHAT.read_text(encoding="utf-8"))
        audits = AUDITS.read_text(encoding="utf-8")
        self.assertIn("'apps/padiem-chat/static/**'", audits)
        for script in (
            "b62_dom_sink_audit.py",
            "b62_static_origin_audit.py",
            "b62_browser_persistence_audit.py",
        ):
            self.assertIn(script, audits)
        self.assertTrue((ROOT / "apps/padiem-chat/tests/test_b62_3084_web_connect_this_computer.py").exists())
        self.assertIn("  browser-qa:\n    needs: plan", master)
        self.assertIn("  accessibility-browser-qa:\n    needs: plan", master)


if __name__ == "__main__":
    unittest.main()
