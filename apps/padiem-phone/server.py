"""Loopback-only phone task and script preview API.

Do not deploy publicly: no production login, tenant authorization, SIP provider,
customer billing, voice processing or durable telephone task queue exists.
Only demo scripts persist to the current computer user's private app-data path.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import sys

from phone_mock import TaskError
from phone_history import DurableMockPhoneTasks, local_history_path
from phone_reports import task_timeline, task_report, stage_usage
from phone_scripts import ScriptStore, local_preview_path

STATIC = Path(__file__).parent / "static"
STORE = DurableMockPhoneTasks(local_history_path(local_preview_path()))
SCRIPTS = ScriptStore(local_preview_path())
MAX_JSON_BYTES = 8192


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "PadiemPhonePreview/0.2"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict | list) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, exception: TaskError) -> None:
        self._json(exception.status, {"error": str(exception)})

    def _route(self) -> str:
        return urlsplit(self.path).path

    def _check_loopback_host(self) -> None:
        """Deny DNS rebinding and cross-origin script mutations on local API."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        if host not in allowed:
            raise TaskError("invalid_host", 403)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}"}:
            raise TaskError("cross_origin_forbidden", 403)

    def _body(self) -> object:
        length_header = self.headers.get("Content-Length")
        if not length_header or not length_header.isdigit():
            raise TaskError("invalid_length", 411)
        size = int(length_header)
        if size < 1 or size > MAX_JSON_BYTES:
            raise TaskError("request_too_large", 413)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise TaskError("invalid_content_type", 415)
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TaskError("invalid_json") from None

    def do_GET(self) -> None:
        try:
            self._check_loopback_host()
            path = self._route()
            if path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path in ("/app.js", "/styles.css"):
                content_type = "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self._send(200, (STATIC / path.lstrip("/")).read_bytes(), content_type)
            elif path == "/assets/padiem-glass-female.jpg":
                self._send(200, (STATIC / "assets" / "padiem-glass-female.jpg").read_bytes(), "image/jpeg")
            elif path == "/api/tasks":
                self._json(200, {"tasks": STORE.list()})
            elif path == "/api/usage":
                self._json(200, STORE.summary())
            elif path == "/api/usage/stages":
                self._json(200, stage_usage(STORE.list()))
            elif path == "/api/scripts":
                self._json(200, {"scripts": SCRIPTS.list()})
            elif path.startswith("/api/tasks/") and path.count("/") == 4 and path.endswith("/timeline"):
                self._json(200, {"timeline": task_timeline(STORE.get(path.split("/")[-2]))})
            elif path.startswith("/api/tasks/") and path.count("/") == 4 and path.endswith("/report"):
                report = task_report(STORE.get(path.split("/")[-2]))
                self._send(200, report.encode("utf-8"), "text/plain; charset=utf-8")
            elif path.startswith("/api/tasks/") and path.count("/") == 3:
                self._json(200, STORE.get(path.split("/")[-1]))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)

    def do_POST(self) -> None:
        try:
            self._check_loopback_host()
            path = self._route()
            if path == "/api/tasks":
                raw = self._body()
                if isinstance(raw, dict) and raw.get("script_id") is not None:
                    if not isinstance(raw["script_id"], str):
                        raise TaskError("invalid_script_id")
                    script = SCRIPTS.resolve(raw["script_id"])
                    if raw.get("goal") != script["goal"] or raw.get("destination") != script["destination"]:
                        raise TaskError("script_payload_mismatch", 409)
                    raw = {**raw, "questions": script["questions"], "notes": script["notes"]}
                self._json(202, STORE.create(raw))
            elif path == "/api/scripts":
                self._json(201, SCRIPTS.create(self._body()))
            elif path.startswith("/api/tasks/") and path.endswith("/cancel") and path.count("/") == 4:
                self._json(200, STORE.cancel(path.split("/")[-2]))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)

    def do_PUT(self) -> None:
        try:
            self._check_loopback_host()
            path = self._route()
            if path.startswith("/api/scripts/") and path.count("/") == 3:
                self._json(200, SCRIPTS.update(path.split("/")[-1], self._body()))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)

    def do_DELETE(self) -> None:
        try:
            self._check_loopback_host()
            path = self._route()
            if path.startswith("/api/scripts/") and path.count("/") == 3:
                raw = self._body()
                self._json(200, SCRIPTS.delete(path.split("/")[-1],
                                               raw.get("revision") if isinstance(raw, dict) else None))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)


def serve() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    httpd = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
    print(f"PADIEM Phone mock only: http://127.0.0.1:{port}", flush=True)
    print("REAL_OUTBOUND_CALLS=DISABLED | PUBLIC_DEPLOYMENT=FORBIDDEN", flush=True)
    print(f"PREVIEW_SCRIPT_FILE={local_preview_path()}", flush=True)
    print(f"PREVIEW_MOCK_HISTORY={local_history_path(local_preview_path())}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
