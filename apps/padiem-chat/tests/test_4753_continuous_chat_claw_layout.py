"""#4753: user-visible Chat/Claw thread remains in its first-use frame."""
from pathlib import Path

S = Path(__file__).resolve().parents[1] / "static"
CHAT = (S / "padiem-chat-ui-polish.css").read_text(encoding="utf8")
CLAW = (S / "claw-focus-layout.css").read_text(encoding="utf8")
INDEX = (S / "index.html").read_text(encoding="utf8")
APP = (S / "app.js").read_text(encoding="utf8")


def test_chat_active_thread_uses_home_frame_and_same_composer_geometry():
    # This catches the actual owner screenshot regression: home width 728px,
    # first submit silently widened chat to a 1080px "new" surface.
    assert ':is([data-state="home"],[data-state="chat"]) .conversation' in CHAT
    assert ':is([data-state="home"],[data-state="chat"]) .composer-wrap' in CHAT
    assert '--padiem-chat-active-lane-width' not in CHAT
    assert 'body .app-shell[data-state="chat"] .conversation {\\n    width:' not in CHAT


def test_claw_general_thread_keeps_landing_layout_after_hero_disappears():
    # Before this fix, all landing CSS stopped matching after showConversation()
    # hid emptyState, activating the wider, taller, separate Claw workbench.
    assert ':not(:has(.claw-workspace[data-view="general"] ~ .conversation))' in CLAW
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation)' in CLAW
    assert ':not(:has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden])))' not in CLAW
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden]))' not in CLAW


def test_single_composer_is_reused_for_both_chat_and_claw():
    assert INDEX.count('id="composerForm"') == 1
    assert INDEX.count('id="messageInput"') == 1
    assert 'showConversation({ preserveClaw: clawGeneralRequest });' in APP
    assert 'input.value = "";' in APP
    assert 'form.addEventListener("submit"' in APP
