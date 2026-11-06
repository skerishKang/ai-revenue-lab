"""#82 connector watch: the host probe reads the health the deploy already reads.

The installed watch read the public hostname, which sits behind the edge in front of
Chat. That edge answered the non-browser probe 403 and the verdict said "unknown".
deploy_from_main.sh has always judged Chat from this host's loopback instead, and the
COM2 middleware exempts GET /health from the proof check. These cases keep the probe
on that loopback and keep a quiet lane from reading as a lost counter.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
WATCH_DIR = HERE.parent / "connector-watch"
MODULE = WATCH_DIR / "connector_watch_host.py"
EXAMPLE = WATCH_DIR / "connector-watch.env.example"
DEPLOY = HERE.parent / "deploy_from_main.sh"
EXECUTOR = HERE.parents[2] / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "local_agent_oracle_mesh_executor.py"


def _load():
    clean = {key: value for key, value in os.environ.items()
             if not key.startswith("CONNECTOR_WATCH_") and key != "PC_QUEUE_BACKEND"}
    with patch.dict(os.environ, clean, clear=True):
        spec = importlib.util.spec_from_file_location("connector_watch_host_under_test", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class TestTheChatProbeIsTheHostLoopback(unittest.TestCase):
    def test_default_probe_is_the_loopback_the_deploy_reads(self):
        self.assertEqual(_load().CHAT_HEALTH_URL, "http://127.0.0.1:8798/health")
        self.assertIn("http://127.0.0.1:8798/health", DEPLOY.read_text(encoding="utf-8"))

    def test_env_example_offers_the_same_probe(self):
        self.assertIn("CONNECTOR_WATCH_CHAT_HEALTH_URL=http://127.0.0.1:8798/health",
                      EXAMPLE.read_text(encoding="utf-8"))


class TestAQuietLaneIsNotALostCounter(unittest.TestCase):
    def setUp(self):
        self.module = _load()

    def test_absent_counters_with_the_idle_heartbeat_are_ok(self):
        self.assertEqual(self.module.counters_verdict(
            {"line_blocked_total": None, "line_cleared_total": None}, idle_seen=True),
            ("ok", "idle_no_work_seen"))

    def test_absent_counters_without_any_poll_stay_unknown(self):
        self.assertEqual(self.module.counters_verdict(
            {"line_blocked_total": None, "line_cleared_total": None}),
            ("unknown", "counters_not_seen"))

    def test_seen_counters_keep_reporting_their_numbers(self):
        self.assertEqual(self.module.counters_verdict(
            {"line_blocked_total": 2, "line_cleared_total": 1}, idle_seen=True),
            ("ok", "line_blocked=2,line_cleared=1"))

    def test_an_edge_refusal_is_unknown_not_a_chat_stall(self):
        self.assertEqual(self.module.health_verdict(403), ("unknown", "chat_health_403"))
        self.assertEqual(self.module.health_verdict(200), ("ok", "chat_health_200"))
        self.assertEqual(self.module.health_verdict(503), ("stall", "chat_health_503"))

    def test_the_watch_reads_the_line_the_executor_prints(self):
        self.assertIn('print("oracle-mesh-executor poll idle", flush=True)',
                      EXECUTOR.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
