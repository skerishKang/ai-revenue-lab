"""B66 UX regression: first greeting keeps existing guided draft; resize reflows.

Loopback HTTP + isolated Chromium; no real customer account/API/model calls,
no database writes, no production secrets or PDF changes.
"""
from __future__ import annotations

import http.server
import json
from pathlib import Path
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MARKER = "B66_QA_PRESERVE_SAVED_DRAFT_20261012"
SAVED = {
    "schema": "b66.guided-draft.v1", "mode": "guided", "step": "price",
    "draft": {"recipient": {"company": MARKER}},
}


class Server(socketserver.TCPServer):
    allow_reuse_address = True


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass


def rects(page):
    return page.evaluate("""() => {
      const rect = selector => {
        const r = document.querySelector(selector).getBoundingClientRect();
        return {left:r.left,right:r.right,width:r.width,center:(r.left+r.right)/2};
      };
      return {
        vw: innerWidth,
        doc: document.documentElement.scrollWidth,
        shell: rect('main.shell'),
        view: rect('#easyView'),
        home: rect('#easyEmpty'),
        composer: rect('.easy-composer'),
        railClosed: document.body.classList.contains('rail-collapsed'),
        previewClosed: document.body.classList.contains('preview-collapsed'),
      };
    }""")


def main():
    with Server(("127.0.0.1", 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1700, "height": 880})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def intercept(route):
                    if route.request.url.endswith("/api/padiem/b66/guided-draft"):
                        method = route.request.method
                        payload = {"ok": True, "state": SAVED} if method == "GET" else {"ok": True}
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps(payload, ensure_ascii=False))
                    else:
                        route.continue_()
                page.route("**/api/padiem/b66/guided-draft", intercept)
                page.add_init_script("""() => {
                    window.__qaConfirmCalls = [];
                    window.confirm = (text) => {
                        window.__qaConfirmCalls.push(text);
                        return false;
                    };
                }""")
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_function("Boolean(window.B66ShellLayout && window.B66QuoteAppBridge)")
                page.evaluate("""() => {
                    window.B66QuoteRuntimeBridge = {
                        readiness: () => ({authenticated:true,skillReady:false,
                                          profileReady:false,ready:false}),
                        clearPending: () => {},
                        assignedSavedSkillId: () => '',
                    };
                    document.dispatchEvent(new CustomEvent('b66:auth-changed',
                        {detail:{authenticated:true}}));
                }""")
                before = page.evaluate("JSON.stringify(window.B66QuoteAppBridge.getDraft())")
                page.locator("#easyComposer").fill("하이")
                page.locator("#easySend").click()
                page.locator("#easyMessageList").get_by_text("안녕하세요!", exact=False).wait_for()
                assert page.evaluate("window.__qaConfirmCalls.length") == 0
                assert page.evaluate("JSON.stringify(window.B66QuoteAppBridge.getDraft())") == before
                assert page.locator("#easyMessageList").get_by_text("하이", exact=True).count() == 1
                print("FIRST_GREETING_PRESERVES_DRAFT_NO_OVERWRITE_PROMPT=PASS", flush=True)

                # Explicitly starting a new quote MUST still protect the saved draft.
                page.locator("#easyChipRow").get_by_role("button", name="질문받으며 새 견적").click()
                page.wait_for_function("window.__qaConfirmCalls.length === 1")
                assert MARKER not in page.locator("#easyMessageList").inner_text()
                assert page.locator("#easyMessageList").get_by_text("하이", exact=True).count() == 1
                assert page.evaluate("JSON.stringify(window.B66QuoteAppBridge.getDraft())") == before
                print("EXPLICIT_NEW_QUOTE_STILL_PROTECTS_ACCOUNT_DRAFT=PASS", flush=True)
                page.locator("#easyChipRow").get_by_role("button", name="처음으로").click()
                assert page.locator("#easyEmpty").is_visible()

                for width in (1700, 1450, 1320, 1260, 1100, 920, 900, 390):
                    page.set_viewport_size({"width": width, "height": 880})
                    page.wait_for_timeout(90)
                    m = rects(page)
                    assert m["doc"] <= width + 2, (width, "horizontal overflow", m)
                    assert m["view"]["width"] > 0, (width, "collapsed center", m)
                    assert abs(m["home"]["center"] - m["view"]["center"]) <= 13, (
                        width, "home not centered in actual middle workspace", m
                    )
                    assert m["composer"]["left"] >= -2 and m["composer"]["right"] <= width + 2, (
                        width, "composer outside visible viewport", m
                    )
                    if width <= 1480:
                        assert m["previewClosed"], (width, "preview must auto-collapse", m)
                    if width <= 900:
                        assert m["railClosed"], (width, "rail mobile overlay should hide", m)
                    print(f"B66_RESPONSIVE_CENTER_PASS={width}px", flush=True)
                page.set_viewport_size({"width": 1700, "height": 880})
                page.wait_for_timeout(90)
                assert not rects(page)["previewClosed"], "auto-collapse must restore on widening"
                assert not errors, errors
                print("B66_RESIZE_RESTORES_DESKTOP_PREVIEW=PASS", flush=True)
                page.close()
            finally:
                browser.close()
        server.shutdown()


if __name__ == "__main__":
    main()
