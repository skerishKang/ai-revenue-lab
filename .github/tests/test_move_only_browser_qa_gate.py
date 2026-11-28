"""#CI: move-only label suppresses only hosted browser QA, not required checks."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BROWSER = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
CHAT = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
LABEL_GUARD = (
    "(github.event_name != 'pull_request' || "
    "!contains(github.event.pull_request.labels.*.name, 'move-only'))"
)
BROWSER_JOBS = (
    "accessibility-browser-qa",
    "auth-history-browser-qa",
    "browser-qa",
    "browser-contract-qa",
    "conversation-delete-browser-qa",
    "conversation-export-browser-qa",
    "deep-research-browser-qa",
    "document-browser-qa",
    "error-retry-browser-qa",
    "image-browser-qa",
    "mobile-touch-target-qa",
    "project-delete-browser-qa",
    "project-files-browser-qa",
    "projects-browser-qa",
    "saved-outputs-browser-qa",
    "structured-answer-browser-qa",
    "web-search-browser-qa",
)


def job_blocks(source: str) -> dict[str, str]:
    source = source.split("\njobs:\n", 1)[1]
    headers = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]+):$", source))
    return {
        m.group(1): source[m.end():headers[i + 1].start() if i + 1 < len(headers) else len(source)]
        for i, m in enumerate(headers)
    }


def selected(event: str, labels: tuple[str, ...], path_plan: bool) -> bool:
    # Truth table for the exact, separately asserted GitHub expression.
    return (event != "pull_request" or "move-only" not in labels) and path_plan


class MoveOnlyBrowserQALabelContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = BROWSER.read_text(encoding="utf-8")
        cls.jobs = job_blocks(cls.workflow)

    def test_event_reruns_for_label_changes_and_preserves_existing_events(self):
        trigger = self.workflow.split("on:\n  pull_request:\n", 1)[1].split(
            "\n  workflow_dispatch:", 1
        )[0]
        self.assertRegex(
            trigger, r"(?m)^    types: \[opened, reopened, synchronize, labeled, unlabeled\]$"
        )
        self.assertIn('    paths-ignore:\n      - "apps/padiem-chat/tests/**"', trigger)
        self.assertIn("  workflow_dispatch:", self.workflow)

    def test_every_hosted_browser_job_has_the_exact_only_pr_move_only_guard(self):
        self.assertEqual(set(self.jobs), {"plan", *BROWSER_JOBS})
        for job in BROWSER_JOBS:
            with self.subTest(job=job):
                source = self.jobs[job]
                expected = (
                    "    needs: plan\n"
                    "    if: ${{ "
                    + LABEL_GUARD
                    + f" && needs.plan.outputs.{job.replace('-', '_')} == 'true' "
                    + "}}"
                )
                self.assertIn(expected, source)
                # The exact path-selected condition remains a conjunct.
                self.assertEqual(len(re.findall(r"(?m)^    if:", source)), 1)
        self.assertNotIn("!contains(github.event.pull_request.labels.*.name", self.jobs["plan"])
        self.assertEqual(self.workflow.count("!contains(github.event.pull_request.labels.*.name, 'move-only')"), 17)

    def test_labeled_skips_and_unlabeled_keeps_original_path_routing(self):
        # Both states of the path plan are checked; a label never enables a QA
        # job that would otherwise be unselected.
        for planned in (False, True):
            with self.subTest(planned=planned):
                self.assertEqual(selected("pull_request", (), planned), planned)
                self.assertFalse(selected("pull_request", ("move-only",), planned))
                self.assertEqual(selected("pull_request", ("other",), planned), planned)
                self.assertEqual(selected("workflow_dispatch", (), planned), planned)
        self.assertTrue(selected("pull_request", (), True))
        self.assertFalse(selected("pull_request", ("move-only",), True))
        self.assertTrue(selected("pull_request", (), True))  # label removed

    def test_plan_contract_runs_and_required_fan_in_is_not_skipped(self):
        self.assertIn(
            "python -m unittest discover -s .github/tests -p test_move_only_browser_qa_gate.py -v",
            self.jobs["plan"],
        )
        required = CHAT.read_text(encoding="utf-8")
        self.assertIn("  b62-test:\n    name: b62-test\n    if: always()", required)
        self.assertIn('test "$PLAN_RESULT" = success', required)
        self.assertIn('test "${SOURCE_READ_RESULT:-}" = success', required)
        # A skipped browser leaf must not be falsely counted as a passed
        # required pytest, source-reading, or Worker check in the b62-test.
        b62_test = job_blocks(required)["b62-test"]
        self.assertNotIn("browser-qa", b62_test)
        self.assertNotIn("move-only", required)
        self.assertIn("b62-chat-pytest", b62_test)
        self.assertIn("b62-source-read-tests", b62_test)
        self.assertIn("b62-worker-suite", b62_test)


if __name__ == "__main__":
    unittest.main()
