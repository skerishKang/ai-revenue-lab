"""Offline tests for the read-only COM2 post-cutover report."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "post_cutover_report.py"
SPEC = importlib.util.spec_from_file_location("post_cutover_report", TOOL)
report_module = importlib.util.module_from_spec(SPEC)
sys.modules["post_cutover_report"] = report_module
SPEC.loader.exec_module(report_module)

CUTOVER = datetime(2026, 10, 31, 21, 7, tzinfo=timezone(timedelta(hours=9)))
START = CUTOVER
END = CUTOVER + timedelta(hours=24)
SECRETS = (
    "owner@example.com",
    "TOKEN-LEAK",
    "QUERY-LEAK",
    "COOKIE-LEAK",
    "BODY-LEAK",
    "req_0123456789abcdef01234567",
)


def request_event(route, status, request_id="req_0123456789abcdef01234567"):
    return json.dumps(
        {
            "event": "http_request",
            "service": "padiem-chat",
            "ts": "2026-10-31T21:10:00.000Z",
            "request_id": request_id,
            "request_id_source": "generated",
            "method": "GET",
            "route": route,
            "product": "chat",
            "status": status,
            "duration_ms": 1.5,
            "outcome": "server_error" if status >= 500 else "ok",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


FAKE_JOURNAL = "\n".join(
    [
        "Traceback (most recent call last):",
        '  File "/opt/padiem/chat-com2/app/auth.py", line 12, in handler',
        '    login(email="owner@example.com", token="TOKEN-LEAK", body="BODY-LEAK")',
        "NoGilError: Attempted to use PyProxy when Python GIL not held",
        "ERROR:    Exception in ASGI application",
        request_event("/api/auth/status", 500),
        request_event("/api/projects/abc?access_token=QUERY-LEAK", 502),
        request_event("/api/projects", 200),
        request_event("/api/auth/status", 503),
        'INFO:     127.0.0.1:12345 - "GET /api/auth/status?cookie=COOKIE-LEAK HTTP/1.1" 500 Internal Server Error',
    ]
) + "\n"


def fake_units(chat_journal=FAKE_JOURNAL):
    return [
        report_module.observe_unit(
            "padiem-chat-com2",
            chat_journal,
            None,
            "ActiveState=active\nNRestarts=1\nExecMainStatus=0\n",
            {"status": "PASS", "http_status": 200},
        ),
        report_module.observe_unit(
            "padiem-p01",
            "",
            None,
            "ActiveState=active\nNRestarts=0\nExecMainStatus=0\n",
            {"status": "PASS", "http_status": 200},
        ),
        report_module.observe_unit(
            "padiem-b14",
            "",
            None,
            "ActiveState=active\nNRestarts=0\nExecMainStatus=0\n",
            {"status": "PASS", "http_status": 200},
        ),
    ]


class AnalyzeJournal(unittest.TestCase):
    def test_counts_signatures_and_uses_app_events_over_access_log(self):
        stats = report_module.analyze_journal(FAKE_JOURNAL)
        self.assertEqual(stats["tracebacks"], 1)
        self.assertEqual(stats["error_lines"], 1)
        self.assertEqual(stats["nogil_occurrences"], 1)
        self.assertEqual(stats["pyproxy_occurrences"], 1)
        self.assertEqual(stats["telemetry_records"], 4)
        self.assertEqual(stats["access_records"], 1)
        http = report_module.choose_http(stats)
        self.assertTrue(http["available"])
        self.assertEqual(http["source"], "app_request_events")
        self.assertEqual(http["request_records"], 4)
        self.assertEqual(http["total"], 3)
        self.assertEqual(http["by_route"], {"/api/auth/status": 2, "/api/projects/*": 1})
        self.assertEqual(http["focus"], {"/api/auth/status": 2, "/api/projects": 1})

    def test_access_log_is_used_when_the_app_has_no_request_events(self):
        text = (
            'INFO:     127.0.0.1:1 - "GET /api/auth/status?token=TOKEN-LEAK HTTP/1.1" 500 Internal Server Error\n'
            'INFO:     127.0.0.1:2 - "GET /api/projects/abc?email=owner@example.com HTTP/1.1" 503 Service Unavailable\n'
            'INFO:     127.0.0.1:3 - "GET /api/projects HTTP/1.1" 200 OK\n'
        )
        http = report_module.choose_http(report_module.analyze_journal(text))
        self.assertTrue(http["available"])
        self.assertEqual(http["source"], "access_log")
        self.assertEqual(http["request_records"], 3)
        self.assertEqual(http["total"], 2)
        self.assertEqual(http["by_route"], {"/api/auth/status": 1, "/api/projects/*": 1})
        rendered = json.dumps(http)
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)

    def test_no_request_records_means_5xx_is_unavailable(self):
        http = report_module.choose_http(report_module.analyze_journal("Traceback (most recent call last):\nERROR: boom\n"))
        self.assertFalse(http["available"])
        self.assertIsNone(http["total"])
        self.assertEqual(http["reason"], "no_request_records")

    def test_unreadable_journal_has_no_zero_counts(self):
        unit = report_module.observe_unit("padiem-chat-com2", None, "exit_1", "NRestarts=0\n", None)
        self.assertIsNone(unit["counts"])
        self.assertFalse(unit["journal"]["read"])
        self.assertEqual(unit["http_5xx"]["reason"], "journal_unreadable")


class RoutePrivacy(unittest.TestCase):
    def test_routes_are_bounded_and_query_free(self):
        self.assertEqual(report_module.normalize_route("/api/auth/status?x=1"), "/api/auth/status")
        self.assertEqual(report_module.normalize_route("/api/projects"), "/api/projects")
        self.assertEqual(report_module.normalize_route("/api/projects/abc?x=1"), "/api/projects/*")
        self.assertEqual(report_module.normalize_route("/api/projects/abc/files"), "/api/projects/*")
        self.assertEqual(report_module.normalize_route("/api/users/alice"), "/api/users/*")
        self.assertEqual(report_module.normalize_route("/user/owner@example.com"), "/user/*")
        self.assertEqual(report_module.normalize_route("https://example.invalid/secret"), "<unknown>")

    def test_report_contains_no_raw_journal_material(self):
        units = fake_units()
        report = report_module.build_report(START, END, CUTOVER, units)
        summary = report_module.render_summary(report)
        rendered = json.dumps(report)
        for secret in SECRETS:
            self.assertNotIn(secret, summary)
            self.assertNotIn(secret, rendered)
        self.assertNotIn("request_id", rendered)
        self.assertIn("5xx 집계 불가", summary)


class Closure(unittest.TestCase):
    def test_clean_full_window_is_closeable(self):
        text = request_event("/api/auth/status", 200) + "\n" + request_event("/api/projects", 200) + "\n"
        units = fake_units(text)
        report = report_module.build_report(START, END, CUTOVER, units)
        self.assertTrue(report["closure"]["window_covers_full_24h"])
        self.assertTrue(report["closure"]["issues"]["#5479"]["pass"])
        self.assertTrue(report["closure"]["issues"]["#6127"]["pass"])
        self.assertTrue(report["closure"]["closeable"])
        self.assertEqual(report["closure"]["reasons"], [])

    def test_short_window_is_not_closeable(self):
        text = request_event("/api/auth/status", 200) + "\n"
        units = fake_units(text)
        report = report_module.build_report(START + timedelta(hours=1), END, CUTOVER, units)
        self.assertFalse(report["closure"]["window_covers_full_24h"])
        self.assertFalse(report["closure"]["closeable"])
        self.assertIn("window_does_not_cover_cutover_24h", report["closure"]["reasons"])

    def test_recurrence_blocks_closure(self):
        report = report_module.build_report(START, END, CUTOVER, fake_units())
        closure = report["closure"]
        self.assertFalse(closure["issues"]["#5479"]["pass"])
        self.assertFalse(closure["issues"]["#6127"]["pass"])
        self.assertFalse(closure["closeable"])
        self.assertIn("nogil_recurrence", closure["reasons"])
        self.assertIn("chat_focus_5xx", closure["reasons"])

    def test_unavailable_5xx_blocks_closure_with_unknown_issue(self):
        units = fake_units("No errors in this window.\n")
        report = report_module.build_report(START, END, CUTOVER, units)
        closure = report["closure"]
        self.assertFalse(closure["issues"]["#6127"]["pass"])
        self.assertFalse(closure["closeable"])
        self.assertIn("chat_5xx_unavailable", closure["reasons"])
        self.assertIn("#6127=UNKNOWN", report_module.render_summary(report))


class Health(unittest.TestCase):
    def test_health_checks_status_and_never_prints_a_body(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/health":
                    status, body = 200, b'{"status":"ok","secret":"BODY-LEAK"}'
                elif self.path == "/bad":
                    status, body = 200, b'{"status":"degraded","secret":"BODY-LEAK"}'
                elif self.path == "/not-json":
                    status, body = 200, b"BODY-LEAK"
                elif self.path == "/redirect":
                    status, body = 302, b""
                else:
                    status, body = 503, b'{"status":"down","secret":"BODY-LEAK"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if self.path == "/redirect":
                    self.send_header("Location", "http://example.invalid/health")
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:%d" % server.server_port
            passed = report_module.probe_health(base + "/health", 2.0)
            failed = report_module.probe_health(base + "/down", 2.0)
            degraded = report_module.probe_health(base + "/bad", 2.0)
            malformed = report_module.probe_health(base + "/not-json", 2.0)
            redirect = report_module.probe_health(base + "/redirect", 2.0)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(passed, {"status": "PASS", "http_status": 200})
        self.assertEqual(failed, {"status": "FAIL", "http_status": 503, "reason": "http_status"})
        self.assertEqual(degraded, {"status": "FAIL", "http_status": 200, "reason": "status_not_ok"})
        self.assertEqual(malformed, {"status": "FAIL", "http_status": 200, "reason": "health_body_malformed"})
        self.assertEqual(redirect, {"status": "FAIL", "http_status": 302, "reason": "http_status"})
        rendered = json.dumps([passed, failed, degraded, malformed, redirect])
        self.assertNotIn("BODY-LEAK", rendered)
        self.assertNotIn("example.invalid", rendered)

    def test_health_rejects_non_loopback_or_credentialed_urls(self):
        for url in (
            "https://chat.padiem.net/health",
            "http://user:password@127.0.0.1/health",
            "http://127.0.0.1/health?token=TOKEN-LEAK",
        ):
            result = report_module.probe_health(url, 1.0)
            self.assertEqual(result["status"], "INVALID")
            self.assertNotIn("TOKEN-LEAK", json.dumps(result))


class CommandLine(unittest.TestCase):
    def test_main_prints_summary_json_and_writes_json_out(self):
        original = report_module.collect_unit

        def fake_collect(unit, start, end, health_url, **kwargs):
            observed = fake_units()[report_module.UNITS.index(unit)]
            if health_url is None:
                observed["health"] = {"status": "SKIPPED", "http_status": None}
            return observed

        report_module.collect_unit = fake_collect
        try:
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "report.json"
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = report_module.main(
                        [
                            "--since",
                            "2026-10-31T21:07:00+09:00",
                            "--until",
                            "2026-11-01T21:07:00+09:00",
                            "--no-health",
                            "--json-out",
                            str(target),
                        ]
                    )
                written = target.read_text(encoding="utf-8")
        finally:
            report_module.collect_unit = original
        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("PADIEM COM2 POST-CUTOVER REPORT", text)
        self.assertIn("closure:", text)
        printed = json.loads(text.strip().splitlines()[-1])
        stored = json.loads(written)
        self.assertEqual(printed["kind"], report_module.KIND)
        self.assertEqual(stored["kind"], report_module.KIND)
        self.assertEqual(len(stored["units"]), 3)
        self.assertEqual(stored["units"][0]["health"]["status"], "SKIPPED")


class Commands(unittest.TestCase):
    def test_commands_are_read_only(self):
        start, end = START, END
        journal = report_module.journalctl_argv("padiem-chat-com2", start, end)
        show = report_module.systemctl_argv("padiem-chat-com2")
        self.assertEqual(journal[0], "journalctl")
        self.assertIn("--no-pager", journal)
        self.assertNotIn("--vacuum", journal)
        self.assertNotIn("--rotate", journal)
        self.assertEqual(show[:2], ["systemctl", "show"])
        for verb in ("start", "stop", "restart", "enable", "disable"):
            self.assertNotIn(verb, show)

    def test_systemd_props_are_parsed_as_numbers(self):
        props = report_module.parse_systemd_props("ActiveState=active\nNRestarts=4\nExecMainStatus=1\n")
        self.assertEqual(props, {"active_state": "active", "n_restarts": 4, "exec_main_status": 1})
        self.assertIsNone(report_module.parse_systemd_props("NRestarts=x\n")["n_restarts"])


if __name__ == "__main__":
    unittest.main()
