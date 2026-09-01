from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_JS = (ROOT / "static/theme.js").read_text(encoding="utf-8")
THEME_INIT = (ROOT / "static/theme-init.js").read_text(encoding="utf-8")
GLASS_CSS = (ROOT / "static/padiem-glass.css").read_text(encoding="utf-8")
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
    assert "--glass:" in GLASS_CSS


def test_glass_theme_keeps_readability_and_reduced_transparency_fallback() -> None:
    assert "--text: #17202a" in GLASS_CSS
    assert "--user-bubble-text: #ffffff" in GLASS_CSS
    assert '.assistant-content { color: #17212a !important; }' in GLASS_CSS
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
    assert "PADIEM CHAT</span>" not in HTML
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
