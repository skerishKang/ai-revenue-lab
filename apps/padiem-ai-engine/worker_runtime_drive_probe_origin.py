from __future__ import annotations

import argparse
import gzip
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _headers(
        self,
        length: int,
        *,
        content_type: str = "text/plain",
        content_encoding: str | None = None,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if content_encoding is not None:
            self.send_header("Content-Encoding", content_encoding)
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _write(self, payload: bytes) -> None:
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/normal":
            payload = b"normal-ok"
            self._headers(len(payload))
            self._write(payload)
            return

        if self.path == "/gzip-json":
            payload = gzip.compress(b'{"files":[]}')
            self._headers(
                len(payload),
                content_type="application/json",
                content_encoding="gzip",
            )
            self._write(payload)
            return

        if self.path == "/chunks":
            first = b"chunk-one"
            second = b"chunk-two"
            self._headers(len(first) + len(second))
            self._write(first)
            time.sleep(0.45)
            self._write(second)
            return

        if self.path == "/slow-headers":
            time.sleep(0.6)
            payload = b"too-late"
            self._headers(len(payload))
            self._write(payload)
            return

        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9101)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
