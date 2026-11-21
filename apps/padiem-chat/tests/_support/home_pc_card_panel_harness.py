"""First-screen PC connection panel harness (#5634, #8060 21차).

Keeps the raw ``rfile.read`` of the selection POST and the shipped-sheet reads
out of the contract test module: the test receives parsed tags, attribute maps
and the running server fixture. The two endpoints are the only ones the panel
really calls.
"""
from __future__ import annotations

import http.server
import json
import threading
from html.parser import HTMLParser
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"

# The deployment capability of the running service, so the web-search control
# really arrives and can be clicked while the panel is open.
HEALTH = {
    "web_tools_ready": True,
    "deep_research_ready": False,
    "auth_configured": True,
    "history_store_bound": True,
    "projects_code_ready": True,
    "projects_code_store_bound": True,
    "saved_outputs_code_ready": True,
    "saved_output_store_bound": True,
}

# Twelve confirmed devices: enough that the panel's own scroll has to work, and
# a mix of online / offline rows so both state chips render.
DIRECTORY = {
    "ok": True,
    "available": True,
    "ownerScoped": True,
    "selectedDeviceId": None,
    "devices": [
        {
            "deviceId": "owner-node-%02d-%s" % (index, "b" * 40),
            "deviceName": "내 데스크톱" if index == 0 else "외부 노드 %02d" % index,
            "platform": "Windows 11",
            "state": "CONNECTED" if index % 4 in (0, 3) else "OFFLINE",
            "usable": index % 4 in (0, 3),
            "executable": index % 4 in (0, 3),
            "selectable": index % 4 in (0, 3),
        }
        for index in range(12)
    ],
}

CONNECT_ENDPOINT = "/api/claw/local-access/devices"
SELECT_ENDPOINT = "/api/claw/local-access/devices/select"


class ConnectorHandler(http.server.SimpleHTTPRequestHandler):
    """The static app plus the two endpoints the panel really calls."""

    directory_reads = 0
    selection_posts = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(HEALTH)
        if self.path.startswith("/api/auth/status"):
            return self._json({"ready": True, "authenticated": True, "session_state": "signed_in",
                               "user": {"id": "usr_" + "a" * 32, "name": "Test User"}})
        if self.path.startswith(CONNECT_ENDPOINT):
            ConnectorHandler.directory_reads += 1
            return self._json(DIRECTORY)
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith(SELECT_ENDPOINT):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            body = json.loads(raw or "{}")
            ConnectorHandler.selection_posts.append(body)
            return self._json(
                {"ok": True, "selectedDeviceId": body.get("device_id")}
            )
        self.send_response(404)
        self.end_headers()


def static_url_fixture():
    """Session-scoped static server; the test module wraps it as a fixture."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html?theme=padiem-glass" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


class _FragmentTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def index_button_subtree(element_id):
    """One index.html button and its descendants, parsed: [(tag, attrs)]."""
    page = (_STATIC / "index.html").read_text(encoding="utf-8")
    marker = 'id="%s"' % element_id
    start = page.index(marker)
    fragment = page[page.rindex("<button", 0, start): page.index("</button>", start)]
    parser = _FragmentTags()
    parser.feed(fragment)
    parser.close()
    return parser.tags
