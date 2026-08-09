import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class PortfolioTestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/api/github-status":
            payload = {
                "ok": True,
                "schemaVersion": 2,
                "syncedAt": "2026-08-09T00:00:00Z",
                "stale": True,
                "repository": {
                    "fullName": "skerishKang/ai-revenue-lab",
                    "url": "https://github.com/skerishKang/ai-revenue-lab",
                    "latestSha": None,
                },
                "businesses": [],
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 4173), PortfolioTestHandler).serve_forever()
