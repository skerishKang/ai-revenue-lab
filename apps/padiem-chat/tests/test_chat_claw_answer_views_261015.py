"""Chat/Claw answer icons, user avatar, Connectors/Automation standalone pages.

Covers the bounded UI slice: five answer action icons (copy, regenerate,
listen, share, more) with no like/dislike rating, user-bubble avatar, removal
of the repetitive "AI 응답" completion line, and the Connectors/Automation
sidebar entries opening standalone Glass pages that reuse the existing
dialog/panel logic, endpoints and auth gates.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_answer_bar_has_exactly_five_icon_actions_and_no_rating() -> None:
    src = _read("outputs.js")
    for cls in (
        '"answer-action answer-copy"',
        '"answer-action answer-regenerate"',
        '"answer-action answer-listen"',
        '"answer-action answer-share"',
        '"answer-action answer-more"',
    ):
        assert cls in src, f"missing action button {cls}"
    lowered = src.lower()
    for token in ("answer-like", "answer-dislike", "thumbs-up", "thumbs-down", "thumbup", "thumbdown"):
        assert token not in lowered, f"rating control leaked: {token}"
    # TXT download stays inside the more menu; the save entry stays hidden.
    assert '"answer-action answer-download"' in src
    assert "answer-txt-download" in src
    assert "save.hidden = true" in src
    # Icon buttons expose hover/keyboard descriptions, never bare glyphs.
    assert 'setAttribute("aria-label"' in src
    assert "button.title" in src


def test_action_buttons_render_only_when_capable() -> None:
    src = _read("outputs.js")
    assert "if (regen)" in src
    assert "if (ttsApi())" in src
    assert "if (shareAvailable())" in src
    assert "PadiemChatRegenerate" in src
    assert "PadiemVoiceTTSOutput" in src
    assert "navigator.share" in src


def test_regenerate_replays_through_the_guarded_request_path() -> None:
    app = _read("app.js")
    assert "window.PadiemChatRegenerate = Object.freeze" in app
    assert "lastCompletedAnswerRequest" in app
    # Latest-completed-only, still connected, lifecycle-completed, no overlap.
    assert "stored.article !== article" in app
    assert "article.isConnected" in app
    assert "isCompleted(article)" in app
    assert "if (inFlight) return null;" in app
    assert 'querySelectorAll(".assistant-message")' in app
    # Same guarded path as a fresh submit; no duplicate user bubble.
    assert "void requestAnswer(stored.outboundMessages, stored.skill" in app
    regen_block = app.split("window.PadiemChatRegenerate", 1)[1].split("});", 1)[0]
    assert "addUserMessage" not in regen_block
    assert "model_id" not in regen_block
    assert "tier" not in regen_block
    # Stale context cannot survive a conversation reset.
    assert "lastCompletedAnswerRequest = null;" in app


def test_repetitive_ai_response_line_is_removed_brand_kept() -> None:
    app = _read("app.js")
    lifecycle = _read("message-lifecycle.js")
    assert 'textContent = uiT("ai-response")' not in app
    assert 'label.textContent = "AI 응답"' not in lifecycle
    # Truthful non-default states stay: mock preview, skill title, failures.
    assert 'uiT("mock-response")' in app
    assert "skillTitle" in app
    html = _read("index.html")
    assert "data-assistant-product" in html
    assert "Padiem Chat" in html


def test_user_bubble_has_avatar_and_templates_keep_brand_meta() -> None:
    html = _read("index.html")
    user = re.search(r'<template id="userMessageTemplate">(.*?)</template>', html).group(1)
    assert 'class="message-bubble"' in user
    assert 'class="user-avatar"' in user
    assert 'aria-hidden="true"' in user
    assistant = re.search(r'<template id="assistantMessageTemplate">(.*?)</template>', html).group(1)
    assert 'class="assistant-avatar"' in assistant
    assert "data-assistant-product" in assistant
    assert "data-runtime-label" in assistant
    css = _read("answer-actions.css")
    assert ".user-avatar" in css
    assert ".user-message" in css


def test_connectors_nav_opens_standalone_page_never_a_popup() -> None:
    html = _read("index.html")
    app = _read("app.js")
    assert 'id="connectorsView"' in html
    assert 'id="connectorsViewBody"' in html
    assert 'aria-controls="connectorsView"' in html
    assert 'addEventListener("click", openConnectorsView)' in app
    assert "connectorsDialog.showModal" not in app
    # The grid moves once into the page; queries scope to the page first.
    assert "mountConnectorsView" in app
    assert 'getElementById("connectorsViewBody")' in app
    assert "function connectorsScope()" in app
    # Existing projection, endpoints and auth behavior are reused unchanged.
    assert 'fetch("/api/connectors/status"' in app
    assert "/api/connectors/google/ticket" in app
    # The dialog element stays for contract compatibility.
    assert 'id="connectorsDialog"' in html
    css = _read("standalone-views.css")
    assert '.app-shell[data-state="connectors"] .conversation' in css
    assert '.app-shell[data-state="connectors"] .composer-wrap' in css


def test_automation_nav_opens_standalone_page_reusing_panel() -> None:
    html = _read("index.html")
    app = _read("app.js")
    assert 'id="automationView"' in html
    assert 'id="automationViewBody"' in html
    assert 'shell.dataset.state = "automation"' in app
    assert "mountAutomationView" in app
    assert "loadClawAutomationRules();" in app
    # Signed-in gate and session scoping are preserved.
    assert "if (!clawWorkspace || !clawAutomation || !authState.authenticated) return;" in app
    assert "clawAutomationSchedulerNote" in html
    # The scheduler note still refuses to claim the scheduler is running.
    assert "자동 실행이 이미 활성화되어 있다는 뜻이 아닙니다" in html
    css = _read("standalone-views.css")
    assert '.app-shell[data-state="automation"] .conversation' in css


def test_nav_active_covers_new_states() -> None:
    app = _read("app.js")
    assert 'getElementById("connectorsNavButton")' in app
    assert 'getElementById("automationNavButton")' in app
    assert 'state === "connectors" ? "page" : "false"' in app
    assert 'state === "automation" ? "page" : "false"' in app


def test_new_locale_keys_exist_in_ko_and_en() -> None:
    source = _read("locale.js")
    ko_part, en_part = source.split("en: {", 1)
    for key in (
        "answer-copy", "answer-regenerate", "answer-listen", "answer-listen-stop",
        "answer-share", "answer-more", "answer-txt-download",
        "automation-view-title", "automation-view-kicker",
    ):
        assert f'"{key}":' in ko_part, f"missing ko {key}"
        assert f'"{key}":' in en_part, f"missing en {key}"
