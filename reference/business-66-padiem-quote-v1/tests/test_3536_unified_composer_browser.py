"""#3536 offline browser acceptance: one composer, left management, scoped single dispatch.

All HTTP is a loopback static server. The B14 interpreter is replaced in the
browser with a stub; neither real provider nor production is contacted.
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import os
from pathlib import Path
import threading
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return


async def main():
    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as pw:
            launch = {"headless": True}
            browser_path = os.environ.get("B66_PARITY_BROWSER", "")
            if browser_path:
                launch["executable_path"] = browser_path
            browser = await pw.chromium.launch(**launch)
            try:
                page = await browser.new_page(viewport={"width": 1600, "height": 1080})
                requests = []
                page.on("request", lambda req: requests.append((req.method, req.url)))
                url = "http://127.0.0.1:" + str(server.server_address[1]) + "/index.html"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_function("window.B66ShellLayout && window.B66QuoteRuntimeBridge")
                # Let the loopback /auth/status 404 settle before navigation assertions.
                await page.wait_for_timeout(300)
                result = await page.evaluate("""() => ({
                  activeInput: document.querySelectorAll('#easyComposer').length,
                  activeSend: document.querySelectorAll('#easySend').length,
                  legacyInput: document.querySelectorAll('#padiemQuoteRequest').length,
                  legacySend: document.querySelectorAll('#padiemQuoteGenerate').length,
                  modelInRail: document.querySelectorAll('#shellModelSelect #padiemQuoteModelSelect').length,
                  modelCount: document.querySelectorAll('#padiemQuoteModelSelect').length,
                  skillInRail: document.querySelectorAll('#shellSkillSelect #padiemSavedSkillSelect').length,
                  statusInRail: document.querySelectorAll('#shellRail #padiemQuoteStatus').length,
                  modelHiddenSignedOut: document.getElementById('shellModelControl').hidden
                })""")
                assert result == {
                    "activeInput": 1, "activeSend": 1, "legacyInput": 0,
                    "legacySend": 0, "modelInRail": 1, "modelCount": 1,
                    "skillInRail": 1, "statusInRail": 1,
                    "modelHiddenSignedOut": True,
                }, result

                await page.evaluate("""() => document.dispatchEvent(new CustomEvent(
                    'b66:auth-changed', {detail:{authenticated:true}}))""")
                assert await page.evaluate(
                    "() => !document.getElementById('shellModelControl').hidden"
                )
                await page.evaluate("""() => document.dispatchEvent(new CustomEvent(
                    'b66:auth-changed', {detail:{authenticated:false}}))""")
                assert await page.evaluate(
                    "() => document.getElementById('shellModelControl').hidden"
                )

                await page.click("#directModeButton")
                assert await page.evaluate("() => !document.getElementById('directView').hidden")
                await page.click("#shellRecentQuote")
                assert await page.evaluate("() => !document.getElementById('easyView').hidden")
                assert await page.evaluate("() => document.getElementById('directView').hidden")
                assert await page.evaluate("() => !document.getElementById('easyHistoryPanel').hidden")
                await page.click("#directModeButton")
                async with page.expect_file_chooser():
                    await page.click("#shellFileImport")
                assert await page.evaluate("() => !document.getElementById('easyView').hidden")

                # One mocked interpretation request; second immediate click must be ignored.
                await page.evaluate("""() => {
                  window.__interpretCalls = 0;
                  window.__resolveInterpret = null;
                  Object.defineProperty(window, 'B66QuoteRuntimeBridge', {
                    configurable: true,
                    value: {
                      readiness: () => ({ready: true, authenticated: true, skillReady: true}),
                      interpret: () => {
                        window.__interpretCalls++;
                        return new Promise(resolve => { window.__resolveInterpret = resolve; });
                      },
                      clearPending: () => {},
                      errorText: code => code
                    }
                  });
                  document.getElementById('freeChatStarter').click();
                }""")
                await page.evaluate("""() => {
                  document.getElementById('easyComposer').value = '견적 2개';
                  document.getElementById('easySend').click();
                  document.getElementById('easySend').click();
                }""")
                await page.wait_for_function("window.__interpretCalls === 1")
                assert await page.evaluate("() => document.getElementById('easySend').disabled")

                # Old-account output must never bleed into a new account after scope change.
                await page.evaluate("""() => document.dispatchEvent(new CustomEvent(
                  'b66:account-scope-changed', {detail:{privateStateReadable:false}}))""")
                assert await page.evaluate("() => !document.getElementById('easySend').disabled")
                assert await page.evaluate("() => document.getElementById('easyComposer').value === ''")
                assert await page.evaluate("() => document.getElementById('easyMessageList').children.length === 0")
                await page.evaluate("() => window.__resolveInterpret({ok:false, code:'interpret_failed'})")
                await page.wait_for_timeout(30)
                assert await page.evaluate("() => document.getElementById('easyMessageList').children.length === 0")
                assert await page.evaluate("() => !document.getElementById('easySend').disabled")

                # Account change in the same JS turn must cancel even the queued dispatch.
                await page.evaluate("""() => {
                  document.getElementById('freeChatStarter').click();
                  document.getElementById('easyComposer').value = '보내지 말아야 할 견적';
                  document.getElementById('easySend').click();
                  document.dispatchEvent(new CustomEvent(
                    'b66:account-scope-changed', {detail:{privateStateReadable:false}}));
                }""")
                await page.wait_for_timeout(30)
                assert await page.evaluate("() => window.__interpretCalls === 1")
                assert await page.evaluate("() => document.getElementById('easyMessageList').children.length === 0")

                # All permitted network here is loopback static GET; no live B14 POST.
                external = [(method, href) for method, href in requests
                            if not href.startswith("http://127.0.0.1:")]
                assert not external, external
                assert not any(method == "POST" for method, _ in requests), requests
                print("B66_3536_BROWSER_E2E=PASS")
                print("FREE_FORM_INPUT_SURFACES=1")
                print("DUPLICATE_INTERPRET_DISPATCH=0")
                print("STALE_ACCOUNT_RESPONSE_VISIBLE=0")
                print("B14_PROVIDER_POSTS=0")
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    asyncio.run(main())
