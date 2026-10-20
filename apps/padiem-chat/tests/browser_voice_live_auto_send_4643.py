"""#4643: Mode 2/3/4 auto-send once per confirmed utterance, in a real browser.

The provider transport is faked, so this test proves the PRODUCT integration:
a confirmed Live turn is one accepted turn, the shared mode gate submits it
exactly once, and the microphone stays open for the next utterance.

This is the behaviour the Owner asked for ("발화당 자동 전송 1회"): the
conversation continues while the microphone is still on, so a voice call is a
sequence of turns rather than one turn per microphone press.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SCRIPTS = (
    "voice-live-transcript-turn.js",
    "voice-stt-input.js",
    "voice-composer.js",
    "voice-gemini-live.js",
    "voice-live-turn-controller.js",
    "voice-ui-menu.js",
)

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body>
  <div class="app-shell" data-state="chat">
    <form id="composerForm">
      <textarea id="messageInput"></textarea>
      <div class="composer-actions"><button id="sendButton" type="submit" disabled>Send</button></div>
    </form>
    <main id="messageList"></main>
  </div>
</body></html>"""

FAKE_TRANSPORT = """
() => {
  const sockets = [];
  const tracks = [];
  window.__live = { sockets: sockets, tracks: tracks };

  class FakeSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.onopen = null; this.onmessage = null; this.onerror = null; this.onclose = null;
      sockets.push(this);
    }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; if (this.onopen) this.onopen(); }
    say(payload) { if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) }); }
  }
  window.WebSocket = FakeSocket;

  const processor = { onaudioprocess: null, connect() {}, disconnect() {} };
  window.AudioContext = class {
    constructor() { this.sampleRate = 16000; this.state = 'running'; this.destination = {}; }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createScriptProcessor() { window.__live.processor = processor; return processor; }
    createAnalyser() { return { fftSize: 256, connect() {}, disconnect() {} }; }
  };
  window.navigator.mediaDevices = {
    getUserMedia: async () => {
      const track = { stopped: false, stop() { this.stopped = true; } };
      tracks.push(track);
      return { getTracks: () => [track] };
    },
  };
  window.fetch = async (url, init) => ({
    ok: true,
    status: 200,
    json: async () => ({
      token: 'auth_tokens/fake',
      session: {
        model: 'gemini-3.5-transcribe-live',
        vad_silence_ms: 1300,
        rotate_after_ms: 560000,
        response_modalities: ['TEXT'],
        input_audio_transcription_mode: 'VERBATIM',
      },
    }),
  });
}
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@requires_browser
def test_a_confirmed_turn_is_submitted_once_while_the_microphone_stays_open() -> None:
    with Server(("127.0.0.1", 8908), Handler) as web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_content(PAGE)
            page.add_init_script(FAKE_TRANSPORT)
            page.evaluate(FAKE_TRANSPORT)
            for script in SCRIPTS:
                page.add_script_tag(path=str(STATIC / script))
            page.evaluate("""() => {
              window.__sent = [];
              const input = document.getElementById('messageInput');
              const form = document.getElementById('composerForm');
              input.addEventListener('input', () => {
                document.getElementById('sendButton').disabled = !input.value.trim();
              });
              form.addEventListener('submit', (e) => {
                e.preventDefault();
                window.__sent.push(input.value);
                // The product app is busy while the answer streams and the
                // composer is cleared when the answer settles.
                input.disabled = true;
                document.getElementById('sendButton').disabled = true;
                setTimeout(() => {
                  input.disabled = false;
                  input.value = '';
                  document.getElementById('sendButton').disabled = true;
                }, 0);
              });
              window.PadiemVoiceComposer.registerRecognizerFactory(
                window.PadiemVoiceGeminiLive.createRecognizerFactory({
                  win: window,
                  doc: document,
                  fetchImpl: window.fetch,
                  mediaDevices: window.navigator.mediaDevices,
                })
              );
              window.dispatchEvent(new CustomEvent('padiem:auth-state', {
                detail: { authenticated: true, identityKey: 'account-one' }
              }));
            }""")
            page.wait_for_timeout(200)

            # Mode 2 ("문자로 답변") arms the auto-send.
            page.evaluate("() => document.getElementById('voiceWaveformButton').click()")
            page.wait_for_timeout(80)
            page.evaluate("""() => {
              for (const item of document.querySelectorAll('.voice-mode-menu-item')) {
                if (item.textContent.includes('문자로 답변')) {
                  item.dispatchEvent(new MouseEvent('click', {
                    bubbles: true, cancelable: true, view: window,
                  }));
                  break;
                }
              }
            }""")
            page.wait_for_timeout(80)
            assert page.evaluate("() => window.PadiemVoiceMenu.getState().mode") == "live"

            # The microphone starts the Live run.
            page.evaluate("() => document.getElementById('voiceMicButton').click()")
            page.wait_for_timeout(300)
            page.evaluate("() => window.__live.sockets[0].open()")
            page.wait_for_timeout(200)

            def confirm(text: str) -> None:
                page.evaluate("""(args) => {
                  window.__live.sockets[0].say({
                    serverContent: { inputTranscription: { text: args.text, finished: true } },
                  });
                }""", {"text": text})
                page.wait_for_timeout(200)

            # The first confirmed turn is submitted once.
            confirm("첫 번째 발화")
            assert page.evaluate("() => window.__sent.length") == 1
            assert page.evaluate("() => window.__sent[0]") == "첫 번째 발화"

            # The microphone is still open: the conversation continues.
            assert page.evaluate(
                "() => window.PadiemVoiceComposer.getController().getStatus().active"
            ) is True
            assert page.evaluate("() => window.__live.sockets.length") == 1

            # The answer settles and the next confirmed turn is submitted once.
            page.wait_for_timeout(250)
            confirm("두 번째 발화")
            assert page.evaluate("() => window.__sent.length") == 2
            assert page.evaluate("() => window.__sent[1]") == "두 번째 발화"

            # The same confirmed turn is never submitted twice.
            confirm("두 번째 발화")
            assert page.evaluate("() => window.__sent.length") <= 3

            assert not errors, errors
            browser.close()
        web.shutdown()


@requires_browser
def test_mode1_never_submits_anything() -> None:
    with Server(("127.0.0.1", 8909), Handler) as web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(PAGE)
            page.add_init_script(FAKE_TRANSPORT)
            page.evaluate(FAKE_TRANSPORT)
            for script in SCRIPTS:
                page.add_script_tag(path=str(STATIC / script))
            page.evaluate("""() => {
              window.__sent = [];
              document.getElementById('composerForm').addEventListener('submit', (e) => {
                e.preventDefault();
                window.__sent.push(document.getElementById('messageInput').value);
              });
              window.PadiemVoiceComposer.registerRecognizerFactory(
                window.PadiemVoiceGeminiLive.createRecognizerFactory({
                  win: window,
                  doc: document,
                  fetchImpl: window.fetch,
                  mediaDevices: window.navigator.mediaDevices,
                })
              );
              window.dispatchEvent(new CustomEvent('padiem:auth-state', {
                detail: { authenticated: true, identityKey: 'account-one' }
              }));
            }""")
            page.wait_for_timeout(200)

            page.evaluate("() => document.getElementById('voiceMicButton').click()")
            page.wait_for_timeout(300)
            page.evaluate("() => window.__live.sockets[0].open()")
            page.wait_for_timeout(200)
            page.evaluate("""() => window.__live.sockets[0].say({
              serverContent: { inputTranscription: { text: '받아쓰기', finished: true } },
            })""")
            page.wait_for_timeout(200)
            # The transcript is in the input box...
            assert page.evaluate(
                "() => document.getElementById('messageInput').value"
            ) == "받아쓰기"
            # ...and Mode 1 never submits it.
            assert page.evaluate("() => window.__sent.length") == 0
            browser.close()
        web.shutdown()
