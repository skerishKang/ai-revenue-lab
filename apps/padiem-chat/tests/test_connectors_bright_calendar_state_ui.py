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

DIALOG_ID = "connectorsDialog"
CALENDAR_CARD_ID = "connector:google:calendar@1"

NEW_LOCALE_KEYS = (
    "connectors-calendar-oauth-connected",
    "connectors-calendar-read-pending",
    "connectors-calendar-read-activating",
    "connectors-calendar-read-active",
    "connectors-calendar-read-failed",
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
    return app.split(marker, 1)[1].split(end, 1)[0]


def _pure_mapping_block() -> str:
    app = _app()
    start = "  function connectorSupportKey(value) {"
    end = "  function liveConnectorCards() {"
    assert start in app and end in app
    return start.lstrip() + app.split(start, 1)[1].split(end, 1)[0]


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


def test_all_safe_diagnostic_codes_are_mapped_in_the_app_source() -> None:
    block = _connector_block()
    for code, locale_key in SAFE_DIAGNOSTIC_CODES.items():
        assert f'"{code}"' in block, code
        assert f'"{locale_key}"' in block, locale_key


def test_app_js_is_locale_only_and_contains_no_korean_anywhere() -> None:
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
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = f"""
const authState = {{ authenticated: true }};
{_pure_mapping_block()}
const states = ["unknown", "activating", "active", "failed", "bogus", "constructor"].map(calendarReadStateKey);
const safeCodes = {json.dumps(list(SAFE_DIAGNOSTIC_CODES))};
const safeErrors = safeCodes.map(function (code) {{
  return calendarReadActivationErrorKey({{ calendarReadErrorCode: code }});
}});
const fallbackErrors = [
  {{ calendarReadErrorCode: "some_future_unreviewed_code" }},
  {{ calendarReadErrorCode: "calendar_activation_identity_unavailable" }},
  {{ calendarReadErrorCode: "constructor" }},
  {{}},
  null,
].map(calendarReadActivationErrorKey);
console.log(JSON.stringify({{ states, safeErrors, fallbackErrors }}));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["states"] == [
        "connectors-calendar-read-pending",
        "connectors-calendar-read-activating",
        "connectors-calendar-read-active",
        "connectors-calendar-read-failed",
        "connectors-calendar-read-pending",
        "connectors-calendar-read-pending",
    ]
    generic = "connectors-calendar-read-activation-error"
    # Every reviewed safe code maps to its own bounded copy.
    assert payload["safeErrors"] == [SAFE_DIAGNOSTIC_CODES[code] for code in SAFE_DIAGNOSTIC_CODES]
    # Unknown, not-in-scope, and hostile codes all fall back to the generic
    # OAuth-preserving message — nothing ever renders the raw server text.
    assert payload["fallbackErrors"] == [generic, generic, generic, generic, generic]


def test_app_state_machine_is_in_session_scope_and_fail_safe() -> None:
    block = _connector_block()
    assert 'let googleCalendarReadState = "unknown";' in block
    # The old request-receipt flags are gone; one closed state remains.
    assert "googleCalendarReadActivationDone" not in block
    assert "googleCalendarReadActivationInFlight" not in block
    assert 'googleCalendarReadState = "activating"' in block
    assert 'googleCalendarReadState = "active"' in block
    assert 'googleCalendarReadState = "failed"' in block
    # The READ line only shows on the connected OAuth axis, and hides otherwise.
    assert 'card.dataset.connectorStatus !== "connected"' in block
    assert "function renderCalendarReadState()" in block
    assert "renderCalendarReadState();" in block
    # The workspace copy becomes the OAuth fact only for a connected row,
    # and every other connector keeps the generic workspace copy.
    assert 'setConnectorCopy(calendarCard.querySelector("[data-connector-workspace]"), "connectors-calendar-oauth-connected");' in block
    assert 'row.workspace_state === "connected"' in block
    # Bounded code intake: the server's raw message text is never rendered.
    assert "data.error.code" in block
    assert "data.error.message" not in block
    assert "calendarReadActivationErrorKey(error)" in block


def test_no_secret_or_authority_material_enters_the_calendar_state_surface() -> None:
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
    block = _connector_block()
    assert block.count('method: "POST"') == 2, "exactly the status + activation endpoints"
    assert "googleCalendarReadActivationAfterConnectReturn = true" in block
    assert "await activateGoogleCalendarRead()" in block
    assert "connectorWorkspaceKey(row.workspace_state)" in block
