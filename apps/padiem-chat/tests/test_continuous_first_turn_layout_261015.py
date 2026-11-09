"""Owner-accepted inline first-turn, not a replacement conversation surface."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
#7216 R5 step 5a: showConversation moved into chat-conversation-module.js.
CONV = (STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_first_user_turn_preserves_original_hero_and_appends_messages() -> None:
    # #7216 R5 step 5a: showConversation moved into chat-conversation-module.js.
    assert 'const startingOnLanding = !restoreSaved' in CONV
    assert 'const continuingLanding = !restoreSaved' in CONV
    assert 'deps.emptyState.hidden = !keepLanding;' in CONV
    assert 'deps.messageList.hidden = false;' in CONV
    assert 'conversationPanel.dataset.continuousThread = "true"' in CONV
    assert 'showConversation({ preserveClaw: clawGeneralRequest });' in APP


def test_saved_conversation_reopens_without_hero_and_new_chat_resets() -> None:
    assert 'showConversation({ preserveClaw: isVerifiedClawThread, restoreSaved: true })' in APP
    # #7216 R5 step 5a: the body moved with showConversation into the module.
    assert 'delete deps.messageList.closest(".conversation")?.dataset.continuousThread;' in CONV
    assert 'emptyState.hidden = false;' in APP


def test_same_panel_dom_and_inline_message_list_for_chat_and_claw() -> None:
    hero = HTML.index('id="emptyState"')
    messages = HTML.index('id="messageList"')
    assert hero < messages
    assert "CENTRAL_CONTINUOUS_CHAT_CLAW_20261015" in CSS
    assert '.conversation[data-continuous-thread="true"] .empty-state:not([hidden])' in CSS
    assert '.conversation[data-continuous-thread="true"] #messageList:not([hidden])' in CSS
    assert 'margin-top: clamp(28px, 3.2vh, 48px)' in CSS
