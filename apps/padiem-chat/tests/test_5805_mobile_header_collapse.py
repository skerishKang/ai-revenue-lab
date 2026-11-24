"""#5805 — default phone header collapse, without the comparison switch.

Verify CSS declarations and media scope, parsed asset order, and actual scroll
behavior of the shipped JavaScript in a deterministic Node VM.
"""
from pathlib import Path
import subprocess

from css_rules import declaration, find_rules_with_selector, rules_for_sheet
from _support.html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[1]
POLISH = rules_for_sheet("interaction-polish.css")
COLLAPSE = rules_for_sheet("mobile-header-collapse.css")
TAGS = tags_for_page("index.html")
TOPBAR = ".app-shell .main-panel > .topbar"
MENU = TOPBAR + " #mobileMenu"
COLLAPSED = ".app-shell[data-header-collapsed] .main-panel > .topbar"
PHONE = "(max-width: 920px)"
REDUCED = PHONE + " and (prefers-reduced-motion: reduce)"


def _rule(rules, selector, media):
    matches = [rule for rule in find_rules_with_selector(rules, selector)
               if rule.media == media]
    assert len(matches) == 1, (selector, media, matches)
    return matches[0]


def _run_vm(case):
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "fixtures" / "mobile_header_collapse_vm.cjs"),
         str(ROOT / "static" / "mobile-header-collapse.js"), case],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_no_comparison_switch_is_left_behind() -> None:
    # No variant styles, markup or query-parameter dependency.
    for rule in COLLAPSE:
        fields = [*rule.selectors, *rule.declarations, *rule.declarations.values(),
                  rule.media or ""]
        assert all("floating" not in field and "data-mobile-header" not in field
                   for field in fields)
    for _, attrs in TAGS:
        assert "data-mobile-header" not in attrs
        assert all("mobile-header-variants" not in (value or "") for value in attrs.values())
    _run_vm("comparison")


def test_collapse_is_the_default_without_a_parameter() -> None:
    _rule(COLLAPSE, TOPBAR, PHONE)
    _rule(COLLAPSE, COLLAPSED, PHONE)
    assert all("data-mobile-header" not in selector
               for rule in COLLAPSE for selector in rule.selectors)


def test_the_row_collapses_by_height_and_stays_in_flow() -> None:
    rule = _rule(COLLAPSE, TOPBAR, PHONE)
    transition = declaration(rule, "transition")
    assert transition is not None and transition.split()[0] == "min-height"
    assert declaration(rule, "position") is None
    assert declaration(_rule(COLLAPSE, COLLAPSED, PHONE), "min-height") == "0"
    # #5804: no fixed element in any rule on this sheet.
    assert all((declaration(rule, "position") or "").split()[:1] != ["fixed"]
               for rule in COLLAPSE)
    base = _rule(POLISH, TOPBAR, PHONE)
    assert declaration(base, "position") == "sticky"
    assert declaration(base, "min-height") == "56px"


def test_the_44px_circle_never_moves_or_shrinks() -> None:
    button = _rule(COLLAPSE, MENU, PHONE)
    assert declaration(button, "position") == "absolute"
    assert declaration(button, "top") == "calc(env(safe-area-inset-top, 0px) + 6px)"
    base = _rule(POLISH, MENU, PHONE)
    assert declaration(base, "width") == "44px"
    assert declaration(base, "height") == "44px"
    assert declaration(base, "border-radius") == "var(--radius-circle)"
    tokens = rules_for_sheet("padiem-tokens.css")
    assert declaration(_rule(tokens, ":root", None), "--radius-circle") == "50%"


def test_collapse_toggle_reads_only_visible_primary_surfaces() -> None:
    _run_vm("scroll")


def test_reduced_motion_disables_the_collapse_animation() -> None:
    assert declaration(_rule(COLLAPSE, TOPBAR, REDUCED), "transition") == "none !important"


def test_the_sheet_and_mirror_are_loaded_on_the_page() -> None:
    styles = [attrs.get("href") for tag, attrs in TAGS
              if tag == "link" and "stylesheet" in (attrs.get("rel") or "").split()]
    scripts = [attrs.get("src") for tag, attrs in TAGS if tag == "script"]
    # Exact asset identities and order, independent of tag formatting.
    assert styles.count("./mobile-header-collapse.css") == 1
    assert scripts.count("./mobile-header-collapse.js") == 1
    assert scripts.index("./app.js") < scripts.index("./mobile-header-collapse.js")
    assert styles.index("./interaction-polish.css") < styles.index("./mobile-header-collapse.css")


def test_the_collapse_rules_stay_inside_the_phone_media_query() -> None:
    for selector, expected in ((TOPBAR, {PHONE, REDUCED}), (COLLAPSED, {PHONE}),
                               (MENU, {PHONE})):
        rules = find_rules_with_selector(COLLAPSE, selector)
        assert {rule.media for rule in rules} == expected, selector
        assert len(rules) == len(expected), selector
