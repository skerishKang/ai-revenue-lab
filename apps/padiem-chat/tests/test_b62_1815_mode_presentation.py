from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPABILITIES = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")


def test_browser_exposes_only_plus_and_pro_tiers() -> None:
    assert 'AVAILABLE_TIERS = Object.freeze(["plus", "pro"])' in CAPABILITIES
    assert 'createModeOption("plus")' in CAPABILITIES
    assert 'createModeOption("pro")' in CAPABILITIES
    assert 'createModeOption("max")' not in CAPABILITIES
    assert 'createModeOption("auto"' not in CAPABILITIES
    assert 'createModeOption("fast"' not in CAPABILITIES
    assert 'createModeOption("balanced"' not in CAPABILITIES
    assert 'createModeOption("deep"' not in CAPABILITIES


def test_pro_is_default_and_selection_is_shared_by_chat_and_claw() -> None:
    assert 'let selectedTier = "pro";' in CAPABILITIES
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
