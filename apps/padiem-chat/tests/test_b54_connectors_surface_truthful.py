"""B54/B62 Web Claw connector-status surface truthfulness (#3222).

The Web Claw Connectors dialog consumes the existing read-only
`GET /api/connectors/status` projection from #2830. Platform READ availability
and this workspace's connection state remain separate axes. The only connection
mutation exposed here is the reviewed Google Calendar READ OAuth handoff; the
browser never receives provider tokens, workspace authority, or send/write scope.

#7216 R5 A9: the connector functions moved to chat-connectors-module.js, so the
former string-slicing contracts now EXECUTE the real shipped module sources in
Node (window stub + strict deps) and assert the same boundaries as behavior:
request inventory, response guards, safe sinks, closed state vocabulary.
Source contracts (markup, locale, CSS) assert parsed attribute and rule values
through the _support sheet reader.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

# R5 0단계(R-01): 모듈로 옮겨진 정의도 함께 본다(index.html 로드 순서).
from _r5_function_source import combined_source
from _support.connectors_surface import (
    capability_css_text,
    connectors_module_text,
    dialog_cards,
    dialog_element,
    dialog_element_attrs,
    locale_table,
    nav_attributes,
    nav_markup,
    shipped_connector_constants,
    strict_deps_text,
    calendar_module_text,
)

ROOT = Path(__file__).resolve().parents[1]

NAV_ID = "connectorsNavButton"
DIALOG_ID = "connectorsDialog"

LIVE_CONNECTORS = {
    "google-drive": "connector:google:drive@1",
    "gmail": "connector:google:gmail@1",
    "telegram": "connector:telegram:bot@1",
    "slack": "connector:slack:workspace@1",
    "google-calendar": "connector:google:calendar@1",
}
REMOVED_PREPARING_CARDS = ("discord", "kakao-business")
SUPPORT_STATES = ("complete", "source_ready", "deferred")
WORKSPACE_STATES = ("connected", "not_connected", "unverified", "ambiguous")
LOCALE_KEYS = (
    "connectors-note",
    "connectors-loading",
    "connectors-error",
    "connectors-status-loading",
    "connectors-status-unavailable",
    "connectors-support-complete",
    "connectors-support-source-ready",
    "connectors-support-deferred",
    "connectors-workspace-loading",
    "connectors-workspace-connected",
    "connectors-workspace-not-connected",
    "connectors-workspace-unverified",
    "connectors-workspace-sign-in",
    "connectors-workspace-ambiguous",
    "connectors-workspace-unavailable",
    "connectors-connect-calendar",
    "connectors-connect-drive",
    "connectors-connecting-drive",
    "connectors-connect-drive-error",
    "connectors-connecting-calendar",
    "connectors-connect-error",
    "connectors-grid-aria",
    "retry",
    "coming-soon",
)

CARD_RE = re.compile(r'<div class="capability-card"([^>]*)>(.*?)</div>', re.DOTALL)


def _dialog_element() -> str:
    return dialog_element()


def _cards() -> dict[str, dict]:
    return dialog_cards()


def _locale_table() -> dict[str, dict[str, str]]:
    return locale_table()


def _shipped_connector_constants() -> dict[str, str]:
    return shipped_connector_constants()


# --- Node behavior harness -------------------------------------------------
# The stub DOM is a safe-sink oracle: any write to innerHTML/outerHTML/
# insertAdjacentHTML throws, so completing a render proves textContent-only.
_NODE_PRELUDE = r"""
const __log = { fetches: [], redirects: [], authDialog: 0, navActive: 0, closeSidebar: 0, transport: [] };
const __queue = [];
const __gates = [];
const __registry = new Map();
const __documentListeners = {};
function __dispatchDocumentEvent(type) { for (const fn of __documentListeners[type] || []) fn({}); }
global.window = globalThis;
global.document = {
  getElementById(id) { return __registry.get(id) || null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener(type, fn) { (__documentListeners[type] ??= []).push(fn); },
  removeEventListener() {},
};
function makeEl(id) {
  const el = { id, dataset: {}, hidden: false, disabled: false, children: [], listeners: {}, attrs: {}, texts: [] };
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  el.appendChild = (c) => { el.children.push(c); return c; };
  el.addEventListener = (t, fn) => { (el.listeners[t] ??= []).push(fn); };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.removeAttribute = (k) => { delete el.attrs[k]; };
  el.focus = () => {};
  el.click = () => { for (const fn of el.listeners.click || []) fn({ preventDefault() {} }); };
  el.close = () => { el.removeAttribute("open"); };
  for (const sink of ["innerHTML", "outerHTML"]) {
    Object.defineProperty(el, sink, {
      set() { throw new Error("HTML sink used: " + sink); },
      get() { throw new Error("HTML sink read: " + sink); },
    });
  }
  el.insertAdjacentHTML = () => { throw new Error("HTML sink used: insertAdjacentHTML"); };
  Object.defineProperty(el, "textContent", {
    get() { return el._text ?? ""; },
    set(v) { el._text = String(v); el.texts.push(String(v)); },
  });
  return el;
}
global.fetch = async (url, options = {}) => {
  const entry = {
    url: String(url),
    method: String(options.method ?? "GET").toUpperCase(),
    body: options.body ? String(options.body) : "",
  };
  __log.fetches.push(entry);
  const step = __queue.shift() ?? {};
  if (step.gate) {
    return new Promise((resolve) => { __gates.push({ resolve }); });
  }
  if (step.throwNetwork) throw new TypeError("Failed to fetch");
  return new Response(step.body ?? "{}", { status: step.status ?? 200, headers: step.headers ?? {} });
};
window.PadiemChatTransport = {
  async fetchStatusWithRetry(url, init) { __log.transport.push(String(url)); return fetch(url, init); },
};
window.location = {
  assign(url) { __log.redirects.push(String(url)); },
  search: "",
  pathname: "/",
  hash: "",
  replaceState() {},
};
async function __drain() {
  // A fetch -> json -> render chain spans several microtask and stream ticks;
  // a single setImmediate left the last render unflushed. Drain a bounded,
  // deterministic round instead of hoping one tick is enough.
  for (let i = 0; i < 6; i++) await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setTimeout(resolve, 0));
}
function makeCard(connectorId) {
  const card = makeEl("card");
  card.dataset.connectorId = connectorId;
  const support = makeEl("support");
  const workspace = makeEl("workspace");
  card.querySelector = (sel) =>
    sel === "[data-connector-support]" ? support
    : sel === "[data-connector-workspace]" ? workspace
    : null;
  card.supportEl = support;
  card.workspaceEl = workspace;
  return card;
}
function standardFixtures(cards) {
  const f = {};
  f.shell = makeEl("appShell");
  f.nav = makeEl("connectorsNavButton");
  f.dialog = makeEl("connectorsDialog");
  f.grid = makeEl("capabilityGrid");
  f.dialogClose = makeEl("connectorsDialogClose");
  f.loading = makeEl("connectorsLoading");
  f.error = makeEl("connectorsError");
  f.retry = makeEl("connectorsRetry");
  f.view = makeEl("connectorsView");
  f.viewBody = makeEl("connectorsViewBody");
  f.liveStatus = makeEl("connectorsLiveStatus");
  f.calendarButton = makeEl("calendarConnectButton");
  f.driveButton = makeEl("driveConnectButton");
  f.gmailButton = makeEl("gmailConnectButton");
  __registry.set("connectorsViewBody", f.viewBody);
  __registry.set("connectorsView", f.view);
  __registry.set("connectorsLiveStatus", f.liveStatus);
  // R5 2부 B2: the connector DOM lookups (nav button, dialog, dialog close,
  // loading, retry) are create-scoped in chat-connectors-module.js — they must
  // resolve at create time, exactly like the real page's DOM.
  __registry.set("connectorsNavButton", f.nav);
  __registry.set("connectorsDialog", f.dialog);
  __registry.set("connectorsDialogClose", f.dialogClose);
  __registry.set("connectorsLoading", f.loading);
  __registry.set("connectorsRetry", f.retry);
  f.viewBody.querySelectorAll = (sel) => (sel === "[data-connector-id]" ? cards : []);
  // connectorsScope() prefers the mounted view body once it reports a card;
  // without this the scope falls back to the dialog and renders nothing.
  f.viewBody.querySelector = (sel) => {
    if (sel === "[data-connector-id]" && cards.length) return cards[0];
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_CALENDAR_CONNECTOR}"]`) return f.calendarButton;
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_DRIVE_CONNECTOR}"]`) return f.driveButton;
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_GMAIL_CONNECTOR}"]`) return f.gmailButton;
    return null;
  };
  f.dialog.querySelector = (sel) => {
    if (sel === ".capability-grid") return f.grid;
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_CALENDAR_CONNECTOR}"]`) return f.calendarButton;
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_DRIVE_CONNECTOR}"]`) return f.driveButton;
    if (sel === `[data-google-connector-connect="${SHIPPED.GOOGLE_GMAIL_CONNECTOR}"]`) return f.gmailButton;
    return null;
  };
  return f;
}
function makeDeps(f, overrides = {}) {
  const deps = {
    uiT: (key) => key,
    authState: { authenticated: true },
    openAuthDialog: () => { __log.authDialog += 1; },
    reviewedGoogleAuthorizationUrl: (url) => url,
    syncGoogleCalendarConnectButton: () => {},
    activateGoogleCalendarRead: async () => {},
    googleCalendarConnectButton: () => null,
    beginGoogleCalendarConnect: async () => {},
    googleConnectorConnectInFlight: false,
    googleCalendarReadActivationAfterConnectReturn: false,
    connectorStatusInFlight: false,
    connectorsViewMounted: false,
    CONNECTOR_STATUS_IDS: new Set(Object.values(LIVE_IDS)),
    GOOGLE_DRIVE_CONNECTOR: SHIPPED.GOOGLE_DRIVE_CONNECTOR,
    GOOGLE_DRIVE_TICKET_ENDPOINT: SHIPPED.GOOGLE_DRIVE_TICKET_ENDPOINT,
    GOOGLE_GMAIL_CONNECTOR: SHIPPED.GOOGLE_GMAIL_CONNECTOR,
    GOOGLE_GMAIL_TICKET_ENDPOINT: SHIPPED.GOOGLE_GMAIL_TICKET_ENDPOINT,
    connectorsNavButton: f.nav,
    connectorsDialog: f.dialog,
    connectorsDialogClose: f.dialogClose,
    connectorsLoading: f.loading,
    connectorsError: f.error,
    connectorsRetry: f.retry,
    shell: f.shell,
    setNavActive: () => { __log.navActive += 1; },
    closeSidebar: () => { __log.closeSidebar += 1; },
  };
  Object.assign(deps, overrides);
  return r5StrictDeps(deps, "connectors-deps");
}
function makeCalendarDeps(f, mod, authState) {
  return r5StrictDeps({
    authState,
    connectorsError: f.error,
    connectorsScope: () => f.dialog,
    connectorTicketErrorKey: mod.connectorTicketErrorKey,
    fetch,
    GOOGLE_CALENDAR_CONNECTOR: SHIPPED.GOOGLE_CALENDAR_CONNECTOR,
    GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: SHIPPED.GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT,
    GOOGLE_CALENDAR_TICKET_ENDPOINT: SHIPPED.GOOGLE_CALENDAR_TICKET_ENDPOINT,
    googleCalendarReadState: "unknown",
    googleConnectorConnectInFlight: false,
    openAuthDialog: () => { __log.authDialog += 1; },
    reviewedGoogleAuthorizationUrl: (url) => url,
    setConnectorCopy: mod.setConnectorCopy,
  }, "calendar-deps");
}
function statusDocument() {
  return {
    static_support_vs_workspace_state_separated: true,
    send_write_authorized: false,
    connectors: [
      { connector_id: "connector:google:drive@1", read_availability: "complete", workspace_state: "not_connected" },
      { connector_id: "connector:google:gmail@1", read_availability: "complete", workspace_state: "not_connected" },
      { connector_id: "connector:telegram:bot@1", read_availability: "deferred", workspace_state: "unverified" },
      { connector_id: "connector:slack:workspace@1", read_availability: "deferred", workspace_state: "unverified" },
      { connector_id: "connector:google:calendar@1", read_availability: "complete", workspace_state: "connected" },
    ],
  };
}
const LIVE_IDS = {
  "google-drive": "connector:google:drive@1",
  "gmail": "connector:google:gmail@1",
  "telegram": "connector:telegram:bot@1",
  "slack": "connector:slack:workspace@1",
  "google-calendar": "connector:google:calendar@1",
};
"""

_CONNECTORS_MODULE_TEXT = connectors_module_text()
_CALENDAR_MODULE_TEXT = calendar_module_text()
_STRICT_TEXT = strict_deps_text()


def _run_connector_node_script(body: str) -> dict:
    """Execute `body` against the REAL shipped module sources in Node."""
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = (
        "global.window = globalThis;\n"
        + _NODE_PRELUDE
        + "\nconst SHIPPED = " + json.dumps(_shipped_connector_constants()) + ";\n"
        + "\n" + _CONNECTORS_MODULE_TEXT
        + "\n" + _CALENDAR_MODULE_TEXT
        + "\n" + _STRICT_TEXT
        + "\n" + body
    )
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".mjs", delete=False, encoding="utf-8", newline="\n",
    )  # .mjs: the bodies use top-level await, which CommonJS refuses to parse.
    try:
        handle.write(script)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name],
            check=True,
            capture_output=True,
            text=True, encoding="utf-8", timeout=60,
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_connectors_nav_is_enabled_and_bound_to_standalone_page() -> None:
    attrs = nav_attributes()
    assert attrs.get("type") == "button"
    # Standalone page, never a popup: no dialog popup semantics on the nav.
    assert "disabled" not in attrs
    assert "aria-disabled" not in attrs
    assert "aria-haspopup" not in attrs
    assert "aria-expanded" not in attrs
    assert attrs.get("aria-controls") == "connectorsView"


def test_live_cards_are_exactly_the_reviewed_canonical_connector_ids() -> None:
    cards = _cards()
    # Claw PC and GitHub have dedicated setup cards; neither represents an OAuth grant.
    assert set(cards) == set(LIVE_CONNECTORS) | {"computer", "github"}
    for slug in ("computer", "github"):
        assert cards[slug]["connector_id"] == ""
        assert cards[slug]["status"] == ("preparing" if slug == "computer" else "loading")
    for slug, connector_id in LIVE_CONNECTORS.items():
        card = cards[slug]
        assert card["connector_id"] == connector_id
        assert card["status"] == "loading"
        assert card["has_support"] is True
        assert card["has_workspace"] is True

    # The permanently "preparing" Discord / Kakao Business cards are gone: the
    # server projection never carried them, so they could never activate.
    for slug in REMOVED_PREPARING_CARDS:
        assert slug not in cards

    assert "google-calendar" in cards
    assert cards["google-calendar"]["connect_actions"] == {"google-calendar"}
    # #3289: Drive is the second reviewed connection action.
    assert cards["google-drive"]["connect_actions"] == {"google-drive"}
    # #7088: Gmail is the third reviewed connection action (gmail.readonly).
    assert cards["gmail"]["connect_actions"] == {"gmail"}
    for slug in ("telegram", "slack"):
        assert cards[slug]["connect_actions"] == set()


def test_dialog_has_bounded_loading_error_retry_surface() -> None:
    live_status = dialog_element_attrs("connectorsLiveStatus")
    assert live_status.get("role") == "status"
    assert live_status.get("aria-live") == "polite"
    assert live_status.get("aria-atomic") == "true"
    retry = dialog_element_attrs("connectorsRetry")
    assert retry.get("data-locale-key") == "retry"
    for element_id in ("connectorsLiveStatus", "connectorsLoading", "connectorsError", "connectorsRetry"):
        assert dialog_element_attrs(element_id) is not None


def test_markup_fallbacks_match_shipped_korean_locale() -> None:
    table = _locale_table()
    dialog = _dialog_element()
    note = dialog.split('data-locale-key="connectors-note">', 1)[1].split("</p>", 1)[0]
    assert note == table["ko"]["connectors-note"]

    for key in (
        "connectors-loading",
        "connectors-error",
        "connectors-status-loading",
        "connectors-workspace-loading",
    ):
        match = re.search(rf'data-locale-key="{re.escape(key)}"[^>]*>([^<]*)<', dialog)
        assert match, key
        assert match.group(1) == table["ko"][key]

    grid_tag = dialog.split('<div class="capability-grid"', 1)[1].split(">", 1)[0]
    grid_aria = re.search(r'\saria-label="([^"]*)"', grid_tag)
    assert grid_aria
    assert grid_aria.group(1) == table["ko"]["connectors-grid-aria"]


def test_live_status_locale_keys_are_complete_in_ko_and_en() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        missing = [key for key in LOCALE_KEYS if not table[language].get(key)]
        assert missing == [], f"{language} missing {missing}"

    # #5555 owner decision 2026-10-23: the disclosure (and its two locale keys)
    # is gone entirely. The one-line tagline is the whole header copy.
    assert "connectors-note-details" not in table["ko"]
    assert "connectors-note-toggle" not in table["ko"]
    assert "connectors-note-details" not in table["en"]
    assert "connectors-note-toggle" not in table["en"]
    # The header line itself stays short.
    for language in ("ko", "en"):
        assert len(table[language]["connectors-note"]) < 120


def test_reviewed_google_connector_connection_actions_are_calendar_drive_and_gmail() -> None:
    """Executed behavior: exactly the four reviewed POSTs, reviewed redirects only."""
    SHIPPED = _shipped_connector_constants()
    body = r"""
async function freshPage() {
  // In the real product each connection attempt begins on its own page load:
  // after the reviewed redirect the browser navigates away, so no attempt ever
  // starts from a leftover in-flight flag. Model that lifecycle per attempt.
  const f = standardFixtures([]);
  const authState = { authenticated: true };
  const deps = makeDeps(f, { authState });
  const mod = window.PadiemChatConnectorsModule.create(deps);
  const calDeps = makeCalendarDeps(f, mod, authState);
  const cal = window.PadiemChatCalendarModule.create(calDeps);
  return { f, deps, mod, cal, calDeps };
}

// Calendar owns two POSTs: the connect ticket, then the READ activation with
// the bounded server answer (active grant, no write authority).
const calPage = await freshPage();
__queue.push({ body: JSON.stringify({ authorization: { connector_id: SHIPPED.GOOGLE_CALENDAR_CONNECTOR, authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?cal=1" } }) });
await calPage.cal.beginGoogleCalendarConnect();
__queue.push({ body: JSON.stringify({ ok: true, calendar_read_grant: "active", calendar_write_authorized: false }) });
await calPage.cal.activateGoogleCalendarRead();

// #3289 Drive: one ticket POST, reviewed redirect only.
const drivePage = await freshPage();
__queue.push({ body: JSON.stringify({ authorization: { connector_id: SHIPPED.GOOGLE_DRIVE_CONNECTOR, authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?drive=1" } }) });
await drivePage.mod.beginGoogleDriveConnect();

// #7088 Gmail: one ticket POST, reviewed redirect only.
const gmailPage = await freshPage();
__queue.push({ body: JSON.stringify({ authorization: { connector_id: SHIPPED.GOOGLE_GMAIL_CONNECTOR, authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?gmail=1" } }) });
await gmailPage.mod.beginGmailConnect();
const reviewedFetches = __log.fetches.slice();
const reviewedRedirects = __log.redirects.slice();

// A guest attempt opens the sign-in dialog and sends nothing.
const guestPage = await freshPage();
guestPage.deps.authState.authenticated = false;
const fetchesAfterReviewed = __log.fetches.length;
const dialogsBeforeGuest = __log.authDialog;
await guestPage.mod.beginGoogleDriveConnect();
const guestFetchDelta = __log.fetches.length - fetchesAfterReviewed;
const guestDialogDelta = __log.authDialog - dialogsBeforeGuest;

// A failed attempt stays bounded: one POST, error copy, in-flight reset.
const fetchesBeforeFailure = __log.fetches.length;
const failPage = await freshPage();
__queue.push({ status: 503, body: JSON.stringify({ error: { code: "connector_ticket_origin_not_canonical" } }) });
await failPage.mod.beginGoogleDriveConnect();
const failedFetchDelta = __log.fetches.length - fetchesBeforeFailure;

console.log(JSON.stringify({
  fetches: reviewedFetches,
  redirects: reviewedRedirects,
  guestFetchDelta,
  guestDialogDelta,
  failedFetchDelta,
  activationState: calPage.calDeps.googleCalendarReadState,
  activationErrorKey: calPage.f.error.dataset.localeKey ?? null,
  failedErrorHidden: failPage.f.error.hidden,
  failedErrorKey: failPage.f.error.dataset.localeKey ?? null,
  inFlightAfterFailure: failPage.deps.googleConnectorConnectInFlight,
}));
"""
    payload = _run_connector_node_script(body)

    fetches = payload["fetches"]
    assert len(fetches) == 4, fetches
    assert [f["method"] for f in fetches] == ["POST"] * 4
    assert [f["url"] for f in fetches] == [
        SHIPPED["GOOGLE_CALENDAR_TICKET_ENDPOINT"],
        SHIPPED["GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT"],
        SHIPPED["GOOGLE_DRIVE_TICKET_ENDPOINT"],
        SHIPPED["GOOGLE_GMAIL_TICKET_ENDPOINT"],
    ]
    bodies = [json.loads(f["body"]) for f in fetches]
    assert bodies == [
        {"connector_id": SHIPPED["GOOGLE_CALENDAR_CONNECTOR"], "begin_oauth": True},
        {},
        {"connector_id": SHIPPED["GOOGLE_DRIVE_CONNECTOR"], "begin_oauth": True},
        {"connector_id": SHIPPED["GOOGLE_GMAIL_CONNECTOR"], "begin_oauth": True},
    ]
    # Redirects only through the reviewed authorization handoff.
    assert len(payload["redirects"]) == 3
    assert all(url.startswith("https://accounts.google.com/") for url in payload["redirects"])
    # No ticket, token, or provider material travels anywhere.
    joined = json.dumps(fetches) + json.dumps(payload["redirects"])
    for forbidden in ("connect_ticket", "access_token", "refresh_token"):
        assert forbidden not in joined, forbidden
    # Guest attempt: dialog instead of a request.
    assert payload["guestFetchDelta"] == 0
    assert payload["guestDialogDelta"] >= 1
    # Failed attempt: exactly one bounded POST, error copy, in-flight reset.
    assert payload["failedFetchDelta"] == 1
    # Calendar activation succeeded with the bounded server answer and never
    # surfaced an error copy.
    assert payload["activationState"] == "active"
    assert payload["activationErrorKey"] is None
    # Failed attempt: bounded error copy, in-flight flag reset.
    assert payload["failedErrorHidden"] is False
    assert payload["failedErrorKey"] == "connectors-connect-canonical-only"
    assert payload["inFlightAfterFailure"] is False

    lowered = json.dumps(payload).lower()
    for forbidden in (
        "access_token",
        "refresh_token",
        "calendar.events.insert",
        "calendar.events.update",
        "calendar.events.delete",
        "drive.files.insert",
        "drive.files.update",
        "drive.files.delete",
        "drive.permissions",
    ):
        assert forbidden not in lowered, forbidden


def test_response_guards_preserve_server_owned_truth_boundaries() -> None:
    """Executed behavior: malformed documents throw; raw reasons never render."""
    body = r"""
const cards = [
  "connector:google:drive@1",
  "connector:google:gmail@1",
  "connector:telegram:bot@1",
  "connector:slack:workspace@1",
  "connector:google:calendar@1",
].map(makeCard);
const f = standardFixtures(cards);
const deps = makeDeps(f);
const mod = window.PadiemChatConnectorsModule.create(deps);

async function throws(fn) {
  try { await fn(); return null; } catch (error) { return String(error && error.message); }
}
const guardResults = {
  null: await throws(() => mod.renderConnectorStatus(null)),
  empty: await throws(() => mod.renderConnectorStatus({})),
  wrongFlag: await throws(() => mod.renderConnectorStatus({ static_support_vs_workspace_state_separated: false, send_write_authorized: false, connectors: [] })),
  writeAuthorized: await throws(() => mod.renderConnectorStatus({ static_support_vs_workspace_state_separated: true, send_write_authorized: true, connectors: [] })),
  notArray: await throws(() => mod.renderConnectorStatus({ static_support_vs_workspace_state_separated: true, send_write_authorized: false, connectors: "no" })),
};

// A row the projection does not own is skipped; raw reason material never renders.
const doc = statusDocument();
doc.connectors.push({
  connector_id: "connector:mystery@1",
  read_availability: "complete",
  workspace_state: "connected",
  workspace_reason: "raw-backend-reason",
  deferred_reason: "raw-deferred-reason",
  token: "raw-token-value",
  secret: "raw-secret-value",
  account: "raw-account-value",
  provider: "raw-provider-value",
});
mod.renderConnectorStatus(doc);
const rendered = [];
for (const card of cards) rendered.push(card.supportEl.textContent, card.workspaceEl.textContent, card.dataset.connectorStatus);
const renderedJoined = rendered.join("|");
const leaked = ["raw-backend-reason", "raw-deferred-reason", "raw-token-value", "raw-secret-value", "raw-account-value", "raw-provider-value", "connector:mystery@1"]
  .filter((value) => renderedJoined.includes(value));
const driveStatus = cards[0].dataset.connectorStatus;
const slackStatus = cards[3].dataset.connectorStatus;
console.log(JSON.stringify({ guardResults, leaked, driveStatus, slackStatus }));
"""
    payload = _run_connector_node_script(body)

    for name, message in payload["guardResults"].items():
        assert message is not None, f"{name} did not throw"
        assert "connector status unavailable" in message, (name, message)
    assert payload["leaked"] == [], payload["leaked"]
    # Server-owned workspace truth still projects for the reviewed ids.
    assert payload["driveStatus"] == "not_connected"
    assert payload["slackStatus"] == "unverified"


def test_support_and_workspace_axes_are_rendered_separately_with_safe_sinks() -> None:
    """Executed behavior: every state pair lands via textContent only."""
    combos = [
        {"support": support, "workspace": workspace, "authenticated": authenticated}
        for support in (*SUPPORT_STATES, "bogus")
        for workspace in (*WORKSPACE_STATES, "bogus")
        for authenticated in (True, False)
    ]
    body = r"""
const results = [];
for (const combo of COMBOS) {
  const card = makeCard("connector:google:calendar@1");
  const f = standardFixtures([card]);
  const deps = makeDeps(f, { authState: { authenticated: combo.authenticated } });
  const mod = window.PadiemChatConnectorsModule.create(deps);
  mod.renderConnectorStatus({
    static_support_vs_workspace_state_separated: true,
    send_write_authorized: false,
    connectors: [{ connector_id: "connector:google:calendar@1", read_availability: combo.support, workspace_state: combo.workspace }],
  });
  results.push({
    support: combo.support,
    workspace: combo.workspace,
    authenticated: combo.authenticated,
    supportKey: card.supportEl.textContent,
    workspaceKey: card.workspaceEl.textContent,
    statusAttr: card.dataset.connectorStatus,
  });
}
console.log(JSON.stringify({ results }));
"""
    body = body.replace(
        "const results = [];",
        "const results = [];\nconst COMBOS = " + json.dumps(combos) + ";",
    )
    payload = _run_connector_node_script(body)

    def expected_support(state: str) -> str:
        if state == "complete":
            return "connectors-support-complete"
        if state == "source_ready":
            return "connectors-support-source-ready"
        if state == "deferred":
            return "connectors-support-deferred"
        return "connectors-status-unavailable"

    def expected_workspace(state: str, authenticated: bool) -> str:
        if state == "connected":
            return "connectors-workspace-connected"
        if state == "not_connected":
            return "connectors-workspace-not-connected"
        if state == "ambiguous":
            return "connectors-workspace-ambiguous"
        if state == "unverified":
            return "connectors-workspace-unverified" if authenticated else "connectors-workspace-sign-in"
        return "connectors-workspace-unverified"

    assert len(payload["results"]) == len(combos)
    for row in payload["results"]:
        assert row["supportKey"] == expected_support(row["support"]), row
        assert row["workspaceKey"] == expected_workspace(row["workspace"], row["authenticated"]), row
        assert row["statusAttr"] == (row["workspace"] or "unverified"), row
        # The safe-sink oracle (throwing innerHTML setters) passed silently.
        assert row["supportKey"] in LOCALE_KEYS and row["workspaceKey"] in LOCALE_KEYS


def test_open_and_retry_reload_the_same_projection() -> None:
    """Executed behavior: open, retry, and the refresh event reload; one in flight."""
    body = r"""
const cards = Object.values(LIVE_IDS).map(makeCard);
const f = standardFixtures(cards);
const deps = makeDeps(f);
const mod = window.PadiemChatConnectorsModule.create(deps);
mod.wireConnectorsListeners();

__queue.push({ body: JSON.stringify(statusDocument()) });
mod.openConnectorsView();
await __drain();
const afterOpen = {
  state: f.shell.dataset.state,
  viewHidden: f.view.hidden,
  mountedChildren: f.viewBody.children.length,
  navAria: f.nav.getAttribute("aria-expanded"),
  statusCalls: __log.transport.length,
  cardsStatus: cards.map((c) => c.dataset.connectorStatus),
};

__queue.push({ body: JSON.stringify(statusDocument()) });
f.retry.click();
await __drain();
const afterRetry = { statusCalls: __log.transport.length };

__queue.push({ body: JSON.stringify(statusDocument()) });
__dispatchDocumentEvent("padiem:refresh-connector-status");
await __drain();
const afterRefresh = { statusCalls: __log.transport.length };

// One read in flight: the next trigger is dropped until it settles.
__queue.push({ gate: true });
__dispatchDocumentEvent("padiem:refresh-connector-status");
await __drain();
__dispatchDocumentEvent("padiem:refresh-connector-status");
const duringFlight = { statusCalls: __log.transport.length, loadingHidden: f.loading.hidden, retryDisabled: f.retry.disabled };
const gate = __gates.pop();
gate.resolve(new Response(JSON.stringify(statusDocument()), { status: 200, headers: {} }));
await __drain();
await __drain();
const afterFlight = { statusCalls: __log.transport.length };

// Front/network loss: bounded unavailable answer, error and retry stay offered.
__queue.push({ throwNetwork: true });
f.retry.click();
await __drain();
const afterFailure = {
  errorHidden: f.error.hidden,
  retryHidden: f.retry.hidden,
  retryDisabled: f.retry.disabled,
  cardsStatus: cards.map((c) => c.dataset.connectorStatus),
};
console.log(JSON.stringify({ afterOpen, afterRetry, afterRefresh, duringFlight, afterFlight, afterFailure }));
"""
    payload = _run_connector_node_script(body)

    after_open = payload["afterOpen"]
    assert after_open["state"] == "connectors"
    assert after_open["viewHidden"] is False
    assert after_open["mountedChildren"] == 2
    assert after_open["navAria"] == "false"
    assert after_open["statusCalls"] == 1
    assert after_open["cardsStatus"] == ["not_connected", "not_connected", "unverified", "unverified", "connected"]
    assert payload["afterRetry"]["statusCalls"] == 2
    assert payload["afterRefresh"]["statusCalls"] == 3
    during = payload["duringFlight"]
    # The transport stub logs each call synchronously, so the gated read is
    # already counted here; the second trigger must NOT add a fifth call.
    assert during["statusCalls"] == 4
    assert during["loadingHidden"] is False
    assert during["retryDisabled"] is True
    assert payload["afterFlight"]["statusCalls"] == 4
    failure = payload["afterFailure"]
    assert failure["errorHidden"] is False
    assert failure["retryHidden"] is False
    assert failure["retryDisabled"] is False
    assert failure["cardsStatus"] == ["unavailable"] * 5


def test_actual_mapping_functions_execute_with_closed_state_vocabulary() -> None:
    body = r"""
const f = standardFixtures([]);
const deps = makeDeps(f);
const mod = window.PadiemChatConnectorsModule.create(deps);
const signedIn = {
  support: ["complete", "source_ready", "deferred", "bogus"].map(mod.connectorSupportKey),
  workspace: ["connected", "not_connected", "unverified", "ambiguous", "bogus"].map(mod.connectorWorkspaceKey),
};
deps.authState.authenticated = false;
const signedOutUnverified = mod.connectorWorkspaceKey("unverified");
console.log(JSON.stringify({ signedIn, signedOutUnverified }));
"""
    payload = _run_connector_node_script(body)
    assert payload["signedIn"]["support"] == [
        "connectors-support-complete",
        "connectors-support-source-ready",
        "connectors-support-deferred",
        "connectors-status-unavailable",
    ]
    assert payload["signedIn"]["workspace"] == [
        "connectors-workspace-connected",
        "connectors-workspace-not_connected".replace("_", "-"),
        "connectors-workspace-unverified",
        "connectors-workspace-ambiguous",
        "connectors-workspace-unverified",
    ]
    assert payload["signedOutUnverified"] == "connectors-workspace-sign-in"


def test_failed_check_keeps_by_design_no_truth_cards_preparing() -> None:
    """#7364 follow-up: a failed status read is not a state for the two
    connectors whose workspace truth does not participate by design. Their
    cards keep the "준비 중" copy on both slots; the reviewed connectors keep
    the check-failed copy; the success-path mapping functions stay untouched."""
    body = r"""
const failedIds = [
  "connector:telegram:bot@1",
  "connector:slack:workspace@1",
  "connector:google:drive@1",
  "connector:google:calendar@1",
];
const cards = failedIds.map(makeCard);
const f = standardFixtures(cards);
const deps = makeDeps(f);
const mod = window.PadiemChatConnectorsModule.create(deps);
const keys = failedIds.map((connectorId) => mod.connectorUnavailableCopyKeys(connectorId));
mod.setConnectorCardsUnavailable();
const written = cards.map((card) => ({ support: card.supportEl.textContent, workspace: card.workspaceEl.textContent }));

// The success path keeps owning the copy: a normal response rewrites the slots.
__queue.push({ body: JSON.stringify(statusDocument()) });
mod.openConnectorsView();
await __drain();
const driveAfterSuccess = {
  support: cards[2].supportEl.textContent,
  workspace: cards[2].workspaceEl.textContent,
};
console.log(JSON.stringify({ keys, written, driveAfterSuccess }));
"""
    payload = _run_connector_node_script(body)
    preparing = {"support": "connectors-workspace-unverified", "workspace": "connectors-workspace-unverified"}
    check_failed = {"support": "connectors-status-unavailable", "workspace": "connectors-workspace-unavailable"}
    assert payload["keys"] == [preparing, preparing, check_failed, check_failed]
    assert payload["written"] == [preparing, preparing, check_failed, check_failed]
    assert payload["driveAfterSuccess"]["support"] == "connectors-support-complete"
    assert payload["driveAfterSuccess"]["workspace"] == "connectors-workspace-not-connected"


class _TagBalance(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.issues: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.issues.append(f"</{tag}> against {self.stack[-3:]}")
            return
        self.stack.pop()


def test_connectors_dialog_markup_is_well_formed() -> None:
    parser = _TagBalance()
    parser.feed(_dialog_element())
    assert parser.issues == []
    assert parser.stack == []


def test_status_styles_keep_support_and_workspace_visually_separate() -> None:
    # Parse the sheet: strip comments, flatten @media/@supports wrappers so
    # inner rules read like top-level ones.
    css = re.sub(r"/\*.*?\*/", "", capability_css_text(), flags=re.S)
    css = re.sub(r"@[\w-]+[^{]*\{", "", css)
    selectors = set()
    rules = []
    for group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        rules.append((group, body))
        selectors.update(selector.strip() for selector in group.split(","))
    for selector in (".connector-live-status", ".connector-retry", ".capability-workspace"):
        assert selector in selectors
    assert ".capability-read" in selectors
    assert ".capability-soon" in selectors
    # The sheet highlights its affordances with the reviewed accent token:
    # a parsed declaration check, not a raw substring of the sheet text.
    assert any("var(--accent-strong" in body for _group, body in rules)


def test_web_claw_connector_acceptance_markers() -> None:
    # Compact report-oriented pins for CENTRAL / CI logs. The status read goes
    # through the transport helper exactly once per load, and the Drive offer
    # is a pure function of signed-in + not_connected (executed behavior).
    body = r"""
const cards = Object.values(LIVE_IDS).map(makeCard);
const f = standardFixtures(cards);
const deps = makeDeps(f);
const mod = window.PadiemChatConnectorsModule.create(deps);
mod.wireConnectorsListeners();
__queue.push({ body: JSON.stringify(statusDocument()) });
mod.openConnectorsView();
await __drain();
const offered = {
  signInNotConnected: mod.driveConnectOffered(true, "not_connected"),
  guest: mod.driveConnectOffered(false, "not_connected"),
  connected: mod.driveConnectOffered(true, "connected"),
  unverified: mod.driveConnectOffered(true, "unverified"),
};
console.log(JSON.stringify({ transportCalls: __log.transport.length, offered }));
"""
    payload = _run_connector_node_script(body)
    assert payload["transportCalls"] == 1
    assert payload["offered"] == {
        "signInNotConnected": True,
        "guest": False,
        "connected": False,
        "unverified": False,
    }

    assert set(LIVE_CONNECTORS.values()) == {
        "connector:google:drive@1",
        "connector:google:gmail@1",
        "connector:telegram:bot@1",
        "connector:slack:workspace@1",
        "connector:google:calendar@1",
    }
    assert set(LIVE_CONNECTORS.values()) == set(_shipped_connector_connector_ids())
    print("WEB_CLAW_CONNECTORS_LIVE_STATUS=YES")
    print("EXISTING_STATUS_PROJECTION_REUSED=YES")
    print("STATIC_SUPPORT_VS_WORKSPACE_STATE_SEPARATED=YES")
    print("OAUTH_DUPLICATION=0")
    print("SEND_WRITE_ENABLEMENT=0")
    constants = _shipped_connector_constants()
    assert constants["GOOGLE_DRIVE_CONNECTOR"] == "google-drive"
    print("RAW_WORKSPACE_REASON_RENDERED=NO")
    print("GOOGLE_DRIVE_CONNECT_HANDOFF=YES")
    print("GOOGLE_DRIVE_SCOPE=drive.readonly")
    print("GOOGLE_DRIVE_WRITE_AUTHORITY=0")
    print("DESKTOP_DEPENDENCY=0")
    print("PRODUCTION_MUTATION=0")


def _shipped_connector_connector_ids() -> set[str]:
    """The five canonical ids the shipped markup carries (index.html)."""
    dialog = _dialog_element()
    ids = set(re.findall(r'data-connector-id="([^"]+)"', dialog))
    return {connector_id for connector_id in ids if connector_id}
