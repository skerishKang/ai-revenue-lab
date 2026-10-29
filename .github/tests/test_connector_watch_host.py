"""#82 — the host-side watch: systemd facts and the executor's own counters.

Only COM2 can see whether the executor process is alive and whether the #6099
watchdog restarted it; only the executor's journal carries the #6106 line counters.
The judgement is small, so the properties are worth pinning hard: a restart is only a
stall when it was the watchdog's exit code, an unread counter is never zero, and the
line that carries the verdict stays parseable by field.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "connector_watch_host", ROOT / "deploy" / "host-com2" / "connector-watch"
    / "connector_watch_host.py",
)
host = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(host)


class TestCounterParsing(unittest.TestCase):
    def test_the_last_value_wins_and_absent_is_none_not_zero(self) -> None:
        journal = (
            "oracle-mesh-executor result ok=True line_blocked_total=0 line_cleared_total=0\n"
            "noise line_blocked_total_other=9\n"
            "oracle-mesh-executor result ok=True line_blocked_total=3 line_cleared_total=2\n"
        )
        self.assertEqual(host.parse_counters(journal),
                         {"line_blocked_total": 3, "line_cleared_total": 2})
        self.assertEqual(host.parse_counters(""),
                         {"line_blocked_total": None, "line_cleared_total": None})
        self.assertEqual(host.parse_counters("line_blocked_total=abc"),
                         {"line_blocked_total": None, "line_cleared_total": None})

    def test_the_reason_has_no_spaces_so_the_line_stays_one_field(self) -> None:
        verdict = host.counters_verdict({"line_blocked_total": 4, "line_cleared_total": 1})
        self.assertEqual(verdict, ("ok", "line_blocked=4,line_cleared=1"))
        self.assertNotIn(" ", verdict[1])
        self.assertEqual(host.counters_verdict(
            {"line_blocked_total": None, "line_cleared_total": None}),
            ("unknown", "counters_not_seen"))


class TestSystemdJudgement(unittest.TestCase):
    def test_only_failed_or_inactive_is_a_stop(self) -> None:
        for active in ("active", "reloading", "activating", "deactivating"):
            self.assertEqual(host.process_verdict({"active": active})[0], "ok", active)
        for active in ("failed", "inactive"):
            self.assertEqual(host.process_verdict({"active": active}),
                             ("stall", f"executor_{active}"))
        for bad in (None, "unknown", 7):
            self.assertEqual(host.process_verdict({"active": bad})[0], "unknown", bad)

    def test_a_watchdog_restart_is_a_stall_and_a_deploy_restart_is_not(self) -> None:
        previous = {"restarts": 2}
        self.assertEqual(
            host.restart_verdict({"restarts": 3, "exit_status": 87}, previous),
            ("stall", "watchdog_restart_1x"),
        )
        self.assertEqual(
            host.restart_verdict({"restarts": 3, "exit_status": 0}, previous),
            ("ok", "restarted_1x_not_watchdog"),
        )
        self.assertEqual(host.restart_verdict({"restarts": 2, "exit_status": 87}, previous),
                         ("ok", "restarts_2"))

    def test_a_first_observation_sets_the_baseline_without_a_verdict(self) -> None:
        self.assertEqual(host.restart_verdict({"restarts": 5, "exit_status": 87}, None),
                         ("ok", "restarts_5_first_observation"))
        self.assertEqual(host.restart_verdict({"restarts": 5}, {}),
                         ("ok", "restarts_5_first_observation"))

    def test_an_unreadable_restart_count_is_unknown(self) -> None:
        self.assertEqual(host.restart_verdict({"restarts": None}, {"restarts": 1}),
                         ("unknown", "restarts_unreadable"))


class TestHealthAndCombine(unittest.TestCase):
    def test_health_reads_only_200_or_5xx_as_decided(self) -> None:
        self.assertEqual(host.health_verdict(200), ("ok", "chat_health_200"))
        self.assertEqual(host.health_verdict(503), ("stall", "chat_health_503"))
        self.assertEqual(host.health_verdict(None), ("unknown", "chat_health_none"))
        self.assertEqual(host.health_verdict(404), ("unknown", "chat_health_404"))

    def test_stall_outranks_unknown_and_an_unknown_word_cannot_become_ok(self) -> None:
        state, reasons = host.combine({
            "counters": ("unknown", "counters_not_seen"),
            "process": ("stall", "executor_failed"),
        })
        self.assertEqual(state, "stall")
        self.assertEqual(len(reasons), 2)
        self.assertEqual(host.combine({"x": ("weird", "?"), "y": ("ok", "k")})[0], "unknown")

    def test_only_a_changed_state_is_worth_a_message(self) -> None:
        self.assertTrue(host.should_notify("stall", None))
        self.assertTrue(host.should_notify("stall", {"state": "ok"}))
        self.assertFalse(host.should_notify("stall", {"state": "stall"}))
        self.assertTrue(host.should_notify("unknown", {"state": "stall"}))


class TestSystemdParse(unittest.TestCase):
    def test_properties_are_read_as_fields(self) -> None:
        parsed = host.parse_systemd({"ActiveState": "active", "NRestarts": 4,
                                     "ExecMainStatus": 0})
        self.assertEqual(parsed, {"active": "active", "restarts": 4, "exit_status": 0})
        self.assertEqual(host.parse_systemd({"ActiveState": "active", "NRestarts": "x"}),
                         {"active": "active", "restarts": None, "exit_status": None})


if __name__ == "__main__":
    unittest.main()
