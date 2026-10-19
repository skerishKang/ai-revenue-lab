"""#3989 B66 quote-only CSS must not force unrelated B62 browser jobs.

No production mutation. A globally-scoped or unreadable B66 stylesheet
must fail-open to all original browser lanes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
MANIFEST = ROOT / ".github/ci/b62_browser_qa_paths.json"
CHAT_CI = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
STATIC_AUDITS = ROOT / ".github/workflows/b62-static-audits.yml"
spec = importlib.util.spec_from_file_location("b62_css_scope", SCRIPT)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)
CSS = "apps/padiem-chat/static/b66-quote-runtime.css"
JS = "apps/padiem-chat/static/b66-quote-runtime.js"


def selected(*paths: str):
    return {n for n, yes in planner.choose_lanes(set(paths), planner.load_paths()).items() if yes}


class B66QuoteCSSScopeContract(unittest.TestCase):
    def test_live_b66_stylesheet_is_b66_class_anchored(self):
        self.assertEqual(planner.B66_QUOTE_CSS, CSS)
        self.assertTrue(planner.b66_quote_css_is_isolated())
        self.assertEqual(selected(CSS), set())
        self.assertEqual(selected(JS), set())
        self.assertEqual(len(planner.load_paths()), 16)
        self.assertNotIn(CSS, planner.GLASS_TAIL_UNCHANGED_LEAVES)

    def test_b66_only_css_stays_excluded_without_hiding_shared_mixed_change(self):
        m = planner.load_paths()
        self.assertEqual(sum(planner.choose_lanes({CSS}, m).values()), 0)
        self.assertEqual(sum(planner.choose_lanes({CSS, JS}, m).values()), 0)
        for shared in (
            "apps/padiem-chat/static/index.html",
            "apps/padiem-chat/static/app.js",
            "apps/padiem-chat/app/app_factory.py",
            "apps/padiem-chat/static/padiem-first-use.css",
        ):
            with self.subTest(shared=shared):
                self.assertEqual(selected(CSS, shared), selected(shared))
        self.assertEqual(
            selected(CSS, ".github/ci/b62_browser_qa_paths.json"),
            set(planner.load_paths()),
        )
        self.assertEqual(
            selected(CSS, ".github/scripts/b62_browser_qa_path_plan.py"),
            set(planner.load_paths()),
        )
        self.assertEqual(
            selected(CSS, ".github/tests/test_3989_b66_quote_css_scope.py"),
            set(planner.load_paths()),
        )
        self.assertEqual(set(planner.choose_lanes(None, m)), set(m))
        self.assertTrue(all(planner.choose_lanes(None, m).values()))

    def test_unscoped_global_css_or_missing_source_fails_open(self):
        valid = """.b66-quote-dialog { color: inherit; }
@media (max-width: 640px) { .b66-quote-dialog, .b66-quote-panel > p { padding: 4px; } }
"""
        self.assertTrue(planner.b66_quote_css_is_isolated(valid))
        for bad in (
            ":root { --quote-color: red; }",
            "body { background: red; }",
            ".b66-quote-dialog, .assistant-message { color: red; }",
            ".quote-dialog { color: red; }",
            "@font-face { font-family: X; }",
            '@import url("https://example.com/styles.css");',
            "@keyframes move { from { opacity: 0; } to { opacity: 1; } }",
            ".b66-quote-dialog { color: inherit;",
            "/* incomplete .b66-quote-dialog { color: red; }",
            "",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(planner.b66_quote_css_is_isolated(bad))
        with patch.object(planner, "b66_quote_css_is_isolated", return_value=False):
            self.assertEqual(selected(CSS), set(planner.load_paths()))
            self.assertEqual(selected(CSS, JS), set(planner.load_paths()))
            self.assertEqual(selected(CSS, "apps/padiem-chat/static/app.js"),
                             set(planner.load_paths()))
        with patch.object(Path, "read_text", side_effect=OSError("missing")):
            self.assertFalse(planner.b66_quote_css_is_isolated())

    def test_css_guard_is_central_and_existing_lane_manifest_remains_unchanged(self):
        manifest = planner.load_paths()
        excluded = "!" + CSS
        for lane, patterns in manifest.items():
            with self.subTest(lane=lane):
                # No 15-lane manifest churn: CSS filtering is guarded by the
                # stylesheet source check in choose_lanes(), not broad patterns.
                self.assertNotIn(excluded, patterns)
                if lane == "mobile-touch-target-qa":
                    continue
                self.assertIn("!apps/padiem-chat/static/b66-quote-runtime.js", patterns)
                self.assertTrue(any(not p.startswith("!") for p in patterns))
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("changed_paths = changed_paths - {B66_QUOTE_CSS}", source)
        self.assertIn("if not b66_quote_css_is_isolated():", source)

    def test_existing_nonbrowser_chat_and_static_security_gates_still_cover_css(self):
        workflow = CHAT_CI.read_text(encoding="utf-8")
        audit = STATIC_AUDITS.read_text(encoding="utf-8")
        self.assertIn('      - "apps/padiem-chat/**"', workflow)
        self.assertIn("  pull_request:", workflow)
        self.assertIn("  push:", workflow)
        self.assertIn('      - \'apps/padiem-chat/static/**\'', audit)
        self.assertIn("python .github/scripts/b62_dom_sink_audit.py", audit)
        self.assertIn("python .github/scripts/b62_static_origin_audit.py", audit)
        self.assertIn("python .github/scripts/b62_browser_persistence_audit.py", audit)
        self.assertIn("./b66-quote-runtime.css", (ROOT / "apps/padiem-chat/static/index.html").read_text(encoding="utf-8"))
        self.assertIn('".github/tests/test_3989_b66_quote_css_scope.py"', SCRIPT.read_text(encoding="utf-8"))
        master = (ROOT / ".github/workflows/b62-browser-qa-unified.yml").read_text(encoding="utf-8")
        self.assertIn("test_3989_b66_quote_css_scope.py", master)


if __name__ == "__main__":
    unittest.main()
