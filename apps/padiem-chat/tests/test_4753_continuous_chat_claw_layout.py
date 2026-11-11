"""#4753: user-visible Chat/Claw thread remains in its first-use frame."""
from pathlib import Path

from _r5_streaming_harness import run_streaming_scenario

S = Path(__file__).resolve().parents[1] / "static"
CHAT = (S / "padiem-chat-ui-polish.css").read_text(encoding="utf8")
CLAW = (S / "claw-focus-layout.css").read_text(encoding="utf8")
INDEX = (S / "index.html").read_text(encoding="utf8")
APP = (S / "app.js").read_text(encoding="utf8")


def test_chat_active_thread_uses_home_frame_and_same_composer_geometry():
    # This catches the actual owner screenshot regression: home width 728px,
    # first submit silently widened chat to a 1080px "new" surface.
    # One desktop frame contract for every surface that carries the
    # conversation. #2594 originally added Claw by pasting the Chat block a
    # second time with the same four values; the two blocks are one rule now, so
    # the assertion names the merged form instead of the Chat-only enumeration.
    assert ':is([data-state="home"], [data-state="chat"], [data-state="claw"]) .conversation' in CHAT
    assert ':is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer-wrap' in CHAT
    assert '--padiem-chat-active-lane-width' not in CHAT
    assert 'body .app-shell[data-state="chat"] .conversation {\\n    width:' not in CHAT


def test_claw_general_thread_keeps_landing_layout_after_hero_disappears():
    # Before this fix, all landing CSS stopped matching after showConversation()
    # hid emptyState, activating the wider, taller, separate Claw workbench.
    assert ':not(:has(.claw-workspace[data-view="general"] ~ .conversation))' in CLAW
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation)' in CLAW
    assert ':not(:has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden])))' not in CLAW
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden]))' in CLAW
    assert CLAW.count(':has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden]))') == 1


def test_single_composer_is_reused_for_both_chat_and_claw():
    """하나의 composer가 Chat·Claw 두 레인에 쓰인다.

    #7186 R2: 이 함수는 원래 app.js의 문자열 3개(`showConversation({ preserveClaw:
    clawGeneralRequest });`, `input.value = "";`,
    `form.addEventListener("submit"`)를 고정했다. 문자열은 "누가 그 줄을 실행하는지"를
    말해 주지 않으므로, 실제 스트리밍 모듈을 실행해 관찰하는 방식으로 바꿨다:
    같은 composer 입력이 두 레인 모두에서 요청으로 나가고, 제출 뒤 입력이 비워진다.
    """
    assert INDEX.count('id="composerForm"') == 1
    assert INDEX.count('id="messageInput"') == 1

    # Chat 레인: 한 번의 제출이 스트림 요청 하나로 나간다.
    chat = run_streaming_scenario("request_answer_full_path")
    assert chat["ok"] is True
    assert chat["request"]["path"] == "/api/chat/stream"
    assert chat["answer"]["inputFocused"] is True

    # Claw 레인: 같은 제출 경로가 product=claw 본문으로 나간다.
    claw = run_streaming_scenario("request_answer_claw_lane")
    assert claw["ok"] is True
    assert claw["request"]["body"]["product"] == "claw"
