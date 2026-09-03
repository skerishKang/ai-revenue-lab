from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
THEME = (STATIC / "theme.js").read_text(encoding="utf-8")
READING = (STATIC / "padiem-glass-reading.css").read_text(encoding="utf-8")
PORTRAIT = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_glass_mode_is_projected_from_explicit_app_conversation_state() -> None:
    assert 'shell.dataset.state==="chat" ? "reading" : "home"' in THEME
    assert 'root.setAttribute("data-glass-mode",mode);' in THEME
    assert 'attributeFilter:["data-state"]' in THEME
    assert 'shell.dataset.state = "chat";' in APP
    assert 'shell.dataset.state = "home";' in APP


def test_glass_reading_branch_freezes_visual_travel_before_old_home_heuristics() -> None:
    reading_branch = THEME.index('if(mode==="reading")')
    message_heuristic = THEME.index('var messageCount=list?list.children.length:0;')
    scroll_heuristic = THEME.index('var pageY=window.scrollY||document.documentElement.scrollTop||0;')
    assert reading_branch < message_heuristic
    assert reading_branch < scroll_heuristic
    assert 'root.style.setProperty("--glass-art-x","0px");' in THEME[reading_branch:message_heuristic]
    assert 'root.style.setProperty("--glass-art-y","0px");' in THEME[reading_branch:message_heuristic]
    assert 'root.style.setProperty("--glass-art-scale","1");' in THEME[reading_branch:message_heuristic]
    assert 'root.style.setProperty("--glass-reveal","0");' in THEME[reading_branch:message_heuristic]
    assert 'resetGlassPointer();' in THEME[reading_branch:message_heuristic]


def test_pointer_motion_remains_home_cinematic_but_is_off_during_reading() -> None:
    pointer = THEME.split("function updateGlassPointer(event){", 1)[1].split("function resetGlassPointer", 1)[0]
    assert 'if(glassMode()==="reading")' in pointer
    assert "resetGlassPointer();" in pointer
    assert 'root.style.setProperty("--glass-pointer-x",(nx*8).toFixed(1)+"px");' in pointer
    assert 'root.style.setProperty("--glass-pointer-y",(ny*5).toFixed(1)+"px");' in pointer


def test_original_home_cinematic_reveal_and_variants_are_preserved() -> None:
    for token in [
        'GLASS_VARIANTS=["female","male"]',
        'var messageTravel=messageCount*.28;',
        'var travel=messageTravel+overflowTravel+scrollTravel;',
        'var reveal=smoothstep(pingPong(travel));',
        'var restMaskStart=variant==="male"?0:2;',
        'var restMaskFull=variant==="male"?22:26;',
        'var openMaskFull=variant==="male"?12:14;',
    ]:
        assert token in THEME
    assert 'padiem-glass-female.jpg' in PORTRAIT
    assert 'padiem-glass-male.jpg' in PORTRAIT


def test_reading_css_is_glass_only_and_reduces_visual_noise() -> None:
    assert 'data-theme="padiem-glass"' in READING
    assert 'data-glass-mode="reading"' in READING
    assert 'body::after' in READING
    assert 'opacity: .025;' in READING
    assert '.main-panel::before' in READING
    assert 'opacity: .14;' in READING
    assert '.conversation' in READING
    assert 'rgba(251, 252, 253, .97)' in READING
    for other_theme in ['data-theme="light"', 'data-theme="dark"', 'data-theme="cinematic"', 'data-theme="padiem-home"']:
        assert other_theme not in READING


def test_mobile_reading_posture_is_calmer_and_overflow_is_not_hidden() -> None:
    assert '@media (max-width: 920px)' in READING
    assert '@media (max-width: 620px)' in READING
    assert 'opacity: .08;' in READING
    assert 'opacity: .055;' in READING
    assert 'overflow-x: hidden' not in READING


def test_reduced_motion_remains_authoritative_in_js_and_css() -> None:
    assert 'prefersReducedMotion()' in THEME
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)")' in THEME
    reduced = THEME.split('if(prefersReducedMotion()){', 1)[1].split('if(mode==="reading")', 1)[0]
    assert 'root.style.setProperty("--glass-art-x","0px");' in reduced
    assert 'root.style.setProperty("--glass-art-y","0px");' in reduced
    assert 'resetGlassPointer();' in reduced
    assert '@media (prefers-reduced-motion: reduce)' in READING
    assert 'transform: none !important;' in READING
    assert 'transition: none !important;' in READING


def test_glass_reading_layer_is_loaded_after_existing_glass_layers() -> None:
    base = THEME.index('ensureStylesheet("./padiem-glass.css"')
    portrait = THEME.index('ensureStylesheet("./padiem-glass-portrait.css"')
    reading = THEME.index('ensureStylesheet("./padiem-glass-reading.css"')
    assert base < portrait < reading


def test_no_new_persistence_or_product_authority() -> None:
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "document.cookie", "cookieStore"]:
        assert forbidden not in THEME
    assert "/api/" not in READING
    assert "provider" not in READING.lower()
    assert "model" not in READING.lower()
