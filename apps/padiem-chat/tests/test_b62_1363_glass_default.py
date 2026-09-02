from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_JS = (ROOT / "static/theme.js").read_text(encoding="utf-8")
THEME_INIT = (ROOT / "static/theme-init.js").read_text(encoding="utf-8")
GLASS_CSS = (ROOT / "static/padiem-glass.css").read_text(encoding="utf-8")


def test_glass_mobile_starter_text_can_break_unbreakable_token_run():
    # Glass mobile default exposed a 7px horizontal overflow (scrollWidth=397
    # at 390px): the document starter's formats run "TXT·Markdown·CSV·…" has
    # no line-break opportunity, so its min-content width forced the 1fr
    # starter-grid track past the viewport.
    starter_small_rules = [
        line for line in GLASS_CSS.splitlines()
        if ".starter small" in line and "padiem-glass" in line
    ]
    assert starter_small_rules
    assert any("overflow-wrap: anywhere" in rule for rule in starter_small_rules)
    # The fix must stay theme-scoped and must not hide overflow globally.
    assert "overflow-x: hidden" not in GLASS_CSS


def test_bare_url_default_is_padiem_glass():
    assert 's="padiem-glass"' in THEME_INIT or "s='padiem-glass'" in THEME_INIT
    assert 'return "padiem-glass"' in THEME_JS
    # getCurrent fallback
    assert 'return getSystemFallback();' in THEME_JS
    assert 'function getSystemFallback()' in THEME_JS
    # init fallback
    assert 'var initial=url||getSystemFallback();' in THEME_JS or 'initial=url||getSystemFallback()' in THEME_JS


def test_default_glass_variant_is_female():
    assert 'glass="female"' in THEME_INIT
    assert 'return getUrlGlassVariant()||"female"' in THEME_JS
    assert 'GLASS_VARIANTS=["female","male"]' in THEME_JS


def test_explicit_theme_overrides():
    for theme in ["light", "dark", "cinematic", "padiem-home", "padiem-glass"]:
        assert f'"{theme}"' in THEME_JS
        assert f'"{theme}"' in THEME_INIT
    # URL authoritative
    assert 'getUrlTheme()' in THEME_JS
    assert 'URLSearchParams' in THEME_JS
    assert 'URLSearchParams' in THEME_INIT
    # glass male
    assert 'get("glass")' in THEME_JS
    assert 'glass=male' in THEME_INIT or 'G.indexOf(g)!==-1' in THEME_INIT


def test_explicit_glass_male_override():
    assert 'isGlassVariant' in THEME_JS
    assert 'applyGlassVariant' in THEME_JS
    assert 'searchParams.set("glass",variant)' in THEME_JS


def test_glass_reveal_keeps_variant_rest_masks_legible():
    # Runtime motion must start from the same legible portrait masks as the
    # female/male CSS variants instead of restoring the old 24%/58% half-face
    # mask on the first animation frame.
    assert 'var variant=getGlassVariant();' in THEME_JS
    assert 'var restMaskStart=variant==="male"?0:2;' in THEME_JS
    assert 'var restMaskFull=variant==="male"?22:26;' in THEME_JS
    assert 'var openMaskFull=variant==="male"?12:14;' in THEME_JS
    assert 'var maskStart=restMaskStart*(1-reveal);' in THEME_JS
    assert 'var maskFull=restMaskFull-((restMaskFull-openMaskFull)*reveal);' in THEME_JS
    assert 'var maskStart=24*(1-reveal);' not in THEME_JS
    assert 'var maskFull=58-(46*reveal);' not in THEME_JS


def test_os_color_scheme_does_not_override_bare_glass():
    # init must not use prefers-color-scheme for theme fallback
    assert 'prefers-color-scheme' not in THEME_INIT or 's="padiem-glass"' in THEME_INIT
    # theme.js handler must not apply fallback when no URL theme
    # Check that handler returns early without applyTheme
    assert 'var handler=function(){\n        if(getUrlTheme()) return;\n        return;' in THEME_JS
    # Ensure getSystemFallback is not called inside handler
    handler_section = THEME_JS.split('var handler=function')[1].split('};')[0] if 'var handler=function' in THEME_JS else ""
    assert 'getSystemFallback()' not in handler_section
    assert 'applyTheme(fallback' not in handler_section


def test_no_forbidden_storage():
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "document.cookie", "cookieStore"]:
        assert forbidden not in THEME_JS
        assert forbidden not in THEME_INIT


def test_conversation_state_not_reset_on_theme_switch():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "padiem:themechange" in THEME_JS
    # app.js should not reload or clear messageList on theme change
    assert "location.reload" not in app_js
    # theme.js should not clear messageList
    assert "messageList" not in THEME_JS or "innerHTML" not in THEME_JS
