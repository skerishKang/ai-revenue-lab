from __future__ import annotations

import argparse
import gzip
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _headers(self, length: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _write(self, payload: bytes) -> None:
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/echo-form":
            payload = body
        elif self.path == "/echo-json":
            prefix = b"probe-ok:" if self.headers.get("X-Probe") == "runtime" else b"bad-header:"
            payload = prefix + body
        else:
            self.send_error(404)
            return
        self._headers(len(payload))
        self._write(payload)

    def do_GET(self):
        if self.path == "/normal":
            payload = b"normal-ok"
            self._headers(len(payload))
            self._write(payload)
            return

        if self.path == "/gzip-json":
            payload = b'{"files":[]}'
            encoded = gzip.compress(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self._write(encoded)
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

        if self.path == "/slow-body":
            first = b"first"
            second = b"second"
            self._headers(len(first) + len(second))
            self._write(first)
            time.sleep(0.6)
            self._write(second)
            return

        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
