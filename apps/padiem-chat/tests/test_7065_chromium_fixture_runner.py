"""The browser fixture runner's process protocol, without launching a browser."""
import json
import subprocess
import sys

import pytest

from test_7065_session_card_browser import capture_fixture


def command(source):
    return [sys.executable, "-c", source]


def test_completed_report_does_not_wait_for_a_hanging_process(tmp_path, monkeypatch):
    processes = []
    original = subprocess.Popen

    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record)
    expected = {"ok": True, "supported": True}
    source = "import time; print(" + repr('<pre id="report">' + json.dumps(expected) + '</pre>') + ", flush=True); time.sleep(30)"
    assert capture_fixture(command(source), tmp_path, timeout=3) == expected
    assert all(process.poll() is not None for process in processes)


@pytest.mark.parametrize("report", [{"ok": False}, {"ok": True, "supported": False}])
def test_failed_or_wrong_report_is_not_promoted_to_success(tmp_path, report):
    source = "print(" + repr('<pre id="report">' + json.dumps(report) + '</pre>') + ", flush=True)"
    result = capture_fixture(command(source), tmp_path, timeout=3)
    assert result != {"ok": True, "supported": True}


def test_fixture_crash_without_a_report_is_failure(tmp_path):
    with pytest.raises(AssertionError, match="fixture process failed"):
        capture_fixture(command("import sys; sys.exit(7)"), tmp_path, timeout=3)


@pytest.mark.parametrize("source", [
    "print('private-fixture-detail', flush=True)",
    "print('<pre id=\"report\">{broken}</pre>', flush=True)",
    "import time; print('private-fixture-detail', flush=True); time.sleep(30)",
])
def test_missing_or_invalid_report_fails_without_printing_output(tmp_path, source, capsys):
    with pytest.raises(AssertionError) as failure:
        capture_fixture(command(source), tmp_path, timeout=.3)
    assert "private-fixture-detail" not in str(failure.value)
    assert "private-fixture-detail" not in repr(failure.value)
    assert capsys.readouterr() == ("", "")
