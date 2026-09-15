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


def test_glass_reading_suppresses_old_scroll_travel_but_accepts_answer_activity() -> None:
    assert 'var answerReveal=mode==="reading"?glassAnswerReveal(now):0;' in THEME
    assert 'if(mode!=="reading"){' in THEME
    message_heuristic = THEME.index('var messageCount=list?list.children.length:0;')
    home_gate = THEME.rindex('if(mode!=="reading"){', 0, message_heuristic)
    assert home_gate < message_heuristic
    assert 'var scrollTravel=pageY/Math.max(520,window.innerHeight*.72);' in THEME
    assert 'noteGlassAnswerActivity()' in THEME
    assert 'mutations.some(mutationTouchesAssistant)' in THEME


def test_pointer_motion_drives_reveal_in_home_and_reading_modes() -> None:
    pointer = THEME.split("function updateGlassPointer(event){", 1)[1].split("function resetGlassPointer", 1)[0]
    assert 'if(glassMode()==="reading")' not in pointer
    assert 'glassPointerReveal=smoothstep(proximity);' in pointer
    assert 'root.style.setProperty("--glass-pointer-x",(nx*8*glassPointerReveal).toFixed(1)+"px");' in pointer
    assert 'root.style.setProperty("--glass-pointer-y",(ny*5*glassPointerReveal).toFixed(1)+"px");' in pointer
    assert 'queueGlassMotion();' in pointer


def test_home_cinematic_reveal_and_variants_are_preserved() -> None:
    for token in [
        'GLASS_VARIANTS=["female","male"]',
        'var messageTravel=messageCount*.28;',
        'var travel=messageTravel+overflowTravel+scrollTravel;',
        'baseReveal=smoothstep(pingPong(travel));',
        'var restMaskStart=reading?(variant==="male"?28:30):(variant==="male"?0:2);',
        'var restMaskFull=reading?(variant==="male"?50:54):(variant==="male"?22:26);',
        'var openMaskFull=reading?(variant==="male"?20:24):(variant==="male"?12:14);',
    ]:
        assert token in THEME
    assert 'padiem-glass-female.jpg' in PORTRAIT
    assert 'padiem-glass-male.jpg' in PORTRAIT


def test_pointer_and_answer_reveal_are_composed_together_boundedly() -> None:
    assert 'var pointerReveal=glassHoverCapable()?glassPointerReveal:0;' in THEME
    assert 'var answerReveal=mode==="reading"?glassAnswerReveal(now):0;' in THEME
    assert '*(1-pointerReveal*.78)' in THEME
    assert '*(1-answerReveal*.86);' in THEME
    assert 'reveal=Math.max(0,Math.min(1,reveal));' in THEME


def test_reading_css_is_glass_only_and_reduces_visual_noise() -> None:
    assert 'data-theme="padiem-glass"' in READING
    assert 'data-glass-mode="reading"' in READING
    assert 'body::after' in READING
    assert 'opacity: .025;' in READING
    assert '.main-panel::before' in READING
    # #2093-4: reading-mode hero presence was rebalanced .14 -> .28 so the
    # brand visual stays calm but visible behind the conversation.
    assert 'opacity: .28;' in READING
    assert '.conversation' in READING
    assert 'rgba(251, 252, 253, .97)' in READING
    for other_theme in ['data-theme="light"', 'data-theme="dark"', 'data-theme="cinematic"', 'data-theme="padiem-home"']:
        assert other_theme not in READING


def test_reading_surface_overrides_legacy_chat_glass_with_explicit_state_scope() -> None:
    selector = 'html[data-theme="padiem-glass"][data-glass-mode="reading"] body .app-shell[data-state="chat"] .conversation'
    assert selector in READING
    block = READING.split(selector, 1)[1].split("}", 1)[0]
    assert 'rgba(251, 252, 253, .97)' in block
    assert 'rgba(242, 246, 248, .94)' in block
    assert 'background:' in block and '!important' in block
    assert 'border-color:' in block and '!important' in block
    assert 'box-shadow:' in block and '!important' in block


def test_mobile_reading_posture_is_calmer_and_overflow_is_not_hidden() -> None:
    assert '@media (max-width: 920px)' in READING
    assert '@media (max-width: 620px)' in READING
    # #2093-4: breakpoints scale proportionally (.16 / .10) and stay calmer
    # than the desktop .28 posture. Scope to each media block because the
    # reduced-motion block also carries an .08 opacity.
    tablet = READING.split('@media (max-width: 920px)', 1)[1].split('@media (max-width: 620px)', 1)[0]
    assert 'opacity: .16;' in tablet
    mobile = READING.split('@media (max-width: 620px)', 1)[1].split('@media (prefers-reduced-motion', 1)[0]
    assert 'opacity: .10;' in mobile
    assert 'overflow-x: hidden' not in READING


def test_reduced_motion_remains_authoritative_in_js_and_css() -> None:
    assert 'prefersReducedMotion()' in THEME
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)")' in THEME
    reduced = THEME.split('if(prefersReducedMotion()){', 1)[1].split('var now=currentGlassTime();', 1)[0]
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
