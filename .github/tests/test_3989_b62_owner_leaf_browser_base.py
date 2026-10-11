"""#3989: only proven leaf modules may skip unrelated shared browser jobs.

Source-only tests executed in the already required browser plan job.
No mock browser, provider call, or new runner is introduced.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
PLANNER = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
LEAF_EXCEPTION = "if: ${{ needs.plan.outputs.glass_visual_tail_required != 'false' }}"
UNRELATED_STEPS = (
    "Sidebar and home IA browser QA",
    "Provider-neutral mode presentation browser QA",
    "Shared capability presentation browser QA",
    "Product surface v2 certification browser QA",
    "Post-certification long-answer and mobile hardening QA",
    "Settled product certification evidence QA",
)
MANDATORY_STEPS = (
    "Desktop and mobile browser QA",
    "Composer and response interaction polish browser QA",
    "Start mock Padiem Chat",
    "Print QA report",
    "Upload browser evidence",
)

spec = importlib.util.spec_from_file_location("b62_browser_owner_leaf_plan", PLANNER)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def _job_steps() -> dict[str, str]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    section = workflow.split("\n  browser-qa:\n", 1)[1].split(
        "\n  conversation-delete-browser-qa:\n", 1
    )[0]
    blocks = re.split(r"(?=^      - name: )", section, flags=re.MULTILINE)
    result = {}
    for block in blocks:
        match = re.match(r"^      - name: ([^\n]+)", block)
        if match:
            result[match.group(1)] = block
    return result


class B62OwnerLeafBrowserBaseTests(unittest.TestCase):
    def test_exact_six_unrelated_shared_visual_steps_only(self):
        steps = _job_steps()
        self.assertEqual(len(UNRELATED_STEPS), 6)
        self.assertEqual(len(set(UNRELATED_STEPS)), 6)
        for step in UNRELATED_STEPS:
            with self.subTest(step=step):
                self.assertIn(step, steps)
                self.assertEqual(steps[step].count(LEAF_EXCEPTION), 1)
                self.assertIn("\n        run:", steps[step])
        # The six unrelated shared steps are the only ones with this precise
        # positive full-test selector, except the separately guarded Glass tail.
        all_names = set(UNRELATED_STEPS) | {
            "Glass zoom, shell, and gutter visual QA (all three, bounded parallel)"
        }
        self.assertEqual(
            {name for name, body in steps.items() if LEAF_EXCEPTION in body},
            all_names,
        )

    def test_baseline_and_composer_remain_mandatory_on_owner_leaf(self):
        steps = _job_steps()
        for name in MANDATORY_STEPS:
            with self.subTest(name=name):
                self.assertIn(name, steps)
                self.assertNotIn(LEAF_EXCEPTION, steps[name])
                self.assertNotIn("\n        if:", steps[name] if name not in ("Print QA report", "Upload browser evidence") else "")
        self.assertIn("B62_QA_VISUAL_SCOPE:", steps["Desktop and mobile browser QA"])
        self.assertIn("b62_browser_visual_qa.py", steps["Desktop and mobile browser QA"])
        self.assertIn("b62_interaction_polish_browser_qa.py", steps[
            "Composer and response interaction polish browser QA"])
        self.assertIn("if: always()", steps["Upload browser evidence"])

    def test_only_modified_proven_leaf_modules_receive_shortcut(self):
        paths = planner.GLASS_TAIL_UNCHANGED_LEAVES
        self.assertEqual(paths, {
            "apps/padiem-chat/static/claw-web-xlsx-sources.js",
            "apps/padiem-chat/static/conversation-export.js",
        })
        for path in paths:
            self.assertFalse(planner.require_glass_visual_tail(
                {path}, {path: "modified"}, expected_files=1))
            for status in ("added", "removed", "renamed", "copied", ""):
                self.assertTrue(planner.require_glass_visual_tail(
                    {path}, {path: status}, expected_files=1))
            self.assertTrue(planner.require_glass_visual_tail(
                {path}, {path: "modified"}, expected_files=None))
            self.assertTrue(planner.require_glass_visual_tail(
                {path}, {path: "modified"}, expected_files=2))
            self.assertTrue(planner.require_glass_visual_tail(
                {path}, {path: "modified"}, expected_files=1, manual=True))
        for shared in ("apps/padiem-chat/static/app.js",
                       "apps/padiem-chat/static/index.html",
                       "apps/padiem-chat/static/padiem-first-use.css",
                       "apps/padiem-chat/app/app_factory.py"):
            self.assertTrue(planner.require_glass_visual_tail(
                {shared}, {shared: "modified"}, expected_files=1))
            path = next(iter(paths))
            self.assertTrue(planner.require_glass_visual_tail(
                {path, shared},
                {path: "modified", shared: "modified"}, expected_files=2))
        self.assertTrue(planner.require_glass_visual_tail(None, None))

    def test_full_plan_ownership_and_separate_feature_jobs_are_retained(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("glass_visual_tail_required: ${{ steps.classify.outputs.glass_visual_tail_required }}", source)
        self.assertIn("  conversation-export-browser-qa:", source)
        self.assertIn("  document-browser-qa:", source)
        self.assertIn("  project-files-browser-qa:", source)
        self.assertIn("  auth-history-browser-qa:", source)
        self.assertIn(".github/tests/test_3989_b62_owner_leaf_browser_base.py",
                      planner.PLAN_FILES)
        self.assertIn("name: Upload browser evidence", source)


if __name__ == "__main__":
    unittest.main()
