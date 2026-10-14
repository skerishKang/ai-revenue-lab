"""#4459 B62 UI source + pytest modules fast lane: strict proofs and unchanged gates."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scope = load_module("b62_4459_mixed_ci", ".github/scripts/b62_ci_impact_scope_3989.py")
browser = load_module("b62_4459_mixed_browser", ".github/scripts/b62_browser_qa_path_plan.py")
WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"

CSS = "apps/padiem-chat/static/history.css"
JS = "apps/padiem-chat/static/app.js"
HTML = "apps/padiem-chat/static/index.html"
UI_TEST = "apps/padiem-chat/tests/test_b62_1735_sidebar_home_ia.py"
UI_TEST2 = "apps/padiem-chat/tests/test_b62_2341_task_alert_inbox_ui.py"
BACKEND_TEST = "apps/padiem-chat/tests/test_projects.py"
SMOKE = browser.UI_ONLY_CSS_SMOKE_LANES


def f(path, status="modified"):
    return {"filename": path, "status": status}


class UiMixedFastLane(unittest.TestCase):
    def test_static_html_js_css_plus_test_modules_are_executed_not_skipped(self):
        cases = ((CSS, UI_TEST), (JS, UI_TEST2), (HTML, BACKEND_TEST),
                 (CSS, JS, HTML, UI_TEST, BACKEND_TEST))
        for sample in cases:
            with self.subTest(sample=sample):
                files = [f(p) for p in sample]
                self.assertEqual(scope.impact_scope(files), scope.UI_MIXED)
                expected = tuple(sorted(p.removeprefix("apps/padiem-chat/") for p in sample
                                        if "/tests/" in p))
                self.assertEqual(scope.ui_mixed_test_modules(files), expected)

    def test_mixed_python_auth_worker_ci_core_and_ambiguous_fail_closed(self):
        unsafe = (
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/app/auth_routes.py",
            "apps/padiem-chat/app/b66_ai_conversation_routes.py",
            "apps/padiem-chat/migrations/041_b66_ai_conversation.sql",
            "apps/padiem-chat/tests/conftest.py",
            "apps/padiem-chat/uv.lock",
            "apps/korean-ai-platform/app/pilot/runner.py",
            "packages/padiem-ai-core/padiem_ai_core/router.py",
            ".github/scripts/b62_sidebar_ia_browser_qa.py",
            ".github/workflows/b62-padiem-chat-ci.yml",
            "apps/padiem-chat/scripts/b62_test_screenshot.png",
            "apps/padiem-chat/tests/test_nested/test_foo.py",
        )
        for hazard in unsafe:
            with self.subTest(hazard=hazard):
                result = scope.impact_scope([f(CSS), f(UI_TEST), f(hazard)])
                self.assertNotEqual(result, scope.UI_MIXED)
        for invalid in (
            [f(CSS), f(UI_TEST, "removed")],
            [f(CSS, "renamed"), f(UI_TEST)],
            [f(CSS), f(UI_TEST, "copied")],
            [f(CSS), f(UI_TEST), f(UI_TEST)],
            [f(CSS), f("apps/padiem-chat/tests/test_../worker.py")],
            [f(CSS), f("apps/padiem-chat/tests\\test_foo.py")],
        ):
            self.assertNotEqual(scope.impact_scope(invalid), scope.UI_MIXED)
        files = [f(CSS), f(UI_TEST)] + [
            f(f"apps/padiem-chat/tests/test_case{i}.py") for i in range(24)
        ]
        self.assertNotEqual(scope.impact_scope(files), scope.UI_MIXED)

    def test_css_plus_exact_presentation_test_selects_six_browser_lanes(self):
        for tests in ((UI_TEST,), (UI_TEST, UI_TEST2)):
            changes = {CSS, *tests}
            statuses = {p: "modified" for p in changes}
            result = browser.choose_lanes(changes, browser.load_paths(),
                                          statuses=statuses, expected_files=len(changes))
            self.assertEqual({name for name, enabled in result.items() if enabled}, SMOKE)
            self.assertTrue(browser.require_glass_visual_tail(changes, statuses,
                                                              expected_files=len(changes)))

    def test_real_pr_4551_css_with_accessibility_test_replay(self):
        # PR #4551 changed exactly this CSS and UI-only test module. Before
        # #4459 both classifier and browser planner routed it to full lanes.
        css = "apps/padiem-chat/static/claw-focus-layout.css"
        test = "apps/padiem-chat/tests/test_4488_claw_automation_touch_accessibility.py"
        rows = [f(css), f(test, "added")]
        self.assertEqual(scope.impact_scope(rows), scope.UI_MIXED)
        self.assertEqual(scope.ui_mixed_test_modules(rows),
                         ("tests/test_4488_claw_automation_touch_accessibility.py",))
        paths = {css, test}
        statuses = {css: "modified", test: "added"}
        observed = browser.choose_lanes(paths, browser.load_paths(),
                                        statuses=statuses, expected_files=2)
        self.assertEqual({name for name, enabled in observed.items() if enabled}, SMOKE)
        self.assertGreater(len(browser.choose_lanes(paths, browser.load_paths())), len(SMOKE))

    def test_unproven_browser_variants_retain_full_fanout(self):
        for other in (BACKEND_TEST, JS, HTML, "apps/padiem-chat/worker.py",
                      ".github/scripts/b62_sidebar_ia_browser_qa.py"):
            changes = {CSS, other}
            statuses = {p: "modified" for p in changes}
            result = browser.choose_lanes(changes, browser.load_paths(),
                                          statuses=statuses, expected_files=2)
            self.assertFalse(browser.is_css_with_presentation_tests(changes, statuses, expected_files=2))
            self.assertEqual(result, browser.choose_lanes(changes, browser.load_paths()))
        changes = {CSS, UI_TEST}
        for statuses, count in (({CSS: "modified"}, 2),
                                ({CSS: "modified", UI_TEST: "renamed"}, 2),
                                ({CSS: "modified", UI_TEST: "modified"}, None),
                                ({CSS: "modified", UI_TEST: "modified"}, 1)):
            self.assertFalse(browser.is_css_with_presentation_tests(
                changes, statuses, expected_files=count))
        # Product-isolated CSS may NEVER gain broader route entitlement.
        css = "apps/padiem-chat/static/b66-quote-runtime.css"
        self.assertFalse(browser.is_css_with_presentation_tests(
            {css, UI_TEST}, {css: "modified", UI_TEST: "modified"}, expected_files=2))

    def test_pr_exact_count_targets_tests_but_push_or_missing_count_runs_full(self):
        base, head = "a"*40, "b"*40
        files = [f(JS), f(UI_TEST, "added")]
        answer = {"status": "ahead", "files": files}
        for event_name, count, expected in (
            ("pull_request", 2, scope.UI_MIXED),
            ("pull_request", None, scope.FULL),
            ("pull_request", 3, scope.FULL),
            ("push", None, scope.FULL),
        ):
            with self.subTest(event_name=event_name, count=count):
                event = {"repository": {"full_name": "skerishKang/ai-revenue-lab"}}
                if event_name == "pull_request":
                    pr = {"base": {"sha": base}, "head": {"sha": head}}
                    if count is not None:
                        pr["changed_files"] = count
                    event["pull_request"] = pr
                else:
                    event.update(before=base, after=head)
                with tempfile.TemporaryDirectory() as tmp:
                    ev, output = Path(tmp)/"event.json", Path(tmp)/"output.txt"
                    ev.write_text(json.dumps(event), encoding="utf-8")
                    env = {"GITHUB_EVENT_PATH": str(ev), "GITHUB_OUTPUT": str(output),
                           "GITHUB_EVENT_NAME": event_name,
                           "GITHUB_REPOSITORY": "skerishKang/ai-revenue-lab",
                           "GITHUB_TOKEN": "test-only"}
                    with patch.dict(os.environ, env), patch.object(
                        scope.urllib.request, "urlopen",
                        side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(answer).encode())
                    ):
                        observed = scope.changed_files(event, event_name,
                                                       "skerishKang/ai-revenue-lab", "test-only")
                        self.assertEqual(observed, files if count != 3 else observed)
                        scope.main()
                    values = dict(x.split("=", 1) for x in output.read_text().splitlines())
                    self.assertEqual(values["scope"], expected)
                    self.assertEqual(values["ui_tests"], "tests/test_b62_1735_sidebar_home_ia.py"
                                     if expected == scope.UI_MIXED else "")

    def test_stable_required_b62_status_and_unmodified_security_gates(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: b62-test", source)
        self.assertIn("name: B62 UI-mixed focused pytest", source)
        self.assertIn("B62_CI_MODE=UI_MIXED_TARGETED", source)
        self.assertIn('test "$MIXED_RESULT" = success', source)
        self.assertIn("uv run --locked python -m pytest -q", source)
        self.assertIn("b62_dom_sink_audit.py", source)
        self.assertIn("b62_static_origin_audit.py", source)
        self.assertIn("b62_browser_persistence_audit.py", source)
        self.assertIn("b62-worker-suite:", source)
        self.assertIn("name: B62 full regression", source)
        self.assertIn("test_4459_b62_ui_mixed_scope.py", source)
        self.assertIn("outputs.ui_tests", source)
        self.assertIn("scope != 'ui_mixed'", source)
        self.assertIn("scope == 'ui_mixed'", source)
        self.assertEqual(source.count("scope != 'b14_tests_only'"), 2)


if __name__ == "__main__":
    unittest.main()
