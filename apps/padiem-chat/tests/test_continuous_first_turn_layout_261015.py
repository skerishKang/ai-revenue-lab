"""Owner-accepted inline first-turn, not a replacement conversation surface."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_first_user_turn_preserves_original_hero_and_appends_messages() -> None:
    assert 'const startingOnLanding = !restoreSaved' in APP
    assert 'const continuingLanding = !restoreSaved' in APP
    assert 'emptyState.hidden = !keepLanding;' in APP
    assert 'messageList.hidden = false;' in APP
    assert 'conversationPanel.dataset.continuousThread = "true"' in APP
    assert 'showConversation({ preserveClaw: clawGeneralRequest });' in APP


def test_saved_conversation_reopens_without_hero_and_new_chat_resets() -> None:
    assert 'showConversation({ preserveClaw: isVerifiedClawThread, restoreSaved: true })' in APP
    assert 'delete messageList.closest(".conversation")?.dataset.continuousThread;' in APP
    assert 'emptyState.hidden = false;' in APP


def test_same_panel_dom_and_inline_message_list_for_chat_and_claw() -> None:
    hero = HTML.index('id="emptyState"')
    messages = HTML.index('id="messageList"')
    assert hero < messages
    assert "CENTRAL_CONTINUOUS_CHAT_CLAW_20261015" in CSS
    assert '.conversation[data-continuous-thread="true"] .empty-state:not([hidden])' in CSS
    assert '.conversation[data-continuous-thread="true"] #messageList:not([hidden])' in CSS
    assert 'margin-top: clamp(28px, 3.2vh, 48px)' in CSS
