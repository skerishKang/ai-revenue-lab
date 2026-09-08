"""Focused contract tests: shell lifecycle + fail-safe disable (S2)."""

import unittest

from padiem_embedded_runtime import (
    EmbeddedShell,
    SidecarContractError,
    parse_bootstrap_config,
)


def make_shell(state_host="lifecycle-host-01"):
    config = parse_bootstrap_config({"host_id": state_host, "shell_version": "0.1.0"})
    return EmbeddedShell(config)


class ShellLifecycleTests(unittest.TestCase):
    def test_full_open_close_journey(self):
        shell = make_shell()
        self.assertEqual(shell.state, "closed")
        self.assertEqual(shell.open(), "opening")
        self.assertEqual(shell.opened(), "open")
        self.assertIsNone(shell.guard_open_interaction())
        self.assertEqual(shell.close(), "closing")
        self.assertEqual(shell.closed_event(), "closed")

    def test_illegal_transitions_fail_closed(self):
        shell = make_shell()
        with self.assertRaises(SidecarContractError):
            shell.opened()
        self.assertEqual(shell.state, "closed")
        shell.open()
        with self.assertRaises(SidecarContractError):
            shell.close()
        self.assertEqual(shell.state, "opening")

    def test_disable_from_any_state_and_refuse_work(self):
        shell = make_shell()
        shell.open()
        result = shell.disable("operator hold")
        self.assertTrue(result.ok)
        self.assertEqual(shell.state, "disabled")
        with self.assertRaises(SidecarContractError):
            shell.open()
        guarded = shell.guard_open_interaction()
        self.assertIsNotNone(guarded)
        self.assertFalse(guarded.ok)
        self.assertEqual(guarded.fallback, "host-primary-continue")

    def test_enable_rearms_only_to_closed(self):
        shell = make_shell()
        shell.disable("demo complete")
        self.assertEqual(shell.enable(), "closed")
        self.assertEqual(shell.open(), "opening")

    def test_fail_marks_disabled_and_keeps_host_safe(self):
        shell = make_shell()
        shell.open()
        shell.opened()
        result = shell.fail("transport unavailable")
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "disabled")
        self.assertEqual(result.fallback, "host-primary-continue")
        self.assertEqual(shell.state, "disabled")

    def test_no_cross_instance_state(self):
        first = make_shell("host-a")
        second = make_shell("host-b")
        first.open()
        first.disable("a done")
        self.assertEqual(second.state, "closed")
        self.assertEqual(second.host_id, "host-b")


if __name__ == "__main__":
    unittest.main()
