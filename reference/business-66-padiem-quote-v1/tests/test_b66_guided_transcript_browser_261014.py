"""B66 deterministic Guided Q/A real Chromium test, loopback and synthetic only.

Proves exact words are sent in account-scoped Guided PUT, restored after reload,
and accessible by the distinct previous-Guided rail. No Production/model/files.
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import threading

from playwright.async_api import async_playwright
from test_b66_dialogue_ux_browser_4657 import ROOT, DialogueHandler, _reset_state

GUIDED_ID_PREFIX = "gdt_"


async def main():
    _reset_state()
    DialogueHandler.state["/b66/guided-conversations"] = {"ok": True, "conversations": []}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(DialogueHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    snapshots = []
    active = {"state": None}

    async def guided_stub(route):
        request = route.request
        suffix = request.url.split("/api/padiem", 1)[-1].split("?", 1)[0]
        if suffix == "/b66/guided-draft":
            if request.method == "GET":
                payload = {"ok": True, "state": active["state"]}
            elif request.method == "PUT":
                state = request.post_data_json
                snapshots.append(state)
                active["state"] = state
                payload = {"ok": True}
            elif request.method == "DELETE":
                active["state"] = None
                payload = {"ok": True}
            else:
                payload = {"ok": False}
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps(payload, ensure_ascii=False))
            return
        if suffix == "/b66/guided-conversations":
            latest = active["state"]
            rows = ([{"conversation_id": latest["conversationId"], "updated_at": "2026-10-14"}]
                    if latest and latest.get("transcript") else [])
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps({"ok": True, "conversations": rows}))
            return
        if suffix.startswith("/b66/guided-conversations/"):
            latest = active["state"]
            gid = suffix.rsplit("/", 1)[-1]
            if latest and latest.get("conversationId") == gid:
                payload = {"ok": True, "conversation": {
                    "conversation_id": gid, "messages": latest["transcript"]}}
                status = 200
            else:
                payload, status = {"ok": False}, 404
            await route.fulfill(status=status, content_type="application/json",
                                body=json.dumps(payload, ensure_ascii=False))
            return
        await route.continue_()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900},
                                            service_workers="block")
            await ctx.route("**/api/padiem/b66/guided-*", guided_stub)
            page = await ctx.new_page()
            await page.goto(base + "/index.html", wait_until="load")
            await page.wait_for_function("() => window.B66QuoteRuntimeBridge && window.B66GuidedDraftServer")
            await page.evaluate("""() => {
              const existing = window.B66QuoteRuntimeBridge;
              window.B66QuoteRuntimeBridge = {
                ...existing,
                readiness: () => ({authenticated:true,profileReady:true,skillReady:true,ready:true}),
                assignedSavedSkillId: () => "",
                supportedItemRows: () => 3,
                getCompanyProfile: () => ({company:"SYNTHETIC QA"}),
              };
            }""")
            await page.click("#guidedStarter")
            await page.wait_for_function("() => document.querySelectorAll('#easyMessageList .easy-assistant-message').length >= 1")
            await page.fill("#easyComposer", "TEST COMPANY")
            await page.click("#easySend")
            await page.fill("#easyComposer", "없음")
            await page.click("#easySend")
            await page.wait_for_function("() => document.querySelectorAll('#easyMessageList .easy-message').length >= 5")
            await page.wait_for_timeout(650)
            assert snapshots, "Guided state never sent to account store"
            state = snapshots[-1]
            assert state["conversationId"].startswith(GUIDED_ID_PREFIX)
            transcript = state["transcript"]
            assert any(m["role"] == "user" and m["content"] == "TEST COMPANY" for m in transcript)
            assert any(m["role"] == "assistant" and "담당자" in m["content"] for m in transcript)
            assert any(m["role"] == "user" and m["content"] == "없음" for m in transcript)
            assert state["step"] == "itemName"
            initial_messages = len(transcript)

            # A genuinely independent page GETs persisted state and restores Q/A.
            page2 = await ctx.new_page()
            await page2.goto(base + "/index.html", wait_until="load")
            await page2.wait_for_function("() => window.B66QuoteRuntimeBridge && window.B66GuidedDraftServer")
            await page2.click("#resumeDraftStarter")
            await page2.wait_for_function("() => document.querySelectorAll('#easyMessageList .easy-message').length >= 5")
            text = await page2.locator("#easyMessageList").inner_text()
            assert "TEST COMPANY" in text and "담당자" in text and "없음" in text
            await page2.wait_for_timeout(300)
            assert active["state"]["conversationId"] == state["conversationId"]
            assert len(active["state"]["transcript"]) >= initial_messages

            # Left rail shows retained *Guided* messages separately from AI Chat.
            await page2.click("#shellPreviousGuidedDialogue")
            await page2.wait_for_selector("#easyHistoryPanel .easy-history-card")
            await page2.locator("#easyHistoryPanel .easy-history-card button").first.click()
            await page2.wait_for_function(
                "() => document.querySelector('#easyMessageList')?.textContent?.includes('TEST COMPANY')")
            assert "TEST COMPANY" in await page2.locator("#easyMessageList").inner_text()
            assert not any(path.endswith("/b66/ai/chat") for method, path in DialogueHandler.calls)
            print("B66_GUIDED_TRANSCRIPT_BROWSER=PASS")
            print("B66_GUIDED_INDEPENDENT_PAGE_RESTORE=PASS")
            print("B66_GUIDED_PREVIOUS_HISTORY_RAIL=PASS")
            print("PRODUCTION_MUTATION=0")
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
