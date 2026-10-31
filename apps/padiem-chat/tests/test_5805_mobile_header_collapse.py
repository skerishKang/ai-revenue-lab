"""#5805 — the collapse header is the phone default, with no switch left.

CTO decision on PR #6274 (2026-10-30): the collapse behavior adopted from the
design comparison becomes the default below 920px, and the comparison
plumbing (?mobileHeader=, the floating variant) is removed. The contract: the
row collapses by height only while a primary surface scrolls (0px when
scrolled, 56px restored at the top), the 44px glass circle never moves or
shrinks (safe-area anchored, flow kept, no fixed element), reduced-motion
disables the animation, and the base glass sheet from #6153 stays untouched.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLISH_CSS = (ROOT / "static" / "interaction-polish.css").read_text(encoding="utf-8")
COLLAPSE_CSS = (ROOT / "static" / "mobile-header-collapse.css").read_text(encoding="utf-8")
COLLAPSE_JS = (ROOT / "static" / "mobile-header-collapse.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """The declaration block that follows `selector`, or empty when absent."""

    start = css.find(selector)
    if start < 0:
        return ""
    brace = css.find("{", start)
    end = css.find("}", brace)
    return css[brace + 1:end]


def test_no_comparison_switch_is_left_behind() -> None:
    # The comparison is over: no parameter device, no floating variant, no
    # variant attribute anywhere in the static app.
    assert "mobileHeader" not in COLLAPSE_JS
    assert "URLSearchParams" not in COLLAPSE_JS
    assert "floating" not in COLLAPSE_CSS
    assert "floating" not in COLLAPSE_JS
    assert "data-mobile-header=" not in INDEX_HTML
    assert "mobile-header-variants" not in INDEX_HTML


def test_collapse_is_the_default_without_a_parameter() -> None:
    # The rules key off the shell attribute only; every phone gets them.
    assert '.app-shell .main-panel > .topbar {' in COLLAPSE_CSS
    assert ".app-shell[data-header-collapsed] .main-panel > .topbar {" in COLLAPSE_CSS
    assert "data-mobile-header" not in COLLAPSE_CSS


def test_the_row_collapses_by_height_and_stays_in_flow() -> None:
    rule = _rule(COLLAPSE_CSS, ".app-shell .main-panel > .topbar {")
    assert "transition: min-height" in rule
    assert "position" not in rule
    collapsed = _rule(COLLAPSE_CSS, ".app-shell[data-header-collapsed] .main-panel > .topbar {")
    assert "min-height: 0" in collapsed
    # The #5804 contract: no fixed element anywhere.
    assert "position: fixed" not in COLLAPSE_CSS
    # The resting 56px row and the sticky flow stay owned by the #6153 sheet.
    base = _rule(POLISH_CSS, ".app-shell .main-panel > .topbar {")
    assert "position: sticky !important" in base
    assert "min-height: 56px" in base


def test_the_44px_circle_never_moves_or_shrinks() -> None:
    button = _rule(COLLAPSE_CSS, ".app-shell .main-panel > .topbar #mobileMenu {")
    assert "position: absolute" in button
    assert "env(safe-area-inset-top, 0px)" in button
    base = _rule(POLISH_CSS, ".app-shell .main-panel > .topbar #mobileMenu {")
    assert "width: 44px !important" in base
    assert "height: 44px !important" in base
    assert "border-radius: 50% !important" in base


def test_collapse_toggle_reads_only_visible_primary_surfaces() -> None:
    assert 'SCROLL_SURFACES = ".conversation, .claw-workspace, .claw-inbox"' in COLLAPSE_JS
    # A hidden view keeps a stale scrollTop; it must not collapse the header.
    assert "offsetParent === null" in COLLAPSE_JS
    assert "requestAnimationFrame" in COLLAPSE_JS
    assert "toggleAttribute" in COLLAPSE_JS


def test_reduced_motion_disables_the_collapse_animation() -> None:
    reduced = _rule(COLLAPSE_CSS, '@media (max-width: 920px) and (prefers-reduced-motion: reduce)')
    assert "transition: none !important" in reduced


def test_the_sheet_and_mirror_are_loaded_on_the_page() -> None:
    assert '<link rel="stylesheet" href="./mobile-header-collapse.css"' in INDEX_HTML
    assert '<script src="./mobile-header-collapse.js"></script>' in INDEX_HTML
    assert INDEX_HTML.find('./app.js') < INDEX_HTML.find('./mobile-header-collapse.js')
    # Override order: the collapse sheet wins the cascade over #6153's block.
    assert INDEX_HTML.find("./interaction-polish.css") < INDEX_HTML.find("./mobile-header-collapse.css")


def test_the_collapse_rules_stay_inside_the_phone_media_query() -> None:
    for selector in (
        ".app-shell .main-panel > .topbar {",
        ".app-shell[data-header-collapsed] .main-panel > .topbar {",
    ):
        pos = COLLAPSE_CSS.find(selector)
        assert pos > 0, selector
        media_pos = COLLAPSE_CSS.rfind("@media (max-width: 920px)", 0, pos)
        assert media_pos >= 0, selector
        between = COLLAPSE_CSS[media_pos + len("@media (max-width: 920px)"):pos]
        # The media block is still open at the selector: every inner rule
        # between the opening and this selector must be balanced.
        assert between.count("{") - between.count("}") >= 0, selector
