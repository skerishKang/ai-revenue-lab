"""Offline QA login -> orchestration tests. No external requests."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "scripts" / "post_deploy_ai_answer_check.py"
spec = importlib.util.spec_from_file_location("ai_answer_check", path)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize(("mode", "expected"), [
    ("ok", ("PASS", "none")),
    ("503", ("FAIL", "entitlement_unavailable")),
    ("401", ("FAIL", "qa_login_refused")),
    ("401_answer", ("FAIL", "unauthorized")),
])
def test_login_then_one_answer_or_bounded_failure(monkeypatch, capsys, mode, expected):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def reply(self, status, payload, cookie=False):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if cookie:
                self.send_header("Set-Cookie", "qa_session=fake; Path=/")
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            if self.path.endswith("/login"):
                self.reply(401, {"error": {"code": "invalid_credentials"}}, False) if mode == "401" else self.reply(200, {"ok": True}, True)
            elif self.path == "/api/orchestration":
                assert "qa_session=fake" in self.headers.get("Cookie", "")
                if mode == "401_answer":
                    self.reply(401, {"error": {"code": "unauthorized"}})
                elif mode == "503":
                    self.reply(503, {"error": {"code": "entitlement_unavailable", "message": "never print"}})
                else:
                    self.reply(200, {"answer": "never print"})
            else:
                self.reply(404, {})
        def do_GET(self):
            calls.append(self.path)
            self.reply(200, {"authenticated": True})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("QA_DEPLOY_USERNAME", "synthetic-user")
    monkeypatch.setenv("QA_DEPLOY_PASSWORD", "synthetic-password")
    try:
        assert check.check(f"http://127.0.0.1:{server.server_port}") == expected
        assert calls.count("/api/orchestration") == (0 if mode == "401" else 1)
        captured = capsys.readouterr()
        assert "synthetic" not in captured.out + captured.err
        assert "never print" not in captured.out + captured.err
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_missing_credentials_and_bad_origin_fail_closed(monkeypatch):
    monkeypatch.delenv("QA_DEPLOY_USERNAME", raising=False)
    monkeypatch.delenv("QA_DEPLOY_PASSWORD", raising=False)
    assert check.check("http://127.0.0.1:1") == ("FAIL", "qa_credential_missing")
    assert check.check("http://example.com") == ("FAIL", "invalid_chat_origin")
    assert check.check("https://example.com") == ("FAIL", "invalid_chat_origin")


def _canary(code):
    # Kept for readers tracing the real error path: bounded_call raises this
    # class and _check_once converts it to a FAIL tuple before the retry sees it.
    return check.CanaryError(code)


def test_a_transport_blip_is_retried_and_then_passes(monkeypatch):
    """11-09 measured failure: one blip, then the identical request passes."""
    calls = []
    sleeps = []

    def fake_once(base_url):
        calls.append(base_url)
        if len(calls) == 1:
            return ("FAIL", "http_transport_unavailable")
        return ("PASS", "none")

    monkeypatch.setattr(check, "_check_once", fake_once)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("PASS", "none")
    assert len(calls) == 2
    assert sleeps == [check.TRANSPORT_RETRY_SECONDS]


def test_a_non_transport_code_fails_immediately_without_retry(monkeypatch):
    calls = []
    sleeps = []

    def fake_once(base_url):
        calls.append(base_url)
        return ("FAIL", "empty_answer")

    monkeypatch.setattr(check, "_check_once", fake_once)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("FAIL", "empty_answer")
    assert len(calls) == 1
    assert sleeps == []


def test_transport_failure_on_every_attempt_still_fails(monkeypatch):
    calls = []
    sleeps = []

    def fake_once(base_url):
        calls.append(base_url)
        return ("FAIL", "http_transport_unavailable")

    monkeypatch.setattr(check, "_check_once", fake_once)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("FAIL", "http_transport_unavailable")
    assert len(calls) == check.TRANSPORT_ATTEMPTS
    assert sleeps == [check.TRANSPORT_RETRY_SECONDS] * (check.TRANSPORT_ATTEMPTS - 1)


def test_a_real_dropped_connection_is_retried_end_to_end(monkeypatch):
    """The retry engages on the real transport error class, not a mock shape.

    The first orchestration POST is answered by closing the socket mid-request
    (the URLError/OSError class bounded_call maps to http_transport_unavailable);
    the second attempt gets a normal answer. On the pre-retry check this test
    fails with ("FAIL", "http_transport_unavailable") — the regression proof.
    """
    state = {"orchestrations": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, payload, cookie=False):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if cookie:
                self.send_header("Set-Cookie", "qa_session=fake; Path=/")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path.endswith("/login"):
                self.reply(200, {"ok": True}, True)
                return
            if self.path == "/api/orchestration":
                state["orchestrations"] += 1
                if state["orchestrations"] == 1:
                    # Drop the connection without a response: a transport error.
                    self.connection.close()
                    return
                self.reply(200, {"answer": "never print"})
                return
            self.reply(404, {})

        def do_GET(self):
            self.reply(200, {"authenticated": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("QA_DEPLOY_USERNAME", "synthetic-user")
    monkeypatch.setenv("QA_DEPLOY_PASSWORD", "synthetic-password")
    monkeypatch.setattr(check.time, "sleep", lambda _s: None)
    try:
        assert check.check(f"http://127.0.0.1:{server.server_port}") == ("PASS", "none")
        assert state["orchestrations"] == 2
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _fake_once(codes):
    """A scripted _check_once: returns the next code on each call."""
    calls = []
    def fake(base_url):
        calls.append(base_url)
        code = codes[min(len(calls) - 1, len(codes) - 1)]
        return ("FAIL", code) if code else ("PASS", "none")
    return fake, calls


def test_a_provider_delay_is_retried_with_a_short_gap(monkeypatch):
    """11-24: one slow provider answer, then the same request passes."""
    sleeps = []
    fake, calls = _fake_once(["upstream_timeout", None])
    monkeypatch.setattr(check, "_check_once", fake)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("PASS", "none")
    assert len(calls) == 2
    assert sleeps == [check.DELAY_RETRY_SECONDS]


def test_a_persistent_provider_delay_is_degraded_not_fail(monkeypatch):
    """A provider that stays slow for the whole window cannot redden a deploy."""
    sleeps = []
    fake, calls = _fake_once(["upstream_timeout"])
    monkeypatch.setattr(check, "_check_once", fake)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("DEGRADED", "upstream_timeout")
    assert len(calls) == check.TRANSPORT_ATTEMPTS
    assert sleeps == [check.DELAY_RETRY_SECONDS] * (check.TRANSPORT_ATTEMPTS - 1)


def test_other_provider_delay_codes_share_the_degraded_path(monkeypatch):
    sleeps = []
    fake, calls = _fake_once(["provider_server_error"])
    monkeypatch.setattr(check, "_check_once", fake)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("DEGRADED", "provider_server_error")
    assert len(calls) == check.TRANSPORT_ATTEMPTS
    assert sleeps == [check.DELAY_RETRY_SECONDS] * (check.TRANSPORT_ATTEMPTS - 1)


@pytest.mark.parametrize("code", [
    "no_safe_error_code", "empty_answer", "entitlement_unavailable",
    "qa_login_refused", "ai_check_unavailable", "unexpected_http_json_shape",
])
def test_other_error_codes_still_fail_on_the_first_attempt(monkeypatch, code):
    """Only the named delay classes get a retry; every other code keeps FAIL."""
    sleeps = []
    fake, calls = _fake_once([code])
    monkeypatch.setattr(check, "_check_once", fake)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("FAIL", code)
    assert len(calls) == 1
    assert sleeps == []


def test_a_delay_that_turns_into_a_real_defect_fails_immediately(monkeypatch):
    sleeps = []
    fake, calls = _fake_once(["upstream_timeout", "empty_answer"])
    monkeypatch.setattr(check, "_check_once", fake)
    monkeypatch.setattr(check.time, "sleep", sleeps.append)
    assert check.check("https://chat.padiem.net") == ("FAIL", "empty_answer")
    assert len(calls) == 2
    assert sleeps == [check.DELAY_RETRY_SECONDS]


@pytest.mark.parametrize(("verdict", "code", "line", "exit_code"), [
    ("PASS", "none", "ai:PASS", 0),
    ("DEGRADED", "upstream_timeout", "ai:DEGRADED error_code=upstream_timeout", 0),
    ("FAIL", "no_safe_error_code", "ai:FAIL error_code=no_safe_error_code", 1),
])
def test_main_verdict_line_and_exit_code(monkeypatch, capsys, verdict, code, line, exit_code):
    monkeypatch.setattr(check, "check", lambda _base: (verdict, code))
    monkeypatch.setattr(check.argparse.ArgumentParser, "parse_args", lambda self: type(
        "Args", (), {"base_url": "https://chat.padiem.net"})())
    assert check.main() == exit_code
    assert capsys.readouterr().out.strip() == line
