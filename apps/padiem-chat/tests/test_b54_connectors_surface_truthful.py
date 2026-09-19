"""B54/B62 Connectors surface truthfulness (#2779).

The B62 shell used to ship a disabled Connectors nav entry and an all-or-nothing
placeholder that told the owner every connector was "not connected yet / coming
soon". Shared READ support for Google Drive, Gmail and Telegram is now accepted
platform truth, so that copy is stale — but B62 has no trusted per-user
connector-status projection, so it must not swing to the opposite lie either.

This contract fixes the two facts the surface is allowed to state, separately:

1. whether Padiem supports a connector at the shared platform layer;
2. whether this screen can verify or configure *this* workspace's connection
   (it cannot, and says so).

The informational dialog is opened by the existing sidebar entry, performs no
request at all, and returns focus to that entry on close. Copy and status facts
are asserted from the shipped markup and locale table; the open/close/focus and
network-silence behaviour is measured by a Node harness that executes the real
`static/app.js` against a DOM stub built from the ids `index.html` declares.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
CAPABILITY_CSS = ROOT / "static/capability-nav.css"

NAV_ID = "connectorsNavButton"
DIALOG_ID = "connectorsDialog"
READ_KEY = "connectors-status-read"
SOON_KEY = "coming-soon"

# Accepted platform facts. Slack / Discord / Kakao Business stay preparing.
EXPECTED_STATUS = {
    "google-drive": "read-supported",
    "gmail": "read-supported",
    "telegram": "read-supported",
    "slack": "preparing",
    "discord": "preparing",
    "kakao-business": "preparing",
}
READ_CONNECTORS = ("google-drive", "gmail", "telegram")
PREPARING_CONNECTORS = ("slack", "discord", "kakao-business")

CONNECTOR_KEYS = ("connectors-kicker", "connectors-title", "connectors-note", READ_KEY)

# A claim that this workspace is connected, or an offer to connect it here.
CONNECTION_CLAIM = re.compile(r"연결됨|연결하기|\bconnected\b|\bconnect\b|\b연결된\b", re.IGNORECASE)
# A claim that outbound sending is available from this surface.
SEND_CLAIM = re.compile(r"발송|보내기|\bsend\b|\bupload\b|\bwrite\b", re.IGNORECASE)
ALL_SOON_CLAIM = re.compile(r"coming soon|준비 중|not connected yet|아직 연결되지 않았", re.IGNORECASE)

CARD_RE = re.compile(r'<div class="capability-card"([^>]*)>(.*?)</div>', re.DOTALL)


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _nav_markup() -> str:
    index = _index()
    marker = f'id="{NAV_ID}"'
    assert marker in index
    return index.split("<button", 1)[0] + index.split(marker, 1)[0].rsplit("<button", 1)[-1] + index.split(marker, 1)[1].split("</button>", 1)[0]


def _dialog_element() -> str:
    """The whole `<dialog>…</dialog>` element for the connectors surface."""
    index = _index()
    before, _ = index.split(f'id="{DIALOG_ID}"', 1)
    start = before.rindex("<dialog")
    return index[start:].split("</dialog>", 1)[0] + "</dialog>"


def _cards() -> dict[str, dict[str, str]]:
    cards: dict[str, dict[str, str]] = {}
    for attrs, inner in CARD_RE.findall(_dialog_element()):
        connector = re.search(r'data-connector="([^"]+)"', attrs)
        if not connector:
            continue
        status = re.search(r'data-connector-status="([^"]+)"', attrs)
        key = re.search(r'data-locale-key="([^"]+)"', inner)
        cards[connector.group(1)] = {
            "status": status.group(1) if status else "",
            "key": key.group(1) if key else "",
            "inner": inner,
            "label": re.sub(r"<[^>]+>", "", inner).strip(),
        }
    return cards


def _locale_table() -> dict[str, dict[str, str]]:
    """Parse the shipped KO/EN copy out of locale.js, so asserted copy is shipped copy."""
    source = LOCALE_JS.read_text(encoding="utf-8")
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    table = {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }
    assert table["ko"] and table["en"]
    return table


def _connectors_wiring_block() -> str:
    app = _app()
    marker = "// Connectors informational surface (#2779)"
    assert marker in app
    return app.split(marker, 1)[1].split('if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);', 1)[0]


# ── the entry point is usable and targets the existing dialog ──────────────


def test_connectors_nav_is_enabled_and_bound_to_the_existing_dialog() -> None:
    nav = _nav_markup()
    assert 'type="button"' in nav
    assert "disabled" not in nav
    assert 'aria-disabled="true"' not in nav
    assert 'tabindex="-1"' not in nav
    # It still advertises the dialog contract, not a new view.
    assert 'aria-haspopup="dialog"' in nav
    assert f'aria-controls="{DIALOG_ID}"' in nav
    assert 'aria-expanded="false"' in nav
    # The controlled dialog is the one that already existed.
    assert _index().count(f'id="{DIALOG_ID}"') == 1
    assert _index().count(f'id="{NAV_ID}"') == 1


def test_connectors_nav_is_wired_and_dialog_close_is_wired() -> None:
    block = _connectors_wiring_block()
    assert 'connectorsNavButton.addEventListener("click", openConnectorsDialog)' in block
    assert 'connectorsDialogClose.addEventListener("click", closeConnectorsDialog)' in block
    # Escape closes the informational dialog through the same single path.
    assert 'connectorsDialog.addEventListener("cancel"' in block
    assert "closeConnectorsDialog()" in block
    # Focus returns to the sidebar entry that opened it.
    assert "connectorsNavButton.focus()" in block


# ── platform support is stated, per-user connection is not invented ────────


def test_platform_support_status_matches_the_accepted_facts() -> None:
    cards = _cards()
    assert set(cards) == set(EXPECTED_STATUS), sorted(cards)
    for connector, expected in EXPECTED_STATUS.items():
        assert cards[connector]["status"] == expected, f"{connector}: {cards[connector]['status']}"


def test_read_supported_connectors_are_not_labelled_coming_soon() -> None:
    cards = _cards()
    for connector in READ_CONNECTORS:
        card = cards[connector]
        assert f'data-locale-key="{READ_KEY}"' in card["inner"], card["inner"]
        assert SOON_KEY not in card["inner"], f"{connector} still shows the coming-soon label"
        assert not ALL_SOON_CLAIM.search(card["label"]), card["label"]
    for connector in PREPARING_CONNECTORS:
        card = cards[connector]
        assert SOON_KEY in card["inner"], card["inner"]
    # The shared coming-soon key stays for surfaces that really are preparing.
    assert f'"{SOON_KEY}"' in LOCALE_JS.read_text(encoding="utf-8")


def test_no_card_or_copy_claims_a_workspace_connection() -> None:
    dialog = _dialog_element()
    assert not CONNECTION_CLAIM.search(dialog), CONNECTION_CLAIM.search(dialog).group(0)
    table = _locale_table()
    for language in ("ko", "en"):
        for key in CONNECTOR_KEYS:
            copy = table[language][key]
            assert not CONNECTION_CLAIM.search(copy), f"{language}/{key}: {copy}"
    # No per-user state can be injected: the surface is markup + locale only.
    app = _app()
    assert "capability-card" not in app
    assert "data-connector" not in app


def test_connector_note_separates_support_from_workspace_state() -> None:
    table = _locale_table()
    ko, en = table["ko"]["connectors-note"], table["en"]["connectors-note"]
    assert "워크스페이스" in ko and "workspace" in en
    assert "지원" in ko and "support" in en
    # It must say this screen neither verifies nor configures the connection.
    assert "확인" in ko and "설정" in ko
    assert "does not" in en and "verify" in en and "configure" in en
    # And it must not fall back to the stale all-or-nothing claim.
    for copy in (ko, en):
        assert not ALL_SOON_CLAIM.search(copy), copy
    # KO/EN parity for every key this surface uses.
    for key in CONNECTOR_KEYS:
        assert table["ko"][key] and table["en"][key]


def test_markup_fallbacks_match_the_shipped_korean_copy() -> None:
    """The pre-locale render must not show different copy from the loaded one."""
    table = _locale_table()
    dialog = _dialog_element()
    note = dialog.split(f'data-locale-key="connectors-note">', 1)[1].split("</p>", 1)[0]
    assert note == table["ko"]["connectors-note"]
    for card in _cards().values():
        # Only the locale-bound status span is copy; the card name is a label.
        span = re.search(rf'data-locale-key="{re.escape(card["key"])}">([^<]*)</span>', card["inner"])
        assert span, card["inner"]
        assert span.group(1) == table["ko"][card["key"]], f"{card['key']}: {span.group(1)}"
    # The grid carries both a locale key and its Korean fallback; match the real
    # aria-label attribute (a leading space), not the data-locale-aria-label one.
    grid_tag = dialog.split('<div class="capability-grid"', 1)[1].split(">", 1)[0]
    grid_aria = re.search(r'\saria-label="([^"]*)"', grid_tag)
    assert grid_aria, grid_tag
    assert grid_aria.group(1) == table["ko"]["connectors-grid-aria"]


def test_connector_surface_implies_no_send_or_write_capability() -> None:
    dialog = _dialog_element()
    assert not SEND_CLAIM.search(dialog), SEND_CLAIM.search(dialog).group(0)
    table = _locale_table()
    for language in ("ko", "en"):
        for key in CONNECTOR_KEYS:
            copy = table[language][key]
            assert not SEND_CLAIM.search(copy), f"{language}/{key}: {copy}"


def test_claw_copy_no_longer_conflates_connectors_with_send_authority() -> None:
    table = _locale_table()
    ko, en = table["ko"]["claw-status"], table["en"]["claw-status"]
    # The stale claim that connectors are simply not connected is gone.
    assert "커넥터와 발송은 아직 연결되지 않았습니다" not in ko
    assert "Connectors and sending are not connected yet" not in en
    # Availability now depends on workspace setup...
    assert "워크스페이스" in ko and "workspace" in en
    # ...and sending is still explicitly not offered.
    assert "발송" in ko and "지원하지 않" in ko
    assert "sending" in en and "not supported" in en
    assert not CONNECTION_CLAIM.search(ko) and not CONNECTION_CLAIM.search(en)


# ── no new authority, and the rest of the shell is untouched ───────────────


def test_connectors_surface_adds_no_network_authority() -> None:
    block = _connectors_wiring_block()
    assert "fetch(" not in block
    assert "XMLHttpRequest" not in block
    app = _app()
    # Word-boundary matches: "unauthorized" must not read as an OAuth surface.
    for forbidden in (r"/api/connectors", r"\boauth\b", r"access_token", r"\bauthorize\b", r"\brefresh_token\b"):
        assert not re.search(forbidden, app, re.IGNORECASE), forbidden


def test_chat_and_claw_navigation_remains_intact() -> None:
    index = _index()
    # Chat and Claw entries are unchanged and usable.
    assert 'id="clawNavButton" type="button"' in index
    assert "disabled" not in index.split('id="clawNavButton"', 1)[1].split("</button>", 1)[0]
    for key in ("nav-claw", "nav-connectors", "nav-skills", "new-chat"):
        assert f'data-locale-key="{key}"' in index
    # The Skills dialog keeps its own honest preparing state; this slice only
    # touches Connectors.
    skills = index.split('id="skillsDialog"', 1)[1].split("</dialog>", 1)[0]
    assert f'data-locale-key="{SOON_KEY}"' in skills
    assert 'id="skillsNavButton" type="button" disabled aria-disabled="true"' in index


class _TagBalance(HTMLParser):
    """Minimal well-formedness checker: every opened element is closed in order.

    There is no browser in this suite, so this is the substitute for the
    structural part of a render: malformed markup would otherwise only surface
    in CI, where the dialog has no dedicated QA script.
    """

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.issues: list[str] = []
        self.seen: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.seen.append(tag)
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.issues.append(f"</{tag}> against {self.stack[-3:]}")
            return
        self.stack.pop()


def test_connectors_dialog_markup_is_well_formed() -> None:
    dialog = _dialog_element()
    parser = _TagBalance()
    parser.feed(dialog)
    assert parser.issues == [], parser.issues
    assert parser.stack == [], parser.stack
    # The dialog keeps its labelled heading, an explicit close control and the
    # single grid that holds the connector cards.
    assert dialog.startswith("<dialog") and dialog.endswith("</dialog>")
    assert dialog.count("<dialog") == 1
    assert f'id="{DIALOG_ID}Title"' in dialog
    assert _index().count(f'aria-labelledby="{DIALOG_ID}Title"') == 1
    assert 'id="connectorsDialogClose"' in dialog
    assert dialog.count('class="capability-grid"') == 1
    assert parser.seen.count("div") >= 7


def test_status_style_uses_existing_shared_tokens() -> None:
    css = CAPABILITY_CSS.read_text(encoding="utf-8")
    assert ".capability-read" in css
    # Reuses the shared accent token rather than inventing a new palette entry.
    assert "var(--accent-strong" in css
    assert ".capability-soon" in css


# ── behavioral proof via Node harness executing real app.js ────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const INDEX = fs.readFileSync(process.argv[3], "utf8");

const declaredIds = [];
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const idMatch = /\sid="([^"]+)"/.exec(m[2]);
    if (idMatch && declaredIds.indexOf(idMatch[1]) < 0) declaredIds.push(idMatch[1]);
  }
}
const navMarkup = INDEX.split("<button")
  .filter((part) => /\sid="connectorsNavButton"/.test(part))
  .map((part) => part.split("</button>")[0])
  .join(" ");
const dialogOpens = [];

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, open: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
  el.querySelectorAll = (sel) => (sel && sel.indexOf("claw-chip") >= 0 ? [] : el.children);
  el.focus = () => { doc.activeElement = el; };
  el.blur = () => { if (doc.activeElement === el) doc.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.showModal = () => { el.open = true; dialogOpens.push(el.id); };
  el.close = () => { el.open = false; (el.listeners.close || []).forEach((fn) => fn({})); };
  el.matches = () => false;
  return el;
}

const byId = {};
function add(id, tag) { const e = makeEl(tag); e.id = id; byId[id] = e; return e; }
declaredIds.forEach((id) => add(id, "div"));
byId.projectForm.querySelector = () => makeEl("div");

// Seed the attributes the shipped markup declares for the entry point, so the
// aria-expanded state machine is exercised from its real starting value.
const declaredNav = {};
navMarkup.replace(/([a-zA-Z-]+)="([^"]*)"/g, (m, key, value) => { declaredNav[key] = value; return m; });
Object.keys(declaredNav).forEach((key) => { if (key !== "class") byId.connectorsNavButton.setAttribute(key, declaredNav[key]); });

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "quote" }];
byId.clawAction.value = "quote";
byId.clawRunHistory.hidden = true;
byId.clawResultCard.hidden = true;
byId.clawWorkspace.hidden = true;

const requests = [];
function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}
async function fetchImpl(url, opts) {
  opts = opts || {};
  requests.push({ url: String(url), method: (opts.method || "GET").toUpperCase() });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  return jsonResponse(200, {});
}

const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

const shim = {
  document: doc,
  fetch: fetchImpl,
  console,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (key) => key },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  PadiemAttachmentCapabilities: {
    limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
    images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
    textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
    copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
  },
  PadiemBinaryDocuments: null,
};
shim.window = shim;
vm.createContext(shim);
vm.runInContext(APP, shim, { filename: "app.js" });

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks, requests, dialogOpens })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  const cancel = (el) => (el.listeners.cancel || []).forEach((fn) => fn({ preventDefault() {} }));
  await tick(40);

  const nav = byId.connectorsNavButton;
  const dialog = byId.connectorsDialog;

  // 1) The entry point is reachable and advertises the dialog contract. The
  //    declared attributes come from the SHIPPED markup; app.js only owns the
  //    aria-expanded state, which is measured below.
  checks.NAV_IS_ENABLED_AND_DECLARES_DIALOG =
    !!nav && nav.disabled === false &&
    navMarkup.indexOf("disabled") < 0 &&
    navMarkup.indexOf('aria-haspopup="dialog"') >= 0 &&
    navMarkup.indexOf('aria-controls="connectorsDialog"') >= 0 &&
    navMarkup.indexOf('aria-expanded="false"') >= 0 &&
    nav.getAttribute("aria-expanded") === "false";
  if (!checks.NAV_IS_ENABLED_AND_DECLARES_DIALOG) fail("NAV_IS_ENABLED_AND_DECLARES_DIALOG: " + navMarkup);

  // 2) Opening issues no request at all.
  const before = requests.length;
  nav.click();
  await tick(40);
  checks.OPEN_IS_NETWORK_FREE = requests.length === before && dialogOpens.length === 1 && dialog.open === true;
  if (!checks.OPEN_IS_NETWORK_FREE) fail("OPEN_IS_NETWORK_FREE: " + JSON.stringify({ added: requests.slice(before), dialogOpens }));

  // 3) It opens only the informational surface — no view or workspace change.
  checks.OPEN_DOES_NOT_CHANGE_THE_APP_VIEW =
    shell.dataset.state === "home" && byId.clawWorkspace.hidden === true && dialogOpens.length === 1;
  if (!checks.OPEN_DOES_NOT_CHANGE_THE_APP_VIEW) fail("OPEN_DOES_NOT_CHANGE_THE_APP_VIEW: " + shell.dataset.state);
  checks.ARIA_EXPANDED_TRACKS_OPEN_STATE = nav.getAttribute("aria-expanded") === "true";
  if (!checks.ARIA_EXPANDED_TRACKS_OPEN_STATE) fail("ARIA_EXPANDED_TRACKS_OPEN_STATE: " + nav.getAttribute("aria-expanded"));

  // 4) Closing returns focus to the sidebar entry that opened it.
  byId.connectorsDialogClose.click();
  await tick(40);
  checks.CLOSE_RESTORES_FOCUS_TO_THE_ENTRY =
    dialog.open === false && doc.activeElement === nav && nav.getAttribute("aria-expanded") === "false";
  if (!checks.CLOSE_RESTORES_FOCUS_TO_THE_ENTRY) {
    fail("CLOSE_RESTORES_FOCUS_TO_THE_ENTRY: " + JSON.stringify({ open: dialog.open, active: doc.activeElement && doc.activeElement.id }));
  }

  // 5) Escape closes through the same path and restores focus again.
  nav.click();
  await tick(20);
  cancel(dialog);
  await tick(20);
  checks.ESCAPE_CLOSES_AND_RESTORES_FOCUS =
    dialog.open === false && doc.activeElement === nav && nav.getAttribute("aria-expanded") === "false";
  if (!checks.ESCAPE_CLOSES_AND_RESTORES_FOCUS) {
    fail("ESCAPE_CLOSES_AND_RESTORES_FOCUS: " + JSON.stringify({ open: dialog.open, active: doc.activeElement && doc.activeElement.id }));
  }

  // 6) Reopening still works, and the whole journey stayed inside the existing
  //    authority — no connector, OAuth or provider endpoint was ever touched.
  nav.click();
  await tick(20);
  checks.REOPEN_STILL_WORKS = dialog.open === true && dialogOpens.length === 3;
  if (!checks.REOPEN_STILL_WORKS) fail("REOPEN_STILL_WORKS: " + dialogOpens.length);
  const allowed = new Set(["/api/auth/status", "/api/projects", "/api/conversations", "/api/claw/runs", "/api/claw/memory", "/api/claw/inbox/tasks"]);
  const touched = Array.from(new Set(requests.map((r) => r.url.split("?")[0])));
  checks.NO_CONNECTOR_ENDPOINT_AND_NO_NEW_AUTHORITY = touched.every((u) => allowed.has(u));
  if (!checks.NO_CONNECTOR_ENDPOINT_AND_NO_NEW_AUTHORITY) {
    fail("NO_CONNECTOR_ENDPOINT_AND_NO_NEW_AUTHORITY: " + JSON.stringify(touched.filter((u) => !allowed.has(u))));
  }

  console.log(JSON.stringify({ ok: true, checks, requests, dialogOpens }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_connectors_surface_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(INDEX_HTML)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_connectors_entry_opens_only_the_informational_dialog() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "NAV_IS_ENABLED_AND_DECLARES_DIALOG",
        "OPEN_IS_NETWORK_FREE",
        "OPEN_DOES_NOT_CHANGE_THE_APP_VIEW",
        "ARIA_EXPANDED_TRACKS_OPEN_STATE",
        "CLOSE_RESTORES_FOCUS_TO_THE_ENTRY",
        "ESCAPE_CLOSES_AND_RESTORES_FOCUS",
        "REOPEN_STILL_WORKS",
        "NO_CONNECTOR_ENDPOINT_AND_NO_NEW_AUTHORITY",
    ):
        assert checks.get(name) is True, name
    # Exactly the dialog was opened, and never anything else.
    assert payload["dialogOpens"] == ["connectorsDialog"] * 3, payload["dialogOpens"]


if __name__ == "__main__":
    test_connectors_nav_is_enabled_and_bound_to_the_existing_dialog()
    test_connectors_nav_is_wired_and_dialog_close_is_wired()
    test_platform_support_status_matches_the_accepted_facts()
    test_read_supported_connectors_are_not_labelled_coming_soon()
    test_no_card_or_copy_claims_a_workspace_connection()
    test_connector_note_separates_support_from_workspace_state()
    test_markup_fallbacks_match_the_shipped_korean_copy()
    test_connector_surface_implies_no_send_or_write_capability()
    test_claw_copy_no_longer_conflates_connectors_with_send_authority()
    test_connectors_surface_adds_no_network_authority()
    test_chat_and_claw_navigation_remains_intact()
    test_connectors_dialog_markup_is_well_formed()
    test_status_style_uses_existing_shared_tokens()
    test_behavioral_harness_passes()
    test_behavioral_connectors_entry_opens_only_the_informational_dialog()
    print("B54_CONNECTORS_SURFACE_TRUTHFUL_TESTS=PASS")
