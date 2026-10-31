import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("cutover_smoke", Path(__file__).resolve().parents[1] / "scripts" / "chat_post_cutover_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_origin_and_cookie_validation():
    assert smoke.origin("https://chat.padiem.net/") == "https://chat.padiem.net"
    with pytest.raises(ValueError):
        smoke.origin("https://user:password@example.com/")
    with pytest.raises(ValueError):
        smoke.origin("http://example.com/")
    with pytest.raises(ValueError):
        smoke.parse_cookie("a=b\nsecret=x", "https://chat.padiem.net")


def test_guest_browser_blocks_writes_and_reports_status():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("local Chrome unavailable")
    writes = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            writes.append(self.path)
            self.send_response(204)
            self.end_headers()
        def do_GET(self):
            if self.path == "/health":
                data, content = b'{"status":"ok","runtime":"mock"}', "application/json"
            elif self.path == "/api/auth/status":
                data, content = b'{"ready":true,"authenticated":false,"user":null}', "application/json"
            elif self.path == "/style.css":
                data, content = b"body { color: red; }", "text/css"
            elif self.path == "/script.js":
                data, content = b"fetch('/api/write',{method:'POST',body:'x'}).catch(()=>{});", "application/javascript"
            else:
                data, content = b'<html><head><link rel="stylesheet" href="/style.css"></head><body><div class="app-shell">Chat</div><script src="/script.js"></script></body></html>', "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = smoke.smoke(f"http://127.0.0.1:{server.server_port}", browser_executable=str(chrome))
        assert report["stages"]["health"]["status"] == "PASS"
        assert report["stages"]["front"]["status"] == "UNVERIFIED"
        assert report["stages"]["guest"]["status"] == "PASS"
        assert report["stages"]["assets"]["status"] == "PASS"
        assert report["stages"]["auth_status"]["status"] == "PASS"
        assert report["stages"]["conversation"]["reason"] == "login required"
        assert report["stages"]["console"]["blocked_requests"] >= 1
        assert not writes
        assert "secret" not in json.dumps(report)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
