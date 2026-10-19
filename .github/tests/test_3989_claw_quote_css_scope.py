"""#3989: Claw supplier quote compare CSS belongs to Claw UI, not generic B62.

Fail open on missing/altered selectors and any uncertain or mixed PR. No test
is removed; five relevant owner lanes and every existing static security/Chat
gate remain mandatory when only safe Claw compare styles change.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
BROWSER = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
CHAT = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
AUDITS = ROOT / ".github/workflows/b62-static-audits.yml"
QUOTECSS = "apps/padiem-chat/static/claw-quote-compare.css"
MANUALCSS = "apps/padiem-chat/static/claw-manual-intake.css"
spec = importlib.util.spec_from_file_location("b62_quote_css_3989", PLAN)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)
KEEP = {
    "accessibility-browser-qa", "auth-history-browser-qa", "browser-qa",
    "document-browser-qa", "project-files-browser-qa",
}


def selected(*names: str) -> set[str]:
    return {job for job, yes in
            planner.choose_lanes(set(names), planner.load_paths()).items() if yes}


class ClawQuoteCSSScopeContract(unittest.TestCase):
    def test_real_claw_quote_css_routes_five_owner_browser_lanes(self):
        self.assertEqual(planner.CLAW_QUOTE_COMPARE_CSS, QUOTECSS)
        self.assertTrue(planner.claw_quote_css_is_isolated())
        self.assertEqual(selected(QUOTECSS), KEEP)
        self.assertEqual(selected(MANUALCSS, QUOTECSS), KEEP)
        self.assertEqual(len(planner.load_paths()), 16)
        self.assertNotIn(QUOTECSS, planner.GLASS_TAIL_UNCHANGED_LEAVES)
        html = (ROOT / "apps/padiem-chat/static/index.html").read_text(encoding="utf-8")
        self.assertIn('href="./claw-quote-compare.css"', html)
        self.assertIn('src="./claw-quote-compare.js"', html)

    def test_mixed_shared_or_unknown_ownership_is_additive_not_suppressed(self):
        for name in (
            "apps/padiem-chat/static/index.html",
            "apps/padiem-chat/static/app.js",
            "apps/padiem-chat/app/app_factory.py",
            "apps/padiem-chat/static/claw-workspace.css",
            "apps/padiem-chat/static/claw-quote-compare.js",
        ):
            with self.subTest(name=name):
                self.assertEqual(selected(QUOTECSS, name), selected(name) | KEEP)
        self.assertEqual(selected(QUOTECSS, "apps/padiem-chat/static/padiem-first-use.css"),
                         set(planner.load_paths()))
        self.assertEqual(selected(QUOTECSS, "apps/padiem-chat/static/b66-quote-runtime.js"), KEEP)
        for plan in (
            ".github/scripts/b62_browser_qa_path_plan.py",
            ".github/workflows/b62-browser-qa-unified.yml",
            ".github/tests/test_3989_claw_quote_css_scope.py",
            ".github/ci/b62_browser_qa_paths.json",
        ):
            with self.subTest(plan=plan):
                self.assertEqual(selected(QUOTECSS, plan), set(planner.load_paths()))
        self.assertEqual(selected(QUOTECSS, MANUALCSS, "apps/padiem-chat/static/app.js"),
                         selected("apps/padiem-chat/static/app.js") | KEEP)

    def test_selector_whitelist_allows_actual_responsive_claw_rules(self):
        safe = '''
.claw-quote-compare { display: block; }
.app-shell:not([data-state="claw"]) .claw-quote-compare,
.claw-workspace[data-view="inbox"] ~ .claw-quote-compare { display: none; }
.claw-qc-primary:disabled, .claw-qc-field:first-of-type { opacity: 0.4; }
.claw-qc-status[data-state="error"] { color: red; }
@media (max-width: 920px) {
    .claw-qc-controls, .claw-qc-form-actions > button { grid-template-columns: 1fr; }
}
'''
        self.assertTrue(planner.claw_quote_css_is_isolated(safe))

    def test_broadened_global_malformed_or_at_rule_css_forces_all_jobs(self):
        unsafe = (
            "",
            "body { display: none; }",
            ":root { --shared: red; }",
            ".assistant-message { color: red; }",
            ".claw-qc-controls, body { background: red; }",
            ".claw-qc-controls ~ .conversation { display: none; }",
            ".claw-quote-compare:has(body) { color: red; }",
            "@font-face { font-family: Example; }",
            "@keyframes move { from { opacity: 0; } }",
            "@media (max-width: 700px) { .claw-qc-controls { width: 80%; } }",
            '@import url("https://bad.test/global.css");',
            ".claw-qc-controls { background: url(https://bad.test/x); }",
            "/* incomplete .claw-qc-controls { color: red; }",
            ".claw-qc-controls { color: red;",
            "@media (max-width: 920px) { body { color: red; } }",
            ".claw-qc-controls { .assistant-message { color: red; } }",
        )
        for css in unsafe:
            with self.subTest(css=css):
                self.assertFalse(planner.claw_quote_css_is_isolated(css))
        with patch.object(planner, "claw_quote_css_is_isolated", return_value=False):
            self.assertEqual(selected(QUOTECSS), set(planner.load_paths()))
            self.assertEqual(selected(QUOTECSS, "apps/padiem-chat/static/app.js"),
                             set(planner.load_paths()))
        with patch.object(Path, "read_text", side_effect=OSError("missing")):
            self.assertFalse(planner.claw_quote_css_is_isolated())
        self.assertTrue(all(planner.choose_lanes(None, planner.load_paths()).values()))

    def test_security_ownership_and_no_new_browser_job_are_pinned(self):
        browser = BROWSER.read_text(encoding="utf-8")
        self.assertIn("test_3989_claw_quote_css_scope.py", browser)
        self.assertIn('".github/tests/test_3989_claw_quote_css_scope.py"',
                      PLAN.read_text(encoding="utf-8"))
        self.assertIn('      - "apps/padiem-chat/**"', CHAT.read_text(encoding="utf-8"))
        audits = AUDITS.read_text(encoding="utf-8")
        self.assertIn("'apps/padiem-chat/static/**'", audits)
        for name in (
            "b62_dom_sink_audit.py",
            "b62_static_origin_audit.py",
            "b62_browser_persistence_audit.py",
        ):
            self.assertIn(name, audits)
        self.assertIn("  browser-qa:\n    needs: plan", browser)
        self.assertIn("  accessibility-browser-qa:\n    needs: plan", browser)
        self.assertEqual(planner.CLAW_MANUAL_QA_OWNERS, KEEP)
        self.assertTrue((ROOT / "apps/padiem-chat/tests/test_b54_claw_quote_compare_ui.py").exists())


if __name__ == "__main__":
    unittest.main()
