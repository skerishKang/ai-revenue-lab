"""#5805 — the phone header is a light glass menu, not a full-width band.

The bar still has to stay at the top of the visual viewport on Android Edge
(#5804), so the layout contract is unchanged: the shell owns the height, the
header stays in flow (sticky), and only the conversation scrolls. What changes
is the surface — the bar no longer paints a background, and the one control
carries a translucent circular glass tone with a 44px target and a safe-area
inset.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLISH_CSS = (ROOT / "static" / "interaction-polish.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """The declaration block that follows `selector`, or empty when absent."""

    start = POLISH_CSS.find(selector)
    if start < 0:
        return ""
    brace = POLISH_CSS.find("{", start)
    end = POLISH_CSS.find("}", brace)
    return POLISH_CSS[brace + 1:end]


def test_the_phone_header_stays_in_flow_above_the_conversation() -> None:
    rule = _rule(".app-shell .main-panel > .topbar {")
    assert "position: sticky !important" in rule
    # #5804 must not come back: a fixed bar is what left the menu under Edge's
    # own scroll offsets.
    assert "position: fixed" not in rule
    assert "min-height: 56px" in rule


def test_the_phone_header_is_not_a_painted_surface() -> None:
    rule = _rule(".app-shell .main-panel > .topbar {")
    assert "background: transparent !important" in rule
    assert "border: 0 !important" in rule
    assert "box-shadow: none !important" in rule


def test_the_phone_header_keeps_the_safe_area_inset() -> None:
    rule = _rule(".app-shell .main-panel > .topbar {")
    assert "env(safe-area-inset-top, 0px)" in rule


def test_the_menu_control_is_a_44px_glass_circle() -> None:
    rule = _rule(".app-shell .main-panel > .topbar #mobileMenu {")
    assert "width: 44px !important" in rule
    assert "height: 44px !important" in rule
    assert "min-height: 44px" in rule
    assert "border-radius: 50% !important" in rule
    assert "backdrop-filter: blur(14px)" in rule
    assert "-webkit-backdrop-filter: blur(14px)" in rule
    assert "rgba(255, 255, 255, .58)" in rule


def test_the_glass_menu_stays_readable_on_the_dark_themes() -> None:
    rule = _rule('html[data-theme="dark"] .app-shell .main-panel > .topbar #mobileMenu,')
    assert "rgba(255, 255, 255, .16) !important" in rule
    assert "color: #eef6fb !important" in rule
    assert 'html[data-theme="cinematic"]' in POLISH_CSS


def test_the_glass_rules_are_scoped_to_the_phone_width() -> None:
    """Nothing here leaks into the wide layout the desktop already uses."""

    media = POLISH_CSS.rfind("@media (max-width: 920px)", 0, POLISH_CSS.find(
        ".app-shell .main-panel > .topbar {"))
    assert media >= 0
    assert POLISH_CSS.count(".app-shell .main-panel > .topbar {") == 1
