from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPABILITIES = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")


def test_auto_is_the_only_execution_available_mode() -> None:
    assert 'selected: "auto"' in CAPABILITIES
    assert 'available: Object.freeze(["auto"])' in CAPABILITIES
    assert 'previewOnly: Object.freeze(["fast", "balanced", "deep"])' in CAPABILITIES
    assert 'createModeOption("auto", true)' in CAPABILITIES
    assert 'createModeOption("fast", false)' in CAPABILITIES
    assert 'createModeOption("balanced", false)' in CAPABILITIES
    assert 'createModeOption("deep", false)' in CAPABILITIES


def test_mode_presentation_does_not_change_request_routing() -> None:
    assert 'const payload = { messages: outboundMessages, mode: "auto", skill };' in APP
    assert 'mode: "fast"' not in APP
    assert 'mode: "balanced"' not in APP
    assert 'mode: "deep"' not in APP


def test_mode_copy_states_ui_ready_is_not_backend_active() -> None:
    assert "현재 실제 실행은 Auto만 연결되어 있습니다." in CAPABILITIES
    assert "실제 모델 연결 전까지 선택할 수 없습니다." in CAPABILITIES
    assert "Only Auto is connected to live execution right now." in CAPABILITIES
    assert "cannot be selected until trusted backend mappings are active" in CAPABILITIES


def test_mode_ui_contains_no_provider_or_model_authority() -> None:
    mode_block = CAPABILITIES.split("const MODE_COPY", 1)[1].split("let deployment", 1)[0].lower()
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
        assert forbidden not in mode_block


def test_mode_controls_are_keyboard_and_touch_ready() -> None:
    assert 'modePill.setAttribute("role", "button")' in CAPABILITIES
    assert 'modePill.setAttribute("tabindex", "0")' in CAPABILITIES
    assert 'modePill.setAttribute("aria-haspopup", "dialog")' in CAPABILITIES
    assert 'event.key === "Enter" || event.key === " "' in CAPABILITIES
    assert 'event.key === "Escape"' in CAPABILITIES
    assert "min-height: 48px" in CSS
    assert "@media (max-width: 720px)" in CSS
