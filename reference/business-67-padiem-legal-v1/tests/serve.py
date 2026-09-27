"""serve.py — threaded static server for the B67 review surface.

`python -m http.server` is single-threaded and deadlocks a browser that opens
parallel asset connections, which makes the page look broken during automated
verification. This serves the same directory concurrently so the browser loads
the surface the way a user would.

Run:  python reference/business-67-padiem-legal-v1/tests/serve.py [port]
"""

from __future__ import annotations

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # Never serve a stale surface during a review pass.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT)))
    print(f"B67 review surface: http://127.0.0.1:{port}/  (root: {ROOT})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
