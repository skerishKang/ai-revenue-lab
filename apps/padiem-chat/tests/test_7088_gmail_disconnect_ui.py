"""#7088 4/4 — Gmail 연결 해제 버튼(앱 연결 화면) 계약.

`claw-gmail-account-management.js`를 Node vm에서 실제로 실행해 다음을 관찰한다:

- 버튼 노출 조건: 카드 `data-connector-status === "connected"`일 때만 보이고,
  그 외(not_connected/loading/unavailable)에는 숨는다;
- 해제 요청: 첫 클릭은 확인 문구만 보여 요청이 없고, 두 번째 클릭에서
  `POST /api/connectors/google/gmail/disconnect` **정확히 1건**(빈 본문 —
  서버가 body·query를 거부한다), credentials same-origin;
- 성공: `padiem:refresh-connector-status` 이벤트가 발행되고, 카드가
  not_connected로 바뀌면 버튼이 숨는다(카드가 "연결 안 됨"으로 바뀌는 경로);
- 실패: 검증되지 않은 응답에서는 요청 후 피드백에
  `connectors-gmail-remove-failed` 문구 키가 표시된다.

문구 키는 locale.js의 ko·en 양쪽에 선언되어 있는지 별도로 단정한다
(`window.__padiemLocale.text`는 하네스에서 키 반환 스텁으로 대체).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
MODULE = (STATIC / "claw-gmail-account-management.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

COPY_KEYS = (
    "connectors-gmail-remove",
    "connectors-gmail-remove-confirm-button",
    "connectors-gmail-remove-confirm",
    "connectors-gmail-removed",
    "connectors-gmail-remove-failed",
)


class _ScriptSrcParser(HTMLParser):
    """index.html의 script src 순서를 문자열 위치가 아니라 마크업에서 읽는다."""

    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        for name, value in attrs:
            if name == "src" and value:
                self.srcs.append(value)


def test_index_loads_the_gmail_management_module_before_the_generic_manager() -> None:
    parser = _ScriptSrcParser()
    parser.feed(INDEX)
    order = parser.srcs
    assert order.count("./claw-gmail-account-management.js") == 1
    assert order.index("./claw-gmail-account-management.js") < order.index(
        "./claw-connector-management.js"
    )


def test_index_wires_the_button_and_feedback_into_the_gmail_card() -> None:
    card = INDEX.split('data-connector-id="connector:google:gmail@1"', 1)[1].split(
        "</div>", 1
    )[0]
    assert 'id="connectorGmailRemove"' in card
    assert 'id="connectorGmailFeedback"' in card
    assert 'data-locale-key="connectors-gmail-remove"' in card
    assert 'role="status"' in card


def test_locale_declares_every_gmail_copy_key_in_ko_and_en() -> None:
    _, after = LOCALE.split("ko: {", 1)
    ko = after.split("en: {", 1)[0]
    en = after.split("en: {", 1)[1]
    for block in (ko, en):
        for key in COPY_KEYS:
            assert f'"{key}"' in block, key


def test_app_js_does_not_own_the_gmail_disconnect_wiring() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "connectorGmailRemove" not in app
    assert "gmail/disconnect" not in app


_HARNESS_JS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: true, disabled: false, textContent: "", dataset: {},
    attrs, listeners: {}, open: false, clicks: 0,
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { this.clicks += 1; (this.listeners.click || []).forEach((fn) => fn()); },
    querySelector() { return null; }, querySelectorAll() { return []; },
  };
}

const elements = {
  connectorsDialog: makeElement("connectorsDialog"),
  connectorGmailRemove: makeElement("connectorGmailRemove"),
  connectorGmailFeedback: makeElement("connectorGmailFeedback"),
};
const gmailCard = makeElement("gmailCard");
gmailCard.dataset.connectorStatus = "loading";
const cards = { '[data-connector-id="connector:google:gmail@1"]': gmailCard };

const live = {
  events: [],
  fetchCalls: [],
  fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, state: "off" }) }),
};
const observers = [];
global.MutationObserver = class {
  constructor(callback) { this.callback = callback; observers.push(callback); }
  observe() {}
};
function flushObservers() { observers.forEach((observer) => observer()); }

const document = {
  getElementById: (id) => (elements[id] || null),
  querySelector: (selector) => (cards[selector] || null),
  dispatchEvent: (event) => { live.events.push(event.type); },
};
const ctx = {
  document,
  console,
  window: {
    __padiemLocale: { text: (key) => key },
    dispatchEvent: (event) => { live.events.push(event.type); },
  },
  fetch: async (...a) => { live.fetchCalls.push(a); return live.fetchImpl(...a); },
  Event, Map, Set, Object, Promise, Error, JSON,
  MutationObserver: class { constructor(callback) { observers.push(callback); } observe() {} },
  setTimeout: (fn) => fn(),
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "claw-gmail-account-management.js" });

const results = {};
function surfaces() {
  return {
    removeHidden: elements.connectorGmailRemove.hidden,
    removeDisabled: elements.connectorGmailRemove.disabled,
    removeText: elements.connectorGmailRemove.textContent,
    feedbackHidden: elements.connectorGmailFeedback.hidden,
    feedbackText: elements.connectorGmailFeedback.textContent,
  };
}
function setCardStatus(value) {
  gmailCard.dataset.connectorStatus = value;
  flushObservers();
}

(async () => {
// 1. Exposure: only a connected card shows the button.
results.exposure = {};
for (const state of ["connected", "not_connected", "loading", "unavailable"]) {
  setCardStatus(state);
  results.exposure[state] = {
    hidden: elements.connectorGmailRemove.hidden,
    disabled: elements.connectorGmailRemove.disabled,
  };
}
setCardStatus("connected");

// 2. First click shows the confirm copy and sends no request.
live.fetchCalls = [];
elements.connectorGmailRemove.click();
results.firstClick = {
  posts: live.fetchCalls.length,
  feedback: elements.connectorGmailFeedback.textContent,
  feedbackShown: elements.connectorGmailFeedback.hidden === false,
};

// 3. Second click posts exactly once: reviewed path, empty body, credentials.
elements.connectorGmailRemove.click();
await new Promise((resolve) => setTimeout(resolve, 5));
results.post = {
  posts: live.fetchCalls.length,
  url: live.fetchCalls[0][0],
  method: live.fetchCalls[0][1].method,
  body: live.fetchCalls[0][1].body || null,
  credentials: live.fetchCalls[0][1].credentials,
};

// 4. Success: one status-refresh event; the card flips to not_connected and
//    the button hides again.
results.success = {
  refreshEvent: live.events.includes("padiem:refresh-connector-status"),
  feedback: elements.connectorGmailFeedback.textContent,
};
setCardStatus("not_connected");
results.afterFlip = { hidden: elements.connectorGmailRemove.hidden };

// 5. Failure: a verified refusal shows the bounded copy after one attempt and
//    never claims success.
setCardStatus("connected");
live.fetchCalls = [];
live.fetchImpl = async () => ({ ok: false, status: 500, json: async () => ({ ok: false }) });
elements.connectorGmailRemove.click();
elements.connectorGmailRemove.click();
await new Promise((resolve) => setTimeout(resolve, 5));
results.failure = {
  posts: live.fetchCalls.length,
  feedback: elements.connectorGmailFeedback.textContent,
  feedbackShown: elements.connectorGmailFeedback.hidden === false,
};

process.stdout.write(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_HARNESS_JS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "claw-gmail-account-management.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_exposure_follows_the_card_status(observed: dict) -> None:
    exposure = observed["exposure"]
    assert exposure["connected"] == {"hidden": False, "disabled": False}
    assert exposure["not_connected"] == {"hidden": True, "disabled": False}
    assert exposure["loading"] == {"hidden": True, "disabled": False}
    assert exposure["unavailable"] == {"hidden": True, "disabled": False}


def test_first_click_confirms_without_posting(observed: dict) -> None:
    assert observed["firstClick"]["posts"] == 0
    assert observed["firstClick"]["feedback"] == "connectors-gmail-remove-confirm"
    assert observed["firstClick"]["feedbackShown"] is True


def test_second_click_posts_the_reviewed_disconnect_exactly_once(observed: dict) -> None:
    post = observed["post"]
    assert post["posts"] == 1
    assert post["url"] == "/api/connectors/google/gmail/disconnect"
    assert post["method"] == "POST"
    assert post["body"] is None  # the route rejects a request body
    assert post["credentials"] == "same-origin"


def test_success_publishes_the_status_refresh_and_the_card_flips(observed: dict) -> None:
    assert observed["success"]["refreshEvent"] is True
    assert observed["success"]["feedback"] == "connectors-gmail-removed"
    assert observed["afterFlip"]["hidden"] is True


def test_failure_shows_the_bounded_copy_and_never_claims_success(observed: dict) -> None:
    failure = observed["failure"]
    assert failure["posts"] == 1  # one attempt: no replay on a verified refusal
    assert failure["feedback"] == "connectors-gmail-remove-failed"
    assert failure["feedbackShown"] is True
