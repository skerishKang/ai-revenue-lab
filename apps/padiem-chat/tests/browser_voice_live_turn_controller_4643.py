"""Browser proof for the independent #4643 Mode 2 live turn controller."""

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
        page.route("**/*", lambda route: route.continue_())
        page.set_content(
            f"<!doctype html><html><body><script src='http://127.0.0.1:{port}/voice-live-turn-controller.js'></script></body></html>"
        )
        page.wait_for_timeout(1000)
        loaded = page.evaluate("typeof window.PadiemVoiceLiveTurnController")

        result = page.evaluate(
            """() => {
               const make = (mode) => {
                 let submitted = 0;
                 const commits = [];
                 const previews = [];
                 let inflate = false;
                 const c = window.PadiemVoiceLiveTurnController.create({
                   accountKey: 'acct-1',
                   getAccountKey: () => 'acct-1',
                   getInFlight: () => inflate,
                   commitText: (text) => { commits.push(text); },
                   submit: () => { submitted += 1; },
                   onPreview: (text) => { previews.push(text); },
                   mode: mode
                 });
                 return {
                   controller: c,
                   submitted: () => submitted,
                   commits: commits,
                   previews: previews,
                   setInFlight: (value) => { inflate = value; }
                 };
               };

               const basic = make('basic');
               basic.controller.handleFinal({ text: 'basic final', finalId: 'basic-1' });

               const live = make('live');
               live.controller.handleInterim({ text: 'interim hello', finalId: 'live-interim' });
               const previewsBeforeFinal = live.previews.length;
               live.controller.handleFinal({ text: 'live final', finalId: 'live-1' });
               const submitsAfterFirst = live.submitted();
               live.controller.handleFinal({ text: 'live final', finalId: 'live-1' });
               const submitsAfterDuplicate = live.submitted();

               const inflight = make('live');
               inflight.setInFlight(true);
               const inflightResult = inflight.controller.handleFinal({ text: 'inflight final', finalId: 'live-2' });

               const account = make('live');
               const accountResult = account.controller.handleFinal({
                 text: 'wrong account final',
                 finalId: 'live-3',
                 accountKey: 'acct-2'
               });

               return {
                 loaded: typeof window.PadiemVoiceLiveTurnController,
                 basic_submits: basic.submitted(),
                 live_submits_after_first: submitsAfterFirst,
                 duplicate_delta: submitsAfterDuplicate - submitsAfterFirst,
                 interim_previews: previewsBeforeFinal,
                 live_interim_submitted: false,
                 inflight_reason: inflightResult.reason,
                 inflight_blocked: inflight.submitted() === 0,
                 account_reason: accountResult.reason,
                 account_blocked: account.submitted() === 0,
                 live_commits: live.commits
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
        result["loaded"] == "object"
        and result["basic_submits"] == 0
        and result["live_submits_after_first"] == 1
        and result["duplicate_delta"] == 0
        and result["interim_previews"] == 1
        and result["inflight_blocked"] is True
        and result["account_blocked"] is True
        and result["live_commits"] == ["live final"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
