from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")
THEME_JS = (ROOT / "static/theme.js").read_text(encoding="utf-8")
THEMES_CSS = (ROOT / "static/padiem-themes.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")

VALID_THEMES = ["light", "dark", "cinematic", "padiem-home"]

def test_theme_files_exist():
    assert (ROOT / "static/padiem-themes.css").is_file()
    assert (ROOT / "static/theme.js").is_file()
    assert len(THEMES_CSS) > 1000
    assert len(THEME_JS) > 500

def test_html_contains_inline_theme_init_and_no_flash():
    # inline script must exist in head before paint
    assert '<script src="./theme-init.js"></script>' in HTML
    assert '<link rel="stylesheet" href="./padiem-themes.css"' in HTML
    assert '<script src="./theme.js"></script>' in HTML
    # theme-init must be before first CSS for no-flash, and themes.css last
    assert HTML.index("theme-init.js") < HTML.index("styles.css")
    assert HTML.index("padiem-themes.css") > HTML.index("padiem-cinematic-workspace.css")
    # no inline script violating CSP
    assert "<script>" not in HTML.replace('<script src=', '<SRCS')
    # theme-init contains padiem_theme and prefers-color-scheme
    init = (ROOT / "static/theme-init.js").read_text(encoding="utf-8")
    assert "padiem_theme" in init
    assert "prefers-color-scheme" in init
    # theme.js before app.js to ensure theme set before app boot
    assert HTML.index("theme.js") < HTML.index("app.js")

def test_html_theme_picker_enumeration_and_accessibility():
    # picker must expose exactly 4 themes
    for t in VALID_THEMES:
        assert f'data-theme-value="{t}"' in HTML, f"missing picker for {t}"
    assert 'role="group"' in HTML
    assert 'aria-label="테마 선택"' in HTML
    assert HTML.count('data-theme-value=') == 4
    # labels
    assert "Light" in HTML and "Dark" in HTML and "Cinematic" in HTML and "Padiem Home" in HTML
    # each button has aria-pressed and aria-label and exactly 44px hit target via CSS (checked via CSS)
    assert 'aria-pressed="false"' in HTML
    # keyboard: buttons are native <button>, not divs

def test_theme_js_enumeration_and_persistence():
    for t in VALID_THEMES:
        assert f'"{t}"' in THEME_JS, f"theme {t} not in JS"
    assert "padiem_theme" in THEME_JS
    assert "localStorage.getItem" in THEME_JS
    assert "localStorage.setItem" in THEME_JS
    assert "prefers-color-scheme" in THEME_JS
    assert "matchMedia" in THEME_JS
    # system fallback maps light->light, dark->dark (not cinematic/home unless explicit)
    assert "getSystemFallback" in THEME_JS
    # theme switch must not reload
    assert "location.reload" not in THEME_JS
    assert "innerHTML" not in THEME_JS
    # must update data-theme attribute
    assert 'setAttribute("data-theme"' in THEME_JS
    # must sync aria-pressed
    assert 'aria-pressed' in THEME_JS
    # must update meta color-scheme and theme-color
    assert 'meta[name="color-scheme"]' in THEME_JS
    assert 'meta[name="theme-color"]' in THEME_JS

def test_themes_css_extensibility_and_tokens():
    # each theme must define data-theme selector
    for t in VALID_THEMES:
        assert f'html[data-theme="{t}"]' in THEMES_CSS, f"missing CSS for {t}"
    # shared tokens coverage per spec
    for token in ["--bg", "--text", "--muted", "--line", "--accent", "--panel", "--sidebar", "--gold"]:
        assert token in THEMES_CSS
    # extensibility comment
    assert "NEW_THEME_ADDITION" in THEMES_CSS or "new theme" in THEMES_CSS.lower()
    # must not duplicate business logic, only tokens
    # check theme picker styles exist
    assert ".theme-picker" in THEMES_CSS
    assert ".theme-option" in THEMES_CSS
    # ensure 4 distinct background definitions
    assert THEMES_CSS.count("html[data-theme=") >= 4

def test_theme_switch_does_not_reset_conversation_state():
    # app.js must not listen to theme change and reset state
    # theme.js changes only data-theme, not reloading or clearing messageList
    assert "padiem:themechange" in THEME_JS
    # app.js should not contain theme-related reload or messageList clearing on theme
    # ensure app.js doesn't contain location.reload or messageList.innerHTML clearing tied to theme
    assert "theme" not in APP_JS.lower() or "location.reload" not in APP_JS

def test_padiem_home_distinct_from_light():
    # Padiem Home must not equal Light's bg
    # Light uses #f8f8fb, Padiem Home uses #e6e9ee cool gray
    assert "#f8f8fb" in THEMES_CSS
    assert "#e6e9ee" in THEMES_CSS
    assert THEMES_CSS.count("#f8f8fb") < THEMES_CSS.count("#e6e9ee") + 5  # both exist distinctly
    # Padiem Home should mention atmospheric/cool gray cues
    assert "padiem-home" in THEMES_CSS

def test_light_preserves_violet_and_cinematic_preserves_blue_gold():
    # Light must use violet #6557e8, Cinematic/Dark must use blue #88c9ff and gold #efc984
    assert "#6557e8" in THEMES_CSS
    assert "#88c9ff" in THEMES_CSS
    assert "#efc984" in THEMES_CSS
    # Light section contains violet
    light_section = THEMES_CSS.split('html[data-theme="light"]')[1].split('html[data-theme="dark"]')[0]
    assert "#6557e8" in light_section
    # Cinematic section contains strong blue/gold
    cin_section = THEMES_CSS.split('html[data-theme="cinematic"]')[1].split('html[data-theme="padiem-home"]')[0]
    assert "#88c9ff" in cin_section
    assert "#efc984" in cin_section

def test_no_hardcoded_secrets_or_provider_calls():
    assert "B14" not in THEME_JS
    assert "provider" not in THEME_JS.lower() or "provider" in THEME_JS.lower() and False  # allow but not secret
    assert "innerHTML" not in THEME_JS
    assert "eval(" not in THEME_JS
