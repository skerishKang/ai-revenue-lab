"""#7216 R5 2단계 — 캘린더 구역 모듈 분리 계약.

app.js의 캘린더 9개 함수가 chat-calendar-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 모듈이 클로저 deps getter를
통해 첫 호출 전에 바뀐 값도 읽는지, (2) 로드 순서와 전달 함수가 유지되는지,
(3) 실제 Chromium에서 전달 함수를 직접 호출할 수 있는지를 확인한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-calendar-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "calendarReadStateKey", "calendarReadActivationErrorKey",
    "googleCalendarConnectButton", "googleCalendarCard", "renderCalendarReadState",
    "syncGoogleCalendarConnectButton", "beginGoogleCalendarConnect", "activateGoogleCalendarRead",
)


def test_index_loads_the_calendar_module_before_app() -> None:
    assert INDEX.index("./chat-calendar-module.js") < INDEX.index("./app.js")


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        assert f"function {name}(" in APP, name
        assert re.search(rf"function {name}\([^)]*\) \{{ return calendarModule\(\)\.{name}\(", APP), name
    assert "window.PadiemChatCalendarModule.create({" in APP


def test_module_reads_live_deps_getters_and_closed_vocabulary() -> None:
    node = pytest.importorskip("shutil").which("node")
    if not node:
        pytest.skip("node runtime is required")
    script = """
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
const deps = {
  connectorsScope: () => scope,
  authState: { authenticated: true },
  googleConnectorConnectInFlight: false,
  googleCalendarReadState: "unknown",
  GOOGLE_CALENDAR_CONNECTOR: "google-calendar",
  GOOGLE_CALENDAR_TICKET_ENDPOINT: "/api/connectors/google/ticket",
  GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: "/api/connectors/google/calendar/activate-read",
  setConnectorCopy: (node, key) => { if (node) node.textContent = key; },
  connectorsError: null,
  openAuthDialog: () => {},
  fetch: async () => { throw new Error("no network"); },
  reviewedGoogleAuthorizationUrl: () => null,
};
const instance = window.PadiemChatCalendarModule.create(deps);
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
    forwarder = re.search(
        r"function googleCalendarConnectButton\(\) \{ return calendarModule\(\)\.googleCalendarConnectButton\(\); \}",
        APP,
    )
    assert forwarder, "forwarder not found"
    harness = """
<!doctype html><html><body>
<div id="scope"><button data-google-connector-connect="google-calendar">연결</button></div>
<script>__MODULE__</script>
<script>
window.__deps = {
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
};
window.__instance = window.PadiemChatCalendarModule.create(window.__deps);
function calendarModule() { return window.__instance; }
__FORWARDER__
</script></body></html>
"""
    harness = harness.replace("__MODULE__", MODULE).replace("__FORWARDER__", forwarder.group(0))
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(harness)
        found = page.evaluate("googleCalendarConnectButton().dataset.googleConnectorConnect")
        browser.close()
    assert found == "google-calendar"
