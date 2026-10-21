"""Real-browser proof that the shared voice authority is what the page runs.

Serves the actual static/ directory and loads the real index.html, so the
script-tag order, the browser global and the adapter's delegation are exercised
as the browser sees them — the one thing the Node cases cannot prove, because
Node reaches the authority through require().

The voice backend is mocked at the network layer and the microphone is faked in
the page, exactly as tests/browser_voice_wiring_4643.py does. No provider call,
no paid model, no login. This proves wiring and turn behaviour, not a live STT
result.
"""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

SENTENCE = "광주에서 AI 교육 견적서를 만들어 주세요"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args) -> None:
        pass


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def run(port: int) -> dict:
    result: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page_errors: list[str] = []
        chat_posts: list[str] = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        def route_handler(route):
            url = route.request.url
            if route.request.method == "POST" and (
                "/api/chat" in url or "/api/claw/general" in url
            ):
                chat_posts.append(url)
            if url.endswith("/health"):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"voice_stt_available": True}))
            elif "/api/voice/transcribe" in url or "/api/claw/voice/transcribe" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"text": SENTENCE}))
            elif "/api/voice/identity" in url or "/api/claw/voice/identity" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"identity_key": "browser-key-1"}))
            elif "/api/" in url:
                # Every other backend stays absent: this page must not reach a real
                # service, and a missing route must not look like a working one.
                route.fulfill(status=404, content_type="application/json", body="{}")
            else:
                route.continue_()

        ctx.route("**/*", route_handler)
        ctx.add_init_script("""
          const fakeStream = { getTracks: () => [{ stop() {} }] };
          Object.defineProperty(navigator, "mediaDevices", {
            configurable: true, value: { getUserMedia: async () => fakeStream }
          });
          class FakeRecorder {
            constructor() { this.state = "inactive"; }
            static isTypeSupported() { return true; }
            start() { this.state = "recording"; }
            requestData() {
              if (this.ondataavailable) this.ondataavailable({
                data: new Blob(["browser-fake-speech"], { type: "audio/webm" })
              });
            }
            stop() { this.state = "inactive"; if (this.onstop) this.onstop(); }
          }
          window.MediaRecorder = FakeRecorder;
          class FakeAudioContext {
            createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
            createAnalyser() {
              return { fftSize: 1024, getFloatTimeDomainData(b) { b.fill(0); },
                       getByteTimeDomainData(b) { b.fill(128); } };
            }
            close() { return Promise.resolve(); }
          }
          window.AudioContext = FakeAudioContext;
        """)

        page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        page.wait_for_timeout(1200)

        # 1. The authority is a page global, and it is the object the adapter uses.
        result["authority_is_page_global"] = page.evaluate(
            "typeof window.PadiemVoiceLiveTranscriptTurn === 'object' "
            "&& window.PadiemVoiceLiveTranscriptTurn !== null"
        )
        result["adapter_uses_the_same_object"] = page.evaluate(
            "window.PadiemVoiceSttInput.authority === window.PadiemVoiceLiveTranscriptTurn"
        )
        result["authority_values_in_page"] = page.evaluate(
            "() => [window.PadiemVoiceLiveTranscriptTurn.LIVE_VAD_SILENCE_MS,"
            " window.PadiemVoiceLiveTranscriptTurn.LIVE_TAIL_FLUSH_DRAIN_MS,"
            " window.PadiemVoiceLiveTranscriptTurn.TRANSCRIPT_TURN_STALL_MS,"
            " window.PadiemVoiceLiveTranscriptTurn.LIVE_AUDIO_HANDOFF_FRAMES]"
        )
        result["no_require_in_the_page"] = page.evaluate("typeof require === 'undefined'")
        result["page_errors"] = page_errors

        # 2. Continuous speech through the page's real adapter: two chunks, one row.
        result["one_row_per_turn_in_page"] = page.evaluate("""() => {
          const rows = [];
          const run = window.PadiemVoiceSttInput.createVoiceInputAdapter({
            generation: 1, sessionToken: 'page-1',
            onFinalCandidate: (text) => rows.push(text),
          });
          run.start();
          run.feedInterim('Could you tell me', { generation: 1 });
          run.feedInterim(' which city you grew up in?', { generation: 1 });
          const beforeBoundary = rows.length;
          run.commitFinal({ generation: 1, sessionToken: 'page-1', utteranceId: 'u1' });
          run.commitFinal({ generation: 1, sessionToken: 'page-1', utteranceId: 'u1' });
          return { beforeBoundary, rows };
        }""")

        # 3. The retirement tail flush runs in the page (the audio a dropped
        #    session still holds must reach the transcript).
        result["tail_flush_in_page"] = page.evaluate("""() => {
          const signals = []; const settled = [];
          let closed = 0;
          const session = {
            sendRealtimeInput: (s) => signals.push(s),
            close: () => { closed += 1; },
          };
          const timers = [];
          const flush = window.PadiemVoiceLiveTranscriptTurn.flushLiveTranscriptTail(session, {
            onSettled: (text) => settled.push(text),
            setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
            clearTimer: () => {},
          });
          flush.accept({ text: 'Then I rolled the service back to the previous stable ', finished: false });
          flush.accept({ text: 'build.', finished: true });
          return { signals, settled, closed, drainMs: timers.map(t => t.ms) };
        }""")

        # 4. M1 in the real composer: final lands in the editable input, nothing sends.
        page.evaluate("""() => window.dispatchEvent(new CustomEvent('padiem:auth-state', {
          detail: { authenticated: true, identityKey: 'browser-key-1' } }))""")
        page.wait_for_timeout(150)
        page.locator("#messageInput").fill("")
        page.locator("#voiceMicButton").click()
        page.wait_for_timeout(150)
        page.locator("#voiceMicButton").click()
        try:
            page.wait_for_function(
                f"() => document.getElementById('messageInput')?.value.length > 0", timeout=4000)
        except Exception:
            pass
        result["m1_final_in_input"] = page.evaluate(
            f"() => document.getElementById('messageInput')?.value === {json.dumps(SENTENCE)}"
        )
        result["m1_auto_send_count"] = len(chat_posts)

        # 5. Mobile 390px: the control the four modes hang from is reachable.
        mobile = ctx.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        mobile.wait_for_timeout(800)
        result["mobile_390"] = mobile.evaluate("""() => {
          const btn = document.getElementById('voiceMicButton');
          if (!btn) return { present: false };
          const r = btn.getBoundingClientRect();
          return { present: true, insideViewport: r.left >= 0 && r.right <= window.innerWidth
                                   && r.width > 0 && r.height > 0,
                   horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth };
        }""")
        mobile.close()

        browser.close()
    return result


def main() -> int:
    httpd, port = serve()
    try:
        result = run(port)
    finally:
        httpd.shutdown()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    checks = [
        ("the authority is a page global", result["authority_is_page_global"] is True),
        ("the adapter uses that same object", result["adapter_uses_the_same_object"] is True),
        ("no CommonJS require in the page", result["no_require_in_the_page"] is True),
        ("the authority loaded before the adapter (no fail-closed throw)",
         result["page_errors"] == []),
        ("#87 values shipped", result["authority_values_in_page"] == [1300, 1200, 2500, 40]),
        ("two chunks of one turn make one row",
         result["one_row_per_turn_in_page"] == {
             "beforeBoundary": 0,
             "rows": ["Could you tell me which city you grew up in?"],
         }),
        ("the retired session is signalled and its tail settles once",
         result["tail_flush_in_page"] == {
             "signals": [{"audioStreamEnd": True}],
             "settled": ["Then I rolled the service back to the previous stable build."],
             "closed": 1,
             "drainMs": [1200],
         }),
        ("M1 puts the final in the existing input", result["m1_final_in_input"] is True),
        ("M1 never auto-sends", result["m1_auto_send_count"] == 0),
        ("390px keeps the microphone control on screen",
         result["mobile_390"].get("present") is True
         and result["mobile_390"].get("insideViewport") is True),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print("BROWSER PROOF FAILED: " + ", ".join(failed))
        return 1
    print("BROWSER PROOF PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
