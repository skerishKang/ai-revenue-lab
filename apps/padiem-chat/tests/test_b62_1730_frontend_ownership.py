from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
LIFECYCLE = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
RICH = (STATIC / "rich-response.js").read_text(encoding="utf-8")
CONVERSATION = (STATIC / "conversation-state.js").read_text(encoding="utf-8")
BINARY = (STATIC / "document-binary.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_chat_transport_is_network_only_and_dom_free() -> None:
    for forbidden in (
        "document.",
        "querySelector",
        "PadiemChatConversationState",
        "PadiemChatLifecycle.set",
        "scrollIntoView",
        "replaceChildren",
        "createElement",
    ):
        assert forbidden not in TRANSPORT

    assert 'fetch("/api/chat"' in TRANSPORT
    assert 'fetch("/api/chat/stream"' in TRANSPORT
    assert 'fetch("/api/orchestration/status"' in TRANSPORT
    assert 'postOrchestration("/api/orchestration"' in TRANSPORT
    assert 'postOrchestration("/api/orchestration/resume"' in TRANSPORT
    assert 'postOrchestration("/api/orchestration/cancel"' in TRANSPORT
    assert "setOrchestrationPauseHandler" in TRANSPORT


def test_orchestration_dom_and_state_adapter_is_explicitly_bounded() -> None:
    assert "PadiemChatOrchestrationController" in LIFECYCLE
    assert "setOrchestrationPauseHandler" in LIFECYCLE
    assert 'document.getElementById("messageList")' in LIFECYCLE
    assert 'messageList.querySelectorAll(".assistant-message")' in LIFECYCLE
    assert "PadiemChatConversationState" in LIFECYCLE
    assert "orchestrationUi.render" in LIFECYCLE
    assert "resumeOrchestration" in LIFECYCLE
    assert "cancelOrchestration" in LIFECYCLE
    assert 'document.querySelectorAll(".assistant-message")' not in LIFECYCLE
    assert 'document.querySelector(".assistant-message")' not in LIFECYCLE


def test_rich_response_is_parse_render_only_and_lifecycle_driven() -> None:
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in RICH
    assert "lifecycleApi().isCompleted(article)" in RICH
    assert "MutationObserver" not in RICH
    assert 'document.getElementById("messageInput")' not in RICH
    assert "messageInput.disabled" not in RICH
    assert "fetch(" not in RICH
    assert "PadiemChatConversationState" not in RICH


def test_conversation_request_state_has_one_authority() -> None:
    markers = (
        "let inFlight = false;",
        "let activeRequestController = null;",
        "let activeRequestCancelReason = null;",
        "let conversationEpoch = 0;",
    )
    for marker in markers:
        assert marker in APP
        assert marker not in TRANSPORT
        assert marker not in LIFECYCLE
        assert marker not in RICH
        assert marker not in CONVERSATION

    assert "conversationState.commitAssistant(outboundMessages, answer);" in APP
    assert "conversationState.setConversationId(data.conversation_id);" in APP


def test_attachment_state_remains_single_owned_by_app_controller() -> None:
    assert "let selectedAttachment = null;" in APP
    assert "selectedAttachment" not in TRANSPORT
    assert "selectedAttachment" not in LIFECYCLE
    assert "selectedAttachment" not in RICH
    assert "selectedAttachment" not in BINARY


def test_module_order_keeps_transport_before_bounded_orchestration_adapter() -> None:
    transport = INDEX.index('<script src="./chat-transport.js"></script>')
    conversation = INDEX.index('<script src="./conversation-state.js"></script>')
    lifecycle = INDEX.index('<script src="./message-lifecycle.js"></script>')
    app = INDEX.index('<script src="./app.js"></script>')
    rich = INDEX.index('<script src="./rich-response.js"></script>')
    assert transport < conversation < lifecycle < app < rich


def test_app_no_longer_controls_rich_render_readiness_via_composer_state() -> None:
    assert "messageInput.disabled" not in RICH
    assert "canEnhanceAnswers" not in RICH
    assert 'event.detail.state !== api.states.COMPLETED' in RICH
    assert 'PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED)' in APP
