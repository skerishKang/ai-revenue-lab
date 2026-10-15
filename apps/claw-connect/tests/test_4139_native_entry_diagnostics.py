"""Opt-in native pre-parser tracing: never persist input or exception text."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from padiem_connector.native_launch_diagnostics import PHASES, mark


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native forensic mode")
def test_full_stage_sequence_is_only_fixed_phase_codes(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "Padiem" / "ClawConnect"
    root.mkdir(parents=True)
    target = root / "native-launch-diagnostics.jsonl"
    mark("exe_entry")
    assert not target.exists()  # Explicit opt-in required.
    (root / "native-launch-diagnostics.enabled").touch()
    phases = (
        "exe_entry", "import_begin", "import_ok", "argv_parse_begin",
        "argv_parse_ok", "uri_accepted", "app_construct_begin",
        "app_construct_ok", "single_instance_begin", "single_instance_owned",
        "tray_begin", "tray_created", "tray_run_enter",
    )
    for phase in phases:
        mark(phase)
    mark("exited", exit_code=0)  # unknown phase is ignored
    mark("entry_exit", exit_code=0)
    rows = [json.loads(t) for t in target.read_text(encoding="ascii").splitlines()]
    assert [row["phase"] for row in rows] == [*phases, "entry_exit"]
    assert all(set(row) <= {"phase", "time_utc", "pid", "exit_code", "exception_kind"} for row in rows)
    assert all(row["phase"] in PHASES for row in rows)
    assert rows[-1]["exit_code"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native forensic mode")
def test_exception_kind_is_bounded_and_never_serializes_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "Padiem" / "ClawConnect"
    root.mkdir(parents=True)
    (root / "native-launch-diagnostics.enabled").touch()
    mark("exception", exc=RuntimeError("URI=SECRET credential=SECRET"))
    record = (root / "native-launch-diagnostics.jsonl").read_text(encoding="ascii")
    assert "SECRET" not in record and "credential" not in record
    assert json.loads(record)["exception_kind"] == "RuntimeError"


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native forensic mode")
def test_diagnostic_write_failure_cannot_block_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "Padiem" / "ClawConnect"
    root.mkdir(parents=True)
    (root / "native-launch-diagnostics.enabled").touch()
    from unittest.mock import patch
    with patch("os.open", side_effect=PermissionError("denied")):
        assert mark("exe_entry") is None


def test_known_native_path_stages_cover_early_failures():
    required = {
        "exe_entry", "import_begin", "import_ok", "argv_parse_begin",
        "argv_parse_ok", "uri_accepted", "uri_rejected",
        "app_construct_begin", "app_construct_ok", "single_instance_begin",
        "single_instance_existing", "single_instance_owned",
        "existing_run_result", "signal_delivered", "signal_rejected",
        "tray_begin", "tray_created", "tray_run_enter", "tray_run_exit",
        "app_run_returned", "entry_exit", "exception",
    }
    assert required <= PHASES


def test_native_uri_classification_is_fixed_and_never_records_input(monkeypatch):
    from claw_connect import __main__ as cli
    from padiem_connector import native_launch_diagnostics as diagnostics
    phases = []
    monkeypatch.setattr(diagnostics, "mark", lambda phase, **kwargs: phases.append(phase))

    class AcceptedApp:
        def run(self, *, explicit_connect=False):
            assert explicit_connect
            return 0

    monkeypatch.setattr(cli, "ConnectApp", AcceptedApp)
    scenarios = (
        ("padiem-connector://start", "uri_class_exact", 0),
        ("padiem-connector://start/", "uri_class_trailing_slash", 2),
        ('"padiem-connector://start"', "uri_class_quoted", 2),
        ("padiem-connector://start?token=DO_NOT_LOG", "uri_class_other", 2),
    )
    for uri, expected, result in scenarios:
        phases.clear()
        assert cli.main(["open-from-web", uri]) == result
        assert expected in phases
        assert all(p in diagnostics.PHASES and "DO_NOT_LOG" not in p for p in phases)
        assert ("uri_accepted" in phases) == (result == 0)
