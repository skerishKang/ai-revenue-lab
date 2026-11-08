"""Offline contract for the pc_read latency monitor package.

Pins the operator-facing rules so they cannot drift silently: the 30-minute
schedule, the one-journal-warning rule (failure or end-to-end over 30 s), the
7-day JSONL retention, and the cycle attempting both devices independently.
No service, network or journal is touched.
"""

from __future__ import annotations

import importlib.util
import pathlib

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


def test_retention_is_seven_days_and_warns_on_failure_or_over_30s():
    measure = _load_measure()
    assert measure.RETENTION_DAYS == 7
    assert measure.warn_if_needed(_row()) is False
    assert measure.warn_if_needed(_row(stages={"end_to_end_ms": 30_001.0})) is True
    assert measure.warn_if_needed(_row(call_status="failed")) is True
    assert measure.warn_if_needed(_row(http_status=503)) is True


def test_timer_runs_every_thirty_minutes_and_the_cycle_tries_both_devices():
    timer = (PACKAGE / "padiem-pc-read-metrics.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* *:00/30:00" in timer
    assert "Persistent=true" in timer

    service = (PACKAGE / "padiem-pc-read-metrics.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/padiem/pc-read-metrics/run_cycle.sh" in service

    cycle = (PACKAGE / "run_cycle.sh").read_text(encoding="utf-8")
    assert 'run --device cgi1' in cycle
    assert 'run --device comp1' in cycle
    # One device failing must not skip the other device's measurement.
    assert cycle.index("cgi1") < cycle.index("|| failed=1") < cycle.index("comp1")
    assert 'exit "$failed"' in cycle


def test_install_refuses_to_run_without_the_preplaced_token_files():
    install = (PACKAGE / "install.sh").read_text(encoding="utf-8")
    for name in ("cgi1.token", "comp1.token", "paths.json"):
        assert name in install
    # The installer never reads or prints token values.
    assert "cat " not in install and "echo $secret" not in install
    assert "chmod 600" in install
