"""#4953 verdict units: all normal, one unit inactive, health failure, tunnel down."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("boot_recovery", HERE.parent / "wsl" / "boot_recovery.py")
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


def _unit(name="padiem-mesh-queue.service", *, enabled=True, active=True, required=True):
    return {"unit": name, "kind": "service", "required": required,
            "enabled": enabled, "active": active}


def _health(name="queue", ok=True, required=True):
    return {"name": name, "required": required, "ok": ok, "detail": "ok" if ok else "http_503"}


def _tunnel(name="chat-public", ok=True, required=True):
    return {"name": name, "required": required, "ok": ok, "detail": "ok" if ok else "unreachable"}


class Verdicts(unittest.TestCase):
    def test_all_normal_is_pass(self):
        report = boot.evaluate([_unit(), _unit("meshcentral.service")], [_health()], [_tunnel()])
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["failures"], [])

    def test_one_inactive_unit_fails_and_is_named(self):
        report = boot.evaluate(
            [_unit(), _unit("padiem-broker.service", active=False)], [_health()], [_tunnel()],
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("unit:padiem-broker.service", report["failures"][0])

    def test_a_disabled_or_unknown_unit_never_passes(self):
        for state in ({"enabled": False}, {"active": None}, {"enabled": None}):
            unit = _unit("padiem-chat-com2.service")
            unit.update(state)
            report = boot.evaluate([unit], [], [])
            self.assertEqual(report["status"], "FAIL", state)

    def test_health_failure_fails(self):
        report = boot.evaluate([_unit()], [_health("chat", ok=False)], [_tunnel()])
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("health:chat", report["failures"][0])

    def test_tunnel_down_fails(self):
        report = boot.evaluate([_unit()], [_health()], [_tunnel(ok=False)])
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("tunnel:chat-public", report["failures"][0])

    def test_optional_entries_are_reported_not_failing(self):
        report = boot.evaluate(
            [_unit("external.service", active=False, required=False)],
            [_health("extra", ok=False, required=False)],
            [_tunnel("extra", ok=False, required=False)],
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["skipped"]), 3)

    def test_every_default_expected_unit_is_required(self):
        self.assertTrue(boot.DEFAULT_UNITS)
        for entry in boot.DEFAULT_UNITS:
            self.assertTrue(entry["required"], entry["unit"])
            self.assertIn(entry["kind"], {"service", "timer"})
        names = {entry["unit"] for entry in boot.DEFAULT_UNITS}
        for expected in (
            "padiem-mesh-queue.service", "padiem-file-lane.service",
            "padiem-oracle-mesh-executor.service", "cloudflared.service",
            "meshcentral.service", "padiem-chat-com2.service",
            "padiem-broker.service", "padiem-offsite-backup.timer",
        ):
            self.assertIn(expected, names)


class ConfigAndNotify(unittest.TestCase):
    def test_config_override_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "units.json"
            path.write_text(json.dumps({"units": [_unit("custom.service")], "health": [], "tunnel": []}))
            config = boot.load_config(path)
            self.assertEqual(config["units"][0]["unit"], "custom.service")

    def test_missing_config_falls_back_to_defaults(self):
        config = boot.load_config(Path("/nonexistent/units.json"))
        self.assertEqual(config["units"], boot.DEFAULT_UNITS)

    def test_notify_is_honest_without_channels(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(boot.notify("x"), "not_configured")

    def test_report_file_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(boot, "STATE_DIR", Path(tmp)):
                path = boot._write_state({"status": "PASS"})
                self.assertEqual(path.name, "last.json")
                if os.name != "nt":  # chmod is a no-op on the Windows test host
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
