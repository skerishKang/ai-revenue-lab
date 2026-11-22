from _support.glass_default import css_facts, handler_view, js_view


THEME = js_view("theme.js")
INIT = js_view("theme-init.js")
GLASS_CSS = css_facts("padiem-glass.css")


def test_glass_mobile_starter_text_can_break_unbreakable_token_run():
    # Glass mobile default exposed a 7px horizontal overflow (scrollWidth=397
    # at 390px): the document starter's formats run "TXT·Markdown·CSV·…" has
    # no line-break opportunity, so its min-content width forced the 1fr
    # starter-grid track past the viewport.
    starter_rules = [
        rule for rule in GLASS_CSS["rules"]
        if any(".starter small" in selector and "padiem-glass" in selector
               for selector in rule.selectors)
    ]
    assert starter_rules
    assert any(rule.declarations.get("overflow-wrap") == "anywhere" for rule in starter_rules)
    # The fix must stay theme-scoped and must not hide overflow globally.
    assert ("overflow-x", "hidden") not in GLASS_CSS["declarations"]


def test_bare_url_default_is_padiem_glass():
    assert ("s", '"padiem-glass"') in INIT["assignments"] or (
        "s", "'padiem-glass'"
    ) in INIT["assignments"]
    assert '"padiem-glass"' in THEME["returns"]
    # getCurrent fallback
    assert "getSystemFallback()" in THEME["returns"]
    assert "getSystemFallback" in THEME["function_names"]
    # init fallback
    assert ("initial", "url||getSystemFallback()") in THEME["assignments"]


def test_default_glass_variant_is_female():
    assert ("glass", '"female"') in INIT["assignments"]
    assert 'getUrlGlassVariant()||"female"' in THEME["returns"]
    assert ("GLASS_VARIANTS", '["female","male"]') in THEME["assignments"]


def test_explicit_theme_overrides():
    for theme in ["light", "dark", "cinematic", "padiem-home", "padiem-glass"]:
        assert theme in THEME["string_literals"]
        assert theme in INIT["string_literals"]
    # URL authoritative
    assert "getUrlTheme" in THEME["function_names"]
    assert "URLSearchParams" in THEME["identifiers"]
    assert "URLSearchParams" in INIT["identifiers"]
    # glass male
    assert ("get", '"glass"') in THEME["call_args"]
    assert "G.indexOf(g)!==-1" in INIT["comparisons"]


def test_explicit_glass_male_override():
    assert "isGlassVariant" in THEME["function_names"]
    assert "applyGlassVariant" in THEME["function_names"]
    assert any(
        callee.endswith("searchParams.set") and args == '"glass",variant'
        for callee, args in THEME["call_args"]
    )


def test_glass_reveal_keeps_variant_rest_masks_legible():
    # Home motion must still start from the female/male CSS rest masks, while
    # reading mode may use its calmer rest posture before pointer/answer reveal.
    expected = {
        "restMaskStart": 'reading?(variant==="male"?30:34):(variant==="male"?14:18)',
        "restMaskFull": 'reading?(variant==="male"?58:62):(variant==="male"?42:46)',
        "openMaskStart": 'reading?(variant==="male"?4:5):0',
        "openMaskFull": 'reading?(variant==="male"?20:22):(variant==="male"?8:10)',
        "maskStart": "restMaskStart-((restMaskStart-openMaskStart)*reveal)",
        "maskFull": "restMaskFull-((restMaskFull-openMaskFull)*reveal)",
    }
    for name, value in expected.items():
        assert (name, value) in THEME["assignments"], name
    assert ("maskStart", "24*(1-reveal)") not in THEME["assignments"]
    assert ("maskFull", "58-(46*reveal)") not in THEME["assignments"]


def test_os_color_scheme_does_not_override_bare_glass():
    # init must not use prefers-color-scheme for theme fallback
    assert "prefers-color-scheme" not in INIT["string_literals"] or (
        "s", '"padiem-glass"'
    ) in INIT["assignments"]
    # theme.js handler must return early without applying a fallback theme.
    handler = handler_view("theme.js")
    assert ("getUrlTheme", "") in handler["call_args"]
    assert "getSystemFallback" not in handler["identifiers"]
    assert "applyTheme" not in handler["calls"]


def test_no_forbidden_storage():
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "document.cookie", "cookieStore"]:
        assert forbidden not in THEME["identifiers"] | THEME["member_chains"]
        assert forbidden not in INIT["identifiers"] | INIT["member_chains"]


def test_conversation_state_not_reset_on_theme_switch():
    app = js_view("app.js")
    assert "padiem:themechange" in THEME["string_literals"]
    # app.js should not reload or clear messageList on theme change
    assert "location.reload" not in app["member_chains"]
    # theme.js should not clear messageList
    assert "messageList" not in THEME["identifiers"] or "innerHTML" not in THEME["identifiers"]
