"""#4643: the Gemini Live engine in a real browser, with the transport faked.

The provider is faked on purpose: this test proves the CLIENT path end to end
in a real browser -- the microphone run, the Live session, the interim text
appearing in the input box while the user speaks, the confirmed sentence
merging into the existing input, no automatic send, and a microphone that
leaves no session, no capture and no timer behind.

The wire format and the session lifecycle are covered by
`voice_gemini_live_4643.cjs`; this test covers the product integration.
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

# A fake Live transport: the same frames the provider sends, so the engine's
# real message handling runs.
FAKE_TRANSPORT = """
() => {
  const sockets = [];
  const tracks = [];
  window.__live = { sockets: sockets, tracks: tracks, open: 0, closed: 0, frames: [] };

  class FakeSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.onopen = null; this.onmessage = null; this.onerror = null; this.onclose = null;
      sockets.push(this);
    }
    send(data) { this.sent.push(JSON.parse(data)); window.__live.frames.push(JSON.parse(data)); }
    close() { this.closed = true; this.readyState = 3; window.__live.closed += 1; }
    open() { this.readyState = 1; window.__live.open += 1; if (this.onopen) this.onopen(); }
    say(payload) { if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) }); }
  }
  window.WebSocket = FakeSocket;

  const processor = { onaudioprocess: null, connect() {}, disconnect() {} };
  window.AudioContext = class {
    constructor() { this.sampleRate = 16000; this.state = 'running'; this.destination = {}; }
    async resume() {}
    async close() { window.__live.audioClosed = (window.__live.audioClosed || 0) + 1; }
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
  // The same-origin token route, answered by the fake transport.
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
def test_the_live_transcript_reaches_the_input_box_and_nothing_is_sent() -> None:
    with Server(("127.0.0.1", 8907), Handler) as web:
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
              document.getElementById('composerForm').addEventListener('submit', (e) => {
                e.preventDefault();
                window.__sent.push(document.getElementById('messageInput').value);
              });
              // The product seam: the engine's own recognizer factory, the one
              // the wiring stage installs as the default provider.
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

            # The microphone starts the Live run.
            page.evaluate("() => document.getElementById('voiceMicButton').click()")
            page.wait_for_timeout(300)
            assert page.evaluate("() => window.__live.sockets.length") == 1
            # The provider accepts the session: the setup frame is the first
            # thing on the wire.
            page.evaluate("() => window.__live.sockets[0].open()")
            page.wait_for_timeout(200)
            socket_url = page.evaluate("() => window.__live.sockets[0].url")
            assert "access_token=auth_tokens%2Ffake" in socket_url
            setup = page.evaluate("() => window.__live.sockets[0].sent[0].setup")
            assert setup["model"] == "models/gemini-3.5-transcribe-live"
            assert setup["generationConfig"]["responseModalities"] == ["TEXT"]
            assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 1300
            assert setup["inputAudioTranscription"] == {"languageCodes": [], "mode": "VERBATIM"}

            # One microphone frame reaches the provider as PCM media.
            page.evaluate("""() => {
              const p = window.__live.processor;
              p.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(8) } });
            }""")
            media = page.evaluate(
                "() => window.__live.frames.find((f) => f.realtimeInput && f.realtimeInput.mediaChunks)"
            )
            assert media["realtimeInput"]["mediaChunks"][0]["mimeType"] == "audio/pcm;rate=16000"

            # The provider's interim text appears in the input box while the
            # user is still speaking.
            page.evaluate("""() => window.__live.sockets[0].say({
              serverContent: { interimInputTranscription: { text: '실시간' } }
            })""")
            page.wait_for_timeout(120)
            assert page.evaluate("() => document.getElementById('messageInput').value") == "실시간"

            # The confirmed sentence merges into the existing input and the
            # run continues.
            page.evaluate("""() => window.__live.sockets[0].say({
              serverContent: { inputTranscription: { text: '실시간 전사', finished: true } }
            })""")
            page.wait_for_timeout(150)
            assert page.evaluate("() => document.getElementById('messageInput').value") == "실시간 전사"
            page.evaluate("""() => window.__live.sockets[0].say({
              serverContent: { interimInputTranscription: { text: '계속' } }
            })""")
            page.wait_for_timeout(120)
            assert page.evaluate("() => document.getElementById('messageInput').value") == "실시간 전사 계속"

            # M1 never sends.
            assert page.evaluate("() => window.__sent.length") == 0

            # The microphone off leaves no session, no capture and no timer.
            page.evaluate("() => document.getElementById('voiceMicButton').click()")
            page.wait_for_timeout(200)
            assert page.evaluate("() => window.__live.sockets[0].closed") is True
            assert page.evaluate("() => window.__live.tracks[0].stopped") is True
            assert page.evaluate("() => window.__live.audioClosed") >= 1
            # No reconnect and no new session after the microphone went off.
            page.wait_for_timeout(400)
            assert page.evaluate("() => window.__live.sockets.length") == 1
            assert page.evaluate("() => window.__sent.length") == 0
            assert not errors, errors
            browser.close()
        web.shutdown()
