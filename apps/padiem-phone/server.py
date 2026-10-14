"""Loopback-only prototype API for outbound phone tasks.

Do not deploy this preview server publicly: it intentionally has no login,
persistence, phone provider, biller, or multi-tenant authorization.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import sys

from phone_mock import MockPhoneTasks, TaskError

STATIC = Path(__file__).parent / "static"
STORE = MockPhoneTasks()
MAX_JSON_BYTES = 8192


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "PadiemPhonePreview/0.1"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict | list) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, exception: TaskError) -> None:
        self._json(exception.status, {"error": str(exception)})

    def _route(self) -> str:
        return urlsplit(self.path).path

    def do_GET(self) -> None:
        path = self._route()
        try:
            if path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path in ("/app.js", "/styles.css"):
                content_type = "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self._send(200, (STATIC / path.lstrip("/")).read_bytes(), content_type)
            elif path == "/api/tasks":
                self._json(200, {"tasks": STORE.list()})
            elif path == "/api/usage":
                self._json(200, STORE.summary())
            elif path.startswith("/api/tasks/") and path.count("/") == 3:
                self._json(200, STORE.get(path.split("/")[-1]))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)

    def do_POST(self) -> None:
        path = self._route()
        try:
            if path == "/api/tasks":
                length_header = self.headers.get("Content-Length")
                if not length_header or not length_header.isdigit():
                    raise TaskError("invalid_length", 411)
                size = int(length_header)
                if size < 1 or size > MAX_JSON_BYTES:
                    raise TaskError("request_too_large", 413)
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise TaskError("invalid_content_type", 415)
                raw = self.rfile.read(size)
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise TaskError("invalid_json") from None
                self._json(202, STORE.create(payload))
            elif path.startswith("/api/tasks/") and path.endswith("/cancel") and path.count("/") == 4:
                self._json(200, STORE.cancel(path.split("/")[-2]))
            else:
                self._json(404, {"error": "not_found"})
        except TaskError as error:
            self._error(error)


def serve() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    # Binding strictly to loopback is a deliberate safety boundary for the mock.
    httpd = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
    print(f"PADIEM Phone mock only: http://127.0.0.1:{port}", flush=True)
    print("REAL_OUTBOUND_CALLS=DISABLED | PUBLIC_DEPLOYMENT=FORBIDDEN", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
