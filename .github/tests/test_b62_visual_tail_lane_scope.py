"""#5461: the visual tail's lane scope must keep the hosted Glass Zoom proof and
stop the isolated COM2 lane from repeating it.

Two lanes run the same visual-tail runner:

* the GitHub-hosted browser QA lane, on every pull request, which owns the
  complete three-suite contract including the 2560x1440 Glass Zoom composition;
* the isolated COM2 container lane, executed through a root-owned host command
  that cannot pass an argument, where the same Glass Zoom suite has never
  completed (measured: the 240 s per-suite cap, and a fail-closed fan-in that
  turned the whole canary red so the lane's other suites stopped producing a
  signal).

The scope therefore has to be explicit on the hosted side, the isolated default
has to keep the meaningful Shell and Gutter composition checks, and a skipped
suite must never be reported as executed or passed.
"""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".github/scripts/b62_browser_qa_tail_parallel.py"
HOSTED_WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
COM2_CANARY = ROOT / ".github/workflows/com2-b62-generic-browser-canary.yml"
WORKFLOWS = ROOT / ".github/workflows"
TAIL_SCRIPT = "b62_browser_qa_tail_parallel.py"
ZOOM_SUITE = "b62_glass_zoom_visual_qa.py"
SHELL_SUITE = "b62_glass_shell_visual_qa.py"
GUTTER_SUITE = "b62_chat_gutter_visual_qa.py"
# A command line runs the runner as `python <path>`; a path mention (the
# canary's changed-path selector) is not an invocation.
INVOCATION = re.compile(r"\bpython\s+[^\s'\"]*b62_browser_qa_tail_parallel\.py")

spec = importlib.util.spec_from_file_location("b62_qa_tail_scope", RUNNER)
tail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tail)


def _invocations(text: str) -> list[str]:
    """Every command line that invokes the visual-tail runner.

    A path mention (for example the canary's changed-path selector) is not an
    invocation, so only lines that run the script with python count.
    """

    return [
        line.strip()
        for line in text.splitlines()
        if INVOCATION.search(line) and not line.strip().startswith("#")
    ]


def _requests_full_scope(text: str) -> bool:
    """True when every invocation in the text asks for the full scope."""

    invocations = _invocations(text)
    if not invocations:
        return False
    return all("--scope full" in line for line in invocations)


class VisualTailLaneScopeContract(unittest.TestCase):
    def test_the_hosted_lane_asks_for_the_full_scope_explicitly(self):
        workflow = HOSTED_WORKFLOW.read_text(encoding="utf-8")
        invocations = _invocations(workflow)
        self.assertEqual(len(invocations), 1, invocations)
        self.assertIn("--scope full", invocations[0])
        self.assertTrue(_requests_full_scope(workflow))

    def test_every_repo_side_invocation_asks_for_the_full_scope(self):
        # A new workflow that forgets the scope would silently drop the hosted
        # Glass Zoom proof, so every invocation in the repository is checked.
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if not _invocations(text):
                continue
            self.assertTrue(
                _requests_full_scope(text),
                f"{path.name} invokes the visual tail without --scope full",
            )

    def test_the_hosted_lane_still_runs_on_every_pull_request(self):
        workflow = HOSTED_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^on:\n(?:.*\n)*?\s{2}pull_request:")
        job = workflow.split("\n  browser-qa:\n", 1)[1].split(
            "\n  conversation-delete-browser-qa:\n", 1
        )[0]
        # The hosted job still gates the visual tail on the planner's own
        # classification, and still runs the Glass Zoom suite.
        self.assertIn(
            "if: ${{ needs.plan.outputs.glass_visual_tail_required != 'false' }}", job
        )
        self.assertIn(ZOOM_SUITE.replace(".py", ".py"), tail.SCOPE_SUITES[tail.FULL_SCOPE])
        self.assertIn("B62_GLASS_SHELL_MODE: functional", job)

    def test_the_default_scope_is_the_isolated_lane_scope(self):
        self.assertEqual(tail.DEFAULT_SCOPE, tail.ISOLATED_SCOPE)
        self.assertEqual(
            tail.SCOPE_SUITES[tail.ISOLATED_SCOPE],
            (SHELL_SUITE, GUTTER_SUITE),
        )
        self.assertNotIn(ZOOM_SUITE, tail.SCOPE_SUITES[tail.ISOLATED_SCOPE])
        self.assertEqual(tail.SCOPE_SUITES[tail.FULL_SCOPE], tail.SCRIPTS)
        self.assertEqual(len(tail.SCRIPTS), 3)

    def test_an_unknown_scope_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            tail.resolve_scope(["--scope", "bogus"])
        self.assertNotEqual(raised.exception.code, 0)
        # An unrelated argument is reported and ignored, so a host command that
        # owns this invocation cannot break the lane by adding one.
        self.assertEqual(tail.resolve_scope(["--unrelated", "value"]), tail.DEFAULT_SCOPE)

    def test_the_isolated_scope_runs_shell_and_gutter_and_reports_the_skip(self):
        observed: list[str] = []
        out = io.StringIO()
        with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
            with patch.object(
                tail,
                "execute",
                side_effect=lambda name: (
                    observed.append(name)
                    or (name, 0, 0.1, "PASS")
                ),
            ):
                from contextlib import redirect_stdout

                with redirect_stdout(out):
                    self.assertEqual(tail.main([]), 0)
        output = out.getvalue()
        self.assertEqual(observed, [SHELL_SUITE, GUTTER_SUITE])
        self.assertIn(f"B62_VISUAL_TAIL_SCOPE={tail.ISOLATED_SCOPE}", output)
        self.assertIn(f"B62_VISUAL_TAIL_SKIPPED={ZOOM_SUITE}", output)
        self.assertIn("B62_VISUAL_TAIL_SKIP_REASON=", output)
        self.assertIn("B62_VISUAL_TAIL_HOSTED_COVERAGE=", output)
        self.assertIn("B62_VISUAL_TAIL_EXECUTED=2", output)
        self.assertIn("B62_VISUAL_TAIL_SKIPPED_COUNT=1", output)
        self.assertIn("B62_VISUAL_TAIL_FAIL_COUNT=0", output)
        # The skipped suite is never reported as a passing case.
        self.assertNotIn(f"B62_VISUAL_TAIL_STATUS_{ZOOM_SUITE}=", output)
        self.assertNotIn(f"=== B62_VISUAL_TAIL_CASE={ZOOM_SUITE}", output)

    def test_the_full_scope_still_runs_all_three_suites(self):
        observed: list[str] = []
        out = io.StringIO()
        from contextlib import redirect_stdout

        with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
            with patch.object(
                tail,
                "execute",
                side_effect=lambda name: (
                    observed.append(name)
                    or (name, 0, 0.1, "PASS")
                ),
            ):
                with redirect_stdout(out):
                    self.assertEqual(tail.main(["--scope", "full"]), 0)
        output = out.getvalue()
        self.assertEqual(observed, list(tail.SCRIPTS))
        self.assertIn("B62_VISUAL_TAIL_EXECUTED=3", output)
        self.assertIn("B62_VISUAL_TAIL_SKIPPED_COUNT=0", output)
        self.assertNotIn("B62_VISUAL_TAIL_SKIPPED=", output)

    def test_the_isolated_canary_keeps_the_host_owned_command(self):
        # The isolated lane is executed through the root-owned host command, so
        # the lane's scope is the runner's default and the canary keeps its
        # selective changed-path selection.
        canary = COM2_CANARY.read_text(encoding="utf-8")
        self.assertIn("/usr/local/sbin/padiem-ci-b62-generic-browser-check", canary)
        self.assertIn("selected=", canary)
        self.assertNotIn("--scope", canary)

    def test_mutations_are_detected(self):
        workflow = HOSTED_WORKFLOW.read_text(encoding="utf-8")
        # 1. A hosted lane that drops the explicit scope is detected.
        dropped = workflow.replace(" --scope full", "")
        self.assertNotEqual(dropped, workflow)
        self.assertFalse(_requests_full_scope(dropped))

        # 2. A hosted lane that asks for the isolated scope is detected.
        isolated = workflow.replace("--scope full", "--scope isolated")
        self.assertNotEqual(isolated, workflow)
        self.assertFalse(_requests_full_scope(isolated))

        # 3. An isolated scope that re-adds the high-resolution suite is
        #    detected: the duplicate would come back.
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn(
            ZOOM_SUITE,
            re.search(
                r"ISOLATED_SCOPE: \(([^)]*)\)", source, re.DOTALL
            ).group(1),
        )
        self.assertIn(ZOOM_SUITE, source)


if __name__ == "__main__":
    unittest.main()
