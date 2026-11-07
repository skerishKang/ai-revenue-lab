"""UI polish contract: auth-dialog AA contrast and the unverified card copy.

The polish layer (padiem-chat-ui-polish.css) is the only sheet allowed to
correct the frozen theme sheets. These tests pin the two 2026-11-08 fixes:
the auth panel ink stays ≥4.5:1 (WCAG AA) against every pixel of its own
surface in both themes, and the connectors page renders the unverified
workspace rows with the reviewed "준비 중" copy instead of the failure line.
"""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"


def _relative_luminance(hex_color: str) -> float:
    def channel(pair: str) -> float:
        value = int(pair, 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (hex_color[i:i + 2] for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rule_block(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, f"missing polish rule: {selector}"
    return match.group(1)


def test_polish_layer_keeps_auth_panel_ink_above_aa():
    css = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
    for selector in (
        'html[data-theme="padiem-glass"] .auth-panel',
        'html[data-theme="dark"] .auth-panel',
    ):
        block = _rule_block(css, selector)
        colors = re.findall(r"#[0-9a-fA-F]{6}\b", block)
        assert len(colors) >= 2, (selector, colors)
        ink = colors[-1]  # the color declaration is the last hex in the block
        for surface in colors[:-1]:
            ratio = _contrast(ink, surface)
            assert ratio >= 4.5, (selector, ink, surface, round(ratio, 2))


def test_polish_layer_is_linked_after_the_frozen_sheets():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    polish = html.find('href="./padiem-chat-ui-polish.css"')
    frozen = html.find('href="./history.css"')
    assert polish != -1 and frozen != -1 and frozen < polish


def test_unverified_workspace_copy_is_preparing_ko_and_coming_soon_en():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert '"connectors-workspace-unverified": "준비 중"' in locale
    assert '"connectors-workspace-unverified": "Coming soon"' in locale
    # The failure line stays reserved for real failures.
    assert '"connectors-status-unavailable": "확인 실패 · 다시 시도"' in locale


def test_unverified_rows_render_through_the_reviewed_key():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # renderConnectorStatus writes the workspace line from the row state and
    # connectorWorkspaceKey routes the unverified state to the reviewed key.
    assert 'card.dataset.connectorStatus = String(row.workspace_state || "unverified")' in app
    assert '"connectors-workspace-unverified"' in app


def test_connectors_page_card_ids_match_the_client_status_set():
    """A drifted connector id makes rows go missing, which renders the real
    failure line on both card lines (#7100-era failure shape)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    card_ids = set(re.findall(r'data-connector-id="([^"]+)"', html))
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    set_body = app.split("CONNECTOR_STATUS_IDS = new Set([", 1)[1].split("]);", 1)[0]
    client_ids = set(re.findall(r'"(connector:[^"]+)"', set_body))
    assert card_ids == client_ids, (sorted(card_ids - client_ids), sorted(client_ids - card_ids))
