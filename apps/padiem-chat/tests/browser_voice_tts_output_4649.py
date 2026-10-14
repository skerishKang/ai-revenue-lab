"""Browser proof for default browser TTS output module."""

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


def serve():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def run(port):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(
            f"<!doctype html><html><body><script src='http://127.0.0.1:{port}/voice-tts-output.js'></script></body></html>"
        )
        page.wait_for_timeout(1000)

        result = page.evaluate(
            """() => {
               const moduleType = typeof window.PadiemVoiceTTSOutput;
               const supported = moduleType === 'object';
               const t = supported ? window.PadiemVoiceTTSOutput.create({ userGestureSeen: true, lang: 'ko-KR' }) : null;
               const speaksWithoutGesture = supported
                 ? window.PadiemVoiceTTSOutput.create({ userGestureSeen: false }).speakText('hello') === false
                 : false;
               const safe = supported ? window.PadiemVoiceTTSOutput.safeText('**bold** `code` [link](https://example.com)') : '';
               return {
                 moduleType: moduleType,
                 supported: t ? t.isSupported() : false,
                 state: t ? t.getState() : null,
                 blocked_without_gesture: speaksWithoutGesture,
                 safe_text: safe
               };
            }"""
        )
        browser.close()
        return result


def main():
    httpd, port = serve()
    try:
        result = run(port)
    finally:
        httpd.shutdown()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    ok = (
        result["moduleType"] == "object"
        and result["blocked_without_gesture"] is True
        and result["safe_text"] == "bold code link"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
