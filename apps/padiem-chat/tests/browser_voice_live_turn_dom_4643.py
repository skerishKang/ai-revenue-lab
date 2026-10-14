"""DOM-form proof for #4643 Mode2 approved-final submission."""

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
            f"""
            <!doctype html>
            <html><body>
              <form id="composerForm">
                <input id="input" name="prompt">
                <button id="sendButton" type="submit">Send</button>
              </form>
              <script src='http://127.0.0.1:{port}/voice-live-turn-controller.js'></script>
            </body></html>
            """
        )
        page.wait_for_timeout(1000)

        result = page.evaluate(
            """() => {
               const form = document.getElementById('composerForm');
               let submitCount = 0;
               let lastText = '';
               form.addEventListener('submit', (event) => {
                 event.preventDefault();
                 submitCount += 1;
                 lastText = document.getElementById('input').value;
               });
               let inflate = false;
               const c = window.PadiemVoiceLiveTurnController.create({
                 accountKey: 'acct-1',
                 getAccountKey: () => 'acct-1',
                 getInFlight: () => inflate,
                 commitText: (text) => { document.getElementById('input').value = text; },
                 submit: () => form.requestSubmit(),
               });
               c.setMode('live');

               const results = {};
               c.handleInterim({ text: 'interim hello' });
               results.interim_submits = submitCount;
               inflate = true;
               c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'live final', finalId: 'f1' });
               results.inflight_blocked = submitCount;
                results.inflight_reason = c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'live final', finalId: 'f1' }).reason;
                inflate = false;
               c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'live final', finalId: 'f1' });
               results.after_duplicate = submitCount;
               c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'second live final', finalId: 'f2' });
               results.after_second = submitCount;
               c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'second live final', finalId: 'f2' });
               results.after_second_duplicate = submitCount;
               c.setCompositionActive(true);
               c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'ime pending', finalId: 'f3' });
               results.composition_blocked = submitCount;
               c.endComposition();
               const flushed = c.handleFinal({ accepted: true, sessionGeneration: 1, text: 'after composition', finalId: 'f4' });
               results.composition_flush_submitted = flushed.submitted ? submitCount : submitCount;
               return Object.assign(results, { last_text: lastText, total_submits: submitCount });
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
        result["interim_submits"] == 0
        and result["inflight_blocked"] == 0
        and result["after_duplicate"] == 1
        and result["after_second"] == 2
        and result["after_second_duplicate"] == 2
        and result["composition_blocked"] == 2
        and result["total_submits"] == 3
        and result["last_text"] == "after composition"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())