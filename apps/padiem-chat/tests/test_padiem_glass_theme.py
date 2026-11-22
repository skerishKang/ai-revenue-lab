"""Glass theme contracts against parsed shipped sheets (no raw source reads here).

Raw CSS/JS/HTML reads live in tests/_support; the assertions below bind the
same selectors, token values, literals and DOM boundaries through parsers.
"""
from __future__ import annotations

from _support import glass_theme_source as source
from _support import theme_sheets


def _glass_rules():
    return [rule for rule in theme_sheets.rules("padiem-glass.css")]


def _parts(rule) -> set[str]:
    """Selectors in one parsed (possibly comma-grouped) rule."""
    return {part.strip() for part in rule.selector.split(",")}


def _rule(selector: str):
    return [rule for rule in _glass_rules() if selector in _parts(rule)]


def _decls(selector: str) -> dict[str, str]:
    return {decl.prop: decl.value for rule in _rule(selector) for decl in rule.decls}


def _any_value(prop: str, wanted: str, *, contains: bool = False) -> bool:
    for rule in _glass_rules():
        for decl in rule.decls:
            if decl.prop != prop:
                continue
            if contains and wanted in decl.value:
                return True
            if not contains and decl.value == wanted:
                return True
    return False


def _js_text(name: str) -> str:
    return " ".join(sorted(source.js_strings(name) | source.js_identifiers(name) | source.js_members(name)))


def test_padiem_glass_is_additive_fifth_theme() -> None:
    for name in ("theme.js", "theme-init.js"):
        literals = source.js_strings(name)
        assert "padiem-glass" in literals
    assert any('data-theme-value="padiem-glass"' in value for value in source.js_strings("theme.js"))
    assert "Padiem Glass" in source.js_strings("theme.js")
    assert _rule('html[data-theme="padiem-glass"]')
    # Existing static picker remains untouched; fifth option is appended at runtime.
    for existing in ["light", "dark", "cinematic", "padiem-home"]:
        assert existing in source.theme_picker_values()


def test_glass_theme_has_image_ready_background_slot_and_fallback() -> None:
    assert _any_value("--padiem-glass-background-image", "none")
    assert _any_value("background-image", "var(--padiem-glass-background-image)", contains=True)
    assert _any_value("background-size", "cover", contains=True)
    assert _any_value("background-position", "center")
    assert _any_value("background-image", "linear-gradient", contains=True)


def test_glass_surfaces_are_frosted_not_opaque_redesign() -> None:
    for selector in [
        "sidebar",
        "topbar",
        "starter",
        "composer",
        "settings-panel",
        "source-card",
        "rich-response",
    ]:
        assert _rule(f'html[data-theme="padiem-glass"] .{selector}')
    assert _any_value("backdrop-filter", "blur(", contains=True)
    assert _any_value("background", "rgba(", contains=True) or _any_value("background-color", "rgba(", contains=True)
    # #7187 R3 5차: the Glass palette lives in padiem-tokens.css.
    assert theme_sheets.token_value("padiem-glass", "--glass") is not None


def test_glass_theme_keeps_readability_and_reduced_transparency_fallback() -> None:
    assert theme_sheets.token_value("padiem-glass", "--text") == "#17202a"
    assert theme_sheets.token_value("padiem-glass", "--user-bubble-text") == "#ffffff"
    # #8008 9차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
    assert _decls('html[data-theme="padiem-glass"] .assistant-content').get("color") == "#17212a"
    assert "(prefers-reduced-transparency: reduce)" in source.css_at_rules()
    assert _any_value("backdrop-filter", "none")


def test_glass_theme_preserves_url_authority_and_no_forbidden_storage() -> None:
    assert "URLSearchParams" in source.js_identifiers("theme.js")
    assert "history.replaceState" in source.js_members("theme.js")
    assert "URLSearchParams" in source.js_identifiers("theme-init.js")
    forbidden = [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "cookieStore",
        "serviceWorker",
        "CacheStorage",
    ]
    for name in ("theme.js", "theme-init.js"):
        text = _js_text(name)
        for token in forbidden:
            assert token not in text
    assert "location.reload" not in source.js_members("theme.js")


def test_glass_theme_does_not_touch_prior_visual_contracts() -> None:
    assert "https://padiem.net/" in source.index_hrefs()
    assert "Padiem Chat" in source.html_text()
    assert "Padiem Chat</span>" in source.dom_markers()
    assert _any_value("text-transform", "none")
    assert any(attrs.get("class") == "sidebar-bottom" for _tag, attrs in source.index_attrs())
    markers = source.dom_markers()
    assert "topbar:settingsButton" not in markers
    assert "topbar:loginButton" not in markers


def test_glass_theme_has_no_provider_or_core_behavior() -> None:
    combined = " ".join([
        _js_text("theme.js"),
        _js_text("theme-init.js"),
        " ".join(rule.selector for rule in _glass_rules()),
        " ".join(decl.prop + " " + decl.value for rule in _glass_rules() for decl in rule.decls),
    ])
    for forbidden in ["provider_id", "selected_provider", "selected_model", "B14", "padiem-ai-core", "control-plane"]:
        assert forbidden not in combined


def test_glass_file_button_keeps_dark_foreground_on_interaction() -> None:
    hover = 'html[data-theme="padiem-glass"] .composer .tool-button:hover:not(:disabled)'
    focus = 'html[data-theme="padiem-glass"] .composer .tool-button:focus-visible:not(:disabled)'
    active = 'html[data-theme="padiem-glass"] .composer .tool-button:active:not(:disabled)'
    assert _rule(hover)
    assert _rule(focus)
    assert _rule(active)
    assert _decls(hover).get("color") == "#17212a"


def test_glass_second_home_headline_line_stays_readable_on_bright_surface() -> None:
    # #7817: the line's colour is a theme token now, not a rule in this sheet.
    assert not _rule('html[data-theme="padiem-glass"] .empty-state h1 br + span')
    value = theme_sheets.token_value("padiem-glass", "--hero-sub-color")
    assert value == "#56616b"
    assert _contrast(_hex(value), (227, 231, 233)) >= 4.5
    assert _contrast(_hex(value), (225, 229, 231)) >= 4.5


def _hex(value: str) -> tuple[int, int, int]:
    digits = value.lstrip("#")
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    def lum(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])

    hi, lo = max(lum(fg), lum(bg)), min(lum(fg), lum(bg))
    return (hi + 0.05) / (lo + 0.05)
