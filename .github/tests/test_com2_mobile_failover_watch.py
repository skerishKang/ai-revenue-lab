"""Bounded COM2 mobile offline watchdog contracts."""
import datetime as dt
import importlib.util
import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("com2_mobile_failover_watch", SCRIPTS / "com2_mobile_failover_watch.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW = dt.datetime(2026, 10, 20, 1, tzinfo=dt.timezone.utc)
SHA = "a" * 40
REPO = "skerishKang/ai-revenue-lab"
def timestamp(age):
    return (NOW - dt.timedelta(minutes=age)).isoformat().replace("+00:00", "Z")
def pr(age=35, sha=SHA, state="open"):
    return {"state":state,"updated_at":timestamp(age),"head":{"sha":sha,"repo":{"full_name":REPO}}}
def status(context, state, age=35):
    return {"context":context,"state":state,"created_at":timestamp(age)}

class MobileWatch(unittest.TestCase):
    def test_only_mobile_sources(self):
        self.assertTrue(mod.selected([{"filename":"apps/padiem-chat/app/main.py"}]))
        self.assertTrue(mod.selected([{"filename":".github/scripts/b62_mobile_touch_target_qa.py"}]))
        self.assertFalse(mod.selected([{"filename":"docs/README.md"}]))
        self.assertFalse(mod.selected([{"filename":"apps/padiem-chat/tests/unit.py"}]))
        self.assertTrue(mod.selected([{"filename":"docs/file"+str(i)} for i in range(100)]))
    def test_stale_absent_or_pending(self):
        self.assertTrue(mod.eligible(pr(), [], REPO, NOW))
        self.assertTrue(mod.eligible(pr(), [status(mod.CONTEXT,"pending")], REPO, NOW))
        self.assertFalse(mod.eligible(pr(), [status(mod.CONTEXT,"pending",5)], REPO, NOW))
    def test_terminal_and_dispatched_skip(self):
        for state in ("success","failure"):
            self.assertFalse(mod.eligible(pr(), [status(mod.CONTEXT,state)], REPO, NOW))
        for state in ("pending","success"):
            self.assertFalse(mod.eligible(pr(), [status(mod.MARKER,state)], REPO, NOW))
        self.assertTrue(mod.eligible(pr(), [status(mod.MARKER,"failure")], REPO, NOW))
    def test_strict_head_and_age(self):
        self.assertFalse(mod.eligible(pr(5), [], REPO, NOW))
        self.assertFalse(mod.eligible(pr(state="closed"), [], REPO, NOW))
        self.assertFalse(mod.eligible(pr(sha="bad"), [], REPO, NOW))
        self.assertFalse(mod.eligible(pr(), [], "other/repo", NOW))
if __name__ == "__main__":
    unittest.main()
