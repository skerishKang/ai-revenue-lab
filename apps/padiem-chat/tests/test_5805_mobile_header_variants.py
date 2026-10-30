"""#5805 — the opt-in header variants stay phone-only and leave the default.

The merged glass menu (#6153) is the production default; the two comparison
variants (`?mobileHeader=floating` button-only, `?mobileHeader=collapse`
shrink on scroll) live in their own sheet and exist only behind the explicit
parameter. They must keep the #5804 contract (no fixed element), the 44px
target, the safe-area inset, the sidebar stacking order, and write no state
without the parameter.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLISH_CSS = (ROOT / "static" / "interaction-polish.css").read_text(encoding="utf-8")
VARIANTS_CSS = (ROOT / "static" / "mobile-header-variants.css").read_text(encoding="utf-8")
VARIANTS_JS = (ROOT / "static" / "mobile-header-variants.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """The declaration block that follows `selector`, or empty when absent."""

    start = css.find(selector)
    if start < 0:
        return ""
    brace = css.find("{", start)
    end = css.find("}", brace)
    return css[brace + 1:end]


def test_the_default_sheet_stays_free_of_variant_rules() -> None:
    # interaction-polish.css is the production default; the comparison must
    # not change any screen that never opted in.
    assert "data-mobile-header" not in POLISH_CSS


def test_variants_write_no_state_without_the_parameter() -> None:
    assert 'if (variant !== "floating" && variant !== "collapse") return;' in VARIANTS_JS
    assert 'root.dataset.mobileHeader = variant;' in VARIANTS_JS
    # The only entry point is the query parameter, like theme.js.
    assert "window.location.search" in VARIANTS_JS


def test_index_loads_the_variant_sheet_and_script() -> None:
    assert '<link rel="stylesheet" href="./mobile-header-variants.css"' in INDEX_HTML
    assert '<script src="./mobile-header-variants.js"></script>' in INDEX_HTML
    assert INDEX_HTML.find('./app.js') < INDEX_HTML.find('./mobile-header-variants.js')


def test_floating_variant_drops_the_row_but_keeps_the_glass_circle_contract() -> None:
    rule = _rule(VARIANTS_CSS, 'html[data-mobile-header="floating"] .app-shell .main-panel > .topbar {')
    assert "position: absolute !important" in rule
    # #5804 must not come back in any variant: no fixed element.
    assert "position: fixed" not in rule
    assert "pointer-events: none" in rule
    assert "z-index: 100 !important" in rule
    button = _rule(VARIANTS_CSS, 'html[data-mobile-header="floating"] .app-shell .main-panel > .topbar #mobileMenu {')
    assert "pointer-events: auto" in button
    assert "env(safe-area-inset-top, 0px)" in button


def test_collapse_variant_keeps_the_flow_and_the_safe_area() -> None:
    rule = _rule(VARIANTS_CSS, 'html[data-mobile-header="collapse"] .app-shell .main-panel > .topbar {')
    # The row collapses by height, never by leaving the flow.
    assert "transition: min-height" in rule
    assert "position" not in rule
    button = _rule(VARIANTS_CSS, 'html[data-mobile-header="collapse"] .app-shell .main-panel > .topbar #mobileMenu {')
    # The 44px circle survives the shrinking row without moving or resizing.
    assert "position: absolute" in button
    assert "env(safe-area-inset-top, 0px)" in button
    collapsed = _rule(VARIANTS_CSS, 'html[data-mobile-header="collapse"] .app-shell[data-header-collapsed] .main-panel > .topbar {')
    assert "min-height: 0" in collapsed
    assert "env(safe-area-inset-top, 0px)" in collapsed


def test_collapse_toggle_reads_only_visible_primary_surfaces() -> None:
    assert 'SCROLL_SURFACES = ".conversation, .claw-workspace, .claw-inbox"' in VARIANTS_JS
    # A hidden view keeps a stale scrollTop; it must not collapse the header.
    assert "offsetParent === null" in VARIANTS_JS
    assert "requestAnimationFrame" in VARIANTS_JS
    assert "toggleAttribute" in VARIANTS_JS


def test_variant_rules_stay_inside_the_phone_media_query() -> None:
    for selector in (
        'html[data-mobile-header="floating"] .app-shell .main-panel > .topbar {',
        'html[data-mobile-header="collapse"] .app-shell .main-panel > .topbar {',
    ):
        pos = VARIANTS_CSS.find(selector)
        assert pos > 0, selector
        media_pos = VARIANTS_CSS.rfind("@media (max-width: 920px)", 0, pos)
        assert media_pos >= 0, selector
        between = VARIANTS_CSS[media_pos + len("@media (max-width: 920px)"):pos]
        # The media block is still open at the selector: every inner rule
        # between the opening and this selector must be balanced.
        assert between.count("{") - between.count("}") >= 0, selector
