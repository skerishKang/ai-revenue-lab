"""#8060 parsed facts for the B66 PC-connect static/server contract.

Raw static reads stay here; contract tests assert parsed markup order, parsed
source values and token sets instead of pinning source spelling.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

EXPECTED_IDS = (
    "b66QuotePcToggle", "b66QuotePcPanel", "b66QuotePcStatus",
    "b66QuotePcList", "b66QuotePcRefresh",
)
LOADER_FORBIDDEN = (
    'method: "POST"', 'method: "PUT"', 'method: "DELETE"',
    "localStorage", "sessionStorage", "postMessage", "new WebSocket",
    "document.cookie", "pairingToken", "fetch('/api/command",
)
LOADER_ALLOWED = (
    "nativeFetch(PC_DIRECTORY_PATH", "directory.devices",
    "device.online", "device.revoked",
)
ENTITLEMENT_EXPRESSIONS = (
    "pcDirectoryEnabled: data.pc_device_list_enabled === true",
    "pcSection.hidden = true",
    "runtime?.pcDirectoryEnabled === true",
    "if (pcSection) pcSection.hidden = !pcEnabled;",
)
LIFECYCLE_EXPRESSIONS = (
    "pcPanel.hidden = true;",
    "void loadPcDirectory();",
    "pcQuerySequence += 1",
    "current === pcQuerySequence && !section.hidden",
    "resetPcDirectory();",
    "signedIn = !!(auth && auth.authenticated === true);",
    "if (signedIn) refresh();",
)
AUTH_EVENTS = ("padiem:auth-state", "padiem:auth-changed", "padiem:account-changed")
UNAVAILABLE_COPY = (
    "PC 연결 서비스가 아직 준비되지 않았습니다. 연결이 완료됐다고 표시하지 않습니다.",
    "The PC connection service is not ready. No connection is claimed.",
)
SERVER_EXPRESSIONS = ("pc_device_list_enabled", "b66_pc_directory_available(request, uid)")
GATE_EXPRESSIONS = (
    "evaluate_pc_access(",
    "ProductPcAccessPolicy",
    'B66_PC_DIRECTORY_PATH = "/api/b66/connect/devices"',
    "grant.workspace_ref != workspace",
    "return await claw_device_directory(request)",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def runtime_source() -> str:
    return _read(STATIC / "b66-quote-runtime.js")


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            src = dict(attrs).get("src")
            if src:
                self.sources.append(src)


def script_order() -> tuple[str, ...]:
    parser = _Scripts()
    parser.feed(_read(STATIC / "index.html"))
    parser.close()
    return tuple(parser.sources)


def _present(tokens, source: str) -> tuple[str, ...]:
    return tuple(token for token in tokens if token in source)


def runtime_facts() -> dict:
    source = runtime_source()
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    loader = code.split("async function loadPcDirectory() {", 1)[1].split(
        "function closeDialog()", 1)[0] if "async function loadPcDirectory() {" in code else ""
    return {
        "element_ids": tuple(sorted(set(re.findall(r'"(b66QuotePc[A-Za-z]+)"', code)))),
        "directory_path": tuple(re.findall(r'PC_DIRECTORY_PATH = "([^"]+)"', code)),
        "handoff_projection": "window.PadiemClawLocalHandoff?.deriveDeviceDirectory" in code,
        "credentials": tuple(sorted(set(re.findall(r'credentials:\s*"([^"]+)"', code)))),
        "byte_gate_present": "MAX_PC_DIRECTORY_BYTES" in code,
        "json_parse_payload": "const payload = JSON.parse(raw)" in code,
        "loader_methods": tuple(re.findall(r'method: "([A-Z]+)"', loader)),
        "loader_present": _present(LOADER_ALLOWED, loader),
        "loader_forbidden": _present(LOADER_FORBIDDEN, loader),
        "loader_external_url": "https://github.com/" in loader,
        "entitlement_present": _present(ENTITLEMENT_EXPRESSIONS, code),
        "lifecycle_present": _present(LIFECYCLE_EXPRESSIONS, code),
        "auth_events": tuple(sorted(set(re.findall(r'"(padiem:[a-z-]+)"', code)))),
        "auth_event_arrays": tuple(re.findall(
            r'for \(const eventName of (\["padiem:[a-z-]+"(?:, "padiem:[a-z-]+")*\])', code)),
        "logout_reset": bool(re.search(r"resetPcDirectory\(\);\s*runtime = null;", code)),
        "unavailable_copy": _present(UNAVAILABLE_COPY, code),
    }


def server_facts() -> dict:
    server = _read(ROOT / "app" / "b66_quote_routes.py")
    gate = _read(ROOT / "app" / "b66_pc_directory_routes.py")
    return {
        "server_present": _present(SERVER_EXPRESSIONS, server),
        "gate_present": _present(GATE_EXPRESSIONS, gate),
    }
