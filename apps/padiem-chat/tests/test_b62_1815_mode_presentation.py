from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPABILITIES = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
THEMES = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
GLASS = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
GLASS_READING = (STATIC / "padiem-glass-reading.css").read_text(encoding="utf-8")
CERT_QA = (ROOT.parent.parent / ".github" / "scripts" / "b62_product_surface_certification_browser_qa.py").read_text(encoding="utf-8")


def test_browser_exposes_only_plus_tier_while_pro_and_max_are_hold() -> None:
    assert 'AVAILABLE_TIERS = Object.freeze(["plus"])' in CAPABILITIES
    assert 'createModeOption("plus")' in CAPABILITIES
    assert 'createModeOption("pro")' not in CAPABILITIES
    assert 'createModeOption("max")' not in CAPABILITIES
    assert 'createModeOption("auto"' not in CAPABILITIES
    assert 'createModeOption("fast"' not in CAPABILITIES
    assert 'createModeOption("balanced"' not in CAPABILITIES
    assert 'createModeOption("deep"' not in CAPABILITIES


def test_plus_is_default_and_selection_is_shared_by_chat_and_claw() -> None:
    assert 'let selectedTier = "plus";' in CAPABILITIES
    assert 'window.PadiemTierSelection = Object.freeze({' in CAPABILITIES
    assert 'tier: selectedProductTier()' in APP
    assert 'const payload = { messages: outboundMessages, mode: "auto", tier: selectedProductTier(), skill };' in APP


def test_tier_copy_contains_no_provider_or_model_authority() -> None:
    tier_block = CAPABILITIES.split("const TIER_COPY", 1)[1].split("let selectedTier", 1)[0].lower()
    for forbidden in (
        "openai",
        "anthropic",
        "claude",
        "gemini",
        "poolside",
        "laguna",
        "nemotron",
        "openrouter",
        "provider_id",
        "model_id",
    ):
        assert forbidden not in tier_block


def test_old_user_visible_auto_fast_balanced_deep_copy_is_removed() -> None:
    for old_copy in (
        "Only Auto is connected to live execution right now.",
        "현재 실제 실행은 Auto만 연결되어 있습니다.",
        "Fast · Balanced · Deep",
    ):
        assert old_copy not in CAPABILITIES


def test_tier_controls_are_keyboard_and_touch_ready() -> None:
    assert 'modePill.setAttribute("role", "button")' in CAPABILITIES
    assert 'modePill.setAttribute("tabindex", "0")' in CAPABILITIES
    assert 'modePill.setAttribute("aria-haspopup", "dialog")' in CAPABILITIES
    assert 'event.key === "Enter" || event.key === " "' in CAPABILITIES
    assert 'event.key === "Escape"' in CAPABILITIES
    assert "min-height: 48px" in CSS
    assert "@media (max-width: 720px)" in CSS


def test_browser_never_renders_internal_provider_or_model_route_metadata() -> None:
    assert "route-details" not in APP
    assert '"route-question"' not in LOCALE
    assert '"provider-route"' not in LOCALE
    assert '"model-label"' not in LOCALE
    for stylesheet in (THEMES, GLASS, GLASS_READING):
        assert ".route-details" not in stylesheet


def test_legacy_mode_qa_and_html_markers_are_removed() -> None:
    assert "Legacy regression marker only" not in INDEX
    assert "mode_fast_balanced_deep" not in CERT_QA
    assert "Fast / Balanced / Deep trusted execution mapping" not in CERT_QA
    assert '"surface": "tier_plus_only"' in CERT_QA
    assert '"surface": "tier_max"' in CERT_QA
    assert '"presentation": "BROWSER_HIDDEN"' in CERT_QA


def test_tier_trigger_and_popover_are_composer_anchored() -> None:
    topbar = INDEX.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]
    composer_tools = INDEX.split('<div class="composer-tools">', 1)[1].split("</div>", 1)[0]
    assert 'model-pill' not in topbar
    assert 'model-pill composer-tier-trigger' in composer_tools
    assert 'type="button"' in composer_tools
    assert 'const modeHost = document.querySelector(".composer-tools");' in CAPABILITIES
    assert 'modeHost.classList.add("tier-control-host")' in CAPABILITIES
    assert "modeHost.appendChild(modePanel)" in CAPABILITIES
    assert "document.body.appendChild(modePanel)" not in CAPABILITIES
    assert ".tier-control-host" in CSS
    assert "position: absolute" in CSS
    assert "bottom: calc(100% + 12px)" in CSS
    assert "position: fixed" not in CSS
    assert "top: 68px" not in CSS


def test_glass_tier_trigger_stays_visible_on_bright_composer() -> None:
    selector = 'html[data-theme="padiem-glass"] .composer .model-pill[data-mode-control="true"] {'
    assert selector in CSS
    block = CSS.split(selector, 1)[1].split("}", 1)[0]
    assert "background: rgba(255, 255, 255, .62)" in block
    assert "color: #25333e" in block
    assert 'html[data-theme="padiem-glass"] .composer .model-pill[data-mode-control="true"]:hover {' in CSS
    spark_selector = 'html[data-theme="padiem-glass"] .composer .model-pill[data-mode-control="true"] .status-spark {'
    assert spark_selector in CSS
    spark_block = CSS.split(spark_selector, 1)[1].split("}", 1)[0]
    assert "color: #4f86ad" in spark_block
    assert "opacity: 1" in spark_block


def test_glass_tier_popover_uses_bright_frosted_surface_not_dark_group() -> None:
    assert 'html[data-theme="padiem-glass"] .mode-presentation-panel {' in CSS
    glass_block = CSS.split('html[data-theme="padiem-glass"] .mode-presentation-panel {', 1)[1].split("}", 1)[0]
    assert "rgba(252, 253, 254, .96)" in glass_block
    assert "color: #17212a" in glass_block
    assert "blur(28px)" in glass_block
    dark_group = CSS.split('html[data-theme="dark"] .mode-presentation-panel,', 1)[1].split("{", 1)[0]
    assert 'padiem-glass' not in dark_group
