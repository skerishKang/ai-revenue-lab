"""Real-browser proof for #4643 voice wiring.

Serves the actual static/ directory and loads the real voice-stt-input.js,
voice-composer.js and voice-stt-wiring.js in Chromium. The STT backend is
mocked at the network layer (it is still OFF), so this proves the *wiring*
works -- script load, composer mount, microphone permission, recognizer
factory registration, and the final-transcript-into-input path -- without
pretending a paid provider call happened.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header(
            "Permissions-Policy", "camera=(), microphone=(self), geolocation=()"
        )
        super().end_headers()


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def run(port: int) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            permissions=["microphone"],
            extra_http_headers={"Accept": "application/json"},
        )
        page = ctx.new_page()
        console_errors: list[str] = []
        outbound_posts: list[str] = []
        upload_prefixes: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        def route_handler(route):
            url = route.request.url
            if route.request.method == "POST" and ("/api/chat" in url or "/api/claw/general" in url):
                outbound_posts.append(url)
            if url.endswith("/health"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"voice_stt_available": True}),
                )
            elif "/api/voice/transcribe" in url:
                # The fake recorder emits the same marker contract as Chrome:
                # only the first dataavailable of a recorder run has the WebM
                # init segment. The provider cannot decode a bare fragment.
                prefix = ""
                try:
                    raw = route.request.post_data_buffer
                    prefix = raw[:4].decode("latin-1")
                except Exception:
                    prefix = ""
                upload_prefixes.append(prefix)
                if not prefix.startswith("INIT"):
                    route.fulfill(
                        status=400,
                        content_type="application/json",
                        body=json.dumps({"error": {"code": "invalid_audio"}}),
                    )
                    return
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {"text": "광주에서 AI 교육 견적서를 만들어 주세요"}
                    ),
                )
            elif "/api/voice/identity" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"identity_key": "test-key-1"}),
                )
            else:
                route.continue_()

        ctx.route("**/*", route_handler)

        # Real page, real mic click / recorder lifecycle, same-origin mocked
        # voice API. No paid provider, no browser permission dialog.
        ctx.add_init_script("""
          const fakeTrack = { stop() {} };
          const fakeStream = { getTracks: () => [fakeTrack] };
          Object.defineProperty(navigator, "mediaDevices", {
            configurable: true, value: { getUserMedia: async () => fakeStream }
          });
          // Controllable clock so the reviewed 4s minimum / 700ms silence cut
          // can be crossed without real-time waits.
          let fakeNow = 10000;
          try {
            Object.defineProperty(performance, "now", {
              configurable: true, value: () => fakeNow
            });
          } catch (e) { /* fall back to the real clock */ }
          window.__voiceTest = {
            advance(ms) { fakeNow += ms; },
            speak(on) { window.__speaking = on === true; },
          };
          class FakeRecorder {
            constructor() { this.state = "inactive"; this.emitted = 0; }
            static isTypeSupported() { return true; }
            _emit() {
              // Chrome puts the WebM init segment in the first dataavailable
              // of a recorder run only; later events are bare fragments.
              const marker = this.emitted === 0 ? "INIT" : "FRAG";
              this.emitted += 1;
              if (this.ondataavailable) this.ondataavailable({
                data: new Blob([marker], {type: "audio/webm"})
              });
            }
            start() { this.state = "recording"; this._emit(); }
            requestData() { if (this.state === "recording") this._emit(); }
            stop() { this.state = "inactive"; this._emit(); if (this.onstop) this.onstop(); }
          }
          window.MediaRecorder = FakeRecorder;
          class FakeAudioContext {
            createMediaStreamSource() { return {connect(){}}; }
            createAnalyser() {
              return {
                fftSize: 1024,
                getFloatTimeDomainData(buffer) { buffer.fill(window.__speaking ? 0.1 : 0); }
              };
            }
            close() {}
          }
          window.AudioContext = FakeAudioContext;
        """)

        page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        page.wait_for_timeout(2000)

        result: dict = {}

        result["wiring_defined"] = page.evaluate("typeof window.PadiemVoiceSttWiring")
        result["composer_defined"] = page.evaluate("typeof window.PadiemVoiceComposer")
        result["adapter_defined"] = page.evaluate("typeof window.PadiemVoiceSttInput")
        result["console_errors"] = console_errors

        result["mic_button_present"] = page.evaluate(
            "!!document.getElementById('voiceMicButton')"
        )

        result["factory_registered"] = page.evaluate(
            """() => {
              const c = window.PadiemVoiceComposer?.getController?.();
              if (!c) return false;
              const s = c.getStatus();
              return s.statusKey !== 'voice-unavailable-wiring';
            }"""
        )

        result["mic_disabled_when_signed_out"] = page.evaluate(
            """() => {
              const btn = document.getElementById('voiceMicButton');
              return btn ? btn.disabled : null;
            }"""
        )

        # Authenticate in the browser only; production CP/STT remains OFF.
        page.evaluate("""() => window.dispatchEvent(
          new CustomEvent('padiem:auth-state',{
            detail:{authenticated:true,identityKey:'test-key-1'}
          }))""")
        page.wait_for_timeout(100)
        result["mic_enabled_when_mock_authenticated"] = page.evaluate(
            "() => document.getElementById('voiceMicButton')?.disabled === false"
        )
        if result["mic_enabled_when_mock_authenticated"]:
            page.locator("#voiceMicButton").click()
            page.wait_for_timeout(100)
            page.locator("#voiceMicButton").click()
            try:
                page.wait_for_function(
                    "() => document.getElementById('messageInput')?.value.includes('광주에서 AI 교육 견적서')",
                    timeout=3500,
                )
            except Exception:
                pass
        result["stop_final_in_editable_input"] = page.evaluate(
            "() => document.getElementById('messageInput')?.value === '광주에서 AI 교육 견적서를 만들어 주세요'"
        )
        result["auto_submit_count"] = len(outbound_posts)
        result["composer_uploads_all_init"] = bool(upload_prefixes) and all(
            prefix.startswith("INIT") for prefix in upload_prefixes
        )
        composer_upload_count = len(upload_prefixes)

        # The composer ends the recognizer at every VAD cut, so consecutive
        # non-stop chunks are only reachable through the factory itself. Two
        # chunks must both upload a file that starts with the WebM init
        # segment; a reused recorder sends a bare fragment for chunk two and
        # the mocked provider rejects it with 400 invalid_audio.
        page.reload(wait_until="load")
        page.wait_for_timeout(400)
        result["factory_started"] = page.evaluate(
            """() => {
              window.__factoryEvents = [];
              const factory = window.PadiemVoiceSttWiring.createRecognizerFactory({
                win: window,
                doc: document,
                fetchImpl: window.fetch.bind(window),
                mediaDevices: navigator.mediaDevices,
              });
              window.__factorySession = factory({
                onFinal: (event) => window.__factoryEvents.push({
                  kind: 'final', text: event.text, id: event.utteranceId
                }),
                onError: (code) => window.__factoryEvents.push({
                  kind: 'error', code: String(code)
                }),
                onEnd: () => window.__factoryEvents.push({ kind: 'end' }),
              }, { generation: 1, sessionToken: 'browser-test' });
              return !!(window.__factorySession && window.__factorySession.stop);
            }"""
        )
        if result["factory_started"]:
            for _ in range(2):
                page.evaluate(
                    "window.__voiceTest.speak(true); window.__voiceTest.advance(100)"
                )
                page.wait_for_timeout(120)
                page.evaluate(
                    "window.__voiceTest.speak(false); window.__voiceTest.advance(4100)"
                )
                page.wait_for_timeout(350)
            factory_events = page.evaluate("window.__factoryEvents") or []
            result["factory_finals"] = [
                event for event in factory_events if event.get("kind") == "final"
            ]
            result["factory_errors"] = [
                event for event in factory_events if event.get("kind") == "error"
            ]
            page.evaluate(
                "window.__factorySession && window.__factorySession.stop('user-stopped')"
            )
        else:
            result["factory_finals"] = []
            result["factory_errors"] = [{"kind": "error", "code": "factory-not-started"}]
        result["factory_uploads"] = upload_prefixes[composer_upload_count:]
        result["factory_uploads_all_init"] = len(result["factory_uploads"]) >= 2 and all(
            prefix.startswith("INIT") for prefix in result["factory_uploads"]
        )

        result["permissions_policy_header"] = page.evaluate(
            """async () => {
              const r = await fetch('/index.html', { credentials: 'same-origin' });
              return r.headers.get('Permissions-Policy') || '';
            }"""
        )

        browser.close()
        return result


def main() -> int:
    httpd, port = serve()
    try:
        result = run(port)
    finally:
        httpd.shutdown()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Backend API calls (auth/identity/claw services) are intentionally
    # absent from the static-only test server and report 404s. Those are not
    # JavaScript failures and must not fail the wiring proof.
    js_console_errors = [
        error for error in (result.get("console_errors") or [])
        if not str(error).startswith("Failed to load resource")
    ]
    result["js_console_errors"] = js_console_errors
    ok = (
        result["wiring_defined"] == "object"
        and result["composer_defined"] == "object"
        and result["adapter_defined"] == "object"
        and result["mic_button_present"] is True
        and result["factory_registered"] is True
        and result["mic_enabled_when_mock_authenticated"] is True
        and result["stop_final_in_editable_input"] is True
        and result["auto_submit_count"] == 0
        and result["composer_uploads_all_init"] is True
        and result["factory_started"] is True
        and len(result["factory_finals"]) == 2
        and not result["factory_errors"]
        and result["factory_uploads_all_init"] is True
        and not js_console_errors
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
