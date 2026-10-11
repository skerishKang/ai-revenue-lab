"""#3989 contract: B62 can install headless shell, never omit Linux deps.

Source tests run in existing plan job without a browser install or new lane.
Real Linux Chromium/visual verification remains mandatory on exact PR HEAD.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
PLAN = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
VERSION = "1.55.0"
EXPECTED_JOBS = frozenset({
    "accessibility-browser-qa", "auth-history-browser-qa", "browser-qa",
    "conversation-delete-browser-qa", "conversation-export-browser-qa",
    "deep-research-browser-qa", "document-browser-qa",
    "error-retry-browser-qa", "image-browser-qa", "mobile-touch-target-qa",
    "project-delete-browser-qa", "project-files-browser-qa",
    "projects-browser-qa", "saved-outputs-browser-qa",
    "structured-answer-browser-qa", "web-search-browser-qa",
})


def jobs():
    source = WORKFLOW.read_text(encoding="utf-8").split("\n  plan:\n", 1)[1]
    chunks = re.split(r"(?=^  [a-z][a-z0-9-]*:\n)", source, flags=re.MULTILINE)
    found = {}
    for block in chunks:
        match = re.match(r"^  ([a-z][a-z0-9-]*):\n", block)
        if match:
            found[match.group(1)] = block
    return found


class B62HeadlessShellContract(unittest.TestCase):
    def test_all_sixteen_jobs_install_pinned_headless_shell_with_os_deps(self):
        observed = jobs()
        self.assertEqual(set(observed), EXPECTED_JOBS)
        exact = "uv run playwright install --with-deps --only-shell chromium"
        cache_key = "key: b62-playwright-headless-shell-1.55.0-"
        for name, job in observed.items():
            with self.subTest(job=name):
                self.assertEqual(job.count("name: Install Chromium runtime"), 1)
                self.assertEqual(job.count(exact), 1)
                self.assertEqual(job.count(cache_key), 1)
                self.assertIn("uv pip install 'playwright==1.55.0'", job)
                self.assertIn("path: ~/.cache/ms-playwright", job)
                self.assertNotIn("install --with-deps chromium", job)
                self.assertNotIn("b62-playwright-1.55.0-", job)
                self.assertNotIn("install chromium --only-shell", job)
                self.assertIn("actions/cache@v4", job)
                self.assertIn("actions/upload-artifact@v4", job)
        self.assertEqual(WORKFLOW.read_text(encoding="utf-8").count(exact), 16)

    def test_all_chromium_call_sites_launch_only_default_headless_shell(self):
        inspected = []
        for source in sorted((ROOT / ".github/scripts").glob("b62*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if not isinstance(f, ast.Attribute) or f.attr != "launch":
                    continue
                browser = f.value
                if not isinstance(browser, ast.Attribute) or browser.attr != "chromium":
                    continue
                kw = {x.arg: x.value for x in node.keywords}
                self.assertFalse(node.args, f"positional browser launch {source.name}")
                self.assertNotIn("channel", kw, source.name)
                self.assertNotIn("executable_path", kw, source.name)
                if "headless" in kw:
                    self.assertIsInstance(kw["headless"], ast.Constant, source.name)
                    self.assertIs(kw["headless"].value, True, source.name)
                inspected.append(source.name)
        self.assertGreaterEqual(len(inspected), 25, inspected)

    def test_existing_daily_strict_certification_is_unchanged(self):
        scheduled = (ROOT / ".github/workflows/b62-glass-animation-timing-certification.yml")
        content = scheduled.read_text(encoding="utf-8")
        self.assertIn("B62_GLASS_SHELL_MODE: strict", content)
        self.assertIn("run: uv run playwright install --with-deps chromium", content)
        self.assertIn("  schedule:", content)

    def test_plan_guard_pins_this_install_scope_contract(self):
        plan = PLAN.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('".github/tests/test_3989_b62_headless_shell_install.py"', plan)
        self.assertIn(
            "python -m unittest discover -s .github/tests -p test_3989_b62_headless_shell_install.py -v",
            workflow,
        )
        self.assertIn("  browser-qa:\n    needs: plan", workflow)
        self.assertIn("  conversation-export-browser-qa:\n    needs: plan", workflow)


if __name__ == "__main__":
    unittest.main()
