"""Offline contract tests for exact-SHA hosted failover decisions."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "com2_policy_failover_watch.py"
spec = importlib.util.spec_from_file_location("com2_policy_failover_watch", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW = dt.datetime(2026, 10, 20, 1, 0, tzinfo=dt.timezone.utc)
SHA = "a" * 40
REPO = "skerishKang/ai-revenue-lab"


def iso(minutes):
    return (NOW - dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def pr(minutes=30, sha=SHA, repo=REPO):
    return {"state": "open", "updated_at": iso(minutes), "head": {"sha": sha, "repo": {"full_name": repo}}}


def status(context, state, minutes=30):
    return {"context": context, "state": state, "created_at": iso(minutes)}


class FailoverWatchTest(unittest.TestCase):
    def check(self, pull, statuses):
        return mod.should_fallback(pull, statuses, REPO, NOW)

    def test_absent_status_after_wait(self):
        self.assertTrue(self.check(pr(), []))

    def test_recent_pr_not_dispatched(self):
        self.assertFalse(self.check(pr(5), []))

    def test_stale_pending_status(self):
        self.assertTrue(self.check(pr(), [status("COM2 full policy", "pending")]))

    def test_recent_pending_status(self):
        self.assertFalse(self.check(pr(), [status("COM2 full policy", "pending", 5)]))

    def test_success_and_test_failure_are_final(self):
        for state in ("success", "failure"):
            with self.subTest(state=state):
                self.assertFalse(self.check(pr(), [status("COM2 full policy", state)]))

    def test_dispatch_marker_avoids_duplicates(self):
        for state in ("pending", "success"):
            with self.subTest(state=state):
                self.assertFalse(self.check(pr(), [status("COM2 hosted failover dispatch", state)]))

    def test_failed_dispatch_can_retry(self):
        self.assertTrue(self.check(pr(), [status("COM2 hosted failover dispatch", "failure")]))

    def test_wrong_head_or_closed_pr(self):
        self.assertFalse(self.check(pr(sha="bad"), []))
        self.assertFalse(self.check(pr(repo="someone/else"), []))
        pull = pr()
        pull["state"] = "closed"
        self.assertFalse(self.check(pull, []))

    def test_stale_pr_outside_window_is_ignored(self):
        self.assertFalse(self.check(pr(3 * 24 * 60), []))


if __name__ == "__main__":
    unittest.main()
