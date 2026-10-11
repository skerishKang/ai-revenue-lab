"""#3989 Glass timing ownership: strict daily, functional PR, no silent skips."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / ".github/scripts/b62_glass_shell_visual_qa.py"
PR = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
SCHEDULE = ROOT / ".github/workflows/b62-glass-animation-timing-certification.yml"


def run_from_original_ast(mode: str):
    tree = ast.parse(SHELL.read_text(encoding="utf-8"))
    target = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_checks")
    compiled = compile(ast.fix_missing_locations(ast.Module(body=[target], type_ignores=[])), str(SHELL), "exec")
    calls: list[str] = []

    class Page:
        async def close(self):
            calls.append("page_closed")

    class Context:
        async def new_page(self):
            return Page()

        async def close(self):
            calls.append("context_closed")

    class Browser:
        async def new_context(self, **kwargs):
            return Context()

        async def new_page(self, **kwargs):
            return Page()

        async def close(self):
            calls.append("browser_closed")

    class Playwright:
        chromium = None
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def launch(self):
            return Browser()

    play = Playwright()
    play.chromium = play

    async def strict(page, variant):
        calls.append("strict:" + variant)
        return {"status": "PASS"}

    async def functional(page, variant):
        calls.append("functional:" + variant)
        return {"status": "PASS", "timing_certification": "NOT_RUN_IN_PR"}

    async def retry(cycle, **kwargs):
        return await cycle()

    async def check_one(page):
        calls.append("mask_or_control")
        return {"status": "PASS"}

    async def check_browser(browser):
        calls.append("reduced_motion_or_touch")
        return {"status": "PASS"}

    env = {
        "async_playwright": lambda: play,
        "SHELL_CERTIFICATION_MODE": mode,
        "VARIANTS": ("female", "male"),
        "_check_variant": strict,
        "_check_variant_functional": functional,
        "with_timing_retries": retry,
        "_check_mask_modes": check_one,
        "_check_controls": check_one,
        "_check_reduced_motion": check_browser,
        "_check_touch": check_browser,
        "TIMING_EVIDENCE": [],
    }
    exec(compiled, env)
    result = {"views": {}}
    asyncio.run(env["_run_checks"](result))
    return calls, result


class GlassTimingOwnershipTest(unittest.TestCase):
    def test_functional_pr_executes_both_variants_and_all_shared_behavior(self):
        calls, report = run_from_original_ast("functional")
        self.assertEqual([x for x in calls if x.startswith("functional:")],
                         ["functional:female", "functional:male"])
        self.assertFalse(any(x.startswith("strict:") for x in calls))
        self.assertEqual(calls.count("mask_or_control"), 2)
        self.assertEqual(calls.count("reduced_motion_or_touch"), 2)
        self.assertEqual(calls.count("browser_closed"), 1)
        self.assertIn("reduced-motion", report["views"])
        self.assertIn("touch", report["views"])

    def test_daily_strict_retains_original_both_variant_timing_functions(self):
        calls, report = run_from_original_ast("strict")
        self.assertEqual([x for x in calls if x.startswith("strict:")],
                         ["strict:female", "strict:male"])
        self.assertFalse(any(x.startswith("functional:") for x in calls))
        self.assertEqual(calls.count("mask_or_control"), 2)
        self.assertEqual(calls.count("reduced_motion_or_touch"), 2)
        self.assertEqual(calls.count("browser_closed"), 1)

    def test_strict_source_thresholds_and_functional_settled_assertions(self):
        tree = ast.parse(SHELL.read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        strict = ast.unparse(functions["_check_variant"])
        functional = ast.unparse(functions["_check_variant_functional"])
        self.assertEqual(strict.count("check_settle_window("), 2)
        self.assertIn("lo_ms=1800", strict)
        self.assertIn("lo_ms=1600", strict)
        self.assertEqual(strict.count("hi_ms=3600"), 2)
        self.assertNotIn("check_settle_window(", functional)
        self.assertNotIn("_sample_shell_at(", functional)
        for check in ("_wait_completed_shell(", "_wait_progress_below(",
                      "_send_answer_turn(", "_assert_no_horizontal_overflow("):
            self.assertIn(check, functional)
        source = SHELL.read_text(encoding="utf-8")
        self.assertIn('os.environ.get("B62_GLASS_SHELL_MODE", "strict")', source)
        self.assertIn('SHELL_CERTIFICATION_MODE not in ("strict", "functional")', source)

    def test_daily_strict_is_independent_nonblocking_and_evidence_retaining(self):
        scheduled = SCHEDULE.read_text(encoding="utf-8")
        self.assertIn("  schedule:\n    - cron: '25 18 * * *'", scheduled)
        self.assertNotIn("\n  pull_request:", scheduled)
        self.assertNotIn("\n  workflow_dispatch:", scheduled)
        self.assertNotIn("\n  push:", scheduled)
        self.assertIn("  contents: read", scheduled)
        self.assertIn("B62_GLASS_SHELL_MODE: strict", scheduled)
        self.assertIn("PADIEM_CHAT_RUNTIME_MODE: mock", scheduled)
        self.assertIn("PADIEM_CHAT_LIVE_ENABLED: \"false\"", scheduled)
        self.assertIn("uv run python ../../.github/scripts/b62_glass_shell_visual_qa.py", scheduled)
        self.assertIn("if: always()", scheduled)
        self.assertIn("actions/upload-artifact@v4", scheduled)
        self.assertNotIn("continue-on-error: true", scheduled)
        self.assertNotIn("secrets.", scheduled)

        pr = PR.read_text(encoding="utf-8")
        job = pr.split("\n  browser-qa:\n", 1)[1].split("\n  conversation-delete-browser-qa:\n", 1)[0]
        self.assertIn("B62_GLASS_SHELL_MODE: functional", job)
        self.assertIn("b62_browser_qa_tail_parallel.py", job)
        self.assertIn("name: Desktop and mobile browser QA", job)
        self.assertIn("name: Upload browser evidence", job)
        self.assertNotIn("continue-on-error: true", job)


if __name__ == "__main__":
    unittest.main()
