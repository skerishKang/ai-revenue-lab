"""#7216 R5 2단계 — 캘린더 구역 모듈 분리 계약.

app.js의 캘린더 9개 함수가 chat-calendar-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 모듈이 클로저 deps getter를
통해 첫 호출 전에 바뀐 값도 읽는지, (2) 로드 순서와 전달 함수가 유지되는지,
(3) 실제 Chromium에서 전달 함수를 직접 호출할 수 있는지를 확인한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.turn_projects_calendar_source import (
    app_js, calendar_module_js, chat_app_context_js, foundation_css, index_html,
    locale_source, read as _source_read, strict_deps_js,
)

from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = app_js()
STRICT = strict_deps_js()
MODULE = calendar_module_js()
CONTEXT = chat_app_context_js()
INDEX = index_html()

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
    script = "const window = {}; const app = {};\n" + MODULE + "\n" + STRICT + "\n" + body
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
    deps_block = create_receives_app_context(APP, "window.PadiemChatCalendarModule")
    payload = _node_json(
        f"""
const connectors = {{
  connectorsScope: {{ name: "scope-1" }},
  connectorTicketErrorKey: () => "ticket-error",
  setConnectorCopy: () => {{}},
}};
let googleCalendarReadState = "unknown";
let setConnectorCopy = () => {{}};
let fetch = async () => ({{}});
const captured = {deps_block};
const live = {{
  scope: captured.connectorsScope.name,
  readState: captured.googleCalendarReadState,
  // R5 B5: the connector id is module-owned now.
  ownsConnector: !("GOOGLE_CALENDAR_CONNECTOR" in captured),
}};
connectors.connectorsScope = {{ name: "scope-2" }};
googleCalendarReadState = "active";
const after = {{
  scope: captured.connectorsScope.name,
  readState: captured.googleCalendarReadState,
}};
captured.googleCalendarReadState = "failed";
console.log(JSON.stringify({{ live, after, written: googleCalendarReadState }}));
"""
    )
    assert payload["live"] == {
        "scope": "scope-1",
        "readState": "unknown",
        "ownsConnector": True,
    }
    assert payload["after"] == {"scope": "scope-2", "readState": "active"}
    assert payload["written"] == "failed", "the app deps setter writes the closure variable"


def test_app_registers_calendar_and_apis_are_reachable() -> None:
    assert 'app.provide("calendar", window.PadiemChatCalendarModule.create(Object.setPrototypeOf({' in APP
    for name in NAMES:
        assert f"function {name}(" not in APP, name
        assert f"{name}," in MODULE, name
    assert "calendarModuleInstance = app.provide(\"calendar\", window.PadiemChatCalendarModule.create(" in APP

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, setAttribute() {} }),
  },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-calendar-module.js", "utf8"), sandbox,
  { filename: "chat-calendar-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("calendar", window.PadiemChatCalendarModule.create(app));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_module_reads_live_deps_getters_and_closed_vocabulary() -> None:
    node = pytest.importorskip("shutil").which("node")
    if not node:
        pytest.skip("node runtime is required")
    script = STRICT + """
const moduleSource = %s;
const appModule = { exports: {} };
const window = {};
const app = {};
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


def test_registry_api_runs_in_real_chromium() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    harness = """
<!doctype html><html><body>
<div id="scope"><button data-google-connector-connect="google-calendar">연결</button></div>
<script>__CONTEXT__</script>
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
window.__app = window.PadiemChatAppContext.create({});
window.__app.provide("calendar", window.__instance);
</script></body></html>
"""
    harness = (harness.replace("__STRICT__", STRICT).replace("__MODULE__", MODULE)
               .replace("__CONTEXT__", CONTEXT))
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(harness)
        found = page.evaluate("window.__app.googleCalendarConnectButton().dataset.googleConnectorConnect")
        browser.close()
    assert found == "google-calendar"
