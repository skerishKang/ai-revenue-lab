"""#4816 M4 call screen: per-turn history, elapsed time, and tab-close teardown.

Same harness as ``test_4816_voice_mode_bounds.py``: the shipped static modules,
a mocked recognizer and a mocked speechSynthesis, no provider call and no audio
device. The conversation the history reads is the page's own ``#messageList``;
this view keeps no transcript store of its own.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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

HISTORY = """() => Array.from(document.querySelectorAll('#voiceCallHistory .voice-call-turn'))
  .map((row) => ({
    role: row.className,
    who: (row.querySelector('.voice-call-turn__role') || {}).textContent || '',
    text: (row.querySelector('.voice-call-turn__text') || {}).textContent || '',
  }))"""


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as tool:
        instance = tool.chromium.launch(headless=True)
        yield instance
        instance.close()


def open_page(browser, *, clock: bool = False):
    page = browser.new_page()
    if clock:
        page.clock.install()
    page.set_content(HTML)
    page.evaluate(TTS_MOCK)
    for script in SCRIPTS:
        page.add_script_tag(path=str(ROOT / script))
    page.evaluate(BOOTSTRAP)
    page.wait_for_timeout(60)
    return page


def select_mode(page, mode):
    page.evaluate(
        """(mode) => {
          document.querySelector('.voice-mode-menu-item[data-mode="' + mode + '"]')
            .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }""",
        mode,
    )
    page.wait_for_timeout(60)


def append_turn(page, who: str, text: str, *, update_in_place: bool = False):
    """Append one conversation turn the way the app renders it."""
    page.evaluate(
        """(args) => {
          const list = document.getElementById('messageList');
          if (args.update) {
            const all = list.querySelectorAll('article.assistant-message .assistant-content');
            const last = all[all.length - 1];
            if (last) last.textContent = args.text;
            return;
          }
          if (args.who === 'user') {
            const article = document.createElement('article');
            article.className = 'message user-message';
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            bubble.textContent = args.text;
            article.appendChild(bubble);
            list.appendChild(article);
            return;
          }
          const article = document.createElement('article');
          article.className = 'message assistant-message';
          const body = document.createElement('div');
          body.className = 'assistant-body';
          const content = document.createElement('div');
          content.className = 'assistant-content';
          content.textContent = args.text;
          body.appendChild(content);
          article.appendChild(body);
          list.appendChild(article);
        }""",
        {"who": who, "text": text, "update": update_in_place},
    )
    page.wait_for_timeout(80)


def test_the_call_screen_lists_each_turn_from_the_conversation(browser):
    """M4-①: turns are read from the conversation, not copied into a new store."""
    page = open_page(browser)
    # A turn that happened BEFORE the call must not be replayed as call history.
    append_turn(page, "user", "통화 전 질문")
    append_turn(page, "assistant", "통화 전 답변")

    select_mode(page, "call")
    assert page.evaluate("() => document.getElementById('voiceCallPanel').hidden") is False
    assert page.evaluate(HISTORY) == []

    append_turn(page, "user", "견적서 정리해줘")
    append_turn(page, "assistant", "견적서 초안입니다")
    rows = page.evaluate(HISTORY)
    assert [row["text"] for row in rows] == ["견적서 정리해줘", "견적서 초안입니다"], rows
    assert "user" in rows[0]["role"] and "assistant" in rows[1]["role"], rows
    assert rows[0]["who"] and rows[1]["who"], rows

    # A streamed answer updates the same turn instead of adding another.
    append_turn(page, "assistant", "견적서 초안입니다 (수정)", update_in_place=True)
    rows = page.evaluate(HISTORY)
    assert [row["text"] for row in rows] == ["견적서 정리해줘", "견적서 초안입니다 (수정)"], rows
    page.close()


def test_the_call_screen_shows_elapsed_time_and_stops_at_the_end(browser):
    """M4-②: elapsed time ticks during the call and freezes when it ends."""
    page = open_page(browser, clock=True)
    select_mode(page, "call")
    timer = "() => document.getElementById('voiceCallTimer').textContent"
    assert page.evaluate(timer) == "00:00"

    page.clock.fast_forward(65_000)
    assert page.evaluate(timer) == "01:05"

    page.evaluate("() => document.getElementById('voiceCallEnd').click()")
    page.wait_for_timeout(50)
    frozen = page.evaluate(timer)
    page.clock.fast_forward(30_000)
    assert page.evaluate(timer) == frozen
    assert frozen.startswith("01:0"), frozen
    page.close()


def test_page_hide_ends_the_call_and_drops_a_late_turn(browser):
    """M4-③: closing or reloading the tab ends the call through endTurn."""
    page = open_page(browser)
    select_mode(page, "call")
    # The recognizer factory is registered when capture starts, exactly as the
    # microphone does it; the call itself does not start a second capture.
    page.evaluate("() => document.getElementById('voiceMicButton').click()")
    page.wait_for_timeout(60)
    page.evaluate(
        """() => {
          const c = window.__test.callbacks;
          c.onFinal({text: '통화 중 발화', utteranceId: 'm4-1', stopped: false});
          c.onTurnComplete({accepted: true, endOfTurn: true, finalId: 'm4-1'});
        }"""
    )
    page.wait_for_timeout(80)
    assert page.evaluate("() => Array.from(window.__test.sent)") == ["통화 중 발화"]
    cancelled_before = page.evaluate("() => window.__ttsCancelled")

    page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    page.wait_for_timeout(80)

    assert page.evaluate("() => document.getElementById('voiceCallPanel').hidden") is True
    assert page.evaluate("() => window.PadiemVoiceMenu.getState().callOn") is False
    # The same session boundary runs: playback is stopped, not left scheduled.
    assert page.evaluate("() => window.__ttsCancelled") > cancelled_before

    before = page.evaluate("() => Array.from(window.__test.sent)")
    page.evaluate(
        """() => {
          const c = window.__test.callbacks;
          c.onFinal({text: '탭을 닫은 뒤 늦은 발화', utteranceId: 'm4-late', stopped: false});
          c.onTurnComplete({accepted: true, endOfTurn: true, finalId: 'm4-late'});
        }"""
    )
    page.wait_for_timeout(120)
    assert page.evaluate("() => Array.from(window.__test.sent)") == before
    assert page.evaluate("() => window.__ttsSpoken.length") == 0
    page.close()
