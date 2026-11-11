"""Connectors dialog brightness + Calendar READ state UX (#connectorsDialog scoped).

Two product fixes, both frontend-only:

1. Brightness — on Padiem Glass the Connectors dialog used the shared
   ``var(--panel)`` background (rgba(235,239,242,.46)) behind a
   rgba(0,0,0,.58) backdrop: a fogged sheet over a dark pit. The fix is
   scoped to ``#connectorsDialog`` only — the Claw and Skills dialogs keep
   their existing shared styling.

2. Calendar state UX — the Google Calendar card must never present
   "workspace connected" (the OAuth axis) as if Calendar READ were usable,
   and an activation failure must never read as an OAuth failure. The two
   axes get separate lines with a closed state vocabulary, and the failure
   copy explicitly preserves the OAuth connection.

Backend contract notes: ``GET /api/connectors/status`` carries no persisted
READ-grant field, and the browser consumes only the read-only projection
plus the two reviewed POST endpoints. No Python, OAuth, or Engine change is
made or asserted here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
CAPABILITY_CSS = ROOT / "static/capability-nav.css"
CALENDAR_MODULE = ROOT / "static/chat-calendar-module.js"
STRICT_DEPS = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

DIALOG_ID = "connectorsDialog"
CALENDAR_CARD_ID = "connector:google:calendar@1"

NEW_LOCALE_KEYS = (
    "connectors-calendar-oauth-connected",
    "connectors-calendar-read-pending",
    "connectors-calendar-read-activating",
    "connectors-calendar-read-active",
    "connectors-calendar-read-failed",
    "connectors-calendar-read-unavailable",
    "connectors-calendar-read-error-engine-auth",
    "connectors-calendar-read-error-workspace",
    "connectors-calendar-read-error-binding",
    "connectors-calendar-read-error-not-connected",
    "connectors-calendar-read-error-grant",
)

# The reviewed #3451 bounded diagnostic vocabulary the UI maps to
# cause-specific, secret-free copy. Anything outside this set (including
# codes #3451 carries but CENTRAL has not assigned to this UI slice) falls
# back to the generic OAuth-preserving message.
SAFE_DIAGNOSTIC_CODES = {
    "calendar_activation_engine_auth_failed": "connectors-calendar-read-error-engine-auth",
    "calendar_activation_workspace_unavailable": "connectors-calendar-read-error-workspace",
    "calendar_activation_binding_unavailable": "connectors-calendar-read-error-binding",
    "calendar_activation_not_connected": "connectors-calendar-read-error-not-connected",
    "calendar_activation_grant_unavailable": "connectors-calendar-read-error-grant",
    "calendar_read_activation_unavailable": "connectors-calendar-read-activation-error",
}

CARD_RE = re.compile(r'<div class="capability-card"([^>]*)>(.*?)</div>', re.DOTALL)


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _css() -> str:
    return CAPABILITY_CSS.read_text(encoding="utf-8")


def _locale_table() -> dict[str, dict[str, str]]:
    source = LOCALE_JS.read_text(encoding="utf-8")
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    return {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }


def _dialog_element() -> str:
    index = _index()
    before, _ = index.split(f'id="{DIALOG_ID}"', 1)
    start = before.rindex("<dialog")
    return index[start:].split("</dialog>", 1)[0] + "</dialog>"


def _calendar_card_inner() -> str:
    dialog = _dialog_element()
    for attrs, inner in CARD_RE.findall(dialog):
        if f'data-connector-id="{CALENDAR_CARD_ID}"' in attrs:
            return inner
    raise AssertionError("google calendar card not found in connectors dialog")


def _connector_block() -> str:
    app = _app()
    marker = "// #3222 Web Claw connector truth."
    assert marker in app
    end = 'if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);'
    assert end in app
    return app.split(marker, 1)[1].split(end, 1)[0] + "\n" + CALENDAR_MODULE.read_text(encoding="utf-8").replace("deps.", "")


def _run_calendar_module(body: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = (
        "const window = {};\n"
        + CALENDAR_MODULE.read_text(encoding="utf-8")
        + "\n"
        + STRICT_DEPS
        + "\n(async () => {\n"
        + body
        + "\n})().catch((error) => { console.error(error); process.exit(1); });"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


_BASE_MODULE_BODY = """
const deps = r5StrictDeps({
  connectorsScope: () => null,
  authState: { authenticated: true },
  googleConnectorConnectInFlight: false,
  googleCalendarReadState: "unknown",
  GOOGLE_CALENDAR_CONNECTOR: "google-calendar",
  GOOGLE_CALENDAR_TICKET_ENDPOINT: "/api/connectors/google/ticket",
  GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: "/api/connectors/google/calendar/activate-read",
  setConnectorCopy: () => {},
  connectorsError: null,
  openAuthDialog: () => {},
  fetch: async () => { throw new Error("no network"); },
  reviewedGoogleAuthorizationUrl: () => null,
}, "calendar.base.deps");
const instance = window.PadiemChatCalendarModule.create(deps);
"""


def _rgba_values(rule_text: str, property_name: str) -> tuple[float, float, float, float] | None:
    match = re.search(
        rf"{re.escape(property_name)}\s*:\s*rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
        rule_text,
    )
    if not match:
        return None
    return tuple(float(part) for part in match.groups())  # type: ignore[return-value]


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        scaled = value / 255.0
        return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(part) for part in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(foreground: str, background: str) -> float:
    fg = _relative_luminance(tuple(int(foreground[i:i + 2], 16) for i in (1, 3, 5)))
    bg = _relative_luminance(tuple(int(background[i:i + 2], 16) for i in (1, 3, 5)))
    lighter, darker = max(fg, bg), min(fg, bg)
    return (lighter + 0.05) / (darker + 0.05)


# ── A. brightness ─────────────────────────────────────────────────────────


def test_connectors_dialog_has_scoped_near_solid_glass_override() -> None:
    css = _css()
    override = re.search(
        r'html\[data-theme="padiem-glass"\] #connectorsDialog\s*\{[^}]*\}',
        css,
    )
    assert override, "scoped padiem-glass override for #connectorsDialog is required"
    rule = override.group(0)
    background = _rgba_values(rule, "background")
    assert background is not None, "override must set a concrete rgba background"
    assert background[:3] == (246, 249, 251, ), "bright sheet tone (246,249,251) expected"
    assert background[3] >= 0.95, "dialog surface must be near-solid (>= .95)"
    assert "color: #17212a" in rule
    assert "inset 0 1px 0" in rule, "glass highlight is kept (GLASS_EFFECT=KEEP)"


def test_connectors_backdrop_is_lighter_and_blurred_while_shared_stays_unchanged() -> None:
    css = _css()
    shared = re.search(r"\.capability-dialog::backdrop\s*\{[^}]*\}", css)
    assert shared, "shared capability-dialog backdrop must remain"
    shared_alpha = _rgba_values(shared.group(0), "background")
    assert shared_alpha == (0, 0, 0, 0.58), "Claw/Skills backdrop is intentionally unchanged"

    scoped = re.search(r"#connectorsDialog::backdrop\s*\{[^}]*\}", css)
    assert scoped, "#connectorsDialog needs its own lighter backdrop"
    rule = scoped.group(0)
    backdrop = _rgba_values(rule, "background")
    assert backdrop is not None
    assert backdrop[3] <= 0.45, f"backdrop darkness must drop below .45, got {backdrop[3]}"
    assert backdrop[3] >= 0.3, "backdrop must still focus the dialog"
    assert "backdrop-filter: blur(" in rule


def test_connectors_cards_are_brighter_than_the_shared_card_surface() -> None:
    css = _css()
    override = re.search(
        r"#connectorsDialog \.capability-card\s*\{[^}]*\}",
        css,
    )
    assert override, "scoped bright card override for the connectors grid is required"
    background = _rgba_values(override.group(0), "background")
    assert background is not None
    assert background[:3] == (255, 255, 255, )
    assert background[3] >= 0.86, "card surface must be bright (>= .86)"


def test_small_text_uses_solid_aa_colors_instead_of_opacity_mutting() -> None:
    css = _css()
    assert "#connectorsDialog .capability-workspace" in css
    muted = re.search(
        r"#connectorsDialog \.capability-kicker,[^}]*#connectorsDialog \.capability-soon\s*\{[^}]*\}",
        css,
        re.DOTALL,
    )
    assert muted, "small-type group must get solid colors inside the dialog"
    rule = muted.group(0)
    assert "opacity: 1" in rule
    assert "color: #3d4c59" in rule
    # The muted gray and every READ-state color must pass AA (>= 4.5) on the
    # bright card surface (approximated by its near-white effective tone).
    for color in ("#3d4c59", "#8a5300", "#175cd3", "#16794c", "#b3261e"):
        assert _contrast_ratio(color, "#f2f6f8") >= 4.5, color


def test_claw_and_skills_dialogs_gain_no_new_rescoping() -> None:
    css = _css()
    assert "#skillsDialog" not in css, "Skills dialog must not be touched"
    # The permanently disabled Skills dialog is gone from the DOM, and its
    # locale keys are gone from both tables, rather than only absent from CSS.
    html = INDEX_HTML.read_text(encoding="utf-8")
    locale = LOCALE_JS.read_text(encoding="utf-8")
    assert "skillsDialog" not in html
    assert "skillsNavButton" not in html
    for key in (
        "nav-skills",
        "skills-kicker",
        "skills-title",
        "skills-note",
        "skill-custom",
        "skills-grid-aria",
    ):
        assert f'"{key}"' not in locale, key
    assert css.count('html[data-theme="padiem-glass"] #clawDialog {') == 1, (
        "the existing Claw override must stay exactly as it was"
    )
    app_block = _connector_block()
    assert "clawDialog" not in app_block


# ── B. Calendar state UX ──────────────────────────────────────────────────


def test_calendar_card_has_a_bounded_read_state_line_only_for_calendar() -> None:
    inner = _calendar_card_inner()
    assert 'class="capability-read-state" data-connector-read-state' in inner
    assert 'role="status"' in inner, "activation state changes are announced politely"
    assert 'data-read-state="pending"' in inner
    assert "hidden" in inner
    assert 'data-locale-key="connectors-calendar-read-pending"' in inner
    dialog = _dialog_element()
    for attrs, _inner in CARD_RE.findall(dialog):
        if f'data-connector-id="{CALENDAR_CARD_ID}"' in attrs:
            continue
        assert "data-connector-read-state" not in attrs


def test_locale_state_copy_is_complete_and_oauth_preserving_in_ko_and_en() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        missing = [key for key in NEW_LOCALE_KEYS if not table[language].get(key)]
        assert missing == [], f"{language} missing {missing}"

    # Workspace connected is stated as the Google-account (OAuth) fact…
    assert "Google 계정 연결됨" == table["ko"]["connectors-calendar-oauth-connected"]
    assert "Google account connected" == table["en"]["connectors-calendar-oauth-connected"]
    # …and the READ axis has its own pending/active copy.
    assert "활성화 필요" in table["ko"]["connectors-calendar-read-pending"]
    assert "needs activation" in table["en"]["connectors-calendar-read-pending"]
    assert table["ko"]["connectors-calendar-read-active"] == "Calendar 읽기 활성화됨"
    # Failure copy keeps the OAuth connection explicitly intact.
    for phrase in ("Google 계정 연결은", "실패했습니다"):
        assert phrase in table["ko"]["connectors-calendar-read-failed"]
    en_failed = table["en"]["connectors-calendar-read-failed"].lower()
    for phrase in ("google account", "failed"):
        assert phrase in en_failed
    assert "연결은 유지됩니다" in table["ko"]["connectors-calendar-read-activation-error"]
    assert "stays connected" in table["en"]["connectors-calendar-read-activation-error"]
    # Done state is a state, not a request receipt.
    assert table["ko"]["connectors-calendar-read-activation-done"] == "Calendar 읽기 활성화됨"
    assert table["en"]["connectors-calendar-read-activation-done"] == "Calendar read access is active"


def test_safe_diagnostic_copy_keeps_the_oauth_connection_explicit() -> None:
    table = _locale_table()
    # auth_failed / workspace / binding: the OAuth link stays intact, only the
    # activation service/workspace/binding check failed.
    for key in (
        "connectors-calendar-read-error-engine-auth",
        "connectors-calendar-read-error-workspace",
        "connectors-calendar-read-error-binding",
    ):
        assert "유지됩니다" in table["ko"][key], key
        assert "stays connected" in table["en"][key].lower(), key
    # grant: the OAuth link completed; only the grant activation/save failed.
    assert "연결은 완료되었습니다" in table["ko"]["connectors-calendar-read-error-grant"]
    assert "is connected" in table["en"]["connectors-calendar-read-error-grant"].lower()
    # not_connected: asks for a re-check without claiming or blaming OAuth.
    assert "다시 확인" in table["ko"]["connectors-calendar-read-error-not-connected"]
    assert "verified again" in table["en"]["connectors-calendar-read-error-not-connected"].lower()


def test_all_safe_diagnostic_codes_map_through_the_calendar_module() -> None:
    body = _BASE_MODULE_BODY + """
const codes = __CODES__;
const mapped = codes.map((code) => instance.calendarReadActivationErrorKey({ calendarReadErrorCode: code }));
console.log(JSON.stringify(mapped));
""".replace("__CODES__", json.dumps(list(SAFE_DIAGNOSTIC_CODES)))
    payload = _run_calendar_module(body)
    assert payload == list(SAFE_DIAGNOSTIC_CODES.values())


def test_app_js_is_locale_only_and_contains_no_korean_anywhere() -> None:
    """Forbidden contract (R2 rule 3): app.js must stay locale-only so user copy
    lives in locale.js. The invariant is about source content, so it stays
    source-level with its reason recorded here."""
    # Repository invariant: app.js carries runtime code and English identifiers
    # only. Every user-facing Korean lives in locale.js (ko table), so this
    # file must not contain Hangul — comments included.
    source = _app()
    hangul = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
    offenders = [
        (index + 1, line.strip())
        for index, line in enumerate(source.splitlines())
        if hangul.search(line)
    ]
    assert offenders == [], f"app.js must be Korean-free (locale-only): {offenders[:5]}"


def test_calendar_state_mapping_functions_execute_with_closed_vocabulary() -> None:
    body = _BASE_MODULE_BODY + """
const states = ["unknown", "activating", "active", "failed", "unavailable", "bogus", "constructor"].map(instance.calendarReadStateKey);
const transitions = [
  ["unknown", "active", "active"],
  ["unknown", "inactive", "unknown"],
  ["unknown", "unavailable", "unavailable"],
  ["unavailable", "active", "active"],
  ["unavailable", "inactive", "unknown"],
  ["unknown", "bogus", "unknown"],
  ["activating", "active", "activating"],
  ["active", "inactive", "active"],
  ["failed", "active", "failed"],
  ["failed", "unavailable", "failed"],
].map(function ([current, server, expected]) {
  return instance.calendarServerGrantSessionState(current, server) === expected;
});
const safeCodes = __CODES__;
const safeErrors = safeCodes.map(function (code) {
  return instance.calendarReadActivationErrorKey({ calendarReadErrorCode: code });
});
const fallbackErrors = [
  { calendarReadErrorCode: "some_future_unreviewed_code" },
  { calendarReadErrorCode: "calendar_activation_identity_unavailable" },
  { calendarReadErrorCode: "constructor" },
  {},
  null,
].map(instance.calendarReadActivationErrorKey);
console.log(JSON.stringify({ states, transitions, safeErrors, fallbackErrors }));
""".replace("__CODES__", json.dumps(list(SAFE_DIAGNOSTIC_CODES)))
    payload = _run_calendar_module(body)
    assert payload["states"] == [
        "connectors-calendar-read-pending",
        "connectors-calendar-read-activating",
        "connectors-calendar-read-active",
        "connectors-calendar-read-failed",
        "connectors-calendar-read-unavailable",
        "connectors-calendar-read-pending",
        "connectors-calendar-read-pending",
    ]
    # Every server-truth transition must match the reviewed expectation,
    # including REFRESH_ACTIVE (a fresh page load shows the persisted grant)
    # and the no-overwrite rules for in-session truths.
    assert payload["transitions"] == [True] * 10
    generic = "connectors-calendar-read-activation-error"
    # Every reviewed safe code maps to its own bounded copy.
    assert payload["safeErrors"] == [SAFE_DIAGNOSTIC_CODES[code] for code in SAFE_DIAGNOSTIC_CODES]
    # Unknown, not-in-scope, and hostile codes all fall back to the generic
    # OAuth-preserving message — nothing ever renders the raw server text.
    assert payload["fallbackErrors"] == [generic, generic, generic, generic, generic]


def test_app_state_machine_is_in_session_scope_and_fail_safe() -> None:
    # Behavioral contract: the Calendar READ state machine drives the DOM and
    # the safe copy from deps; nothing here pins app.js source text.
    # Forbidden contract (R2 rule 3): the old request-receipt flags must not
    # return, because a fresh page would then present a stale done/in-flight
    # truth. Absence is the contract, so it stays source-level.
    block = _connector_block()
    assert "googleCalendarReadActivationDone" not in block
    assert "googleCalendarReadActivationInFlight" not in block
    payload = _run_calendar_module(
        """
function element(dataset) {
  const node = {
    hidden: false, disabled: false, textContent: "",
    dataset: Object.assign({}, dataset || {}),
    querySelector() { return null; },
  };
  return node;
}
const stateLine = element();
const workspaceLine = element();
const card = element();
card.dataset.connectorStatus = "connected";
card.querySelector = (selector) => selector === "[data-connector-read-state]"
  ? stateLine : selector === "[data-connector-workspace]" ? workspaceLine : null;
const button = element();
const errorLine = element();
errorLine.hidden = true;
const scope = element();
scope.querySelector = (selector) => selector === '[data-google-connector-connect="google-calendar"]'
  ? button : selector === '[data-connector-id="connector:google:calendar@1"]' ? card : null;
let opens = 0;
let fetchCalls = [];
let assigned = [];
let fetchImpl = async () => ({ ok: true, json: async () => ({}) });
window.location = { assign(url) { assigned.push(url); } };
const deps = r5StrictDeps({
  connectorsScope: () => scope,
  authState: { authenticated: true },
  googleConnectorConnectInFlight: false,
  googleCalendarReadState: "unknown",
  GOOGLE_CALENDAR_CONNECTOR: "google-calendar",
  GOOGLE_CALENDAR_TICKET_ENDPOINT: "/api/connectors/google/ticket",
  GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT: "/api/connectors/google/calendar/activate-read",
  setConnectorCopy: (node, key) => { if (node) node.textContent = key; },
  connectorsError: errorLine,
  openAuthDialog: () => { opens += 1; },
  fetch: (...args) => fetchImpl(...args),
  reviewedGoogleAuthorizationUrl: (url) => url,
}, "calendar.state.deps");
const instance = window.PadiemChatCalendarModule.create(deps);
// 1. Unknown grant on the connected OAuth axis shows pending and keeps the connection open.
instance.renderCalendarReadState();
const pending = {
  hidden: stateLine.hidden,
  visual: stateLine.dataset.readState || null,
  card: card.dataset.calendarReadState || null,
  copy: stateLine.textContent,
  workspace: workspaceLine.textContent,
};
// 2. Disconnected OAuth axis hides the READ line.
card.dataset.connectorStatus = "loading";
instance.renderCalendarReadState();
const disconnected = { hidden: stateLine.hidden, card: card.dataset.calendarReadState || null };
card.dataset.connectorStatus = "connected";
// 3. Syncing a fresh page with an active persisted grant does not overwrite it.
instance.syncGoogleCalendarConnectButton({ workspace_state: "connected", calendar_read_grant_state: "active" });
const synced = {
  state: deps.googleCalendarReadState,
  visual: stateLine.dataset.readState,
  card: card.dataset.calendarReadState,
  copy: stateLine.textContent,
  workspace: workspaceLine.textContent,
  buttonHidden: button.hidden,
  action: button.dataset.calendarAction,
  disabled: button.disabled,
  buttonCopy: button.textContent,
};
// 3b. A non-string projection and a non-connected row do not change the
//     session state or the generic workspace copy.
deps.googleCalendarReadState = "unknown";
workspaceLine.textContent = "";
instance.syncGoogleCalendarConnectButton({ workspace_state: "not_connected", calendar_read_grant_state: 123 });
const ignored = {
  state: deps.googleCalendarReadState,
  workspace: workspaceLine.textContent,
  action: button.dataset.calendarAction,
};
// 4. Activation enters the transient "activating" state before success.
deps.googleCalendarReadState = "unknown";
deps.googleConnectorConnectInFlight = false;
stateLine.textContent = "";
errorLine.textContent = "";
errorLine.hidden = true;
let releaseActivation = null;
fetchImpl = async (url, options) => {
  fetchCalls.push({ url, options });
  return new Promise((resolve) => {
    releaseActivation = () => resolve({ ok: true, json: async () => ({ ok: true, calendar_read_grant: "active", calendar_write_authorized: false }) });
  });
};
const activation = instance.activateGoogleCalendarRead();
const activating = {
  state: deps.googleCalendarReadState,
  visual: stateLine.dataset.readState,
  copy: stateLine.textContent,
  buttonCopy: button.textContent,
  disabled: button.disabled,
};
releaseActivation();
await activation;
const activated = {
  state: deps.googleCalendarReadState,
  visual: stateLine.dataset.readState,
  card: card.dataset.calendarReadState,
  copy: stateLine.textContent,
  errorHidden: errorLine.hidden,
  buttonCopy: button.textContent,
  disabled: button.disabled,
  endpoint: fetchCalls[fetchCalls.length - 1].url,
  method: fetchCalls[fetchCalls.length - 1].options.method,
  body: fetchCalls[fetchCalls.length - 1].options.body,
  cache: fetchCalls[fetchCalls.length - 1].options.cache,
};
// 5. A failed activation keeps the OAuth connection intact and renders only the
//    bounded failure copy — never the raw server text.
workspaceLine.textContent = "connectors-calendar-oauth-connected";
deps.googleCalendarReadState = "unknown";
deps.googleConnectorConnectInFlight = false;
stateLine.textContent = "";
errorLine.textContent = "";
errorLine.hidden = true;
fetchCalls = [];
fetchImpl = async () => {
  return {
    ok: false,
    json: async () => ({
      error: { code: "calendar_activation_grant_unavailable", message: "RAW_SERVER_SECRET" },
    }),
  };
};
await instance.activateGoogleCalendarRead();
const failed = {
  state: deps.googleCalendarReadState,
  visual: stateLine.dataset.readState,
  card: card.dataset.calendarReadState,
  errorCopy: errorLine.textContent,
  errorHidden: errorLine.hidden,
  buttonCopy: button.textContent,
  disabled: button.disabled,
  workspace: workspaceLine.textContent,
  rawLeaked: (errorLine.textContent || "").includes("RAW_SERVER_SECRET"),
};
// 6. An unauthenticated connection attempt opens login and performs no fetch.
deps.authState.authenticated = false;
fetchCalls = [];
await instance.beginGoogleCalendarConnect();
const unauth = { opens, fetches: fetchCalls.length };
// 7. An authenticated connection attempt posts to the Calendar ticket endpoint.
deps.authState.authenticated = true;
fetchCalls = [];
assigned.length = 0;
fetchImpl = async (url, options) => {
  fetchCalls.push({ url, options });
  return { ok: true, json: async () => ({
    authorization: { connector_id: "google-calendar", authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?client_id=x" },
  }) };
};
await instance.beginGoogleCalendarConnect();
const connected = {
  assigned: assigned.slice(),
  url: fetchCalls[fetchCalls.length - 1].url,
  method: fetchCalls[fetchCalls.length - 1].options.method,
  body: fetchCalls[fetchCalls.length - 1].options.body,
  cache: fetchCalls[fetchCalls.length - 1].options.cache,
  buttonCopy: button.textContent,
};
console.log(JSON.stringify({ pending, disconnected, synced, ignored, activating, activated, failed, unauth, connected }));
"""
    )
    assert payload["pending"] == {
        "hidden": False,
        "visual": "pending",
        "card": "unknown",
        "copy": "connectors-calendar-read-pending",
        "workspace": "",
    }
    assert payload["disconnected"] == { "hidden": True, "card": None }
    assert payload["synced"] == {
        "state": "active",
        "visual": "active",
        "card": "active",
        "copy": "connectors-calendar-read-active",
        "workspace": "connectors-calendar-oauth-connected",
        "buttonHidden": False,
        "action": "activate-read",
        "disabled": True,
        "buttonCopy": "connectors-calendar-read-activation-done",
    }
    assert payload["ignored"] == {
        "state": "unknown",
        "workspace": "",
        "action": "connect",
    }
    assert payload["activating"]["state"] == "activating"
    assert payload["activating"]["visual"] == "activating"
    assert payload["activating"]["copy"] == "connectors-calendar-read-activating"
    assert payload["activating"]["buttonCopy"] == "connectors-activating-calendar-read"
    assert payload["activating"]["disabled"] is True
    assert payload["activated"]["state"] == "active"
    assert payload["activated"]["visual"] == "active"
    assert payload["activated"]["card"] == "active"
    assert payload["activated"]["copy"] == "connectors-calendar-read-active"
    assert payload["activated"]["errorHidden"] is True
    assert payload["activated"]["buttonCopy"] == "connectors-calendar-read-activation-done"
    assert payload["activated"]["disabled"] is True
    assert payload["activated"]["endpoint"] == "/api/connectors/google/calendar/activate-read"
    assert payload["activated"]["method"] == "POST"
    assert payload["activated"]["body"] == "{}"
    assert payload["activated"]["cache"] == "no-store"
    assert payload["failed"]["state"] == "failed"
    assert payload["failed"]["visual"] == "failed"
    assert payload["failed"]["card"] == "failed"
    assert payload["failed"]["errorCopy"] == "connectors-calendar-read-error-grant"
    assert payload["failed"]["errorHidden"] is False
    assert payload["failed"]["buttonCopy"] == "connectors-activate-calendar-read"
    assert payload["failed"]["workspace"] == "connectors-calendar-oauth-connected"
    assert payload["failed"]["rawLeaked"] is False
    assert payload["unauth"] == { "opens": 1, "fetches": 0 }
    assert payload["connected"]["assigned"][0].endswith("client_id=x")
    assert payload["connected"]["url"] == "/api/connectors/google/ticket"
    assert payload["connected"]["method"] == "POST"
    assert "begin_oauth" in payload["connected"]["body"]
    assert "google-calendar" in payload["connected"]["body"]
    assert payload["connected"]["cache"] == "no-store"
    assert payload["connected"]["buttonCopy"] == "connectors-connecting-calendar"


def test_no_secret_or_authority_material_enters_the_calendar_state_surface() -> None:
    """Forbidden contract (R2 rule 3): no credential/authority field or HTML sink
    may enter this surface, even after a refactor. Source-level absence is the
    contract here, so it stays pinned instead of being rewritten as behavior."""
    block = _connector_block()
    lowered = block.lower()
    for forbidden in (
        "binding_ref",
        "actor_ref",
        "workspace_ref",
        "session_id",
        "token",
        "innerhtml",
        "outerhtml",
        "insertadjacenthtml",
    ):
        assert forbidden not in lowered, forbidden


def test_existing_surface_truth_pins_still_hold() -> None:
    """Forbidden/pin contract (R2 rule 3): exactly the four reviewed connector
    POSTs may exist on this surface, and the post-OAuth Calendar continuation
    must stay wired. This spans app.js and the module, so the pin stays
    source-level with its reason recorded here."""
    block = _connector_block()
    # #3289 adds the Drive connect POST; #7088 adds the Gmail connect POST.
    # Nothing else may post from this block.
    assert block.count('method: "POST"') == 4, "exactly the status + activation + drive + gmail connect endpoints"
    assert "googleCalendarReadActivationAfterConnectReturn = true" in block
    assert "await activateGoogleCalendarRead()" in block
    assert "connectorWorkspaceKey(row.workspace_state)" in block
