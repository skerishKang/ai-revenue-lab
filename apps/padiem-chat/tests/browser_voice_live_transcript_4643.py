"""#4643 live (real-time) transcription in a real browser.

The provider WebSocket and the microphone are faked; everything else is the
shipped source: the shared adapter, the ported live engine and the canonical
composer. The point of this test is the browser behaviour the Owner asked
for:

- pressing the microphone and speaking writes the recognised text into the
  composer input **while the user is still speaking**;
- the confirmed sentence replaces that draft in place;
- the next utterance continues after the confirmed text;
- stopping the microphone keeps the text;
- Mode 1 never auto-sends and Mode 2 auto-sends exactly once per utterance.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
SCRIPTS = (
    "voice-stt-input.js",
    "voice-live-transcript.js",
    "voice-composer.js",
    "voice-live-turn-controller.js",
    "voice-ui-menu.js",
)

PAGE_SETUP = """<!doctype html><html lang="ko"><body>
  <div class="app-shell" data-state="chat">
    <form id="composerForm">
      <div class="composer-actions">
        <button id="sendButton" type="submit" disabled>Send</button>
      </div>
      <textarea id="messageInput"></textarea>
    </form>
    <main id="messageList"></main>
  </div>
</body></html>"""

FAKES = """() => {
  window.__live = { sockets: [], sent: [], frames: [] };

  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      window.__live.sockets.push(this);
      setTimeout(() => {
        this.readyState = 1;
        if (this.onopen) this.onopen();
      }, 0);
    }
    send(data) { this.sent.push(data); window.__live.sent.push(data); }
    close() { this.readyState = 3; if (this.onclose) this.onclose({ reason: 'closed' }); }
  }
  window.WebSocket = FakeWebSocket;

  const processor = { onaudioprocess: null, connect() {}, disconnect() {} };
  const source = { connect() {}, disconnect() {} };
  const gain = { gain: { value: 0 }, connect() {}, disconnect() {} };
  window.__live.processor = processor;
  window.AudioContext = function () {
    return {
      sampleRate: 0,
      destination: {},
      resume: async () => {},
      close: async () => {},
      createMediaStreamSource: () => source,
      createScriptProcessor: () => processor,
      createGain: () => gain,
    };
  };

  const tracks = [{ stop() {} }];
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: async () => ({ getTracks: () => tracks }) },
  });

  window.__live.fetch = async (path) => {
    if (path === '/health') {
      return { ok: true, json: async () => ({ voice_stt_available: true }) };
    }
    if (path.indexOf('live-token') !== -1) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          token: 'auth_tokens/browser-test',
          session: {
            model: 'gemini-3.5-transcribe-live',
            vad_silence_ms: 1300,
            rotate_after_ms: 560000,
            response_modalities: ['TEXT'],
            input_audio_transcription_mode: 'VERBATIM',
          },
        }),
      };
    }
    return { ok: true, json: async () => ({ identity_key: 'account-one' }) };
  };
  window.fetch = window.__live.fetch;

  window.__test = { sent: [] };
  const input = document.getElementById('messageInput');
  const form = document.getElementById('composerForm');
  input.addEventListener('input', () => {
    document.getElementById('sendButton').disabled = !input.value.trim();
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    window.__test.sent.push(input.value);
    // Mirror the product app: the composer is busy while the answer streams
    // and is cleared when the answer settles.
    input.disabled = true;
    document.getElementById('sendButton').disabled = true;
    setTimeout(() => {
      input.disabled = false;
      input.value = '';
      document.getElementById('sendButton').disabled = true;
    }, 0);
  });
}"""


def _install(page):
    for script in SCRIPTS:
        page.add_script_tag(path=str(STATIC / script))
    page.evaluate(FAKES)
    page.evaluate("""() => {
      const live = window.PadiemVoiceLiveTranscript;
      const doc = document;
      window.PadiemVoiceComposer.registerRecognizerFactory(live.createRecognizerFactory({
        win: window,
        fetchImpl: window.__live.fetch,
        mediaDevices: navigator.mediaDevices,
        liveTokenPath: '/api/voice/live-token',
      }));
      window.dispatchEvent(new CustomEvent('padiem:auth-state', {
        detail: { authenticated: true, identityKey: 'account-one' },
      }));
    }""")


def test_live_transcription_writes_into_the_input_in_real_time():
    with sync_playwright() as tool:
        browser = tool.chromium.launch()
        page = browser.new_page()
        page.set_content(PAGE_SETUP)
        _install(page)
        page.wait_for_timeout(100)

        # The microphone is pressed.
        page.evaluate("() => document.getElementById('voiceMicButton').click()")
        page.wait_for_timeout(150)
        opened = page.evaluate("() => window.__live.sockets.length")
        assert opened == 1, "one Live session is opened"

        # The user is still speaking: the recognised text is in the input.
        page.evaluate("""() => {
          const socket = window.__live.sockets[0];
          socket.onmessage({ data: JSON.stringify({
            serverContent: { interimInputTranscription: { text: '안녕하세요' } },
          })});
        }""")
        page.wait_for_timeout(50)
        interim_in_input = page.evaluate(
            "() => document.getElementById('messageInput').value"
        )
        assert interim_in_input == "안녕하세요", (
            "the partial must be visible in the composer input while speaking"
        )
        interim_state = page.evaluate(
            "() => window.PadiemVoiceComposer.getController().getStatus().voiceState"
        )
        assert interim_state == "interim"
        # The microphone is still open.
        assert page.evaluate(
            "() => window.PadiemVoiceComposer.getController().getStatus().active"
        ) is True

        # The sentence is confirmed: it replaces the draft in place.
        page.evaluate("""() => {
          const socket = window.__live.sockets[0];
          socket.onmessage({ data: JSON.stringify({
            serverContent: {
              inputTranscription: { text: '안녕하세요 반갑습니다', finished: true },
              turnComplete: true,
            },
          })});
        }""")
        page.wait_for_timeout(50)
        final_in_input = page.evaluate(
            "() => document.getElementById('messageInput').value"
        )
        assert final_in_input == "안녕하세요 반갑습니다"

        # The user keeps talking: the next utterance follows the confirmed text.
        page.evaluate("""() => {
          const socket = window.__live.sockets[0];
          socket.onmessage({ data: JSON.stringify({
            serverContent: { interimInputTranscription: { text: '그리고' } },
          })});
        }""")
        page.wait_for_timeout(50)
        assert page.evaluate(
            "() => document.getElementById('messageInput').value"
        ) == "안녕하세요 반갑습니다 그리고"

        # Mode 1 never auto-sends.
        assert page.evaluate("() => window.__test.sent.length") == 0

        # Stopping the microphone keeps the text that was entered.
        page.evaluate("() => window.PadiemVoiceComposer.getController().stop('user-stopped')")
        page.wait_for_timeout(200)
        assert page.evaluate(
            "() => document.getElementById('messageInput').value"
        ) == "안녕하세요 반갑습니다 그리고"
        assert page.evaluate("() => window.__test.sent.length") == 0

        browser.close()


def test_mode2_auto_sends_exactly_once_per_confirmed_utterance():
    with sync_playwright() as tool:
        browser = tool.chromium.launch()
        page = browser.new_page()
        page.set_content(PAGE_SETUP)
        _install(page)
        page.wait_for_timeout(100)

        # Mode 2 ("문자로 답변") is selected from the shared waveform menu.
        page.evaluate("() => document.getElementById('voiceWaveformButton').click()")
        page.wait_for_timeout(50)
        page.evaluate("""() => {
          const items = document.querySelectorAll('.voice-mode-menu-item');
          for (const it of items) {
            if (it.textContent.includes('문자로 답변')) {
              it.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              break;
            }
          }
        }""")
        page.wait_for_timeout(50)
        assert page.evaluate(
            "() => window.PadiemVoiceMenu.getState().mode"
        ) == "live"

        page.evaluate("() => document.getElementById('voiceMicButton').click()")
        page.wait_for_timeout(150)

        def confirm(text):
            page.evaluate("""(args) => {
              const socket = window.__live.sockets[window.__live.sockets.length - 1];
              socket.onmessage({ data: JSON.stringify({
                serverContent: {
                  inputTranscription: { text: args.text, finished: true },
                  turnComplete: true,
                },
              })});
            }""", {"text": text})
            page.wait_for_timeout(120)

        confirm("첫 번째 발화")
        assert page.evaluate("() => window.__test.sent.length") == 1
        assert page.evaluate("() => window.__test.sent[0]") == "첫 번째 발화"

        # The microphone stays open for the next utterance.
        assert page.evaluate(
            "() => window.PadiemVoiceComposer.getController().getStatus().active"
        ) is True

        # The answer settles: the composer becomes writable again.
        page.wait_for_timeout(200)
        page.evaluate(
            "() => { document.getElementById('messageInput').value = ''; }"
        )
        confirm("두 번째 발화")
        assert page.evaluate("() => window.__test.sent.length") == 2
        assert page.evaluate("() => window.__test.sent[1]") == "두 번째 발화"

        browser.close()


if __name__ == "__main__":
    test_live_transcription_writes_into_the_input_in_real_time()
    test_mode2_auto_sends_exactly_once_per_confirmed_utterance()
    print(json.dumps({"browser_voice_live": "PASS"}))
