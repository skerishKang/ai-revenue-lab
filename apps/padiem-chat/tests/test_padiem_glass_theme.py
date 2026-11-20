from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_JS = (ROOT / "static/theme.js").read_text(encoding="utf-8")
THEME_INIT = (ROOT / "static/theme-init.js").read_text(encoding="utf-8")
GLASS_CSS = (ROOT / "static/padiem-glass.css").read_text(encoding="utf-8")
TOKENS_CSS = (ROOT / "static/padiem-tokens.css").read_text(encoding="utf-8")
HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")


def test_padiem_glass_is_additive_fifth_theme() -> None:
    assert '"padiem-glass"' in THEME_JS
    assert '"padiem-glass"' in THEME_INIT
    assert 'data-theme-value="padiem-glass"' in THEME_JS
    assert 'Padiem Glass' in THEME_JS
    assert 'html[data-theme="padiem-glass"]' in GLASS_CSS
    # Existing static picker remains untouched; fifth option is appended at runtime.
    for existing in ["light", "dark", "cinematic", "padiem-home"]:
        assert f'data-theme-value="{existing}"' in HTML


def test_glass_theme_has_image_ready_background_slot_and_fallback() -> None:
    assert "--padiem-glass-background-image: none" in GLASS_CSS
    assert "var(--padiem-glass-background-image)" in GLASS_CSS
    assert "background-size: cover" in GLASS_CSS
    assert "background-position: center" in GLASS_CSS
    assert "linear-gradient" in GLASS_CSS


def test_glass_surfaces_are_frosted_not_opaque_redesign() -> None:
    for selector in [
        '.sidebar',
        '.topbar',
        '.starter',
        '.composer',
        '.settings-panel',
        '.source-card',
        '.rich-response',
    ]:
        assert f'html[data-theme="padiem-glass"] {selector}' in GLASS_CSS
    assert "backdrop-filter: blur(" in GLASS_CSS
    assert "rgba(" in GLASS_CSS
    # #7187 R3 5차: the Glass palette lives in padiem-tokens.css.
    assert "--glass:" in TOKENS_CSS


def test_glass_theme_keeps_readability_and_reduced_transparency_fallback() -> None:
    assert "--text: #17202a" in TOKENS_CSS
    assert "--user-bubble-text: #ffffff" in TOKENS_CSS
    # #8008 9차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
    assert '.assistant-content { color: #17212a; }' in GLASS_CSS
    assert "@media (prefers-reduced-transparency: reduce)" in GLASS_CSS
    assert "backdrop-filter: none" in GLASS_CSS


def test_glass_theme_preserves_url_authority_and_no_forbidden_storage() -> None:
    assert "URLSearchParams" in THEME_JS
    assert "history.replaceState" in THEME_JS
    assert "URLSearchParams" in THEME_INIT
    for forbidden in [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "cookieStore",
        "serviceWorker",
        "CacheStorage",
    ]:
        assert forbidden not in THEME_JS
        assert forbidden not in THEME_INIT
    assert "location.reload" not in THEME_JS


def test_glass_theme_does_not_touch_prior_visual_contracts() -> None:
    assert 'href="https://padiem.net/"' in HTML
    assert "Padiem Chat" in HTML
    assert "Padiem Chat</span>" in HTML
    assert "text-transform: none" in GLASS_CSS
    assert 'class="sidebar-bottom"' in HTML
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    assert 'id="settingsButton"' not in topbar_html
    assert 'id="loginButton"' not in topbar_html


def test_glass_theme_has_no_provider_or_core_behavior() -> None:
    combined = THEME_JS + THEME_INIT + GLASS_CSS
    for forbidden in ["provider_id", "selected_provider", "selected_model", "B14", "padiem-ai-core", "control-plane"]:
        assert forbidden not in combined


def test_glass_file_button_keeps_dark_foreground_on_interaction() -> None:
    hover = 'html[data-theme="padiem-glass"] .composer .tool-button:hover:not(:disabled)'
    focus = 'html[data-theme="padiem-glass"] .composer .tool-button:focus-visible:not(:disabled)'
    active = 'html[data-theme="padiem-glass"] .composer .tool-button:active:not(:disabled)'
    assert hover in GLASS_CSS
    assert focus in GLASS_CSS
    assert active in GLASS_CSS
    interaction_block = GLASS_CSS.split(hover, 1)[1].split("}", 1)[0]
    assert "color: #17212a" in interaction_block


def test_glass_second_home_headline_line_stays_readable_on_bright_surface() -> None:
    # #7817: the line's colour is a theme token now, not a rule in this sheet.
    # Same target (it has to stay readable on the bright Glass surface), read
    # where the value lives.
    assert 'html[data-theme="padiem-glass"] .empty-state h1 br + span' not in GLASS_CSS
    block = TOKENS_CSS.split('html[data-theme="padiem-glass"] {', 1)[1].split("}", 1)[0]
    assert "--hero-sub-color: #56616b;" in block
    assert _contrast(_hex(block, "--hero-sub-color"), (227, 231, 233)) >= 4.5
    assert _contrast(_hex(block, "--hero-sub-color"), (225, 229, 231)) >= 4.5


def _hex(sheet: str, name: str) -> tuple[int, int, int]:
    import re

    match = re.search(rf"{re.escape(name)}:\s*#([0-9a-fA-F]{{6}})", sheet)
    assert match, name
    value = match.group(1)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    def lum(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])

    hi, lo = max(lum(fg), lum(bg)), min(lum(fg), lum(bg))
    return (hi + 0.05) / (lo + 0.05)
