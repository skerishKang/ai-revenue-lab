"""#7216 R5 2단계 — 캘린더 구역 모듈 분리 계약.

app.js의 캘린더 9개 함수가 chat-calendar-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 모듈이 클로저 deps getter를
통해 첫 호출 전에 바뀐 값도 읽는지, (2) 로드 순서와 전달 함수가 유지되는지,
(3) 실제 Chromium에서 전달 함수를 직접 호출할 수 있는지를 확인한다.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-calendar-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "calendarReadStateKey", "calendarReadActivationErrorKey",
    "googleCalendarConnectButton", "googleCalendarCard", "renderCalendarReadState",
    "syncGoogleCalendarConnectButton", "beginGoogleCalendarConnect", "activateGoogleCalendarRead",
)


class _ScriptSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


def _script_sources(html: str) -> list[str]:
    parser = _ScriptSources()
    parser.feed(html)
    return parser.sources


def _function_block(source: str, name: str) -> str:
    """Return a function declaration without pinning its whitespace or order."""
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    assert match, f"{name} function not found"
    start = match.start()
    index = source.index("{", match.end())
    depth = 0
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError(f"unbalanced function body for {name}")


def _node_json(body: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = "const window = {};\n" + MODULE + "\n" + STRICT + "\n" + body
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_index_loads_the_calendar_module_before_app() -> None:
    sources = _script_sources(INDEX)
    assert "./chat-calendar-module.js" in sources
    assert "./app.js" in sources
    assert sources.index("./chat-calendar-module.js") < sources.index("./app.js")


def test_app_calendar_wiring_reads_live_closure_values() -> None:
    factory = _function_block(APP, "calendarModule")
    payload = _node_json(
        f"""
let calendarModuleInstance = null;
{factory}
let connectorsScope = {{ name: "scope-1" }};
let authState = {{ authenticated: true }};
let googleConnectorConnectInFlight = false;
let googleCalendarReadState = "unknown";
let GOOGLE_CALENDAR_CONNECTOR = "google-calendar";
let GOOGLE_CALENDAR_TICKET_ENDPOINT = "/ticket";
let GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT = "/activate";
let setConnectorCopy = () => {{}};
let connectorsError = null;
let openAuthDialog = () => {{}};
let fetch = async () => ({{}});
let reviewedGoogleAuthorizationUrl = () => null;
let captured = null;
window.PadiemChatCalendarModule = {{ create(deps) {{ captured = deps; return {{}}; }} }};
const created = calendarModule();
const same = calendarModule() === created;
const live = {{
  scope: captured.connectorsScope.name,
  readState: captured.googleCalendarReadState,
  connector: captured.GOOGLE_CALENDAR_CONNECTOR,
}};
connectorsScope = {{ name: "scope-2" }};
googleCalendarReadState = "active";
const after = {{
  scope: captured.connectorsScope.name,
  readState: captured.googleCalendarReadState,
}};
captured.googleCalendarReadState = "failed";
console.log(JSON.stringify({{ same, live, after, written: googleCalendarReadState }}));
"""
    )
    assert payload["same"] is True, "the module instance is created once"
    assert payload["live"] == {
        "scope": "scope-1",
        "readState": "unknown",
        "connector": "google-calendar",
    }
    assert payload["after"] == {"scope": "scope-2", "readState": "active"}
    assert payload["written"] == "failed", "the app deps setter writes the closure variable"


def test_app_forwarders_delegate_every_moved_function() -> None:
    blocks = "\n".join(_function_block(APP, name) for name in NAMES)
    export = ", ".join(NAMES)
    payload = _node_json(
        f"""
const blocks = {json.dumps(blocks)};
const names = {json.dumps(list(NAMES))};
const api = new Function("calendarModule", blocks + "\\nreturn {{{export}}};")(() => fake);
const fake = {{}};
for (const name of names) {{
  fake[name] = (...args) => ({{ name, args }});
}}
const argsByName = {{
  calendarReadStateKey: ["active"],
  calendarReadActivationErrorKey: [{{ calendarReadErrorCode: "x" }}],
  syncGoogleCalendarConnectButton: [{{ workspace_state: "connected" }}],
}};
const rows = names.map((name) => {{
  const out = api[name](...(argsByName[name] || []));
  return [name, out.name, out.args.length];
}});
console.log(JSON.stringify(rows));
"""
    )
    expected = [
        [name, name, 1 if name in {"calendarReadStateKey", "calendarReadActivationErrorKey", "syncGoogleCalendarConnectButton"} else 0]
        for name in NAMES
    ]
    assert payload == expected


def test_module_reads_live_deps_getters_and_closed_vocabulary() -> None:
    node = pytest.importorskip("shutil").which("node")
    if not node:
        pytest.skip("node runtime is required")
    script = STRICT + """
const moduleSource = %s;
const appModule = { exports: {} };
const window = {};
new Function("window", moduleSource)(window);
function el(attrs) {
  const node = {
    hidden: false, disabled: false, textContent: "", dataset: Object.assign({}, attrs || {}),
    querySelector(sel) {
      if (sel === "[data-google-connector-connect=\\"google-calendar\\"]") return button;
      if (sel === "[data-connector-read-state]") return stateLine;
      if (sel === "[data-connector-workspace]") return workspace;
      return null;
    },
  };
  return node;
}
const workspace = el({});
const stateLine = el({});
const button = el({ connector: "google-calendar" });
const scope = el({});
scope.querySelectorAll = () => [button];
const buttonHolder = button;
let readState = "unknown";
const deps = {
  connectorsScope: () => scope,
  authState: { authenticated: true },
  googleConnectorConnectInFlight: false,
  get googleCalendarReadState() { return readState; },
  set googleCalendarReadState(value) { readState = value; },
  GOOGLE_CALENDAR_CONNECTOR: "google-calendar",
  GOOGLE_CALENDAR_TICKET_ENDPOINT: "/api/connectors/google/ticket",
  GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: "/api/connectors/google/calendar/activate-read",
  setConnectorCopy: (node, key) => { if (node) node.textContent = key; },
  connectorsError: null,
  openAuthDialog: () => {},
  fetch: async () => { throw new Error("no network"); },
  reviewedGoogleAuthorizationUrl: () => null,
};
const instance = window.PadiemChatCalendarModule.create(r5StrictDeps(deps, "step2.deps"));
const mapping = ["active", "bogus"].map(instance.calendarReadStateKey);
// The getter must be read at call time: a value set before the first call wins.
deps.googleCalendarReadState = "active";
instance.syncGoogleCalendarConnectButton({ workspace_state: "connected", calendar_read_grant_state: "active" });
const first = button.textContent + "/" + button.disabled;
deps.googleCalendarReadState = "failed";
instance.syncGoogleCalendarConnectButton({ workspace_state: "connected", calendar_read_grant_state: "active" });
const second = button.textContent;
console.log(JSON.stringify({ mapping, first, second, card: instance.googleCalendarCard() === null }));
""".replace("%s", repr(MODULE))
    import json
    import subprocess
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["mapping"] == ["connectors-calendar-read-active", "connectors-calendar-read-pending"]
    assert payload["first"].startswith("connectors-calendar-read-activation-done")
    assert payload["second"] == "connectors-activate-calendar-read"


def test_forwarder_runs_in_real_chromium() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    forwarder = _function_block(APP, "googleCalendarConnectButton")
    harness = """
<!doctype html><html><body>
<div id="scope"><button data-google-connector-connect="google-calendar">연결</button></div>
<script>__MODULE__</script>
<script>
__STRICT__
window.__deps = r5StrictDeps({
  connectorsScope: () => document.getElementById("scope"),
  authState: { authenticated: false },
  googleConnectorConnectInFlight: false,
  googleCalendarReadState: "unknown",
  GOOGLE_CALENDAR_CONNECTOR: "google-calendar",
  GOOGLE_CALENDAR_TICKET_ENDPOINT: "/x",
  GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: "/y",
  setConnectorCopy: () => {},
  connectorsError: null,
  openAuthDialog: () => {},
  fetch: async () => ({}),
  reviewedGoogleAuthorizationUrl: () => null,
}, "step2.browser.deps");
window.__instance = window.PadiemChatCalendarModule.create(window.__deps);
function calendarModule() { return window.__instance; }
__FORWARDER__
</script></body></html>
"""
    harness = (harness.replace("__STRICT__", STRICT).replace("__MODULE__", MODULE)
               .replace("__FORWARDER__", forwarder))
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(harness)
        found = page.evaluate("googleCalendarConnectButton().dataset.googleConnectorConnect")
        browser.close()
    assert found == "google-calendar"
