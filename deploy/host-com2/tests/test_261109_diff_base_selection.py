"""2026-11-09: the plan's diff base is the code the host actually runs.

Defect (measured in production): a #7243 deploy planned ``p01:SKIP
reason_files=0 reason=NO_DEPLOY_PATHS`` although that PR changed
``apps/padiem-ai-engine/app/claw_pc_query_step_driver.py`` — a path the P01
mapping already covers (``deploy_from_main.sh:331``). The plan diffs ``$old``
(the ops checkout HEAD) against the target SHA, and a preceding dry run had
left HEAD *at* the target, so the diff was empty and every service read
``reason_files=0``.

A deploy now records the sha it installed, and the plan prefers that record as
the diff base when the checkout already sits at the target. These tests pin
both directions: a P01-only change selects P01, an unrelated change keeps P01
out, and a release that is behind is never skipped even with an empty diff.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from test_deploy_from_main import DeployHarness


def _plan(harness: DeployHarness, sha: str) -> subprocess.CompletedProcess[str]:
    return harness._run_main(
        sha,
        "--ops-checkout", harness.ops.as_posix(),
        "--state-dir", harness.state.as_posix(),
        "--chat-db", harness.db.as_posix(),
    )


def _record_applied(harness: DeployHarness, sha: str) -> None:
    harness.state.mkdir(parents=True, exist_ok=True)
    (harness.state / "last_applied_sha").write_text(sha + "\n", encoding="utf-8")


class DiffBaseSelectionTest(DeployHarness):
    scenario = "p01"

    def test_a_p01_only_change_is_planned_even_when_head_sits_at_the_target(self) -> None:
        """The checkout parked at the target must not erase the change list."""
        _record_applied(self, self.first)
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DIFF_BASE=LAST_APPLIED_SHA", result.stdout)
        self.assertIn("CHANGED=apps/padiem-ai-engine/asgi.py", result.stdout)
        self.assertIn("DECISION_P01=REDEPLOY", result.stdout)
        self.assertIn("p01:WOULD_DEPLOY", result.stdout)

    def test_without_a_recorded_sha_the_plan_says_so(self) -> None:
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DIFF_BASE=CHECKOUT_AT_TARGET", result.stdout)

    def test_a_p01_release_that_is_behind_is_still_not_skipped(self) -> None:
        """Even with an empty diff the running-code comparison wins."""
        release = (self.p01 / "app").resolve()
        (release / "app" / "claw_pc_query_step_driver.py").write_text(
            "# stale\n", encoding="utf-8",
        )
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P01_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", result.stdout)
        self.assertIn("p01:WOULD_DEPLOY", result.stdout)

class DocsOnlyDiffBaseTest(DeployHarness):
    """A change that maps to no service keeps every service out of the plan."""

    scenario = "docs_only"

    def test_a_docs_only_change_does_not_select_p01(self) -> None:
        _record_applied(self, self.first)
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DECISION_P01=SKIP", result.stdout)
        self.assertIn("p01:SKIP", result.stdout)


class P01PathCoverageTest(unittest.TestCase):
    def test_the_engine_driver_path_maps_to_p01(self) -> None:
        """The mapping that made the SKIP surprising is already correct."""
        script = (Path(__file__).resolve().parents[1] / "deploy_from_main.sh").read_text(
            encoding="utf-8",
        )
        mapping = script.split("service_for_path()", 1)[1].split("p01_matches_target()", 1)[0]
        assert "apps/padiem-ai-engine/*" in mapping
        assert "apps/padiem-ai-engine/*|deploy/host-com2/p01/*" in mapping


class QueueRunningCodeTest(DeployHarness):
    """The queue mirror is compared by file, so a stale copy cannot be skipped."""

    scenario = "queue"

    def setUp(self) -> None:
        super().setUp()
        # The plan reads the mirror from this variable; the apply wrapper uses
        # QUEUE_ROOT. Point both at the harness tree.
        self.env["PADIEM_COM2_MESH_QUEUE_APP"] = self.queue.as_posix()

    def test_a_stale_queue_file_is_not_skipped(self) -> None:
        # The plan must catch a running tree that differs from this commit even
        # when the checkout already sits at the target (empty diff). The tree
        # must look installed first: an install always carries the shared-module
        # links and service.py (an unmarked directory is "not installed").
        (self.queue / "app").mkdir(exist_ok=True)
        (self.queue / "padiem_ai_core").mkdir(exist_ok=True)
        running = self.queue / "service.py"
        running.parent.mkdir(parents=True, exist_ok=True)
        running.write_text("# stale queue", encoding="utf-8")
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("QUEUE_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", result.stdout)
        self.assertIn("DECISION_QUEUE=REDEPLOY", result.stdout)
        self.assertIn("queue:WOULD_DEPLOY", result.stdout)

    def test_the_queue_comparison_is_wired_like_the_other_services(self) -> None:
        """A queue mismatch must reach the plan, not only a printed line."""
        script = (Path(__file__).resolve().parents[1] / "deploy_from_main.sh").read_text(
            encoding="utf-8",
        )
        assert "queue_matches_target()" in script
        assert "QUEUE_RUNNING_CODE=DIFF_OR_UNVERIFIABLE" in script
        assert "wanted[queue]=1" in script
        # The mismatch must also name its reason in the decision line.
        assert "queue) mismatch=$queue_mismatch" in script


class QueueNotInstalledTest(DeployHarness):
    """A directory that is not an install is never reported as behind."""

    scenario = "docs_only"

    def setUp(self) -> None:
        super().setUp()
        self.env["PADIEM_COM2_MESH_QUEUE_APP"] = self.queue.as_posix()

    def test_a_plain_directory_is_not_installed(self) -> None:
        # The harness's queue root holds no app/core links and no service.py.
        (self.queue / "leftover.txt").write_text("x", encoding="utf-8")
        _record_applied(self, self.first)
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("QUEUE_RUNNING_CODE=NOT_INSTALLED", result.stdout)
        self.assertIn("queue:SKIP", result.stdout)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP", result.stdout)

    def test_a_directory_without_the_install_links_is_not_a_stale_mirror(self) -> None:
        """A foreign directory that happens to hold a file is not "behind".

        An install always carries the shared-module links and service.py; a
        directory without them is not this service, so the plan must say
        NOT_INSTALLED rather than redeploy the queue for every commit.
        """
        (self.queue / "service.py").write_text("# stale queue", encoding="utf-8")
        _record_applied(self, self.first)
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = _plan(self, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("QUEUE_RUNNING_CODE=NOT_INSTALLED", result.stdout)
        self.assertIn("queue:SKIP", result.stdout)
