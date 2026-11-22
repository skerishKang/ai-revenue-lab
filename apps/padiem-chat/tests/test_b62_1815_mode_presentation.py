from __future__ import annotations

from _r5_product_capabilities_harness import run_capabilities_scenario
from _support.mode_presentation import (
    cert_qa_dict_pairs,
    cert_qa_string_constants,
    create_mode_option_string_args,
    css_all_declaration_pairs,
    css_custom_property,
    css_declarations,
    css_media_conditions,
    css_rule_selector_lists,
    css_selectors,
    index_facts,
    js_identifiers,
    js_property_string_pairs,
    js_string_literals,
    locale_array_bindings,
    locale_keys,
    streaming_payload_entries,
    tier_copy_facts,
)


GLASS_TRIGGER = (
    'html[data-theme="padiem-glass"] .composer .model-pill[data-mode-control="true"]'
)
GLASS_PANEL = 'html[data-theme="padiem-glass"] .mode-presentation-panel'
DARK_PANEL = 'html[data-theme="dark"] .mode-presentation-panel'


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
    # 생겨서는 안 된다. createModeOption의 문자열 인자(파싱 값)로 확인한다.
    literal_args = create_mode_option_string_args()
    for legacy in ("auto", "fast", "balanced", "deep"):
        assert legacy not in literal_args


def test_guest_sees_only_free_as_usable_and_custom_lane_is_locked() -> None:
    """게스트 화면도 실제 렌더로 관찰한다: free만 사용 가능, Custom 칩은 잠김."""
    guest = run_capabilities_scenario("mode_tiers_guest")
    assert guest["tierGet"] == "free"
    assert guest["optionStatuses"] == ["available", "upgrade", "upgrade", "upgrade"]
    assert guest["customDisabled"] is True
    assert guest["customAriaDisabled"] == "true"


def test_plus_is_default_and_selection_is_shared_by_chat_and_claw() -> None:
    # 기본 등급과 공유 API는 실행으로 관찰한다: 게스트는 free에서 시작하고,
    # PadiemTierSelection은 Chat/Claw가 같은 조작으로 쓰는 조작 세트를 노출한다.
    guest = run_capabilities_scenario("mode_tiers_guest")
    assert guest["tierGet"] == "free"
    member = run_capabilities_scenario("mode_tiers")
    assert member["tierSelectionKeys"] == ["get", "set", "available", "open", "close", "ready"]
    # 요청 payload 객체의 선언 순서와 항목을 파싱 값으로 확인한다.
    assert list(streaming_payload_entries().items()) == [
        ("messages", "outboundMessages"),
        ("tier", "deps.selectedProductTier()"),
        ("skill", "skill"),
    ]
    # The chat `mode` request key is gone with the remnant it came from: no client
    # sends it, and the contract refuses it as an unknown item.
    assert ("mode", "auto") not in js_property_string_pairs("app.js")
    assert ("mode", "auto") not in js_property_string_pairs("chat-streaming-module.js")


def test_tier_copy_contains_no_provider_or_model_authority() -> None:
    """구조 계약(부재 금지): 등급 문구 표에 공급사·모델 권위가 없어야 한다.
    문구 표의 어휘(문자열 리터럴·식별자)를 파싱해 확인한다."""
    facts = tier_copy_facts()
    vocabulary = {token.lower() for token in facts["literals"] | facts["identifiers"]}
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
        assert not any(forbidden in token for token in vocabulary), forbidden


def test_old_user_visible_auto_fast_balanced_deep_copy_is_removed() -> None:
    """구조 계약(부재 금지): 레거시 문구는 소스에 다시 생기면 안 된다."""
    literals = js_string_literals("product-capabilities.js")
    for old_copy in (
        "Only Auto is connected to live execution right now.",
        "현재 실제 실행은 Auto만 연결되어 있습니다.",
        "Fast · Balanced · Deep",
    ):
        assert not any(old_copy in literal for literal in literals), old_copy


def test_tier_controls_are_keyboard_and_touch_ready() -> None:
    """모드알(role·tabindex·aria)과 Enter/Escape 배선은 실제 키 입력으로 관찰한다."""
    member = run_capabilities_scenario("mode_tiers")
    assert member["pillAttrs"]["role"] == "button"
    assert member["pillAttrs"]["tabindex"] == "0"
    assert member["pillAttrs"]["haspopup"] == "dialog"
    assert member["pillAttrs"]["expanded"] == "true"  # 패널을 연 뒤
    assert member["panelHiddenAfterEscape"] is True
    assert member["panelHiddenAfterEnter"] is False
    declarations = css_all_declaration_pairs("mode-presentation.css")
    assert ("min-height", "48px") in declarations
    assert "(max-width: 720px)" in css_media_conditions("mode-presentation.css")


def test_browser_never_renders_internal_provider_or_model_route_metadata() -> None:
    app_vocabulary = js_identifiers("app.js") | js_string_literals("app.js")
    assert not any("route-details" in token for token in app_vocabulary)
    locale_vocabulary = set(locale_keys("ko")) | set(locale_keys("en"))
    for key in ("route-question", "provider-route", "model-label"):
        assert key not in locale_vocabulary
    for sheet in ("padiem-themes.css", "padiem-glass.css", "padiem-glass-reading.css"):
        assert all("route-details" not in selector for selector in css_selectors(sheet))
        assert all(
            "route-details" not in value
            for _prop, value in css_all_declaration_pairs(sheet)
        )


def test_legacy_mode_qa_and_html_markers_are_removed() -> None:
    facts = index_facts()
    assert not any("Legacy regression marker only" in text for text in facts["text_nodes"])
    constants = cert_qa_string_constants()
    assert "mode_fast_balanced_deep" not in constants
    assert not any("Fast / Balanced / Deep trusted execution mapping" in c for c in constants)
    pairs = cert_qa_dict_pairs()
    assert ("surface", "tier_free_baseline") in pairs
    assert ("surface", "tier_max") in pairs
    assert ("presentation", "BROWSER_HIDDEN") in pairs


def test_tier_trigger_and_popover_are_composer_anchored() -> None:
    """트리거·패널 배치는 실제 부착 결과로 관찰한다: 패널은 composer-tools 안에."""
    member = run_capabilities_scenario("mode_tiers")
    assert member["panelFound"] is True
    assert member["panelParentIsModeHost"] is True
    assert member["panelInDocumentBody"] is False
    assert member["styleLinkInHead"] is True
    facts = index_facts()
    assert all(
        "model-pill" not in value
        for _tag, attrs in facts["topbar_elements"]
        for value in attrs.values()
        if value is not None
    )
    composer_tokens = [
        set(attrs.get("class", "").split())
        for _tag, attrs in facts["composer_tools_elements"]
    ]
    assert any({"model-pill", "composer-tier-trigger"} <= tokens for tokens in composer_tokens)
    assert any(
        attrs.get("type") == "button" for _tag, attrs in facts["composer_tools_elements"]
    )
    declarations = css_all_declaration_pairs("mode-presentation.css")
    assert ".tier-control-host" in css_selectors("mode-presentation.css")
    assert ("position", "absolute") in declarations
    assert ("bottom", "calc(100% + 12px)") in declarations
    assert ("position", "fixed") not in declarations
    assert ("top", "68px") not in declarations


def test_glass_tier_trigger_stays_visible_on_bright_composer() -> None:
    trigger = css_declarations("mode-presentation.css", GLASS_TRIGGER)
    assert trigger["background"] == "rgba(255, 255, 255, .62)"
    assert trigger["color"] == "#25333e"
    assert css_declarations("mode-presentation.css", GLASS_TRIGGER + ":hover")
    assert "status-spark" not in index_facts()["all_class_tokens"]


def test_glass_tier_popover_uses_bright_frosted_surface_not_dark_group() -> None:
    panel = css_declarations("mode-presentation.css", GLASS_PANEL)
    assert "rgba(252, 253, 254, .96)" in panel["background"]
    # #7187 9차: 패널 글자는 쓰임새 토큰이 소유한다(토큰 값은 토큰 파일에서 확인).
    assert panel["color"] == "var(--text-panel-ink)"
    assert css_custom_property("padiem-tokens.css", "--text-panel-ink") == "#17212a"
    assert "blur(28px)" in panel["backdrop-filter"]
    dark_lists = css_rule_selector_lists("mode-presentation.css", DARK_PANEL)
    assert dark_lists
    assert all(
        "padiem-glass" not in selector
        for selectors in dark_lists
        for selector in selectors
    )


def test_tier_pill_copy_owns_the_tier_key_instead_of_the_legacy_mode_label() -> None:
    ko, en = locale_keys("ko"), locale_keys("en")
    for table in (ko, en):
        assert "mode" not in table
        assert "tier" in table
    assert ko["tier"] == "AI 등급"
    assert en["tier"] == "AI tier"
    arrays = locale_array_bindings()
    assert (".model-pill span:last-child", "mode") not in arrays
    assert (".model-pill", "aria-label", "mode") not in arrays
    assert (".model-pill", "aria-label", "tier") in arrays
    aria_labels = index_facts()["data_locale_aria_label_values"]
    assert "mode" not in aria_labels
    assert "tier" in aria_labels
