"""Offline contract for the pc_read latency monitor package.

Pins the operator-facing rules so they cannot drift silently: the 30-minute
schedule, the one-journal-warning rule (failure or end-to-end over 30 s), the
7-day JSONL retention, and the cycle attempting both devices independently.
The measured devices are COM1 and COM2; CGI-1 is a customer PC and is not a
target. No service, network or journal is touched.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
PACKAGE = REPO / "deploy" / "host-com2" / "pc-read-metrics"


def _load_measure():
    spec = importlib.util.spec_from_file_location(
        "pc_read_measure", REPO / "scripts" / "ops" / "pc_read_measure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(**overrides):
    row = {
        "http_status": 200, "call_status": "completed",
        "stages": {"end_to_end_ms": 29_999.0},
    }
    row.update(overrides)
    return row


class PcReadMetricsContractTest(unittest.TestCase):
    def test_retention_is_seven_days_and_warns_on_failure_or_over_30s(self):
        measure = _load_measure()
        self.assertEqual(measure.RETENTION_DAYS, 7)
        self.assertFalse(measure.warn_if_needed(_row()))
        self.assertTrue(measure.warn_if_needed(_row(stages={"end_to_end_ms": 30_001.0})))
        self.assertTrue(measure.warn_if_needed(_row(call_status="failed")))
        self.assertTrue(measure.warn_if_needed(_row(http_status=503)))

    def test_timer_runs_every_thirty_minutes_and_the_cycle_tries_both_devices(self):
        timer = (PACKAGE / "padiem-pc-read-metrics.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* *:00/30:00", timer)
        self.assertIn("Persistent=true", timer)

        service = (PACKAGE / "padiem-pc-read-metrics.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/opt/padiem/pc-read-metrics/run_cycle.sh", service)

        cycle = (PACKAGE / "run_cycle.sh").read_text(encoding="utf-8")
        self.assertIn("run --device comp1", cycle)
        self.assertIn("run --device comp2", cycle)
        self.assertNotIn("cgi1", cycle.lower())
        # One device failing must not skip the other device's measurement.
        self.assertLess(cycle.index("comp1"), cycle.index("|| failed=1"))
        self.assertLess(cycle.index("|| failed=1"), cycle.index("comp2"))
        self.assertIn('exit "$failed"', cycle)

    def test_install_requires_com1_and_paths_but_treats_com2_token_as_optional(self):
        install = (PACKAGE / "install.sh").read_text(encoding="utf-8")
        required_line = next(
            line for line in install.splitlines() if line.startswith("for required in")
        )
        self.assertIn("comp1.token", required_line)
        self.assertIn("paths.json", required_line)
        self.assertNotIn("cgi1.token", required_line)
        self.assertNotIn("comp2.token", required_line)
        # The missing COM2 token is reported, not fatal: the timer keeps COM1.
        self.assertIn("comp2.token", install)
        self.assertIn("skip COM2 only", install)
        # The installer never reads or prints token values.
        self.assertNotIn("cat ", install)
        self.assertNotIn("echo $secret", install)
        self.assertIn("chmod 600", install)

    def test_device_choices_are_com1_and_com2_and_cgi1_is_rejected(self):
        script = REPO / "scripts" / "ops" / "pc_read_measure.py"
        rejected = subprocess.run(
            [sys.executable, str(script), "run", "--device", "cgi1"],
            capture_output=True, text=True,
        )
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("invalid choice", rejected.stderr)

        with tempfile.TemporaryDirectory() as config_dir:
            accepted = subprocess.run(
                [sys.executable, str(script),
                 "--config-dir", config_dir,
                 "--store", os.path.join(config_dir, "metrics.jsonl"),
                 "run", "--device", "comp2"],
                capture_output=True, text=True,
            )
        self.assertEqual(accepted.returncode, 3, accepted.stderr)
        self.assertIn("device=comp2 reason=token_missing", accepted.stderr)

    def test_a_pc_without_a_token_is_skipped_with_a_journal_record(self):
        measure = _load_measure()
        with tempfile.TemporaryDirectory() as config_dir:
            args = argparse.Namespace(
                config_dir=config_dir, device="comp2", label="timer", path=None,
                store=os.path.join(config_dir, "metrics.jsonl"),
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = measure.cmd_run(args)
        self.assertEqual(rc, 3)
        self.assertIn("device=comp2 reason=token_missing", stderr.getvalue())

    def test_historic_cgi1_rows_still_summarize(self):
        measure = _load_measure()
        with tempfile.TemporaryDirectory() as config_dir:
            store = os.path.join(config_dir, "metrics.jsonl")
            row = {
                "ts": measure.iso(), "ts_epoch": time.time(), "device": "cgi1",
                "label": "timer", "http_status": 200, "call_status": "completed",
                "stages": {},
            }
            with open(store, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = measure.cmd_summarize(
                    argparse.Namespace(store=store, since_hours=24 * 7)
                )
        self.assertEqual(rc, 0)
        self.assertIn("device=cgi1", out.getvalue())


if __name__ == "__main__":
    unittest.main()