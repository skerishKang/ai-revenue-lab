"""Theme surface contracts — parsed values, not source spelling (#8060 6차)."""
from __future__ import annotations

from pathlib import Path

from _support import theme_static as ts
from css_rules import find_rules_with_selector

ROOT = ts.ROOT

VALID_THEMES = ["light", "dark", "cinematic", "padiem-home"]
GLASS = "padiem-glass"
HOME = "padiem-home"
THEME_JS = ts.theme_js()
THEME_INIT = ts.theme_init_js()
THEME_RULES = ts.theme_rules()
TOKEN_BLOCKS = ts.theme_token_blocks()
JS_CONST = ts.js_constants(THEME_JS)

FORBIDDEN_STORAGE = {"localStorage", "sessionStorage", "indexedDB", "cookieStore", "CacheStorage"}
FORBIDDEN_EVAL = {"eval", "innerHTML", "B14"}
MASK_MODES = ["auto", "on", "off"]
GLASS_VARIANTS = ["female", "male"]
REQUIRED_TOKENS = {"--bg", "--text", "--muted", "--accent", "--panel", "--sidebar", "--gold",
                   "--line", "--input-border-strong", "--focus-ring"}
BLOCK_TOKENS = {"--bg", "--text", "--muted", "--panel", "--sidebar"}
PICKER_RULES = {"theme-picker", "theme-option"}
LIGHT_BG = "#f8f8fb"
HOME_BG = "#e6e9ee"
VIOLET = "#6557e8"
BLUE = "#88c9ff"
GOLD = "#efc984"
BRIGHT_CSS = {"light": THEME_RULES, "padiem-home": THEME_RULES}
CHAT_STATE = '[data-state="chat"]'
IS_CHAT_CLAW = ':is([data-state="chat"],[data-state="claw"])'
SUBTREE = [
    ".assistant-content .rich-response",
    ".assistant-content .rich-response .rich-response-paragraph",
    ".assistant-content .rich-response .rich-response-heading",
    ".assistant-content .rich-response .rich-response-list",
    ".assistant-content .rich-response .rich-response-quote",
    ".answer-action",
    ".reference-note",
]
BRIGHT_TOKEN = {"light": "#1e1e22", "padiem-home": "#1e2a3a"}


def test_theme_files_exist():
    assert (ROOT / "static/padiem-themes.css").is_file()
    assert (ROOT / "static/theme.js").is_file()
    assert len(ts.rules_for_sheet("padiem-themes.css")) > 0
    assert len(THEME_JS) > 500


def test_html_contains_inline_theme_init_and_no_flash():
    tags = ts.index_tags()
    srcs = ts.script_srcs(tags)
    hrefs = ts.stylesheet_hrefs(tags)
    order = ts.asset_order(tags)
    assert "./theme-init.js" in srcs
    assert "./padiem-themes.css" in hrefs
    assert "./theme.js" in srcs
    # theme-init must be before first CSS for no-flash, and themes.css last.
    assert order.index("./theme-init.js") < order.index("./styles.css")
    assert order.index("./padiem-themes.css") > order.index("./padiem-cinematic-workspace.css")
    # no inline script violating CSP
    assert not ts.has_inline_script(tags)
    # theme-init must use URL param (no browser storage) and the canonical Glass fallback.
    init_ids = ts.identifiers(THEME_INIT)
    assert "URLSearchParams" in init_ids
    assert GLASS in ts.array_literal(THEME_INIT, "T")
    assert ts.init_fallback(THEME_INIT) == GLASS
    assert not (FORBIDDEN_STORAGE & init_ids)
    # theme.js before app.js to ensure theme set before app boot.
    assert srcs.index("./theme.js") < srcs.index("./app.js")


def test_html_theme_picker_enumeration_and_accessibility():
    tags = ts.index_tags()
    theme_values = {attrs.get("data-theme-value") for _tag, attrs in tags
                    if attrs.get("data-theme-value")}
    roles = {attrs.get("role") for _tag, attrs in tags if attrs.get("role")}
    aria = {attrs.get("aria-label") for _tag, attrs in tags if attrs.get("aria-label")}
    labels = [attrs.get("data-theme-value") for _tag, attrs in tags
              if attrs.get("data-theme-value")]
    pressed = {attrs.get("aria-pressed") for _tag, attrs in tags
               if "aria-pressed" in attrs}
    assert set(VALID_THEMES) <= theme_values
    assert "group" in roles
    assert "테마 선택" in aria
    assert len(labels) == 4
    assert set(VALID_THEMES) == set(labels)
    assert "false" in pressed


def test_theme_js_enumeration_and_persistence():
    ids = ts.identifiers(THEME_JS)
    assert set(VALID_THEMES) <= set(ts.array_literal(THEME_JS, "VALID"))
    assert "URLSearchParams" in ids
    assert "replaceState" in ids
    assert not (FORBIDDEN_STORAGE & ids)
    assert not ts.has_member(THEME_JS, "document", "cookie")
    assert "prefers-color-scheme" in THEME_JS
    assert "matchMedia" in ids
    assert "getSystemFallback" in ids
    assert "getUrlTheme" in ids
    assert "reload" not in ids
    assert not (FORBIDDEN_EVAL & ids)
    const_keys = set()
    for name, entries in JS_CONST.items():
        const_keys.update(entries)
    assert "data-theme" in THEME_JS
    assert "aria-pressed" in THEME_JS
    assert "color-scheme" in THEME_JS
    assert "theme-color" in THEME_JS


def test_themes_css_extensibility_and_tokens():
    theme_selectors = set(ts.selectors(THEME_RULES))
    assert all(f'html[data-theme="{t}"]' in theme_selectors for t in VALID_THEMES)
    token_text = (ROOT / "static/padiem-tokens.css").read_text(encoding="utf-8")
    token_names = ts.css_custom_properties(token_text)
    assert REQUIRED_TOKENS <= token_names
    for t in VALID_THEMES:
        assert BLOCK_TOKENS <= set(TOKEN_BLOCKS.get(t, {}))
    # picker rules live in the consolidated settings sheet.
    settings_selectors = set(ts.selectors(ts.settings_rules()))
    assert PICKER_RULES <= {s.strip(".") for s in settings_selectors}
    # four distinct background definitions, wrap + narrow media query.
    assert len([s for s in theme_selectors if s.startswith("html[data-theme=")]) >= 4
    assert any("flex-wrap" in d for rule in THEME_RULES for d in rule.declarations)
    assert any("max-width" in m for m in ts.media_scopes(THEME_RULES))


def test_theme_switch_does_not_reset_conversation_state():
    assert "padiem:themechange" in THEME_JS
    assert "reload" not in ts.identifiers(THEME_JS)


def test_padiem_home_distinct_from_light():
    token_text = (ROOT / "static/padiem-tokens.css").read_text(encoding="utf-8")
    values = token_text.count(LIGHT_BG), token_text.count(HOME_BG)
    assert all(v > 0 for v in values)
    assert values[0] < values[1] + 5
    assert any(HOME in s for s in ts.selectors(THEME_RULES))


def test_light_preserves_violet_and_cinematic_preserves_blue_gold():
    def values_for(theme):
        block = TOKEN_BLOCKS.get(theme, {})
        return set(str(v) for v in block.values())
    assert VIOLET in values_for("light")
    assert BLUE in values_for("cinematic")
    assert GOLD in values_for("cinematic")


def test_no_hardcoded_secrets_or_provider_calls():
    ids = ts.identifiers(THEME_JS)
    assert not (FORBIDDEN_EVAL & ids)
    init_ids = ts.identifiers(THEME_INIT)
    assert not (FORBIDDEN_STORAGE & ids)
    assert not (FORBIDDEN_STORAGE & init_ids)


def test_bright_theme_chat_state_regression():
    selectors = set(ts.selectors(THEME_RULES))
    for theme in BRIGHT_CSS:
        prefix = f'html[data-theme="{theme}"] .app-shell{CHAT_STATE}'
        for sel in (".message-bubble", ".assistant-avatar", ".assistant-meta",
                    ".assistant-content", ".composer", ".composer-wrap", ".composer-note"):
            assert f"{prefix} {sel}" in selectors
        assert f'{prefix} .message-bubble' in selectors
    assert f'html[data-theme="dark"] .composer-note' in selectors
    assert f'html[data-theme="cinematic"] .composer-note' in selectors


def test_bright_theme_assistant_answer_subtree_contrast():
    selectors = set(ts.selectors(THEME_RULES))
    for theme, token in BRIGHT_TOKEN.items():
        prefix = f'html[data-theme="{theme}"] .app-shell{IS_CHAT_CLAW}'
        for sel in SUBTREE:
            assert f"{prefix} {sel}" in selectors
        rule_selector = f"{prefix} {SUBTREE[0]}"
        decls = ts.declarations_for(THEME_RULES, rule_selector)
        assert any(token in str(v) for d in decls for v in d.values())
        assert ts.declaration_is_important(THEME_RULES, rule_selector, "color")
    for theme in ("dark", "cinematic"):
        forbidden = f'html[data-theme="{theme}"] .app-shell{CHAT_STATE} .assistant-content .rich-response'
        assert forbidden not in selectors


def test_bright_theme_status_badge_is_readable_in_chat_and_claw():
    selectors = set(ts.selectors(THEME_RULES))
    for theme in BRIGHT_CSS:
        selector = (f'html[data-theme="{theme}"] '
                    f'.app-shell{IS_CHAT_CLAW} .demo-label')
        assert selector in selectors
        decls = ts.declarations_for(THEME_RULES, selector)
        assert any("color" in k for d in decls for k in d)
        assert any("!important" in str(v) for d in decls for v in d.values())
        chat_only = f'html[data-theme="{theme}"] .app-shell{CHAT_STATE} .demo-label'
        assert chat_only not in selectors
    glass = f'html[data-theme="{GLASS}"] .app-shell{IS_CHAT_CLAW} .demo-label'
    glass_rules = ts.glass_rules()
    assert glass in set(ts.selectors(glass_rules))
    glass_decls = ts.declarations_for(glass_rules, glass)
    assert any("#78838c" in str(v) for d in glass_decls for v in d.values())
    assert f'html[data-theme="{GLASS}"] .app-shell{CHAT_STATE} .demo-label' not in set(
        ts.selectors(glass_rules))
    editorial_selectors = set(ts.selectors(ts.editorial_rules()))
    assert f'.app-shell{IS_CHAT_CLAW} .demo-label' in editorial_selectors
    assert f'.app-shell{CHAT_STATE} .demo-label' not in editorial_selectors
    assert ".demo-label" in set(ts.selectors(ts.surfaces_rules()))
