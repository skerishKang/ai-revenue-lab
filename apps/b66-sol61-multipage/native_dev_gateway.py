"""#4117 Windows-only, loopback-only Sol PDF developer proof.

NO customer authorization, public service certificate, external binding,
secrets storage, or Google Drive mutation. Requires explicit CLI opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from pypdf import PdfReader

from native_server_adapter import NativeSolLocalAdapter, NativeSolRejected

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "reference/b66-public-standard-templates/cgi/v1/sol61"
ENGINE = Path(__file__).with_name("sol61_multipage.py")
MAX_REQUEST_BYTES = 32768
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def create_dev_server(port: int = 0, *, host: str = "127.0.0.1"):
    if host != "127.0.0.1":
        raise ValueError("loopback_only")
    verified = NativeSolLocalAdapter(bundle=BUNDLE, engine_file=ENGINE)
    token = secrets.token_urlsafe(32)
    render_lock = threading.Lock()  # Sol mutable font state is NOT thread-safe.

    class Handler(BaseHTTPRequestHandler):
        server_version = "B66SolLocalDev/1"
        sys_version = ""

        def log_message(self, _format, *_args):
            # Do not log customer inputs, filenames, tokens, or quote details.
            return

        def _headers(self, status: int, media: str, length: int, **extra):
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-B66-Dev-Release", "NOT_CERTIFIED")
            for key, value in extra.items():
                self.send_header(key.replace("_", "-"), str(value))
            self.end_headers()

        def _reply(self, status: int, data: bytes, media="application/json", **extra):
            self._headers(status, media, len(data), **extra)
            self.wfile.write(data)

        def _reject(self, status: int, code: str):
            payload = json.dumps({"ok": False, "code": code}, separators=(",", ":")).encode()
            self._reply(status, payload)

        def _trusted_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self._trusted_host():
                return self._reject(403, "dev_host_invalid")
            if self.path == "/health":
                return self._reply(200, b'{"ok":true,"release":"NOT_CERTIFIED"}')
            if self.path != "/":
                return self._reject(404, "dev_route_missing")
            source = Path(__file__).with_name("native_dev_view.html").read_text("utf-8")
            page = source.replace("__DEV_TOKEN__", token).encode("utf-8")
            self._reply(200, page, "text/html; charset=utf-8",
                        Content_Security_Policy=(
                            "default-src 'none'; script-src 'unsafe-inline'; "
                            "style-src 'unsafe-inline'; img-src 'self' blob:; "
                            "frame-src blob:; connect-src 'self'; "
                            "object-src 'none'; base-uri 'none'; form-action 'none'"
                        ))

        def do_POST(self):
            if not self._trusted_host() or self.path != "/dev/render":
                return self._reject(404, "dev_route_unavailable")
            if self.headers.get("X-B66-Dev-Token") != token:
                return self._reject(403, "dev_token_required")
            origin = self.headers.get("Origin")
            if origin != f"http://127.0.0.1:{self.server.server_port}":
                return self._reject(403, "dev_origin_invalid")
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                return self._reject(415, "dev_content_type_invalid")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if not (2 <= length <= MAX_REQUEST_BYTES):
                return self._reject(413, "dev_body_invalid")
            try:
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(request, dict) or set(request) != {"changes"}:
                    raise ValueError("dev_fields_invalid")
                changes = request["changes"]
                if not isinstance(changes, dict):
                    raise ValueError("dev_changes_invalid")
                if set(changes) - {"recipient", "project", "issueDate", "quoteNo", "items"}:
                    raise ValueError("dev_changes_invalid")
                if "items" in changes and (
                    not isinstance(changes["items"], list) or
                    not 1 <= len(changes["items"]) <= 100
                ):
                    raise ValueError("dev_row_count_invalid")
                # QuoteCore is recalculated in Node for every render; the browser
                # never gets to supply trusted totals/slots.
                with render_lock:
                    derived = verified.engine.build_slots(changes)
                    if len(derived["draft"]["items"]) > 100:
                        raise ValueError("dev_row_count_invalid")
                    with tempfile.TemporaryDirectory(prefix="b66-sol-dev-") as temp:
                        path = Path(temp) / "candidate.pdf"
                        result = verified.engine.render(path, changes)
                        data = path.read_bytes()
                pages = len(PdfReader(io.BytesIO(data), strict=True).pages)
                sha = hashlib.sha256(data).hexdigest()
                if (not data.startswith(b"%PDF-") or len(data) > MAX_RESPONSE_BYTES
                        or pages != result["pages"] or sha != result["pdfSha256"]):
                    raise ValueError("dev_pdf_invalid")
            except (ValueError, KeyError, TypeError, UnicodeError, NativeSolRejected):
                return self._reject(422, "dev_render_rejected")
            except Exception:
                return self._reject(503, "dev_renderer_unavailable")
            self._reply(200, data, "application/pdf",
                        X_B66_Dev_Pdf_Sha256=sha, X_B66_Dev_Pages=pages)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server, token


def main():
    parser = argparse.ArgumentParser(description="Loopback-only Sol PDF proof; NOT customer release")
    parser.add_argument("--local-development", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8761)
    args = parser.parse_args()
    server, _token = create_dev_server(args.port)
    print(f"LOCAL_NATIVE_SOL_DEV_URL=http://127.0.0.1:{server.server_port}/", flush=True)
    print("RELEASE=NOT_CERTIFIED; NO_PRODUCTION=YES; NO_GOOGLE_DRIVE_WRITE=YES", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
