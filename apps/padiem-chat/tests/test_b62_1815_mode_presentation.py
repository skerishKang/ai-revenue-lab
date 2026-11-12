from __future__ import annotations

from pathlib import Path

from _r5_product_capabilities_harness import run_capabilities_scenario


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


def test_browser_lists_all_four_tiers_but_only_plus_is_selectable() -> None:
    """등급 칸은 실제 렌더로 관찰한다(#7186): 순서·상태·비활성·선택 배선."""
    member = run_capabilities_scenario("mode_tiers")
    assert member["optionValues"] == ["free", "plus", "pro", "max"]
    assert member["optionStatuses"] == ["available", "available", "upgrade", "upgrade"]
    assert member["optionDisabled"] == [False, False, False, False]
    assert member["optionIcons"] == ["✓", "✓", "↑", "↑"]
    # plus 회원이 free를 고르면 선택이 바뀌고 서버 저장(PUT)이 같은 등급으로 간다.
    assert member["tierGetAfterFreeClick"] == "free"
    assert member["tierEvents"] == ["free"]
    assert member["selectionPut"] == ['{"tier":"free"}']
    # 상위 등급 클릭은 선택을 바꾸지 않고 안내만 남긴다.
    assert member["tierGetAfterUpgradeClick"] == "free"
    assert member["upgradeTruthText"] == "더 높은 등급의 모델을 사용하려면 업그레이드가 필요합니다."
    assert member["upgradeTruthHighlighted"] is True
    # 구조 계약(부재 금지): 레거시 auto·fast·balanced·deep 칸은 소스에 다시
    # 생겨서는 안 된다. 실행 관찰로는 "없어야 할 것"을 증명할 수 없어 문자열로 남긴다.
    for legacy in ("auto", "fast", "balanced", "deep"):
        assert f'createModeOption("{legacy}"' not in CAPABILITIES


def test_guest_sees_only_free_as_usable_and_custom_lane_is_locked() -> None:
    """게스트 화면도 실제 렌더로 관찰한다: free만 사용 가능, Custom 칩은 잠김."""
    guest = run_capabilities_scenario("mode_tiers_guest")
    assert guest["tierGet"] == "free"
    assert guest["optionStatuses"] == ["available", "upgrade", "upgrade", "upgrade"]
    assert guest["customDisabled"] is True
    assert guest["customAriaDisabled"] == "true"


def test_plus_is_default_and_selection_is_shared_by_chat_and_claw() -> None:
    stream = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
    # 기본 등급과 공유 API는 실행으로 관찰한다: 게스트는 free에서 시작하고,
    # PadiemTierSelection은 Chat/Claw가 같은 조작으로 쓰는 조작 세트를 노출한다.
    guest = run_capabilities_scenario("mode_tiers_guest")
    assert guest["tierGet"] == "free"
    member = run_capabilities_scenario("mode_tiers")
    assert member["tierSelectionKeys"] == ["get", "set", "available", "open", "close", "ready"]
    assert "tier: deps.selectedProductTier()" in stream
    assert 'const payload = { messages: outboundMessages, tier: deps.selectedProductTier(), skill };' in stream
    # The chat `mode` request key is gone with the remnant it came from: no client
    # sends it, and the contract refuses it as an unknown item.
    assert 'mode: "auto"' not in APP
    assert 'mode: "auto"' not in stream


def test_tier_copy_contains_no_provider_or_model_authority() -> None:
    """구조 계약(부재 금지): 등급 문구 표에 공급사·모델 권위가 없어야 한다.
    문구 표 자체는 데이터 계약이라 문자열로 남긴다."""
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
    """구조 계약(부재 금지): 레거시 문구는 소스에 다시 생기면 안 된다."""
    for old_copy in (
        "Only Auto is connected to live execution right now.",
        "현재 실제 실행은 Auto만 연결되어 있습니다.",
        "Fast · Balanced · Deep",
    ):
        assert old_copy not in CAPABILITIES


def test_tier_controls_are_keyboard_and_touch_ready() -> None:
    """모드알(role·tabindex·aria)과 Enter/Escape 배선은 실제 키 입력으로 관찰한다."""
    member = run_capabilities_scenario("mode_tiers")
    assert member["pillAttrs"]["role"] == "button"
    assert member["pillAttrs"]["tabindex"] == "0"
    assert member["pillAttrs"]["haspopup"] == "dialog"
    assert member["pillAttrs"]["expanded"] == "true"  # 패널을 연 뒤
    assert member["panelHiddenAfterEscape"] is True
    assert member["panelHiddenAfterEnter"] is False
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
    assert '"surface": "tier_free_baseline"' in CERT_QA
    assert '"surface": "tier_max"' in CERT_QA
    assert '"presentation": "BROWSER_HIDDEN"' in CERT_QA


def test_tier_trigger_and_popover_are_composer_anchored() -> None:
    """트리거·패널 배치는 실제 부착 결과로 관찰한다: 패널은 composer-tools 안에."""
    member = run_capabilities_scenario("mode_tiers")
    assert member["panelFound"] is True
    assert member["panelParentIsModeHost"] is True
    assert member["panelInDocumentBody"] is False
    assert member["styleLinkInHead"] is True
    topbar = INDEX.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]
    composer_tools = INDEX.split('<div class="composer-tools">', 1)[1].split("</div>", 1)[0]
    assert 'model-pill' not in topbar
    assert 'model-pill composer-tier-trigger' in composer_tools
    assert 'type="button"' in composer_tools
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
    assert 'class="status-spark"' not in INDEX


def test_glass_tier_popover_uses_bright_frosted_surface_not_dark_group() -> None:
    assert 'html[data-theme="padiem-glass"] .mode-presentation-panel {' in CSS
    glass_block = CSS.split('html[data-theme="padiem-glass"] .mode-presentation-panel {', 1)[1].split("}", 1)[0]
    assert "rgba(252, 253, 254, .96)" in glass_block
    assert "color: #17212a" in glass_block
    assert "blur(28px)" in glass_block
    dark_group = CSS.split('html[data-theme="dark"] .mode-presentation-panel,', 1)[1].split("{", 1)[0]
    assert 'padiem-glass' not in dark_group


def test_tier_pill_copy_owns_the_tier_key_instead_of_the_legacy_mode_label() -> None:
    ko, en = LOCALE.split("en: {", 1)
    for table in (ko, en):
        assert '"mode"' not in table
        assert '"tier"' in table
    assert '"tier": "AI 등급"' in ko
    assert '"tier": "AI tier"' in en
    assert '[".model-pill span:last-child", "mode"]' not in LOCALE
    assert '[".model-pill", "aria-label", "mode"]' not in LOCALE
    assert '[".model-pill", "aria-label", "tier"]' in LOCALE
    assert 'data-locale-aria-label="mode"' not in INDEX
    assert 'data-locale-aria-label="tier"' in INDEX
