"""#5555 — the Connectors screen reads as one page.

The representative's review of the live screen found a duplicated header, a
wall of top copy, and cards that mixed a capability with a connection state.
These are source contracts for the screen, so a later change cannot quietly
bring the old shape back:

- ONE_PAGE_NAME: the page name is the English ``Connectors`` in both locales,
  and the view header does not repeat it in a second language.
- SHORT_HEADER: the header keeps one short line, and the long explanation
  lives in a disclosure.
- STATUS_BEFORE_CAPABILITY: on every card the connection state is the first
  line after the name and the supported capability is the second, so a
  supported capability is never read as a connected state.
- ONE_STATUS_VOCABULARY: connected / connecting / not connected / could not
  verify / preparing, and the card never claims a state the server did not
  prove.
- GRID: two columns on a desktop, one column on a phone, and every card keeps
  the same padding, the same action row and a 44px action target.
- NO_BACKEND_CHANGE: the screen still reuses the existing endpoints, the
  existing owner-scoped readback and the existing connection actions.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
CONNECTOR_JS = (STATIC / "claw-connector-management.js").read_text(encoding="utf-8")
HOME_JS = (STATIC / "claw-home-choices.js").read_text(encoding="utf-8")
CSS = (STATIC / "capability-nav.css").read_text(encoding="utf-8")


def _card(anchor: str) -> str:
    start = HTML.index(anchor)
    end = HTML.index("</div>", start)
    return HTML[start:end]


# ── the page name ──────────────────────────────────────────────────────────


def test_the_page_name_is_the_english_connectors_in_both_locales():
    assert '"connectors-title": "Connectors"' in LOCALE
    assert '"connectors-title": "커넥터"' not in LOCALE
    # The standalone page title carries the same name.
    view = HTML[HTML.index('id="connectorsView"'):HTML.index('id="connectorsViewBody"')]
    assert 'data-locale-key="connectors-title">Connectors<' in view


def test_no_korean_connector_word_is_left_in_a_display_string():
    """#5555: the page name is the English ``Connectors`` everywhere."""
    for name, text in (
        ("index.html", HTML),
        ("locale.js", LOCALE),
        ("claw-connector-management.js", CONNECTOR_JS),
    ):
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("//", "/*", "*", "<!--", "#")):
                continue
            assert "커넥터" not in stripped, f"{name}:{number}: {stripped[:80]}"
    view = HTML[HTML.index('id="connectorsView"'):HTML.index('id="connectorsViewBody"')]
    # The rendered header, not the source comment that explains the change.
    rendered = re.sub(r"<!--.*?-->", "", view, flags=re.DOTALL)
    assert "connectors-kicker" not in rendered
    assert "Padiem Connectors" not in rendered


def test_the_dialog_title_uses_the_same_english_name():
    dialog = HTML[HTML.index('id="connectorsDialog"'):HTML.index('id="connectorsLiveStatus"')]
    assert 'data-locale-key="connectors-title">Connectors<' in dialog
    assert "커넥터" not in dialog


# ── the header copy ────────────────────────────────────────────────────────


def test_the_header_keeps_one_short_line_and_moves_the_long_text_into_a_details():
    view = HTML[HTML.index('id="connectorsView"'):HTML.index('id="connectorsViewBody"')]
    assert 'data-locale-key="connectors-note">연결된 서비스와 기기를 관리합니다.<' in view
    assert 'data-locale-key="connectors-note-details"' in view
    assert 'data-locale-key="connectors-note-toggle"' in view
    assert "<details" in view
    # The long sentence is no longer the header line itself.
    assert 'data-locale-key="connectors-note">읽기 지원 여부와' not in view
    assert '"connectors-note": "연결된 서비스와 기기를 관리합니다."' in LOCALE
    assert '"connectors-note-details"' in LOCALE
    assert '"connectors-note-toggle"' in LOCALE


# ── the card information order ──────────────────────────────────────────────


def test_every_service_card_shows_the_state_before_the_capability():
    for anchor in (
        'data-connector-id="connector:google:drive@1"',
        'data-connector-id="connector:google:gmail@1"',
        'data-connector-id="connector:telegram:bot@1"',
        'data-connector-id="connector:slack:workspace@1"',
        'data-connector-id="connector:google:calendar@1"',
    ):
        card = _card(anchor)
        state = card.index("data-connector-workspace")
        capability = card.index("data-connector-support")
        assert state < capability, anchor
        # The name still comes first.
        assert card.index("<strong") < state, anchor


def test_the_computer_card_separates_its_state_from_its_setup_note():
    card = _card('id="connectorComputerCard"')
    assert card.index('id="clawComputerLiveStatus"') < card.index(
        'data-locale-key="claw-home-computer-setup"'
    )
    # The setup note is a capability line, not a state line.
    assert 'class="capability-read" data-locale-key="claw-home-computer-setup"' in card


# ── one status vocabulary ──────────────────────────────────────────────────


def test_the_github_card_uses_the_shared_status_vocabulary():
    assert 'tr("연결됨","Connected")' in CONNECTOR_JS
    assert 'tr("미연결","Not connected")' in CONNECTOR_JS
    assert 'tr("확인 불가","Could not verify")' in CONNECTOR_JS
    # The old wording mixed the state with the switch position.
    assert "연결됨 · ON" not in CONNECTOR_JS
    assert "연결 상태 확인 불가" not in CONNECTOR_JS


def test_a_failed_status_read_is_never_reported_as_not_connected():
    # #5553: the card reads the ONE shared state, and the shared
    # classification keeps "could not verify" separate from "not connected".
    shared = (STATIC / "claw-connection-state.js").read_text(encoding="utf-8")
    assert "컴퓨터 연결 상태를 확인하지 못했습니다." in HOME_JS
    assert "The computer connection status could not be confirmed." in HOME_JS
    assert 'return STATE.UNAVAILABLE' in shared
    # The "no approved computers" wording stays a different state.
    assert "아직 승인된 컴퓨터가 없습니다." not in HOME_JS


def test_the_computer_state_comes_from_the_existing_device_directory_reader():
    # #5553: the device directory module stays the ONLY reader of the
    # canonical endpoint, and the card reads what it publishes.
    assert '"/api/claw/local-access/devices"' in (
        STATIC / "claw-device-manager.js"
    ).read_text(encoding="utf-8")
    assert "/api/claw/local-access/devices" not in HOME_JS
    assert "PadiemComputerConnectionState" in HOME_JS
    assert "padiem:computer-connection" in HOME_JS


# ── the grid and the action row ────────────────────────────────────────────


def test_the_grid_is_two_columns_on_a_desktop_and_one_on_a_phone():
    assert re.search(r"\.capability-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,", CSS)
    assert re.search(r"@media \(max-width: 720px\)\s*\{[^}]*\.capability-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)", CSS, re.DOTALL)


def test_every_card_keeps_the_same_padding_and_a_44px_action_target():
    assert re.search(r"\.capability-card\s*\{[^}]*padding:\s*16px", CSS)
    assert re.search(r"\.capability-card \.connector-retry\s*\{[^}]*min-height:\s*44px", CSS)


def test_the_glass_tokens_and_the_existing_status_colours_are_reused():
    # No new palette: the existing tokens and the existing state selectors stay.
    assert "var(--accent-strong, #2f6f99)" in CSS
    assert '.capability-card[data-connector-status="connected"] .capability-workspace' in CSS
    assert "padiem-glass" in CSS


# ── the backend is untouched ────────────────────────────────────────────────


def test_no_connector_endpoint_or_permission_contract_changed():
    # The screen still uses the existing connection endpoints only.
    assert '"/api/connectors/github/status"' in CONNECTOR_JS
    assert '"/api/connectors/github/disconnect"' in CONNECTOR_JS
    assert '"/api/connectors/google/drive/disconnect"' in CONNECTOR_JS
