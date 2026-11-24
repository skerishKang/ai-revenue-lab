"""#5805 — the phone header is a light glass menu, not a full-width band.

The header stays in flow (sticky) and only the conversation scrolls. Contracts
are on parsed rules, including their media scope, rather than source spelling.
"""
from css_rules import declaration, find_rules_with_selector, rules_for_sheet

TOPBAR = ".app-shell .main-panel > .topbar"
MENU = TOPBAR + " #mobileMenu"
PHONE = "(max-width: 920px)"
POLISH = rules_for_sheet("interaction-polish.css")
TOKENS = rules_for_sheet("padiem-tokens.css")


def _rule(selector):
    matches = find_rules_with_selector(POLISH, selector)
    assert len(matches) == 1, (selector, matches)
    assert matches[0].media == PHONE
    return matches[0]


def _token_rule(selector):
    matches = [rule for rule in find_rules_with_selector(TOKENS, selector)
               if rule.media is None]
    assert len(matches) == 1, (selector, matches)
    return matches[0]


def test_the_phone_header_stays_in_flow_above_the_conversation() -> None:
    rule = _rule(TOPBAR)
    assert declaration(rule, "position") == "sticky"
    # #5804: fixed positioning left the menu under Edge's scroll offsets.
    assert declaration(rule, "position") != "fixed"
    assert declaration(rule, "min-height") == "56px"


def test_the_phone_header_is_not_a_painted_surface() -> None:
    rule = _rule(TOPBAR)
    assert declaration(rule, "background") == "transparent !important"
    assert declaration(rule, "border") == "0 !important"
    assert declaration(rule, "box-shadow") == "none !important"


def test_the_phone_header_keeps_the_safe_area_inset() -> None:
    assert declaration(_rule(TOPBAR), "padding-top") == "calc(6px + env(safe-area-inset-top, 0px))"


def test_the_menu_control_is_a_44px_glass_circle() -> None:
    rule = _rule(MENU)
    assert declaration(rule, "width") == "44px"
    assert declaration(rule, "height") == "44px"
    assert declaration(rule, "min-height") == "44px"
    assert declaration(rule, "border-radius") == "var(--radius-circle)"
    assert declaration(_token_rule(":root"), "--radius-circle") == "50%"
    for prop in ("backdrop-filter", "-webkit-backdrop-filter"):
        value = declaration(rule, prop)
        assert value is not None and "blur(14px)" in value.split()
    assert declaration(rule, "background") == "var(--glass)"
    assert declaration(rule, "border") == "1px solid var(--line)"
    assert declaration(rule, "color") == "var(--text)"


def test_the_glass_menu_stays_readable_on_the_dark_themes() -> None:
    rule = _rule(MENU)
    assert declaration(rule, "background") == "var(--glass)"
    assert declaration(rule, "color") == "var(--text)"
    themes = rules_for_sheet("padiem-themes.css")
    glass = rules_for_sheet("padiem-glass.css")
    # The palette lives in the token sheet; component rules remain in each theme.
    for theme in ("dark", "cinematic", "padiem-home"):
        selector = f'html[data-theme="{theme}"]'
        token_rule = _token_rule(selector)
        assert declaration(token_rule, "--glass") is not None, theme
        assert declaration(token_rule, "--panel") is not None, theme
        assert declaration(token_rule, "--text") is not None, theme
        if theme != "padiem-home":
            assert find_rules_with_selector(themes, selector), theme
    selector = 'html[data-theme="padiem-glass"]'
    assert find_rules_with_selector(glass, selector)
    assert declaration(_token_rule(selector), "--glass") is not None


def test_the_glass_rules_are_scoped_to_the_phone_width() -> None:
    """Nothing here leaks into the wide layout the desktop already uses."""
    for selector in (TOPBAR, MENU):
        matches = find_rules_with_selector(POLISH, selector)
        assert len(matches) == 1
        assert matches[0].media == PHONE
