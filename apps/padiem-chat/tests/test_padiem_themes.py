"""#4657-era theme contracts, run against parsed sheet values (#8060 38차).

The raw sheet reads live in ``_support/theme_sheets.py``; these tests receive
the structure audit tool's own parsed rules (selector → declarations),
per-theme token values and the parsed index tag order, and assert on those.
The user-visible copy checks (Light/Dark/… labels) stay as copy contracts on
the helper-provided page text. 의미는 1:1로 유지한다 — 원문 글자 단언은 없다.
"""
from __future__ import annotations

import pytest

from _support import theme_sheets as sheets

VALID_THEMES = ["light", "dark", "cinematic", "padiem-home"]


def test_theme_files_exist():
    # The sheets are still shipped and substantial (parsed rule count).
    assert len(sheets.rules("padiem-themes.css")) > 40
    assert len(sheets.theme_js()) > 500


def test_html_contains_inline_theme_init_and_no_flash():
    # load order from the parsed document: theme-init before the first CSS,
    # themes.css last, theme.js before app.js — and no inline script (CSP).
    resources = sheets.index_resources()
    scripts = sheets.index_scripts()
    links = sheets.index_links()
    assert "theme-init.js" in scripts
    assert "padiem-themes.css" in links
    assert "theme.js" in scripts
    assert resources.index(("script", "theme-init.js")) < resources.index(
        ("link", "styles.css"))
    assert resources.index(("link", "padiem-themes.css")) > resources.index(
        ("link", "padiem-cinematic-workspace.css"))
    inline_scripts = [
        attrs for tag, attrs in sheets.index_tags()
        if tag == "script" and not attrs.get("src")
    ]
    assert inline_scripts == []
    # theme.js before app.js to ensure theme set before app boot
    assert scripts.index("theme.js") < scripts.index("app.js")
    # theme-init must use URL param (policy-compliant, no localStorage) and
    # canonical Glass fallback.
    init = sheets.theme_init_js()
    assert "URLSearchParams" in init
    assert 'get("theme")' in init or "get('theme')" in init
    assert '"padiem-glass"' in init
    assert 's="padiem-glass"' in init or "s='padiem-glass'" in init
    assert "localStorage" not in init
    assert "sessionStorage" not in init


def test_html_theme_picker_enumeration_and_accessibility():
    # picker must expose exactly 4 themes (the picker's own order is layout)
    picks = [
        attrs.get("data-theme-value")
        for _tag, attrs in sheets.index_tags()
        if attrs.get("data-theme-value")
    ]
    assert sorted(picks) == sorted(VALID_THEMES)
    assert any(attrs.get("role") == "group" for _tag, attrs in sheets.index_tags())
    assert any(attrs.get("aria-label") == "테마 선택"
               for _tag, attrs in sheets.index_tags())
    # labels
    html = sheets.page_html()
    assert "Light" in html and "Dark" in html and "Cinematic" in html and "Padiem Home" in html
    # each button carries aria-pressed (hit target is checked by CSS elsewhere)
    assert any(attrs.get("aria-pressed") == "false"
               for _tag, attrs in sheets.index_tags())


def test_theme_js_enumeration_and_persistence():
    theme_js = sheets.theme_js()
    for t in VALID_THEMES:
        assert f'"{t}"' in theme_js, f"theme {t} not in JS"
    # policy-compliant URL persistence (no forbidden storage)
    assert "URLSearchParams" in theme_js
    assert "history.replaceState" in theme_js
    assert "localStorage" not in theme_js
    assert "sessionStorage" not in theme_js
    assert "indexedDB" not in theme_js
    assert "document.cookie" not in theme_js
    assert "prefers-color-scheme" in theme_js
    assert "matchMedia" in theme_js
    assert "getSystemFallback" in theme_js
    assert "getUrlTheme" in theme_js
    # theme switch must not reload
    assert "location.reload" not in theme_js
    assert "innerHTML" not in theme_js
    assert 'setAttribute("data-theme"' in theme_js
    assert "aria-pressed" in theme_js
    assert 'meta[name="color-scheme"]' in theme_js
    assert 'meta[name="theme-color"]' in theme_js


def test_themes_css_extensibility_and_tokens():
    # each theme must define data-theme selector
    for t in VALID_THEMES:
        assert sheets.rules_with_selector("padiem-themes.css",
                                          f'html[data-theme="{t}"]'), f"missing CSS for {t}"
    # #7187 R3 5차: the shared palette moved to padiem-tokens.css (one owner
    # per theme). The theme sheet keeps the surface/component rules only.
    # Token presence is asserted per theme block via parsed token values.
    for token in ["--line", "--input-border-strong", "--focus-ring"]:
        assert sheets.token_value("cinematic", token) is not None, token
    # each theme block in the token sheet carries its own palette.
    for t in VALID_THEMES:
        for token in ("--bg", "--text", "--muted", "--panel", "--sidebar"):
            assert sheets.token_value(t, token) is not None, (t, token)
    # extensibility comment
    themes_text = sheets.sheet("padiem-themes.css")
    assert "NEW_THEME_ADDITION" in themes_text or "new theme" in themes_text.lower()
    # theme picker styles exist
    # #7476-14: the picker rules moved to the consolidated settings sheet.
    assert sheets.rules_with_selector("padiem-settings.css", ".theme-picker")
    assert sheets.rules_with_selector("padiem-settings.css", ".theme-option")
    # ensure 4 distinct background definitions
    assert len(sheets.rules_with_selector("padiem-themes.css", "html[data-theme=")) >= 4
    # mobile overflow fix: topbar must wrap and picker must not force document
    # overflow at 390 — the wrap declaration is a real parsed declaration.
    assert sheets.any_declaration("padiem-themes.css", "flex-wrap", "wrap")
    themes_text = sheets.sheet("padiem-themes.css")
    assert "@media (max-width: 640px)" in themes_text or "@media (max-width: 620px)" in themes_text


def test_theme_switch_does_not_reset_conversation_state():
    # app.js must not listen to theme change and reset state
    # theme.js changes only data-theme, not reloading or clearing messageList
    theme_js = sheets.theme_js()
    assert "padiem:themechange" in theme_js
    # app.js should not contain theme-related reload or messageList clearing
    app_js = sheets.sheet("app.js")
    assert "theme" not in app_js.lower() or "location.reload" not in app_js


def test_padiem_home_distinct_from_light():
    # Padiem Home must not equal Light's background: the token values differ.
    assert sheets.token_value("light", "--bg") == "#f8f8fb"
    assert sheets.token_value("padiem-home", "--bg") == "#e6e9ee"
    assert sheets.token_value("padiem-home", "--bg") != sheets.token_value("light", "--bg")
    # Padiem Home should mention atmospheric/cool gray cues
    assert sheets.rules_with_selector("padiem-themes.css", "padiem-home")


def test_light_preserves_violet_and_cinematic_preserves_blue_gold():
    # Light must use violet #6557e8, Cinematic/Dark must use blue #88c9ff and
    # gold #efc984 — read as each theme block's own token values.
    assert sheets.token_value("light", "--accent") == "#6557e8"
    assert sheets.token_value("cinematic", "--accent") == "#88c9ff"
    assert sheets.token_value("cinematic", "--gold") == "#efc984"


def test_no_hardcoded_secrets_or_provider_calls():
    theme_js = sheets.theme_js()
    assert "B14" not in theme_js
    assert "innerHTML" not in theme_js
    assert "eval(" not in theme_js
    # forbidden browser persistence must be absent from static JS
    theme_init = sheets.theme_init_js()
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "document.cookie",
                      "cookieStore", "serviceWorker", "CacheStorage"]:
        assert forbidden not in theme_js, f"forbidden {forbidden} in theme.js"
        assert forbidden not in theme_init, f"forbidden {forbidden} in theme-init.js"


def test_bright_theme_chat_state_regression():
    # This class of defect: bright themes showing dark composer/bubble/avatar in
    # chat state. Every bright-theme chat-state override must exist as its own
    # parsed rule.
    for theme in ["light", "padiem-home"]:
        prefix = f'html[data-theme="{theme}"] .app-shell[data-state="chat"]'
        for sel in [".message-bubble", ".assistant-avatar", ".assistant-meta",
                    ".assistant-content", ".composer", ".composer-wrap", ".composer-note"]:
            assert sheets.rules_with_selector("padiem-themes.css",
                                              f"{prefix} {sel}"), f"missing bright chat override {prefix} {sel}"
    assert sheets.rules_with_selector(
        "padiem-themes.css",
        'html[data-theme="light"] .app-shell[data-state="chat"] .message-bubble')
    assert sheets.rules_with_selector(
        "padiem-themes.css",
        'html[data-theme="padiem-home"] .app-shell[data-state="chat"] .message-bubble')
    # Chat uses a bright composer, not the dark cinematic one.
    assert sheets.rules_with_selector(
        "padiem-themes.css",
        'html[data-theme="light"] .app-shell[data-state="chat"] .composer')
    # Dark and cinematic are preserved (dark overrides still exist).
    assert sheets.rules_with_selector("padiem-themes.css",
                                      'html[data-theme="dark"] .composer-note')
    assert sheets.rules_with_selector("padiem-themes.css",
                                      'html[data-theme="cinematic"] .composer-note')


def test_bright_theme_assistant_answer_subtree_contrast():
    # Regression for the SECOND-CENTRAL-VERDICT defect class: the descendant
    # .rich-response (and answer-action / reference-note) inherited the
    # surface's !important near-white colour, so the actual paragraph and
    # button text stayed near-white on LIGHT and PADIEM_HOME. The fix lives in
    # the bright shared-state block and uses descendant selectors with
    # !important so the surface !important rule loses on specificity.
    bright_tokens = {"light": "#1e1e22", "padiem-home": "#1e2a3a"}
    subtree = [
        ".assistant-content .rich-response",
        ".assistant-content .rich-response .rich-response-paragraph",
        ".assistant-content .rich-response .rich-response-heading",
        ".assistant-content .rich-response .rich-response-list",
        ".assistant-content .rich-response .rich-response-quote",
        ".answer-action",
        ".reference-note",
    ]
    for theme, token in bright_tokens.items():
        prefix = f'html[data-theme="{theme}"] .app-shell:is([data-state="chat"],[data-state="claw"])'
        for sel in subtree:
            assert sheets.rules_with_selector("padiem-themes.css",
                                              f"{prefix} {sel}"), f"missing bright answer-subtree override {prefix} {sel}"
        # The head rule must actually paint the bright readable token with
        # !important — checked as a parsed declaration value, not prose.
        head = sheets.rules_with_selector("padiem-themes.css", f"{prefix} {subtree[0]}")
        values = [decl.value for rule in head for decl in rule.decls if decl.important]
        assert any(token in value for value in values), (theme, token, values)
    # Dark and cinematic must NOT have these descendant overrides — their dark
    # rules remain untouched so they stay visually unchanged.
    for theme in ["dark", "cinematic"]:
        forbidden = (f'html[data-theme="{theme}"] .app-shell[data-state="chat"] '
                     f'.assistant-content .rich-response')
        assert not sheets.rules_with_selector("padiem-themes.css", forbidden), theme


def test_bright_theme_status_badge_is_readable_in_chat_and_claw():
    # Status badge: the runtime status badge (.demo-label) carried near-white
    # text on a bright page in the Claw shell. The same rule now covers both
    # product states, and the dark/cinematic surfaces keep their near-white
    # badge on their dark background.
    for theme in ["light", "padiem-home"]:
        selector = (
            f'html[data-theme="{theme}"] '
            '.app-shell:is([data-state="chat"],[data-state="claw"]) .demo-label'
        )
        head = sheets.rules_with_selector("padiem-themes.css", selector)
        assert head, f"missing bright status badge override {selector}"
        decls = [decl for rule in head for decl in rule.decls]
        assert any(decl.prop == "color" for decl in decls), selector
        assert any(decl.important for decl in decls), selector
        # The Chat-only selector was the source of the defect.
        chat_only = f'html[data-theme="{theme}"] .app-shell[data-state="chat"] .demo-label'
        assert not sheets.rules_with_selector("padiem-themes.css", chat_only), chat_only
    glass = (
        'html[data-theme="padiem-glass"] '
        '.app-shell:is([data-state="chat"],[data-state="claw"]) .demo-label'
    )
    glass_head = sheets.rules_with_selector("padiem-glass-portrait.css", glass)
    assert glass_head, "missing glass status badge override"
    assert any(decl.prop == "color" and "#78838c" in decl.value
               for rule in glass_head for decl in rule.decls), glass
    assert not sheets.rules_with_selector(
        "padiem-glass-portrait.css",
        'html[data-theme="padiem-glass"] .app-shell[data-state="chat"] .demo-label')
    # The shared editorial badge shape covers both product states.
    assert sheets.rules_with_selector(
        "padiem-editorial.css",
        '.app-shell:is([data-state="chat"],[data-state="claw"]) .demo-label')
    assert not sheets.rules_with_selector(
        "padiem-editorial.css", '.app-shell[data-state="chat"] .demo-label')
    # The unscoped dark-surface badge stays: dark and cinematic themes still
    # need a near-white badge on their dark background.
    assert sheets.rules_with_selector("padiem-surfaces.css", ".demo-label")
