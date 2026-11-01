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
    monkeypatch.setenv("B66_CGI_ALPHA_USERNAME", "synthetic-user")
    monkeypatch.setenv("B66_CGI_ALPHA_PASSWORD", "synthetic-password")
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
    monkeypatch.delenv("B66_CGI_ALPHA_USERNAME", raising=False)
    monkeypatch.delenv("B66_CGI_ALPHA_PASSWORD", raising=False)
    assert check.check("http://127.0.0.1:1") == ("FAIL", "qa_credential_missing")
    assert check.check("http://example.com") == ("FAIL", "invalid_chat_origin")
    assert check.check("https://example.com") == ("FAIL", "invalid_chat_origin")
