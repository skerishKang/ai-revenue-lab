"""Source contract for shared Chat/Claw follow and jump-to-latest behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "static"


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_shared_conversation_motion_covers_chat_and_general_claw():
    motion = _source("conversation-motion.js")
    assert "function inConversation()" in motion
    assert 'state === "chat"' in motion
    assert 'state === "claw"' in motion
    assert 'workspace.dataset.view !== "inbox"' in motion
    assert "function remainingToEnd()" in motion
    assert 'className = "conversation-jump"' in motion
    assert 'data-locale-aria-label", "conversation-jump"' in motion
    assert "function syncJumpButton()" in motion
    assert "addedUsers > 1" in motion
    assert "reset: reset" in motion
    assert "resume: resumeFollow" in motion


def test_lifecycle_reveals_do_not_override_paused_follow():
    lifecycle = _source("message-lifecycle.js")
    assert "function revealArticleIfFollowing(article)" in lifecycle
    assert "!motion.isFollowingLatest()" in lifecycle
    assert lifecycle.count("revealArticleIfFollowing(article);") == 2


def test_jump_control_has_translations_and_glass_styling():
    locale = _source("locale.js")
    styles = _source("interaction-polish.css")
    assert '"conversation-jump": "최신 메시지로 이동"' in locale
    assert '"conversation-jump": "Jump to latest"' in locale
    assert ".conversation-jump {" in styles
    assert ".conversation-jump[hidden]" in styles
    assert ".conversation-jump:focus-visible" in styles


def test_new_and_restored_conversations_reset_shared_follow_state():
    app = _source("app.js")
    assert "window.__padiemConversationMotion?.reset?.();" in app
    assert "window.__padiemConversationMotion?.resume?.();" in app
