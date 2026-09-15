from __future__ import annotations

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _send(self, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if self.path != "/echo-form":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self._send(body)

    def do_GET(self):
        if self.path == "/normal":
            self._send(b"normal-ok")
            return
        if self.path == "/slow-headers":
            time.sleep(0.6)
            self._send(b"too-late")
            return
        if self.path == "/slow-body":
            first = b"first"
            second = b"second"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(first) + len(second)))
            self.end_headers()
            try:
                self.wfile.write(first)
                self.wfile.flush()
                time.sleep(0.6)
                self.wfile.write(second)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
