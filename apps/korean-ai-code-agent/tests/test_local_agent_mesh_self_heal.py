"""#8193 — clock-injected self-heal tests. No sleep, no real service, no network."""
from __future__ import annotations

import unittest

from kagent.local_agent_mesh_self_heal import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_RESTARTS_PER_DAY,
    Health,
    SelfHealer,
    Shell,
)


class SelfHealContract(unittest.TestCase):
    def setUp(self):
        self.clock = [1_700_000_000.0]
        self.probes: list[Health] = []
        self.stopped: list[int] = []
        self.restarts: list[str] = []
        self.sent = []
        self.stale_shell = Shell(pid=4242, age_seconds=7 * 3600,
                                 cpu_seconds=0.7, wait_state="Wait")
        self.healthy = Health(service_running=True, connected=True,
                              last_command_at=self.clock[0], shells=())
        self.wedged = Health(service_running=True, connected=True,
                             last_command_at=self.clock[0] - 3600,
                             shells=(self.stale_shell,))

    def _healer(self, *, allowed=False, restart_ok=True, max_restarts=DEFAULT_MAX_RESTARTS_PER_DAY):
        def probe():
            return self.probes.pop(0) if self.probes else self.wedged

        def stop_shell(pid):
            self.stopped.append(pid)
            return True

        def restart():
            self.restarts.append("mesh")
            return restart_ok

        return SelfHealer(
            now=lambda: self.clock[0],
            probe=probe,
            stop_shell=stop_shell,
            restart_service=restart,
            notify=self.sent.append,
            node="COMP1",
            cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
            max_restarts_per_day=max_restarts,
            restart_allowed=lambda: allowed,
        )

    def test_a_wedged_shell_is_cleared_without_a_restart(self):
        self.probes = [self.wedged, self.healthy]
        healer = self._healer(allowed=True)
        result = healer.run_once()
        self.assertEqual(result.action, "shell_stopped")
        self.assertEqual(result.shells_stopped, (4242,))
        self.assertEqual(self.stopped, [4242])
        self.assertEqual(self.restarts, [])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].node, "COMP1")

    def test_no_permission_skips_restart_and_notifies(self):
        healer = self._healer(allowed=False)
        result = healer.run_once()
        self.assertEqual(result.action, "notify_only")
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.sent[0].detail, "restart permission unavailable")

    def test_a_refused_restart_is_reported_once(self):
        healer = self._healer(allowed=True, restart_ok=False)
        result = healer.run_once()
        self.assertEqual(result.action, "notify_only")
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(self.sent[0].detail, "restart call refused")

    def test_restart_is_used_when_shell_cleanup_did_not_recover(self):
        self.probes = [self.wedged, self.wedged]
        healer = self._healer(allowed=True)
        result = healer.run_once()
        self.assertEqual(result.action, "restarted")
        self.assertEqual(self.stopped, [4242])
        self.assertEqual(self.restarts, ["mesh"])

    def test_cooldown_blocks_a_second_action(self):
        healer = self._healer(allowed=True)
        self.assertEqual(healer.run_once().action, "restarted")
        self.clock[0] += 60
        result = healer.run_once()
        self.assertEqual(result.action, "cooldown")
        self.assertEqual(self.restarts, ["mesh"])

    def test_daily_cap_stops_restarts_and_notifies(self):
        healer = self._healer(allowed=True, max_restarts=1)
        self.assertEqual(healer.run_once().action, "restarted")
        self.clock[0] += DEFAULT_COOLDOWN_SECONDS + 1
        result = healer.run_once()
        self.assertEqual(result.action, "limit")
        self.assertEqual(self.restarts, ["mesh"])

    def test_a_responsive_agent_never_triggers_a_recovery(self):
        self.probes = [self.healthy]
        healer = self._healer(allowed=True)
        result = healer.run_once()
        self.assertEqual(result.action, "none")
        self.assertEqual(self.stopped, [])
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.sent, [])


class RecoveryReport(unittest.TestCase):
    def test_report_uses_the_existing_agent_stall_path_without_secrets(self):
        import json
        import os
        from unittest import mock

        from kagent.local_agent_mesh_self_heal import Recovery, report_recovery
        from kagent.local_agent_mesh_stall_watch import NOTIFY_KEY_ENV

        recovery = Recovery(action="shell_stopped", detail="stale shell cleared",
                            at=1_700_000_000.0, node="COMP1", shells_stopped=(4242,))
        seen = {}

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["timeout"] = timeout
            return Reply()

        with mock.patch.dict(os.environ, {NOTIFY_KEY_ENV: "unit-test-key"}):
            self.assertTrue(report_recovery(recovery, opener=opener))

        self.assertTrue(seen["url"].endswith("/api/ops/notify-event"))
        self.assertEqual(seen["body"]["site"], "pc")
        self.assertEqual(seen["body"]["kind"], "agent_stall")
        self.assertIn("shell_stopped", seen["body"]["title"])
        self.assertNotIn("4242", str(seen["body"]))


if __name__ == "__main__":
    unittest.main()
