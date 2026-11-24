"""Chat/Claw answer icons, user avatar, Connectors/Automation standalone pages.

Covers the bounded UI slice: five answer action icons (copy, regenerate,
listen, share, more) with no like/dislike rating, user-bubble avatar, removal
of the repetitive "AI 응답" completion line, and the Connectors/Automation
sidebar entries opening standalone Glass pages that reuse the existing
dialog/panel logic, endpoints and auth gates.
"""

# R5 0단계(R-01): 함수 선언은 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import definition_source

# #8060 34차: 원문 읽기는 _support 헬퍼(answer_views·claw_static)가 담당하고,
# 시험은 파싱 값(아이콘 목록·태그 속성·규칙·locale 키)으로 단언한다.
from _support.answer_views import (
    answer_icon_actions,
    assistant_product_text,
    element_attrs,
    locale_keys,
    script_sources,
    sheet,
    template_tags,
)
from css_rules import find_rules_with_selector, rules_for_sheet


def test_answer_bar_has_exactly_five_icon_actions_and_no_rating() -> None:
    assert answer_icon_actions() == [
        "answer-action answer-copy",
        "answer-action answer-regenerate",
        "answer-action answer-listen",
        "answer-action answer-share",
        "answer-action answer-more",
    ]
    src = sheet("outputs.js")
    lowered = src.lower()
    for token in ("answer-like", "answer-dislike", "thumbs-up", "thumbs-down", "thumbup", "thumbdown"):
        assert token not in lowered, f"rating control leaked: {token}"
    # TXT download and the saved-answer entry both live in the "기타(···)"
    # menu; the save entry appears only when the store is ready for this owner.
    assert src.count('"answer-action answer-download"') == 1
    assert "answer-txt-download" in src
    assert "moreMenu.appendChild(save)" in src
    assert "save.hidden = !outputsReady" in src
    # Icon buttons expose hover/keyboard descriptions, never bare glyphs.
    assert 'setAttribute("aria-label"' in src
    assert "button.title" in src


def test_action_buttons_render_only_when_capable() -> None:
    src = sheet("outputs.js")
    assert "if (regen)" in src
    assert "if (ttsApi())" in src
    assert "if (shareAvailable())" in src
    assert "PadiemChatRegenerate" in src
    assert "PadiemVoiceTTSOutput" in src
    assert "navigator.share" in src


def test_regenerate_replays_through_the_guarded_request_path() -> None:
    app = sheet("app.js")
    assert app.count("window.PadiemChatRegenerate = Object.freeze") == 1
    assert "lastCompletedAnswerRequest" in app
    # Latest-completed-only, still connected, lifecycle-completed, no overlap.
    assert "stored.article !== article" in app
    assert "article.isConnected" in app
    assert "isCompleted(article)" in app
    assert "if (inFlight) return null;" in app
    assert 'querySelectorAll(".assistant-message")' in app
    # Same guarded path as a fresh submit; no duplicate user bubble.
    # B7: requestAnswer is reached through the module registry
    # (app.provide("streaming")) — the app.js one-line forwarder is gone.
    assert "void streaming.requestAnswer(stored.outboundMessages, stored.skill" in app
    assert "async function requestAnswer(" not in app
    regen_block = app.split("window.PadiemChatRegenerate", 1)[1].split("});", 1)[0]
    assert "addUserMessage" not in regen_block
    assert "model_id" not in regen_block
    assert "tier" not in regen_block
    # Stale context cannot survive a conversation reset.
    assert "lastCompletedAnswerRequest = null;" in app


def test_repetitive_ai_response_line_is_removed_brand_kept() -> None:
    app = sheet("app.js")
    lifecycle = sheet("message-lifecycle.js")
    assert 'textContent = uiT("ai-response")' not in app
    assert 'label.textContent = "AI 응답"' not in lifecycle
    # Truthful non-default states stay: mock preview, skill title, failures.
    # #7216 R5 step 5a: renderAnswer moved into chat-conversation-module.js.
    conv = sheet("chat-conversation-module.js")
    assert 'uiT("mock-response")' in conv
    assert "skillTitle" in conv
    products = [attrs for _tag, attrs in template_tags("assistantMessageTemplate")
                if "data-assistant-product" in attrs]
    assert len(products) == 1
    assert assistant_product_text() == "Padiem Chat"


def test_user_bubble_has_avatar_and_templates_keep_brand_meta() -> None:
    user_tags = template_tags("userMessageTemplate")
    assert any(attrs.get("class") == "message-bubble" for _tag, attrs in user_tags)
    assert any(attrs.get("class") == "user-avatar" and attrs.get("aria-hidden") == "true"
               for _tag, attrs in user_tags)
    assistant_tags = template_tags("assistantMessageTemplate")
    assert any(attrs.get("class") == "assistant-avatar" for _tag, attrs in assistant_tags)
    assert any("data-assistant-product" in attrs for _tag, attrs in assistant_tags)
    assert any("data-runtime-label" in attrs for _tag, attrs in assistant_tags)
    rules = rules_for_sheet("answer-actions.css")
    assert find_rules_with_selector(rules, ".user-avatar")
    assert find_rules_with_selector(rules, ".user-message")


def test_connectors_nav_opens_standalone_page_never_a_popup() -> None:
    assert element_attrs("connectorsView") is not None
    assert element_attrs("connectorsViewBody") is not None
    connectors_nav = element_attrs("connectorsNavButton")
    assert connectors_nav is not None
    assert connectors_nav.get("aria-controls") == "connectorsView"
    app = sheet("app.js")
    connectors = sheet("chat-connectors-module.js")
    calendar = sheet("chat-calendar-module.js")
    # #7216 A9: the click listener and the page mount moved into the module;
    # app.js keeps the single wire call and no popup is ever opened.
    assert 'addEventListener("click", openConnectorsView)' in connectors
    assert "connectorsModule().wireConnectorsListeners();" in app
    assert "connectorsDialog.showModal" not in app
    assert "connectorsDialog.showModal" not in connectors
    # The grid moves once into the page; queries scope to the page first.
    assert "mountConnectorsView" in connectors
    assert 'getElementById("connectorsViewBody")' in connectors
    assert "function connectorsScope()" in definition_source("connectorsScope")
    # Existing projection, endpoints and auth behavior are reused unchanged.
    assert connectors.count('PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status"') == 1
    assert 'PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status"' not in app
    # R5 B5: the Calendar ticket endpoint moved into chat-calendar-module.js.
    assert calendar.count("/api/connectors/google/ticket") == 1
    # The module loads before app.js so the module registry exists at wire time.
    scripts = script_sources()
    assert scripts.index("chat-connectors-module.js") < scripts.index("app.js")
    # The dialog element stays for contract compatibility.
    assert element_attrs("connectorsDialog") is not None
    rules = rules_for_sheet("standalone-views.css")
    assert find_rules_with_selector(rules, '.app-shell[data-state="connectors"] .conversation')
    assert find_rules_with_selector(rules, '.app-shell[data-state="connectors"] .composer-wrap')


def test_automation_nav_opens_standalone_page_reusing_panel() -> None:
    assert element_attrs("automationView") is not None
    assert element_attrs("automationViewBody") is not None
    # R5 A1: 자동화 화면 열기 본문은 chat-automation-module.js로 이동했다.
    app = sheet("app.js") + sheet("chat-automation-module.js")
    assert 'shell.dataset.state = "automation"' in app
    assert "mountAutomationView" in app
    assert "loadClawAutomationRules();" in app
    # Owner decision 2026-10-17: the page stays browsable without a session, so
    # the signed-in gate moved from opening the page to reading the rules. The
    # visitor branch returns before the loader, and the loader still refuses an
    # unauthenticated call, so no rule request can leave the browser.
    assert "if (!deps.clawWorkspace || !deps.clawAutomation) return;" in app
    assert 'if (signedOut) signedOut.hidden = false;\n      return;' in app
    assert "if (!deps.clawAutomation || !deps.authState.authenticated) return;" in app
    assert element_attrs("automationViewSignedOut") is not None
    assert element_attrs("clawAutomationSchedulerNote") is not None
    # The scheduler note still refuses to claim the scheduler is running.
    assert "자동 실행이 이미 활성화되어 있다는 뜻이 아닙니다" in sheet("index.html")
    rules = rules_for_sheet("standalone-views.css")
    assert find_rules_with_selector(rules, '.app-shell[data-state="automation"] .conversation')


def test_nav_active_covers_new_states() -> None:
    # R5 A10: the nav aria rows moved to chat-nav-module.js (same source text).
    app = sheet("app.js") + sheet("chat-nav-module.js")
    assert 'getElementById("connectorsNavButton")' in app
    assert 'getElementById("automationNavButton")' in app
    assert 'state === "connectors" ? "page" : "false"' in app
    assert 'state === "automation" ? "page" : "false"' in app


def test_new_locale_keys_exist_in_ko_and_en() -> None:
    ko_keys = locale_keys("ko")
    en_keys = locale_keys("en")
    for key in (
        "answer-copy", "answer-regenerate", "answer-listen", "answer-listen-stop",
        "answer-share", "answer-more", "answer-txt-download",
        "automation-view-title", "automation-view-kicker",
    ):
        assert key in ko_keys, f"missing ko {key}"
        assert key in en_keys, f"missing en {key}"
