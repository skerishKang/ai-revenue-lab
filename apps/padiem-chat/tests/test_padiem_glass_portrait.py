from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
THEME_JS = (STATIC / "theme.js").read_text(encoding="utf-8")
THEME_INIT = (STATIC / "theme-init.js").read_text(encoding="utf-8")
PORTRAIT_CSS = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_glass_portrait_assets_are_local_and_additive() -> None:
    female = STATIC / "assets/padiem-glass-female.jpg"
    male = STATIC / "assets/padiem-glass-male.jpg"
    assert female.is_file()
    assert male.is_file()
    assert female.stat().st_size > 1_000
    assert male.stat().st_size > 1_000
    assert './assets/padiem-glass-female.jpg' in PORTRAIT_CSS
    assert './assets/padiem-glass-male.jpg' in PORTRAIT_CSS
    assert "drive.google.com" not in PORTRAIT_CSS
    assert "http://" not in PORTRAIT_CSS
    assert "https://" not in PORTRAIT_CSS


def test_glass_has_female_and_male_background_variants() -> None:
    assert 'data-glass-variant="female"' in PORTRAIT_CSS
    assert 'data-glass-variant="male"' in PORTRAIT_CSS
    assert 'GLASS_VARIANTS=["female","male"]' in THEME_JS
    assert 'data-glass-variant-value' in THEME_JS
    assert 'Padiem Glass background' in THEME_JS
    assert 'Female' in THEME_JS
    assert 'Male' in THEME_JS


def test_glass_variant_is_url_authoritative_without_browser_storage() -> None:
    assert 'get("glass")' in THEME_JS
    assert 'searchParams.set("glass",variant)' in THEME_JS
    assert 'get("glass")' in THEME_INIT
    assert 'data-glass-variant' in THEME_INIT
    for forbidden in [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "cookieStore",
    ]:
        assert forbidden not in THEME_JS
        assert forbidden not in THEME_INIT


def test_glass_reserves_right_portrait_zone_and_opaque_chat_surface() -> None:
    assert '.main-panel::before' in PORTRAIT_CSS
    assert 'background-image: var(--padiem-glass-portrait-image)' in PORTRAIT_CSS
    assert '--glass-chat-surface: rgba(238, 242, 245, .82)' in PORTRAIT_CSS
    assert '--glass-composer-surface: rgba(248, 250, 251, .90)' in PORTRAIT_CSS
    assert 'backdrop-filter: blur(30px)' in PORTRAIT_CSS
    assert 'backdrop-filter: blur(32px)' in PORTRAIT_CSS
    assert '@media (min-width: 1280px)' in PORTRAIT_CSS
    assert 'margin-left: clamp(36px, 4vw, 72px)' in PORTRAIT_CSS
    assert 'width: clamp(360px, 32vw, 560px)' in PORTRAIT_CSS


def test_glass_mask_is_dynamic_not_fixed() -> None:
    assert '@property --glass-mask-start' in PORTRAIT_CSS
    assert '@property --glass-mask-full' in PORTRAIT_CSS
    assert '--glass-mask-start: 20%' in PORTRAIT_CSS
    assert '--glass-mask-full: 48%' in PORTRAIT_CSS
    assert 'to left,' in PORTRAIT_CSS
    assert 'transparent var(--glass-mask-start)' in PORTRAIT_CSS
    assert '#000 var(--glass-mask-full)' in PORTRAIT_CSS
    assert '--glass-mask-start 560ms' in PORTRAIT_CSS
    assert '--glass-mask-full 560ms' in PORTRAIT_CSS





def test_glass_face_reveal_targets_right_aligned_portrait_zone() -> None:
    assert 'to left,' in PORTRAIT_CSS
    assert '--glass-mask-start: 18%' in PORTRAIT_CSS
    assert '--glass-mask-full: 46%' in PORTRAIT_CSS
    assert '--glass-mask-start: 14%' in PORTRAIT_CSS
    assert '--glass-mask-full: 42%' in PORTRAIT_CSS
    assert 'var restMaskStart=reading?(variant==="male"?30:34):(variant==="male"?14:18);' in THEME_JS
    assert 'var restMaskFull=reading?(variant==="male"?58:62):(variant==="male"?42:46);' in THEME_JS
    assert 'var openMaskFull=reading?(variant==="male"?20:22):(variant==="male"?8:10);' in THEME_JS
    assert 'root.style.setProperty("--glass-reading-art-opacity"' in THEME_JS


def test_glass_mobile_keeps_chat_primary_and_art_subordinate() -> None:
    assert '@media (max-width: 920px)' in PORTRAIT_CSS
    assert 'opacity: .22' in PORTRAIT_CSS
    assert 'background: rgba(242, 245, 247, .90)' in PORTRAIT_CSS
    assert 'background: rgba(249, 251, 252, .94)' in PORTRAIT_CSS
    assert '@media (max-width: 620px)' in PORTRAIT_CSS
    assert 'opacity: .16' in PORTRAIT_CSS


def test_glass_portrait_reveal_combines_home_travel_pointer_and_live_answer_activity() -> None:
    assert 'function pingPong(value)' in THEME_JS
    assert 'phase<=1?phase:2-phase' in THEME_JS
    assert 'list.children.length' in THEME_JS
    assert 'conversationHeight=list?list.scrollHeight:0' in THEME_JS
    assert 'overflowTravel=Math.max(0,conversationHeight-visibleConversation)/620' in THEME_JS
    assert 'scrollTravel=pageY/Math.max(520,window.innerHeight*.72)' in THEME_JS
    assert 'messageTravel=messageCount*.28' in THEME_JS
    assert 'var travel=messageTravel+overflowTravel+scrollTravel' in THEME_JS
    assert 'baseReveal=smoothstep(pingPong(travel))' in THEME_JS
    assert 'glassPointerReveal=smoothstep(proximity);' in THEME_JS
    assert 'function glassAnswerReveal(now)' in THEME_JS
    assert 'noteGlassAnswerActivity()' in THEME_JS
    assert '*(1-pointerReveal*.94)' in THEME_JS
    assert '*(1-answerReveal*.90);' in THEME_JS
    assert '--glass-mask-start' in THEME_JS
    assert '--glass-mask-full' in THEME_JS
    assert '--glass-reveal' in THEME_JS
    assert 'MutationObserver' in THEME_JS
    assert 'requestAnimationFrame' in THEME_JS


def test_glass_pointer_is_subtle_and_also_drives_reveal() -> None:
    assert 'window.addEventListener("pointermove",updateGlassPointer' in THEME_JS
    assert 'glassPointerReveal=smoothstep(proximity);' in THEME_JS
    assert '(nx*8*glassPointerReveal)' in THEME_JS
    assert '(ny*5*glassPointerReveal)' in THEME_JS
    assert '--glass-pointer-x' in THEME_JS
    assert '--glass-pointer-y' in THEME_JS
    assert 'calc(var(--glass-art-x) + var(--glass-pointer-x))' in PORTRAIT_CSS
    assert 'calc(var(--glass-art-y) + var(--glass-pointer-y))' in PORTRAIT_CSS


def test_glass_reduced_motion_freezes_to_readable_reveal() -> None:
    assert 'prefers-reduced-motion: reduce' in THEME_JS
    assert 'root.style.setProperty("--glass-mask-start","6%")' in THEME_JS
    assert 'root.style.setProperty("--glass-mask-full","24%")' in THEME_JS
    assert '@media (prefers-reduced-motion: reduce)' in PORTRAIT_CSS
    assert 'transition: none !important' in PORTRAIT_CSS


def test_glass_portrait_preserves_prior_b62_layout_contracts() -> None:
    assert 'href="https://padiem.net/"' in HTML
    assert 'Padiem Chat' in HTML
    assert 'class="sidebar-bottom"' in HTML
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    assert 'id="settingsButton"' not in topbar_html
    assert 'id="loginButton"' not in topbar_html


def test_glass_portrait_has_no_provider_core_or_production_behavior() -> None:
    combined = THEME_JS + THEME_INIT + PORTRAIT_CSS
    for forbidden in [
        "provider_id",
        "selected_provider",
        "selected_model",
        "B14",
        "padiem-ai-core",
        "control-plane",
        "wrangler deploy",
    ]:
        assert forbidden not in combined

def test_glass_rejects_synthetic_cyan_visor_regression() -> None:
    assert ".main-panel::after" not in PORTRAIT_CSS
    assert "--glass-cyber-intensity" not in PORTRAIT_CSS
    assert "--glass-cyber-accent" not in PORTRAIT_CSS
    assert "--glass-cyber-shadow" not in PORTRAIT_CSS
    assert "clip-path: polygon(" not in PORTRAIT_CSS
    assert "data-glass-cyber-active" not in THEME_JS
    assert "data-glass-cyber-state" not in THEME_JS
    assert "--glass-cyber-intensity" not in THEME_JS

SHELL_JS = (STATIC / "padiem-glass-shell.js").read_text(encoding="utf-8")


def test_glass_shell_assets_are_local_paired_and_adopted() -> None:
    """Shell states reuse the adopted faces; only the mask object is transplanted
    from the approved sibling renders (cyber-08 visor, cyber-04 face shell)."""
    female = STATIC / "assets/padiem-glass-female-shell.jpg"
    male = STATIC / "assets/padiem-glass-male-shell.jpg"
    assert female.is_file()
    assert male.is_file()
    assert female.stat().st_size > 1_000
    assert male.stat().st_size > 1_000
    assert './assets/padiem-glass-female-shell.jpg' in PORTRAIT_CSS
    assert './assets/padiem-glass-male-shell.jpg' in PORTRAIT_CSS
    assert 'drive.google.com' not in PORTRAIT_CSS


def test_glass_shell_layer_script_is_loaded() -> None:
    assert 'src="./padiem-glass-shell.js"' in HTML
    assert 'glass-shell-portrait' in SHELL_JS
    assert 'glass-shell-field' in SHELL_JS
    assert 'glass-shell-frag' in SHELL_JS


def test_glass_shell_ports_source_fragment_assembly() -> None:
    """The plate-assembly math is the source loader's, not an invented overlay."""
    # original clipShapes verbatim
    assert 'polygon(8% 0,100% 7%,91% 100%,0 88%)' in SHELL_JS
    assert 'polygon(6% 0,100% 11%,93% 92%,0 100%)' in SHELL_JS
    # golden-angle scatter ring, assemble easing, dissolve->portal swap
    assert 'i*2.399' in SHELL_JS
    assert 'ASSEMBLE_START' in SHELL_JS and 'DISSOLVE_AT' in SHELL_JS
    assert 'requestAnimationFrame' in SHELL_JS
    # shell geometry mirrors the live ::before portrait box
    assert 'getComputedStyle(panel,"::before")' in SHELL_JS
    # fragments carry jigsaw slices of the shell image
    assert 'backgroundPosition' in SHELL_JS
    assert 'padiem-glass-' in SHELL_JS and '-shell.jpg' in SHELL_JS


def test_glass_shell_drivers_are_pointer_and_answer_not_scroll() -> None:
    assert '--glass-pointer-reveal' in SHELL_JS
    assert '--glass-answer-reveal' in SHELL_JS
    assert '--glass-pointer-reveal' in THEME_JS
    assert '--glass-answer-reveal' in THEME_JS


def test_glass_shell_mode_and_speed_are_url_authoritative() -> None:
    assert 'GLASS_MASK_MODES=["auto","on","off"]' in THEME_JS
    assert 'data-glass-mask' in THEME_JS
    assert 'data-glass-mask' in THEME_INIT
    assert 'data-glass-speed' in THEME_JS
    assert 'data-glass-speed' in THEME_INIT
    assert 'get("mask")' in THEME_JS
    assert 'get("mask")' in THEME_INIT
    assert 'get("speed")' in THEME_JS
    assert 'get("speed")' in THEME_INIT
    # browser storage stays forbidden across every glass runtime file
    for forbidden in [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "cookieStore",
    ]:
        assert forbidden not in SHELL_JS


def test_glass_shell_controls_live_in_appearance_settings() -> None:
    assert 'data-glass-mask-value' in THEME_JS
    assert '"auto","Auto"' in THEME_JS
    assert '"on","On"' in THEME_JS
    assert '"off","Off"' in THEME_JS
    assert 'glass-speed-range' in THEME_JS
    assert 'Motion speed' in THEME_JS
    assert 'Shell mask' in THEME_JS
    assert '.glass-mask-picker' in PORTRAIT_CSS
    assert '.glass-speed-range' in PORTRAIT_CSS


def test_glass_shell_respects_reduced_motion_and_theme_gate() -> None:
    assert 'prefers-reduced-motion: reduce' in SHELL_JS
    assert 'data-theme' in SHELL_JS
    assert 'padiem-glass' in SHELL_JS
    # layers stay invisible off-theme
    assert 'html:not([data-theme="padiem-glass"]) .glass-shell-portrait' in PORTRAIT_CSS
    assert 'html:not([data-theme="padiem-glass"]) .glass-shell-field' in PORTRAIT_CSS
