"""#4816 voice mode bounds: M2/M3 auto-send once, M2 without TTS, and late
STT/TTS events dropped on end, mute, cancel and account switch.

These are Chromium presentation contracts over the shipped static modules. The
recognizer and speechSynthesis are mocked: no provider call, no audio device.
The shared turn state machine is reused exactly as index.html orders it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Full B62 core runners intentionally do not install Playwright, so the browser
# contracts below are skipped individually there. The wiring contract at the top
# of this module is source-only and always runs: it is the part of #4816 that a
# focused UI lane can prove without a browser.
ROOT = Path(__file__).resolve().parents[1] / "static"
SCRIPTS = (
    "voice-live-transcript-turn.js",
    "voice-stt-input.js",
    "voice-composer.js",
    "voice-live-turn-controller.js",
    "voice-tts-output.js",
    "voice-ui-menu.js",
    "voice-answer-ui.js",
    "voice-call-ui.js",
)

HTML = """<!doctype html><html lang="ko"><body>
  <div class="app-shell" data-state="chat">
    <form id="composerForm">
      <div class="composer-actions">
        <button id="sendButton" type="submit">
          <svg class="send-arrow-icon" aria-hidden="true"></svg>
          <svg class="send-waveform-icon" aria-hidden="true" hidden></svg>
        </button>
      </div>
      <textarea id="messageInput"></textarea>
    </form>
    <main id="messageList"></main>
  </div>
</body></html>"""

TTS_MOCK = """() => {
  window.__voices = [{name: 'Korean', lang: 'ko-KR'}];
  window.__ttsSpoken = [];
  window.__ttsCancelled = 0;
  window.__ttsSpeaking = false;
  Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
    getVoices: () => window.__voices,
    speak: (u) => { window.__ttsSpoken.push(u.text); window.__ttsSpeaking = true; },
    cancel: () => { window.__ttsCancelled += 1; window.__ttsSpeaking = false; },
    get speaking() { return window.__ttsSpeaking; }
  }});
  window.SpeechSynthesisUtterance = function (text) { this.text = text; };
}"""

BOOTSTRAP = """() => {
  const input = document.getElementById('messageInput');
  const form = document.getElementById('composerForm');
  window.__test = {sent: [], runs: []};
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    window.__test.sent.push(input.value);
    input.disabled = true;
    setTimeout(() => {
      input.disabled = false;
      input.value = '';
      input.dispatchEvent(new Event('input', {bubbles: true}));
    }, 0);
  });
  window.PadiemVoiceComposer.registerRecognizerFactory((callbacks) => {
    window.__test.callbacks = callbacks;
    window.__test.runs.push(callbacks);
    return {stop: () => {}};
  });
  window.dispatchEvent(new CustomEvent('padiem:auth-state', {
    detail: {authenticated: true, identityKey: 'account-one'}
  }));
}"""

ANSWER_HTML = (
    '<div class="assistant-body"><div class="assistant-content">'
    '<p>실제로 생성된 답변입니다.</p></div></div>'
)


def test_the_voice_session_boundaries_are_wired_into_the_shipped_modules():
    """Source contract: every end/mute/cancel path uses the one session boundary.

    The behavioural proof is the Chromium suite below; this keeps the wiring
    itself covered on runners without a browser, where a UI-only change is
    reviewed.
    """
    menu = (ROOT / "voice-ui-menu.js").read_text(encoding="utf-8")
    answer = (ROOT / "voice-answer-ui.js").read_text(encoding="utf-8")
    call = (ROOT / "voice-call-ui.js").read_text(encoding="utf-8")

    # One boundary on the existing controller, reused by the mode picker.
    assert "function endTurn(reason)" in menu
    assert "endTurn: endTurn" in menu and "resumeTurn: resumeTurn" in menu
    assert "st.cancelled !== true && st.invalidated !== true" in menu
    assert "if (m !== \"tts\") stopAnswerSpeech();" in menu
    # Call mute and call end are session boundaries; unmute resumes the turn.
    assert 'menuAPI.endTurn("muted")' in call
    assert 'win.PadiemVoiceMenu.endTurn("call-ended")' in call
    assert "menuAPI.resumeTurn()" in call
    # The answer player re-checks authority when the scheduled speak fires.
    assert 'win.addEventListener("padiem:voice-end", stopPlayback);' in answer
    assert "token !== speakToken || !autoSpeakAllowed()" in answer


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as tool:
        instance = tool.chromium.launch(headless=True)
        yield instance
        instance.close()


def open_page(browser):
    page = browser.new_page()
    page.set_content(HTML)
    page.evaluate(TTS_MOCK)
    for script in SCRIPTS:
        page.add_script_tag(path=str(ROOT / script))
    page.evaluate(BOOTSTRAP)
    page.wait_for_timeout(60)
    return page


def select_mode(page, mode):
    """Pick one of the three picker entries through the shipped UI."""
    page.evaluate(
        """(mode) => {
          document.querySelector('.voice-mode-menu-item[data-mode="' + mode + '"]')
            .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }""",
        mode,
    )
    page.wait_for_timeout(40)


def start_mic(page):
    page.evaluate("() => document.getElementById('voiceMicButton').click()")
    page.wait_for_timeout(40)


def speak_turn(page, text, final_id):
    """Deliver one complete mocked utterance, exactly as the recognizer does."""
    page.evaluate(
        """(args) => {
          const c = window.__test.callbacks;
          c.onInterim({accountKey: 'account-one', sessionGeneration: 1, isInterim: true, text: args.text.slice(0, 4)});
          c.onFinal({text: args.text, utteranceId: args.finalId, stopped: false});
        }""",
        {"text": text, "finalId": final_id},
    )
    page.wait_for_timeout(30)
    page.evaluate("() => window.__test.callbacks.onAutoStopRequested()")
    page.wait_for_timeout(40)
    page.evaluate(
        """(finalId) => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: finalId
        })""",
        final_id,
    )
    page.wait_for_timeout(120)


def clear_input(page):
    page.evaluate(
        """() => {
          const input = document.getElementById('messageInput');
          input.value = '';
          input.dispatchEvent(new Event('input', {bubbles: true}));
        }"""
    )
    page.wait_for_timeout(60)


def sent(page):
    return page.evaluate("() => Array.from(window.__test.sent)")


def add_answer(page):
    page.evaluate(
        """(body) => {
          const article = document.createElement('article');
          article.className = 'assistant-message';
          article.innerHTML = body;
          document.getElementById('messageList').appendChild(article);
        }""",
        ANSWER_HTML,
    )


def spoken(page):
    return page.evaluate("() => Array.from(window.__ttsSpoken)")


def test_m2_auto_sends_once_per_utterance_and_never_speaks(browser):
    page = open_page(browser)
    select_mode(page, "text")
    clear_input(page)
    start_mic(page)
    speak_turn(page, "문자로 답변할 발화", "m2-1")

    assert sent(page) == ["문자로 답변할 발화"]

    # The same accepted final must never submit twice.
    page.evaluate(
        """() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm2-1'
        })"""
    )
    page.wait_for_timeout(80)
    assert sent(page) == ["문자로 답변할 발화"]

    # A later utterance in the same live session sends exactly once more.
    clear_input(page)
    start_mic(page)
    speak_turn(page, "두 번째 발화", "m2-2")
    assert sent(page) == ["문자로 답변할 발화", "두 번째 발화"]

    # M2 is "문자로 답변": a generated answer must stay silent.
    add_answer(page)
    page.wait_for_timeout(150)
    assert spoken(page) == []
    page.close()


def test_m3_speaks_the_generated_answer_exactly_once(browser):
    page = open_page(browser)
    select_mode(page, "tts")
    clear_input(page)
    start_mic(page)
    speak_turn(page, "문자와 음성 함께", "m3-1")

    assert sent(page) == ["문자와 음성 함께"]
    assert spoken(page) == []

    # M2 and M3 share one rule: one accepted final is one request.
    page.evaluate(
        """() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm3-1'
        })"""
    )
    page.wait_for_timeout(80)
    assert sent(page) == ["문자와 음성 함께"]

    add_answer(page)
    page.wait_for_timeout(150)
    assert spoken(page) == ["실제로 생성된 답변입니다."]
    assert page.evaluate("() => window.PadiemVoiceMenu.isTtsActive()") is True
    assert page.evaluate("() => window.PadiemVoiceMenu.isCallActive()") is False
    page.close()


def test_account_change_drops_an_already_scheduled_answer_speak(browser):
    """The answer was inserted, its speak scheduled, then the identity changed.

    The scheduled auto-speak belongs to the previous account's session and must
    not start playing after the switch.
    """
    page = open_page(browser)
    select_mode(page, "tts")
    page.evaluate(
        """async (body) => {
          const article = document.createElement('article');
          article.className = 'assistant-message';
          article.innerHTML = body;
          document.getElementById('messageList').appendChild(article);
          // Let the MutationObserver run: this is what schedules the auto-speak.
          await Promise.resolve();
          window.dispatchEvent(new CustomEvent('padiem:auth-state', {
            detail: {authenticated: false}
          }));
        }""",
        ANSWER_HTML,
    )
    page.wait_for_timeout(250)
    assert spoken(page) == []
    page.close()


def test_account_change_resets_the_live_voice_mode(browser):
    """A new identity must not inherit the previous account's armed M3 mode."""
    page = open_page(browser)
    select_mode(page, "tts")
    assert page.evaluate("() => window.PadiemVoiceMenu.getState().ttsOn") is True

    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('padiem:auth-state', {
          detail: {authenticated: false}
        }))"""
    )
    page.wait_for_timeout(60)
    assert page.evaluate("() => window.PadiemVoiceMenu.getState().mode") == "basic"
    assert page.evaluate("() => window.PadiemVoiceMenu.isTtsActive()") is False

    add_answer(page)
    page.wait_for_timeout(200)
    assert spoken(page) == []
    page.close()


def test_an_answer_arriving_after_the_call_ended_is_not_spoken(browser):
    page = open_page(browser)
    select_mode(page, "call")
    add_answer(page)
    page.wait_for_timeout(80)
    page.evaluate("() => document.getElementById('voiceCallEnd').click()")
    page.wait_for_timeout(60)

    # Ending M4 returns to the text conversation; a late answer stays silent.
    add_answer(page)
    page.wait_for_timeout(200)
    assert spoken(page) == []
    assert page.evaluate("() => window.PadiemVoiceMenu.isTtsActive()") is False
    page.close()


def test_switching_from_m3_to_m2_stops_answer_speech(browser):
    page = open_page(browser)
    select_mode(page, "tts")
    add_answer(page)
    page.wait_for_timeout(120)
    assert spoken(page) == ["실제로 생성된 답변입니다."]

    cancelled_before = page.evaluate("() => window.__ttsCancelled")
    select_mode(page, "text")
    assert page.evaluate("() => window.__ttsCancelled") > cancelled_before

    # M2 must not speak the next generated answer either.
    add_answer(page)
    page.wait_for_timeout(150)
    assert spoken(page) == ["실제로 생성된 답변입니다."]
    page.close()


def test_mute_blocks_a_late_accepted_turn(browser):
    page = open_page(browser)
    select_mode(page, "call")
    clear_input(page)
    start_mic(page)
    speak_turn(page, "통화 첫 발화", "m4-1")
    assert sent(page) == ["통화 첫 발화"]

    page.evaluate("() => document.getElementById('voiceCallMute').click()")
    page.wait_for_timeout(60)
    assert page.evaluate("() => document.getElementById('voiceCallMute').getAttribute('aria-pressed')") == "true"

    # The recognizer tail (final + accepted turn) arriving after the mute must
    # not submit anything.
    before = sent(page)
    page.evaluate(
        """() => {
          const c = window.__test.callbacks;
          c.onFinal({text: '음소거 뒤 늦은 발화', utteranceId: 'm4-late', stopped: false});
          c.onTurnComplete({accepted: true, endOfTurn: true, finalId: 'm4-late'});
        }"""
    )
    page.wait_for_timeout(120)
    assert sent(page) == before
    page.close()


def test_ending_the_call_blocks_a_late_accepted_turn(browser):
    page = open_page(browser)
    select_mode(page, "call")
    clear_input(page)
    start_mic(page)
    speak_turn(page, "통화 두 번째 발화", "m4-2")
    assert sent(page) == ["통화 두 번째 발화"]

    page.evaluate("() => document.getElementById('voiceCallEnd').click()")
    page.wait_for_timeout(60)
    assert page.evaluate("() => document.getElementById('voiceCallPanel').hidden") is True

    before = sent(page)
    page.evaluate(
        """() => {
          const c = window.__test.callbacks;
          c.onFinal({text: '통화 종료 뒤 늦은 발화', utteranceId: 'm4-late-2', stopped: false});
          c.onTurnComplete({accepted: true, endOfTurn: true, finalId: 'm4-late-2'});
        }"""
    )
    page.wait_for_timeout(120)
    assert sent(page) == before
    page.close()


def test_late_turn_after_account_switch_is_not_submitted(browser):
    page = open_page(browser)
    select_mode(page, "text")
    clear_input(page)
    start_mic(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('padiem:auth-state', {
          detail: {authenticated: true, identityKey: 'account-two'}
        }))"""
    )
    page.wait_for_timeout(60)

    page.evaluate(
        """() => {
          const c = window.__test.callbacks;
          c.onFinal({text: '다른 계정 늦은 발화', utteranceId: 'late-account', stopped: false});
          c.onTurnComplete({accepted: true, endOfTurn: true, finalId: 'late-account'});
        }"""
    )
    page.wait_for_timeout(150)
    assert sent(page) == []
    page.close()


def test_auto_send_works_again_after_the_call_ended(browser):
    """Ending M4 must not leave the live session cancelled for the next turn."""
    page = open_page(browser)
    select_mode(page, "call")
    page.evaluate("() => document.getElementById('voiceCallEnd').click()")
    page.wait_for_timeout(60)

    # After the call the picker shows M2 ("문자로 답변") still armed.
    clear_input(page)
    start_mic(page)
    speak_turn(page, "통화 뒤 새 발화", "post-call-1")
    assert sent(page) == ["통화 뒤 새 발화"]
    page.close()


def test_mode_changes_never_create_an_extra_request(browser):
    page = open_page(browser)
    select_mode(page, "text")
    clear_input(page)
    start_mic(page)
    speak_turn(page, "요청은 한 번", "m-1")
    assert sent(page) == ["요청은 한 번"]

    select_mode(page, "tts")
    select_mode(page, "call")
    page.evaluate("() => document.getElementById('voiceCallEnd').click()")
    page.wait_for_timeout(120)

    # Same conversation: switching presentation modes and ending the call never
    # re-submits or starts a second model request.
    assert sent(page) == ["요청은 한 번"]
    print(json.dumps({"sent": sent(page), "spoken": spoken(page)}, ensure_ascii=False))
    page.close()
