"""#3989: real fail-closed async branch contracts for fast base visual smoke.

Extract the original coroutine by AST so tests can run offline without
Playwright installation, while exercising the actual source control flow.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".github/scripts/b62_browser_visual_qa.py"
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"


class _Page:
    def __init__(self, label: str, calls: list[str]):
        self.label, self.calls = label, calls

    async def close(self):
        self.calls.append("page_close:" + self.label)


class _Browser:
    def __init__(self, calls: list[str]):
        self.calls = calls
        self.created = 0

    async def new_page(self):
        self.created += 1
        label = "page" + str(self.created)
        self.calls.append("page_open:" + label)
        return _Page(label, self.calls)

    async def close(self):
        self.calls.append("browser_close")


class _Playwright:
    def __init__(self, calls: list[str]):
        self.calls = calls
        self.browser = _Browser(calls)
        self.chromium = self

    async def launch(self, headless: bool):
        assert headless is True
        self.calls.append("browser_launch")
        return self.browser

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.calls.append("playwright_exit")


class VisualLeafSmokeContract(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    @staticmethod
    def extracted_run_checks(calls: list[str], *, fail_view: str | None = None):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        fn = next(node for node in tree.body if
                  isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_checks")
        module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
        play = _Playwright(calls)

        async def phase(report, name, source):
            calls.append("phase:" + name)
            return await source

        async def run_view(page, *, name, width, height, mobile):
            calls.append("check:" + name)
            if name == fail_view:
                raise AssertionError("SYNTHETIC_BASE_VIEW_FAILURE")
            assert width > 0 and height > 0
            assert mobile == (name == "mobile")
            return {"status": "PASS", "name": name}

        async def run_tablet(page):
            calls.append("check:claw_tablet")
            return {"status": "PASS", "name": "claw_tablet"}

        namespace = {
            "Any": Any,
            "async_playwright": lambda: play,
            "_profile_phase": phase,
            "_run_view": run_view,
            "_run_claw_intermediate": run_tablet,
        }
        exec(compile(module, str(SOURCE), "exec"), namespace)
        return namespace["_run_checks"]

    def test_leaf_executes_real_original_desktop_mobile_tablet_branches(self):
        calls = []
        runner = self.extracted_run_checks(calls)
        report = {"views": {}, "padiem_glass_preview": {}}
        asyncio.run(runner(report, visual_scope="leaf"))
        self.assertEqual(
            [c for c in calls if c.startswith("check:")],
            ["check:desktop", "check:mobile", "check:claw_tablet"],
        )
        self.assertEqual(set(report["views"]), {"desktop", "mobile", "claw-tablet-820"})
        self.assertEqual(report["padiem_glass_preview"]["status"], "SKIPPED_PROVEN_UNCHANGED")
        self.assertEqual(report["padiem_glass_reduced_motion"]["status"], "SKIPPED_PROVEN_UNCHANGED")
        self.assertEqual(report["padiem_glass_touch"]["status"], "SKIPPED_PROVEN_UNCHANGED")
        self.assertEqual(calls.count("browser_close"), 1)
        self.assertEqual(calls.count("playwright_exit"), 1)
        self.assertEqual(sum(c.startswith("page_close:") for c in calls), 3)

    def test_leaf_does_not_swallow_desktop_mobile_failure(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                calls = []
                runner = self.extracted_run_checks(calls, fail_view=view)
                report = {"views": {}, "padiem_glass_preview": {}}
                with self.assertRaisesRegex(AssertionError, "SYNTHETIC_BASE_VIEW_FAILURE"):
                    asyncio.run(runner(report, visual_scope="leaf"))
                self.assertEqual(calls.count("browser_close"), 1)
                self.assertEqual(calls.count("playwright_exit"), 1)

    def test_full_scope_and_unchanged_portrait_distinction_are_retained(self):
        self.assertIn('if visual_scope == "leaf":', self.source)
        self.assertIn('for variant in ("female", "male"):', self.source)
        self.assertIn('if VISUAL_SCOPE == "full":', self.source)
        self.assertIn('female_hash = _sha256_file(female_home)', self.source)
        self.assertIn('male_hash = _sha256_file(male_home)', self.source)
        self.assertIn('if female_hash == male_hash:', self.source)
        self.assertIn('if VISUAL_SCOPE not in ("full", "leaf"):', self.source)
        self.assertIn('raise RuntimeError(f"unsupported B62 visual QA scope:', self.source)
        self.assertIn('        "visual_scope": VISUAL_SCOPE,', self.source)
        self.assertIn("SKIPPED_PROVEN_UNCHANGED", self.source)

    def test_workflow_requires_exact_fail_closed_planner_authority(self):
        browser = self.workflow.split("\n  browser-qa:\n", 1)[1].split(
            "\n  conversation-delete-browser-qa:\n", 1)[0]
        authority = "needs.plan.outputs.glass_visual_tail_required == 'false'"
        self.assertIn(authority, browser)
        self.assertIn("B62_QA_VISUAL_SCOPE:", browser)
        self.assertIn("&& 'leaf' || 'full'", browser)
        self.assertEqual(browser.count("b62_browser_visual_qa.py"), 1)
        self.assertIn("uv run python ../../.github/scripts/b62_browser_visual_qa.py", browser)
        self.assertIn("name: Product surface v2 certification browser QA", browser)
        self.assertIn("name: Glass zoom, shell, and gutter visual QA", browser)


if __name__ == "__main__":
    unittest.main()
