"""The browser fixture runner's process and loopback protocols, without launching a browser."""
import json
import subprocess
import sys

import pytest

from test_7065_session_card_browser import capture_fixture


@pytest.fixture(autouse=True)
def force_subprocess_capture(monkeypatch):
    # The stdout protocol below is the --dump-dom fallback. With Playwright
    # installed (some dev environments), capture_fixture would otherwise take
    # the condition-wait path and try to drive `sys.executable` as a browser.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)


def command(source):
    return [sys.executable, "-c", source]


def loopback_fixture(tmp_path):
    fixture = tmp_path / "session.html"
    fixture.write_text("<p>__FIXTURE_BASE__/chat-pc-session.css</p>", encoding="utf-8")
    return fixture


def loopback_source(body):
    # A browser stand-in: loads the served page, posts one report to the same
    # origin, then hangs — exactly the CI shape the loopback harness targets.
    return (
        "import sys, time, urllib.request\n"
        "page = urllib.request.urlopen(sys.argv[-1], timeout=5)\n"
        "body = page.read()\n"
        "assert page.status == 200\n"
        "assert b'__FIXTURE_BASE__' not in body, body[:120]\n"
        "assert b'/chat-pc-session.css' in body, body[:120]\n"
        "base = sys.argv[-1].rsplit('/', 1)[0]\n"
        "urllib.request.urlopen(urllib.request.Request(base + '/report', data=" + repr(body)
        + ", headers={'Content-Type': 'text/plain'}), timeout=5)\n"
        "time.sleep(30)\n"
    )


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


def test_loopback_report_arrives_while_the_browser_is_still_running(tmp_path, monkeypatch):
    processes = []
    original = subprocess.Popen

    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record)
    expected = {"ok": True, "supported": True}
    payload = json.dumps(expected).encode("utf-8")
    report = capture_fixture(
        command(loopback_source(payload)) + ["unused"], tmp_path, timeout=5,
        fixture_file=loopback_fixture(tmp_path))
    assert report == expected
    # The browser stand-in is still asleep: the harness closed it once the
    # report arrived instead of waiting for an exit that never comes.
    assert all(process.poll() is not None for process in processes)


def test_loopback_deadline_without_a_report(tmp_path):
    source = "import time; time.sleep(30)"
    with pytest.raises(AssertionError, match="did not complete before its deadline"):
        capture_fixture(command(source) + ["unused"], tmp_path, timeout=1,
                        fixture_file=loopback_fixture(tmp_path))


def test_loopback_invalid_report_is_not_promoted(tmp_path):
    source = loopback_source(b"{broken}")
    with pytest.raises(AssertionError, match="did not complete before its deadline"):
        capture_fixture(command(source) + ["unused"], tmp_path, timeout=1,
                        fixture_file=loopback_fixture(tmp_path))


def test_loopback_process_exit_without_a_report_is_failure(tmp_path):
    source = "import sys; sys.exit(3)"
    with pytest.raises(AssertionError, match="exited without a completed report"):
        capture_fixture(command(source) + ["unused"], tmp_path, timeout=3,
                        fixture_file=loopback_fixture(tmp_path))
