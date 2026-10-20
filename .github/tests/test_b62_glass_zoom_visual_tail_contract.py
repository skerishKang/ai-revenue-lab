"""#5210: the Glass Zoom visual-tail lane must measure the product's pause
latency, and a failing suite's assertion must survive the COM2 runner's bounded
diagnostic window.

Two contracts:

1. ``b62_glass_zoom_visual_qa.py`` dispatches the scroll-up wheel and reads the
   measurement start clock.  Dispatching is a host-to-page round trip, so
   reading the clock in a *second* round trip adds that host latency to the
   measured pause window.  On a loaded runner the host round trip alone can
   exceed the unchanged 200 ms ceiling, so the suite then measures the
   runner instead of the product.  The clock must be captured inside the same
   in-page evaluation that dispatches the wheel, and that timestamp must be
   the measurement start.

2. ``b62_browser_qa_tail_parallel.py`` runs the three visual-tail suites and
   keeps every suite and its hard failure fan-in.  The COM2 runner only keeps
   the last N log lines, so a failing suite's assertion has to be repeated
   after all suites have printed, otherwise the failure text is lost.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
ZOOM = ROOT / ".github/scripts/b62_glass_zoom_visual_qa.py"
TAIL = ROOT / ".github/scripts/b62_browser_qa_tail_parallel.py"
PLANNER = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
CANARY = ROOT / ".github/workflows/com2-b62-generic-browser-canary.yml"

if "playwright.async_api" not in sys.modules:
    _playwright = types.ModuleType("playwright")
    _async_api = types.ModuleType("playwright.async_api")
    _async_api.Page = object
    _playwright.async_api = _async_api
    sys.modules["playwright"] = _playwright
    sys.modules["playwright.async_api"] = _async_api

_spec = importlib.util.spec_from_file_location("b62_qa_tail", TAIL)
tail = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tail)


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


class GlassZoomPauseClockContract(unittest.TestCase):
    def test_the_wheel_dispatch_returns_the_page_clock_of_the_dispatch(self):
        source = ZOOM.read_text(encoding="utf-8")
        tree = ast.parse(source)
        wheel = _function(tree, "_wheel_up")
        # The wheel is dispatched and the clock is read in one in-page
        # evaluation, and the function returns that timestamp.
        returns = [node for node in ast.walk(wheel) if isinstance(node, ast.Return)]
        self.assertTrue(returns, "the wheel dispatch must return the page clock")
        returned = returns[0].value
        if isinstance(returned, ast.Await):
            returned = returned.value
        self.assertIsInstance(returned, ast.Call)
        self.assertEqual(returned.func.attr, "evaluate")
        expression = returned.args[0]
        self.assertIsInstance(expression, ast.Constant)
        body = expression.value
        self.assertIn("dispatchEvent", body)
        self.assertIn("performance.now()", body)
        # The clock read must happen inside the same evaluation as the
        # dispatch, not in a separate host round trip.
        self.assertEqual(body.count("performance.now()"), 1)

    def test_the_pause_window_starts_at_the_wheel_dispatch_clock(self):
        source = ZOOM.read_text(encoding="utf-8")
        tree = ast.parse(source)
        motion = _function(tree, "_assert_conversation_motion")
        wheels = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_wheel_up"
        ]
        self.assertEqual(len(wheels), 1, "the scroll-up wheel must be dispatched once")
        # The dispatch result is bound to the measurement start.
        assigned = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "wheel_observed"
                for target in node.targets
            )
        ]
        self.assertEqual(len(assigned), 1)
        value = assigned[0].value
        if isinstance(value, ast.Await):
            value = value.value
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(value.func.id, "_wheel_up")
        # The settle measurement uses that timestamp as its start.
        starts = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "wait_state_settled"
        ]
        self.assertTrue(starts)
        start = next(
            keyword.value
            for keyword in starts[0].keywords
            if keyword.arg == "started_ms"
        )
        self.assertIsInstance(start, ast.Name)
        self.assertEqual(start.id, "wheel_observed")

    def test_the_pause_budget_is_unchanged(self):
        source = ZOOM.read_text(encoding="utf-8")
        self.assertIn("lo_ms=0,", source)
        self.assertIn("hi_ms=200,", source)
        self.assertIn("hi_ms=2_500,", source)
        # The suite keeps every original assertion.
        for message in (
            "user scroll-up did not pause auto-follow",
            "DOM growth resumed follow while user was reading history",
            "viewport moved while auto-follow was paused",
            "latest-answer growth was not followed",
        ):
            self.assertIn(message, source)


class VisualTailFailureEvidenceContract(unittest.TestCase):
    def test_all_three_suites_and_the_failure_fan_in_are_unchanged(self):
        self.assertEqual(
            tail.SCRIPTS,
            (
                "b62_glass_shell_visual_qa.py",
                "b62_glass_zoom_visual_qa.py",
                "b62_chat_gutter_visual_qa.py",
            ),
        )
        self.assertEqual(tail.MAX_PARALLEL, 1)
        self.assertEqual(tail.TIMEOUT_SECONDS, 240)

    def test_a_failing_suite_repeats_its_evidence_after_every_suite_printed(self):
        source = TAIL.read_text(encoding="utf-8")
        self.assertIn("B62_VISUAL_TAIL_FAILURE=", source)
        self.assertIn("B62_VISUAL_TAIL_FAILURE_LINE=", source)
        # The repeated failure evidence must be printed after the per-case
        # block, so it lands inside the COM2 runner's bounded log window.
        failure_block = source.index("B62_VISUAL_TAIL_FAILURE=")
        case_block = source.index("B62_VISUAL_TAIL_CASE=")
        self.assertLess(case_block, failure_block)
        self.assertLess(failure_block, source.index("B62_VISUAL_TAIL_EXECUTED="))

    def test_the_repeated_evidence_carries_the_assertion_text(self):
        printed: list[str] = []

        results = [
            ("b62_glass_shell_visual_qa.py", 0, 10.0, "shell PASS\n"),
            (
                "b62_glass_zoom_visual_qa.py",
                1,
                20.0,
                "Traceback (most recent call last):\n"
                "AssertionError: user scroll-up did not pause auto-follow at zoom\n",
            ),
            ("b62_chat_gutter_visual_qa.py", 0, 5.0, "gutter PASS\n"),
        ]
        original = tail.execute
        tail.execute = lambda name: next(r for r in results if r[0] == name)
        try:
            import io
            import os
            from contextlib import redirect_stdout

            buffer = io.StringIO()
            with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
                with redirect_stdout(buffer):
                    self.assertEqual(tail.main(), 1)
            printed.append(buffer.getvalue())
        finally:
            tail.execute = original
        output = "".join(printed)
        self.assertIn("B62_VISUAL_TAIL_STATUS_b62_glass_zoom_visual_qa.py=FAIL", output)
        self.assertIn("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py", output)
        self.assertIn(
            "B62_VISUAL_TAIL_FAILURE_LINE=AssertionError: user scroll-up did not pause auto-follow at zoom",
            output,
        )
        self.assertIn("B62_VISUAL_TAIL_EXECUTED=3", output)
        self.assertIn("B62_VISUAL_TAIL_FAIL_COUNT=1", output)
        # The failure evidence is repeated after every suite printed, so it
        # survives a bounded diagnostic window.
        self.assertLess(
            output.index("B62_VISUAL_TAIL_CASE=b62_glass_shell_visual_qa.py"),
            output.index("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py"),
        )
        self.assertLess(
            output.index("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py"),
            output.index("B62_VISUAL_TAIL_EXECUTED=3"),
        )


class VisualTailScopeSelectionContract(unittest.TestCase):
    """A change to a lane's own script must select that lane.

    The generic Browser lane runs the visual-tail suites itself, so a change
    to one of them has to select the hosted Browser QA lane and the COM2
    Generic Browser canary.  The hosted planner covers the lane-owned suites
    through PLAN_FILES, and the COM2 canary through its changed-file filter.
    """

    LANE_SCRIPTS = (
        ".github/scripts/b62_browser_visual_qa.py",
        ".github/scripts/b62_glass_shell_visual_qa.py",
        ".github/scripts/b62_glass_zoom_visual_qa.py",
        ".github/scripts/b62_chat_gutter_visual_qa.py",
        ".github/scripts/b62_browser_qa_tail_parallel.py",
    )

    def test_the_hosted_planner_selects_every_lane_for_a_lane_script_change(self):
        source = PLANNER.read_text(encoding="utf-8")
        for script in self.LANE_SCRIPTS:
            self.assertIn(f'"{script}"', source, script)

    def test_the_com2_generic_browser_canary_selects_its_own_scripts(self):
        source = CANARY.read_text(encoding="utf-8")
        for script in self.LANE_SCRIPTS:
            self.assertIn(f"p=='{script}'", source, script)
        # The existing product-surface clauses stay in place.
        self.assertIn("p.startswith('apps/padiem-chat/')", source)

    def test_the_canary_still_requires_an_open_same_repository_pr_head(self):
        source = CANARY.read_text(encoding="utf-8")
        self.assertIn("p['state']=='open'", source)
        self.assertIn("p['head']['sha']==sha", source)
        self.assertIn("p['head']['repo']['full_name']==repo", source)


if __name__ == "__main__":
    unittest.main()
