"""Source contract for shared Chat/Claw follow and jump-to-latest behavior."""

from pathlib import Path

from _r5_streaming_harness import run_streaming_scenario

ROOT = Path(__file__).resolve().parents[1] / "static"


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_shared_conversation_motion_covers_chat_and_general_claw():
    motion = _source("conversation-motion.js")
    assert "function inConversation()" in motion
    assert 'state === "chat"' in motion
    assert 'state === "claw"' in motion
    # 작업함 제거(#7109)로 inbox 뷰 조건은 conversation-motion.js에서 삭제 —
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
    """새 대화·저장 대화 재열기에서 공유 팔로우 상태가 리셋된다.

    #7186 R2: 원래 `chat-conversation-module.js`의 문자열
    `window.__padiemConversationMotion?.reset?.();`과 app.js의 `resume` 문자열을
    고정했다. 문자열은 그 줄이 실제로 도는지 말해 주지 않으므로, 스트리밍 모듈을
    실행해 delta마다 팔로우 훅이 불리고 finally에서 endStreaming이 불리는지를
    관찰하는 방식으로 바꿨다. 리셋 자체는 conversation 모듈 소유라 그 계약은
    아래 별도 시험이 계속 지킨다.
    """
    observed = run_streaming_scenario("stream_scroll_follow_hooks")
    motion = observed["motion"]
    assert motion["before"] == 2
    assert motion["after"] == 2
    assert motion["end"] == 1

    # 리셋 호출은 conversation 모듈이 소유한다(구조 계약, 이유: 소유 분리).
    conversation = _source("chat-conversation-module.js")
    assert "window.__padiemConversationMotion?.reset?.();" in conversation


def test_only_stream_deltas_use_the_near_bottom_follow_hooks():
    motion = _source("conversation-motion.js")
    stream = _source("chat-streaming-module.js")
    assert "STREAM_FOLLOW_THRESHOLD = 80" in motion
    assert "beforeStreamingDelta: beforeStreamingDelta" in motion
    assert "afterStreamingDelta: afterStreamingDelta" in motion
    assert "endStreaming: endStreaming" in motion
    assert "beforeStreamingDelta?.()" in stream
    assert "afterStreamingDelta?.(streamScrollIntent)" in stream
    assert "endStreaming?.()" in stream
    assert "const shouldFollowStream = !/\\bapplication\\/json\\b/i.test(responseContentType);" in stream
    assert "const completedOk = await deps.requestCompletedAnswer" in stream
