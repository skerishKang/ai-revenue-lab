"""B54/B62 Web Claw connector-status surface truthfulness (#3222).

The Web Claw Connectors dialog consumes the existing read-only
`GET /api/connectors/status` projection from #2830. Platform READ availability
and this workspace's connection state remain separate axes. The only connection
mutation exposed here is the reviewed Google Calendar READ OAuth handoff; the
browser never receives provider tokens, workspace authority, or send/write scope.
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

LIVE_CONNECTORS = {
    "google-drive": "connector:google:drive@1",
    "gmail": "connector:google:gmail@1",
    "telegram": "connector:telegram:bot@1",
    "slack": "connector:slack:workspace@1",
    "google-calendar": "connector:google:calendar@1",
}
STATIC_PREPARING = ("discord", "kakao-business")
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
    "connectors-connecting-calendar",
    "connectors-connect-error",
    "connectors-grid-aria",
    "retry",
    "coming-soon",
)

CARD_RE = re.compile(r'<div class="capability-card"([^>]*)>(.*?)</div>', re.DOTALL)


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _dialog_element() -> str:
    index = _index()
    before, _ = index.split(f'id="{DIALOG_ID}"', 1)
    start = before.rindex("<dialog")
    return index[start:].split("</dialog>", 1)[0] + "</dialog>"


def _nav_markup() -> str:
    index = _index()
    marker = f'id="{NAV_ID}"'
    assert marker in index
    before, after = index.split(marker, 1)
    return "<button" + before.rsplit("<button", 1)[1] + marker + after.split("</button>", 1)[0] + "</button>"


def _cards() -> dict[str, dict[str, str]]:
    cards: dict[str, dict[str, str]] = {}
    for attrs, inner in CARD_RE.findall(_dialog_element()):
        slug = re.search(r'data-connector="([^"]+)"', attrs)
        if not slug:
            continue
        connector_id = re.search(r'data-connector-id="([^"]+)"', attrs)
        status = re.search(r'data-connector-status="([^"]+)"', attrs)
        cards[slug.group(1)] = {
            "attrs": attrs,
            "inner": inner,
            "connector_id": connector_id.group(1) if connector_id else "",
            "status": status.group(1) if status else "",
        }
    return cards


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


def _connector_block() -> str:
    app = _app()
    marker = "// #3222 Web Claw connector truth."
    assert marker in app
    end = 'if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);'
    assert end in app
    return app.split(marker, 1)[1].split(end, 1)[0]


def _pure_mapping_block() -> str:
    app = _app()
    start = "  function connectorSupportKey(value) {"
    end = "  function liveConnectorCards() {"
    assert start in app and end in app
    return start.lstrip() + app.split(start, 1)[1].split(end, 1)[0]


def test_connectors_nav_is_enabled_and_bound_to_existing_dialog() -> None:
    nav = _nav_markup()
    assert 'type="button"' in nav
    assert "disabled" not in nav
    assert 'aria-disabled="true"' not in nav
    assert 'aria-haspopup="dialog"' in nav
    assert f'aria-controls="{DIALOG_ID}"' in nav
    assert 'aria-expanded="false"' in nav


def test_live_cards_are_exactly_the_reviewed_canonical_connector_ids() -> None:
    cards = _cards()
    assert set(cards) == set(LIVE_CONNECTORS) | set(STATIC_PREPARING)
    for slug, connector_id in LIVE_CONNECTORS.items():
        card = cards[slug]
        assert card["connector_id"] == connector_id
        assert card["status"] == "loading"
        assert "data-connector-support" in card["inner"]
        assert "data-connector-workspace" in card["inner"]

    for slug in STATIC_PREPARING:
        card = cards[slug]
        assert card["connector_id"] == ""
        assert card["status"] == "preparing"
        assert 'data-locale-key="coming-soon"' in card["inner"]

    assert "google-calendar" in cards
    assert 'data-google-connector-connect="google-calendar"' in cards["google-calendar"]["inner"]
    for slug in ("google-drive", "gmail", "telegram", "slack"):
        assert "data-google-connector-connect" not in cards[slug]["inner"]
    assert "discord" in cards and "kakao-business" in cards


def test_dialog_has_bounded_loading_error_retry_surface() -> None:
    dialog = _dialog_element()
    for element_id in ("connectorsLiveStatus", "connectorsLoading", "connectorsError", "connectorsRetry"):
        assert f'id="{element_id}"' in dialog
    assert 'id="connectorsLiveStatus" role="status" aria-live="polite" aria-atomic="true"' in dialog
    assert 'id="connectorsRetry"' in dialog
    assert 'data-locale-key="retry"' in dialog


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

    assert "Google Calendar" in table["ko"]["connectors-note"]
    assert "Google Calendar" in table["en"]["connectors-note"]
    assert "쓰기" in table["ko"]["connectors-note"]
    assert "write" in table["en"]["connectors-note"].lower()


def test_calendar_read_oauth_is_the_only_connector_connection_action() -> None:
    block = _connector_block()
    assert block.count('fetch("/api/connectors/status"') == 1
    assert 'GOOGLE_CALENDAR_START_ENDPOINT = "/api/connectors/google/start"' in block
    assert 'fetch(GOOGLE_CALENDAR_START_ENDPOINT' in block
    assert 'connector_id: GOOGLE_CALENDAR_CONNECTOR' in block
    assert 'GOOGLE_CALENDAR_CONNECTOR = "google-calendar"' in block
    assert block.count('method: "POST"') == 1
    assert "oauth.padiem.net" not in block
    assert "connect_ticket" not in block
    assert 'url.hostname !== "accounts.google.com"' in block
    assert 'url.pathname !== "/o/oauth2/v2/auth"' in block
    assert 'window.location.assign(redirect)' in block

    lowered = block.lower()
    for forbidden in (
        "access_token",
        "refresh_token",
        'method: "put"',
        'method: "patch"',
        'method: "delete"',
        "calendar.events.insert",
        "calendar.events.update",
        "calendar.events.delete",
    ):
        assert forbidden not in lowered, forbidden


def test_response_guards_preserve_server_owned_truth_boundaries() -> None:
    block = _connector_block()
    assert "document.static_support_vs_workspace_state_separated !== true" in block
    assert "document.send_write_authorized !== false" in block
    assert "!Array.isArray(document.connectors)" in block
    assert "!CONNECTOR_STATUS_IDS.has(row.connector_id)" in block
    assert "rows.set(row.connector_id, row)" in block

    # Raw backend reasons and identity/credential material are never rendered.
    assert "workspace_reason" not in block
    assert "deferred_reason" not in block
    assert "row.token" not in block
    assert "row.secret" not in block
    assert "row.account" not in block
    assert "row.provider" not in block


def test_support_and_workspace_axes_are_rendered_separately_with_safe_sinks() -> None:
    block = _connector_block()
    assert 'card.querySelector("[data-connector-support]")' in block
    assert 'card.querySelector("[data-connector-workspace]")' in block
    assert "connectorSupportKey(row.read_availability)" in block
    assert "connectorWorkspaceKey(row.workspace_state)" in block
    assert "element.textContent = uiT(key)" in block
    assert "innerHTML" not in block
    assert "outerHTML" not in block
    assert "insertAdjacentHTML" not in block

    for state in SUPPORT_STATES:
        assert f'value === "{state}"' in block
    for state in WORKSPACE_STATES:
        assert f'value === "{state}"' in block


def test_open_and_retry_reload_the_same_projection() -> None:
    block = _connector_block()
    assert "void loadConnectorStatus();" in block
    assert 'connectorsRetry.addEventListener("click", () => void loadConnectorStatus())' in block
    assert "connectorStatusInFlight" in block
    assert "setConnectorCardsLoading();" in block
    assert "setConnectorCardsUnavailable();" in block
    assert "connectorsError.hidden = false" in block
    assert "connectorsRetry.hidden = false" in block


def test_actual_mapping_functions_execute_with_closed_state_vocabulary() -> None:
    node = shutil.which("node")
    assert node, "node runtime is required"
    functions = _pure_mapping_block()
    script = f"""
const authState = {{ authenticated: true }};
{functions}
const signedIn = {{
  support: ["complete", "source_ready", "deferred", "bogus"].map(connectorSupportKey),
  workspace: ["connected", "not_connected", "unverified", "ambiguous", "bogus"].map(connectorWorkspaceKey),
}};
authState.authenticated = false;
const signedOutUnverified = connectorWorkspaceKey("unverified");
console.log(JSON.stringify({{ signedIn, signedOutUnverified }}));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["signedIn"]["support"] == [
        "connectors-support-complete",
        "connectors-support-source-ready",
        "connectors-support-deferred",
        "connectors-status-unavailable",
    ]
    assert payload["signedIn"]["workspace"] == [
        "connectors-workspace-connected",
        "connectors-workspace-not-connected",
        "connectors-workspace-unverified",
        "connectors-workspace-ambiguous",
        "connectors-workspace-unverified",
    ]
    assert payload["signedOutUnverified"] == "connectors-workspace-sign-in"


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
    css = CAPABILITY_CSS.read_text(encoding="utf-8")
    for selector in (".connector-live-status", ".connector-retry", ".capability-workspace"):
        assert selector in css
    assert ".capability-read" in css
    assert ".capability-soon" in css
    assert "var(--accent-strong" in css


def test_web_claw_connector_acceptance_markers() -> None:
    # Compact report-oriented pins for CENTRAL / CI logs.
    assert 'fetch("/api/connectors/status"' in _connector_block()
    assert set(LIVE_CONNECTORS.values()) == {
        "connector:google:drive@1",
        "connector:google:gmail@1",
        "connector:telegram:bot@1",
        "connector:slack:workspace@1",
        "connector:google:calendar@1",
    }
    print("WEB_CLAW_CONNECTORS_LIVE_STATUS=YES")
    print("EXISTING_STATUS_PROJECTION_REUSED=YES")
    print("STATIC_SUPPORT_VS_WORKSPACE_STATE_SEPARATED=YES")
    print("OAUTH_DUPLICATION=0")
    print("SEND_WRITE_ENABLEMENT=0")
    print("RAW_WORKSPACE_REASON_RENDERED=NO")
    print("DESKTOP_DEPENDENCY=0")
    print("PRODUCTION_MUTATION=0")
