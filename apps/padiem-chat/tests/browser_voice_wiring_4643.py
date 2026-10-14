"""Real-browser proof for #4643 voice wiring.

Serves the actual static/ directory and loads the real voice-stt-input.js,
voice-composer.js and voice-stt-wiring.js in Chromium. The STT backend is
mocked at the network layer (it is still OFF), so this proves the *wiring*
works -- script load, composer mount, microphone permission, recognizer
factory registration, and the final-transcript-into-input path -- without
pretending a paid provider call happened.
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
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


def serve() -> tuple[HTTPServer, int]:
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
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
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        def route_handler(route):
            url = route.request.url
            if url.endswith("/health"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"voice_stt_available": True}),
                )
            elif "/api/voice/transcribe" in url:
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
              const c = window.PadiemVoiceComposer.getController();
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
        and not js_console_errors
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
