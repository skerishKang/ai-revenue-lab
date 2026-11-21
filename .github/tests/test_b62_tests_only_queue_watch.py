import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from b62_tests_only_queue_watch import eligible, recover


class QueueWatchTests(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.now = dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)
        self.run = {"event": "pull_request", "run_attempt": 1,
                    "status": "in_progress", "head_repository": {"full_name": self.repo},
                    "head_sha": "a" * 40, "id": 42, "pull_requests": [{"number": 3}]}
        self.pr = {"state": "open", "head": {"sha": "a" * 40,
                                             "repo": {"full_name": self.repo}}}
        self.job = {"name": "B62 tests-only changed pytest", "status": "queued",
                    "labels": ["self-hosted", "padiem-com2-ci"],
                    "created_at": "2026-11-21T23:54:00Z"}

    def check(self):
        return eligible(self.run, self.pr, [self.job], self.repo, self.now)

    def test_only_expired_queued_exact_head(self):
        self.assertTrue(self.check())
        for key, value in (("status", "in_progress"), ("labels", ["ubuntu-latest"]),
                           ("created_at", "2026-11-21T23:59:00Z"), ("name", "other")):
            with self.subTest(key=key):
                old = self.job[key]
                self.job[key] = value
                self.assertFalse(self.check())
                self.job[key] = old
        self.run["run_attempt"] = 2
        self.assertFalse(self.check())
        self.run["run_attempt"] = 1
        self.pr["head"]["sha"] = "b" * 40
        self.assertFalse(self.check())

    def test_cancel_then_hosted_rerun(self):
        cancelled = {**self.run, "status": "completed", "conclusion": "cancelled"}
        request = Mock(side_effect=[self.pr, {"jobs": [self.job]}, self.run,
                                    {"jobs": [self.job]}, self.pr, None,
                                    cancelled, self.pr, None])
        self.assertTrue(recover(self.repo, self.run, self.now, request, lambda _: None))
        posts = [c.args[0] for c in request.call_args_list if len(c.args) == 2]
        self.assertEqual(posts, ["/repos/owner/repo/actions/runs/42/cancel",
                                 "/repos/owner/repo/actions/runs/42/rerun"])
