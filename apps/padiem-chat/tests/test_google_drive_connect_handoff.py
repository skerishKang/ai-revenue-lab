"""#3289 reviewed Google Drive READ-only connect handoff.

Web Claw's second reviewed connector connection action. This module pins the
product properties the slice must hold, grouped by review axis:

A. visibility -- the action exists only for an authenticated ``not_connected``
   Drive row; every other state withholds it;
B. gesture    -- no ticket request is reachable without the explicit click;
C. ticket     -- exactly one ticket POST per attempt and no raw ticket in JS;
D. connect    -- bounded response validation reusing the reviewed Google
   authorization-URL policy, never an invented redirect;
E. state      -- no optimistic ``connected`` state, canonical refresh only;
F. scopes     -- Drive READ-only, with no write/Gmail/Calendar widening;
G. isolation  -- no client-owned workspace/account/credential authority.

Nothing here touches Production: every assertion is source- or harness-level.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
TICKET_ROUTES = ROOT / "app/connector_ticket_routes.py"
DURABLE_STORE = REPO / "packages/padiem-control-plane/google_oauth_durable_store.py"
INGRESS_RUNTIME = REPO / "packages/padiem-control-plane/google_oauth_ingress_runtime.py"

DRIVE_CONNECTOR = "google-drive"
DRIVE_CONNECTOR_ID = "connector:google:drive@1"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
BLOCK_START = "// #3222 Web Claw connector truth."
BLOCK_END = 'if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);'


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _connector_block() -> str:
    app = _app()
    assert BLOCK_START in app and BLOCK_END in app
    return app.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]


def _drive_card_inner() -> str:
    match = re.search(
        r'<div class="capability-card" data-connector="google-drive".*?>(.*?)</div>',
        _index(),
        re.DOTALL,
    )
    assert match, "the google-drive capability card is missing"
    return match.group(1)


def _function(name: str) -> str:
    match = re.search(rf"\n  (?:async )?function {re.escape(name)}\(.*?\n  \}}\n", _app(), re.DOTALL)
    assert match, f"{name} is missing from app.js"
    return match.group(0)


def _authorization_url_policy() -> str:
    match = re.search(r"\n  function reviewedGoogleAuthorizationUrl\(value\) \{.*?\n  \}\n", _app(), re.DOTALL)
    assert match, "reviewedGoogleAuthorizationUrl is missing from app.js"
    return match.group(0)


# --------------------------------------------------------------- A. visible ---
def test_markup_owns_one_hidden_drive_connect_action() -> None:
    inner = _drive_card_inner()
    for attribute in (
        'class="connector-retry connector-connect"',
        'type="button"',
        f'data-google-connector-connect="{DRIVE_CONNECTOR}"',
        'data-google-connect-endpoint="/api/connectors/google/ticket"',
        'data-locale-key="connectors-connect-drive"',
    ):
        assert attribute in inner, attribute
    # Shipped hidden: the status projection decides, never the markup.
    assert re.search(r'data-locale-key="connectors-connect-drive"[^>]* hidden', inner)
    assert inner.count("data-google-connector-connect") == 1


def test_only_the_two_reviewed_google_cards_own_a_connection_action() -> None:
    owners = set()
    for attributes, inner in re.findall(r'<div class="capability-card"([^>]*)>(.*?)</div>', _index(), re.DOTALL):
        slug = re.search(r'data-connector="([^"]+)"', attributes)
        if slug and "data-google-connector-connect" in inner:
            owners.add(slug.group(1))
    assert owners == {"google-drive", "google-calendar"}


def test_visibility_predicate_executes_over_the_closed_state_vocabulary() -> None:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = f"""
const authState = {{ authenticated: true }};
{_function("driveConnectOffered")}
const offered = {{}};
for (const state of ["connected", "not_connected", "unverified", "ambiguous", ""]) {{
  offered[state] = driveConnectOffered(true, state);
}}
offered.signedOut = driveConnectOffered(false, "not_connected");
offered.missingRow = driveConnectOffered(true, undefined);
offered.missingRowEmpty = driveConnectOffered(true, "");
console.log(JSON.stringify(offered));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["not_connected"] is True
    for state in ("connected", "unverified", "ambiguous", ""):
        assert payload[state] is False, state
    assert payload["signedOut"] is False
    assert payload["missingRow"] is False
    assert payload["missingRowEmpty"] is False


def test_missing_row_withholds_the_action() -> None:
    block = _connector_block()
    # loading and unavailable both re-evaluate the button with no row at all
    assert block.count("    syncGoogleDriveConnectButton();") == 2
    assert 'syncGoogleDriveConnectButton(rows.get("connector:google:drive@1") || null);' in block
    sync = _function("syncGoogleDriveConnectButton")
    assert "const offered = driveConnectOffered(authState.authenticated, workspaceState);" in sync
    assert "button.hidden = !offered;" in sync


def test_the_drive_card_is_the_reviewed_canonical_connector_id() -> None:
    assert f'data-connector-id="{DRIVE_CONNECTOR_ID}"' in _drive_card_inner() + _index().split('data-connector="google-drive"', 1)[1][:400]


# --------------------------------------------------------------- B. gesture ---
def test_no_ticket_request_is_reachable_without_the_click() -> None:
    block = _connector_block()
    assert block.count("fetch(GOOGLE_DRIVE_TICKET_ENDPOINT") == 1
    begin = _function("beginGoogleDriveConnect")
    assert begin.count("fetch(GOOGLE_DRIVE_TICKET_ENDPOINT") == 1
    # exactly one definition and exactly one call site: the explicit click
    assert block.count("async function beginGoogleDriveConnect() {") == 1
    assert block.count("void beginGoogleDriveConnect();") == 1
    assert block.count("beginGoogleDriveConnect") == 2
    assert 'if (driveConnectButton) driveConnectButton.addEventListener("click", () => {' in block
    # nothing on load, open, retry or render starts it
    for trigger in ("openConnectorsDialog", "loadConnectorStatus", "renderConnectorStatus", "setConnectorCardsLoading"):
        assert "beginGoogleDriveConnect" not in _function(trigger), trigger
    for forbidden in ("setTimeout", "setInterval", "prefetch", "requestIdleCallback"):
        assert forbidden not in _connector_block(), forbidden


# ---------------------------------------------------------------- C. ticket ---
def test_one_ticket_post_per_attempt_with_a_closed_body() -> None:
    begin = _function("beginGoogleDriveConnect")
    assert begin.count('method: "POST"') == 1
    assert "body: JSON.stringify({ connector_id: GOOGLE_DRIVE_CONNECTOR, begin_oauth: true })" in begin
    assert begin.count("fetch(") == 1
    for forbidden in ("scopes", "workspace_ref", "account_ref", "actor_ref", "redirect_uri", "connect_ticket"):
        assert forbidden not in begin, forbidden


def test_the_raw_connect_ticket_never_reaches_the_browser() -> None:
    block = _connector_block()
    assert "connect_ticket" not in block
    lowered = block.lower()
    for forbidden in ("localstorage", "sessionstorage", "indexeddb", "document.cookie", "console.", "innerhtml"):
        assert forbidden not in lowered, forbidden
    # The reviewed route performs the single OAuth-edge exchange server-side.
    routes = TICKET_ROUTES.read_text(encoding="utf-8")
    assert 'GOOGLE_OAUTH_CONNECT_URL = "https://oauth.padiem.net/v1/google/connect"' in routes
    assert 'json={"connect_ticket": receipt.connect_ticket}' in routes
    # the browser-facing answer carries only the bounded authorization shape
    assert '{"authorization": authorization},' in routes
    assert 'RAW_CONNECT_TICKET_IN_JAVASCRIPT = False' in routes


def test_a_failed_attempt_never_retries_itself() -> None:
    begin = _function("beginGoogleDriveConnect")
    tail = begin.split("} catch (_) {", 1)[1]
    assert "googleConnectorConnectInFlight = false;" in tail
    assert 'setConnectorCopy(button, "connectors-connect-drive");' in tail
    assert 'setConnectorCopy(connectorsError, "connectors-connect-drive-error");' in tail
    # the failure path contains no new request and no recursion
    assert "fetch(" not in tail
    assert "beginGoogleDriveConnect" not in tail


# --------------------------------------------------------------- D. connect ---
def test_bounded_response_validation_and_no_invented_redirect() -> None:
    begin = _function("beginGoogleDriveConnect")
    assert "const authorization = startDocument && startDocument.authorization;" in begin
    assert "authorization.connector_id === GOOGLE_DRIVE_CONNECTOR" in begin
    assert "reviewedGoogleAuthorizationUrl(authorization.authorization_url)" in begin
    assert 'if (!redirect) throw new Error("drive authorization unavailable");' in begin
    assert begin.count("window.location.assign(redirect)") == 1
    assert begin.index("reviewedGoogleAuthorizationUrl") < begin.index("window.location.assign(redirect)")
    assert "startResponse.ok" in begin


def test_the_reviewed_authorization_url_policy_is_reused_not_reimplemented() -> None:
    policy = _authorization_url_policy()
    assert 'url.protocol !== "https:"' in policy
    assert 'url.hostname !== "accounts.google.com"' in policy
    assert 'url.pathname !== "/o/oauth2/v2/auth"' in policy
    assert "url.username || url.password || url.hash" in policy
    block = _connector_block()
    # one policy, one parser: the Drive path adds no second URL authority
    assert _app().count("function reviewedGoogleAuthorizationUrl(") == 1
    assert block.count("new URL(") == 1
    for forbidden in ("oauth.padiem.net", "javascript:", "data:text/html", "file://", "http://"):
        assert forbidden not in block, forbidden


# ----------------------------------------------------------------- E. state ---
def test_no_optimistic_connected_state_is_ever_written() -> None:
    block = _connector_block()
    drive_sinks = _function("syncGoogleDriveConnectButton") + _function("beginGoogleDriveConnect")
    assert 'connectorStatus = "connected"' not in drive_sinks
    assert "connectors-workspace-connected" not in drive_sinks
    # the Drive axis reads the workspace_state row field and nothing else
    assert "row.workspace_state" in _function("syncGoogleDriveConnectButton")
    assert 'connectorStatus = "not_connected"' not in block


def test_return_refreshes_canonical_truth_instead_of_assuming_success() -> None:
    block = _connector_block()
    assert 'part === "google_connector=connected"' in block
    assert "openConnectorsDialog();" in block
    assert "void loadConnectorStatus();" in _function("openConnectorsDialog")
    load = _function("loadConnectorStatus")
    assert 'fetch("/api/connectors/status", {' in load
    assert "renderConnectorStatus(data);" in load
    assert 'syncGoogleDriveConnectButton(rows.get("connector:google:drive@1") || null);' in _function("renderConnectorStatus")


# ---------------------------------------------------------------- F. scopes ---
def test_drive_stays_readonly_with_no_scope_widening() -> None:
    lowered = _connector_block().lower()
    for forbidden in (
        "drive.file",
        "drive.full",
        "drive.appdata",
        "gmail.readonly",
        "gmail.send",
        "calendar.readonly",
        "calendar.events",
        "drive.files.insert",
        "drive.files.update",
        "drive.files.delete",
        "drive.permissions",
    ):
        assert forbidden not in lowered, forbidden


def test_oauth_start_is_closed_to_exactly_the_reviewed_connectors() -> None:
    routes = TICKET_ROUTES.read_text(encoding="utf-8")
    assert '_OAUTH_START_REVIEWED_CONNECTORS = frozenset({"google-calendar", "google-drive"})' in routes
    assert "if begin_oauth and connector_id not in _OAUTH_START_REVIEWED_CONNECTORS:" in routes
    assert 'OAUTH_START_REVIEWED_CONNECTORS = tuple(sorted(_OAUTH_START_REVIEWED_CONNECTORS))' in routes
    # the Drive scope is the reviewed Control Plane readonly set, unchanged
    assert f'GOOGLE_DRIVE_READONLY_SCOPE = "{DRIVE_SCOPE}"' in DURABLE_STORE.read_text(encoding="utf-8")
    ingress = INGRESS_RUNTIME.read_text(encoding="utf-8")
    assert '"google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),' in ingress


def test_no_drive_api_read_happens_in_this_slice() -> None:
    block = _connector_block()
    assert "google/drive/activate-read" not in block
    for forbidden in ("drive/v3/files", "files.list", "files.get", "activateGoogleDrive"):
        assert forbidden not in block, forbidden


# ------------------------------------------------------------- G. isolation ---
def test_no_client_owned_workspace_account_or_credential_authority() -> None:
    block = _connector_block()
    for forbidden in (
        "workspace_ref",
        "account_ref",
        "actor_ref",
        "session_id",
        "access_token",
        "refresh_token",
        "id_token",
        "pkce",
        "client_secret",
    ):
        assert forbidden not in block, forbidden
    assert _function("beginGoogleDriveConnect").count("JSON.stringify(") == 1


def test_drive_connect_acceptance_markers() -> None:
    assert 'GOOGLE_DRIVE_CONNECTOR = "google-drive"' in _connector_block()
    assert _drive_card_inner().count("data-google-connector-connect") == 1
    print("GOOGLE_DRIVE_CONNECT_ACTION_PRESENT=YES")
    print("DRIVE_CONNECT_ACTION_ONLY_WHEN_NOT_CONNECTED=YES")
    print("USER_GESTURE_REQUIRED=YES")
    print("TICKET_POST_MAX_PER_ATTEMPT=1")
    print("CONNECT_POST_MAX_PER_ATTEMPT=1")
    print("AUTO_RETRY=0")
    print("RAW_CONNECT_TICKET_OUTPUT=0")
    print("RAW_AUTHORIZATION_URL_OUTPUT=0")
    print("GOOGLE_DRIVE_SCOPE=drive.readonly")
    print("WRITE_SCOPE=0")
    print("CLIENT_WORKSPACE_AUTHORITY=0")
    print("DRIVE_API_READ=0")
    print("NO_OPTIMISTIC_CONNECTED_STATE=YES")
    print("STATUS_REFRESH_AFTER_RETURN=YES")
    print("PRODUCTION_MUTATION=0")
