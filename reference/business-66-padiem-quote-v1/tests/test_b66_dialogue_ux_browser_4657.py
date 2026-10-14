"""#4657 B66 customer dialogue UX — real-browser acceptance (offline).

Drives the real B66 customer page in a real Chromium against a loopback server
whose B66 API is a deterministic stub, in the order a customer uses it:

1. the header brand starts a new, empty conversation
2. a signed-in customer asks a question -> the real model path answers and the
   assistant answer is rendered as Markdown (<strong>), never as raw markup
3. the previous-dialogue rail lists that conversation and can search it
4. opening it restores the stored transcript, and the next question continues
   the SAME server-owned conversation id
5. the brand click clears the screen but never deletes the stored dialogue
6. the rail is usable at a mobile width

Nothing here contacts a provider, Production, Secrets or a real identity: the
B66 chat endpoint is a scripted stub, exactly like the existing #3536/#4076
offline browser acceptance. Every value is synthetic and non-routable.

Usage:
    python test_b66_dialogue_ux_browser_4657.py
    B66_4657_EVIDENCE_DIR=<dir> python test_b66_dialogue_ux_browser_4657.py
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import unquote

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE_DIR = os.environ.get("B66_4657_EVIDENCE_DIR")
EVIDENCE = Path(_EVIDENCE_DIR) if _EVIDENCE_DIR else None

MODEL_ID = "google/gemini-3.5-flash-lite"
DIALOGUE_ID = "chat_" + "a" * 32
SECOND_DIALOGUE_ID = "chat_" + "b" * 32
EMAIL = "demo@example.test"

# The exact production bug #4655: literal delimiters shown instead of bold.
FIRST_ANSWER = (
    "1. **한 번에 설명하기**\n"
    "2. **질문에 답하며 작성하기**\n\n"
    "<img src=x onerror=alert(1)>\n"
    "<script>alert(2)</script>"
)
FOLLOW_UP_ANSWER = "**이어서** 답변드립니다."


class DialogueHandler(http.server.SimpleHTTPRequestHandler):
    """Static B66 customer page + a scripted, deterministic B66 dialogue stub."""

    state: dict = {}
    calls: list = []
    chat_requests: list = []

    def log_message(self, *_args):  # pragma: no cover - keep output clean
        return

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _route(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/padiem"):
            return path[len("/api/padiem"):]
        return path

    def _stub_delay(self):
        """A deterministic lateness knob, so a late response can be observed."""
        seconds = type(self).state.get("delaySeconds") or {}
        pending = seconds.get("chat") if self.command == "POST" else seconds.get("dialogue")
        if pending:
            time.sleep(pending)

    def do_GET(self):
        path = self._route()
        if not path.startswith(("/auth/", "/b66/")):
            return super().do_GET()  # real static customer page asset
        type(self).calls.append(("GET", self.path))
        self._stub_delay()
        if path == "/b66/ai/dialogues":
            query = ""
            if "?" in self.path:
                raw = self.path.split("?", 1)[1]
                for part in raw.split("&"):
                    if part.startswith("q="):
                        query = unquote(part[2:])
            rows = list(type(self).state.get("dialogues") or [])
            if query:
                rows = [row for row in rows if query in (row.get("title") or "")]
            return self._json({"ok": True, "authority": "b66-dialogue",
                               "conversations": rows, "query": query})
        prefix = "/b66/ai/dialogues/"
        if path.startswith(prefix):
            conversation_id = path[len(prefix):]
            stored = type(self).state.get("stored") or {}
            conversation = stored.get(conversation_id)
            if conversation is None:
                return self._json({"ok": False, "error": {"code": "conversation_not_found"}}, 404)
            return self._json({"ok": True, "conversation": conversation})
        payload = type(self).state.get(path)
        if payload is None:
            return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
        return self._json(payload)

    def do_DELETE(self):
        path = self._route()
        type(self).calls.append(("DELETE", self.path))
        prefix = "/b66/ai/dialogues/"
        if path.startswith(prefix):
            conversation_id = path[len(prefix):]
            stored = type(self).state.setdefault("stored", {})
            stored.pop(conversation_id, None)
            type(self).state["dialogues"] = [
                row for row in type(self).state.get("dialogues") or []
                if row.get("conversation_id") != conversation_id
            ]
            return self._json({"ok": True, "deleted": True, "conversation_id": conversation_id})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_POST(self):
        path = self._route()
        type(self).calls.append(("POST", self.path))
        self._stub_delay()
        body = self._read_json()
        if path == "/b66/ai/chat":
            type(self).chat_requests.append(body)
            messages = body.get("messages") or []
            last_user = next((m.get("content") for m in reversed(messages)
                              if m.get("role") == "user"), "")
            conversation_id = body.get("conversation_id")
            stored = type(self).state.setdefault("stored", {})
            if conversation_id:
                conversation = stored.get(conversation_id)
                if conversation is None:
                    return self._json(
                        {"ok": False, "error": {"code": "conversation_not_found"}}, 404)
                answer = "늦게 도착한 답변"
            else:
                conversation_id = DIALOGUE_ID
                answer = FIRST_ANSWER
            conversation = stored.get(conversation_id) or {
                "conversation_id": conversation_id,
                "title": last_user[:80] or "새 대화",
                "updated_at": "2026-10-14T01:00:00Z",
                "messages": [],
            }
            conversation["messages"] = list(conversation["messages"]) + [
                {"role": "user", "content": last_user},
                {"role": "assistant", "content": answer},
            ]
            stored[conversation_id] = conversation
            rows = type(self).state.setdefault("dialogues", [])
            if not any(row.get("conversation_id") == conversation_id for row in rows):
                rows.append({
                    "conversation_id": conversation_id,
                    "title": conversation["title"],
                    "updated_at": conversation["updated_at"],
                })
            return self._json({
                "ok": True,
                "answer": answer,
                "model_id": body.get("model_id"),
                "saved_quote": False,
                "model_origin": "registered_model_completion",
                "conversation_id": conversation_id,
                "dialogue_saved": True,
                "search": {"status": "not_needed", "reason": "no_external_evidence_trigger",
                           "sources": []},
            })
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)


SELECT_MODEL_JS = """() => {
  const select = document.getElementById('padiemQuoteModelSelect');
  const real = Array.from(select.options).find(option => option.value);
  if (!real) return '';
  select.value = real.value;
  select.dispatchEvent(new Event('change', {bubbles: true}));
  return select.value;
}"""

ASSISTANT_STATE_JS = """() => {
  const articles = Array.from(document.querySelectorAll('#easyMessageList .easy-message'));
  const assistant = articles.filter(node => node.classList.contains('easy-assistant-message'));
  const last = assistant[assistant.length - 1];
  if (!last) return null;
  const content = last.querySelector('.easy-message-content');
  return {
    text: content ? (content.textContent || '') : '',
    strong: Array.from(content ? content.querySelectorAll('strong') : []).map(n => n.textContent),
    listItems: content ? content.querySelectorAll('.b66-md-item').length : 0,
    images: content ? content.querySelectorAll('img').length : 0,
    scripts: content ? content.querySelectorAll('script').length : 0,
  };
}"""


async def shot(page, name: str) -> None:
    if EVIDENCE is None:
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(EVIDENCE / f"{name}.png"), full_page=True)


def _reset_state() -> None:
    DialogueHandler.state = {
        "/auth/status": {
            "ok": True, "authenticated": True, "session_state": "signed_in",
            "user": {"id": "demo-user", "email": EMAIL},
            "methods": {"google": True, "password": False},
        },
        "/b66/admin/me": {"ok": True, "admin": False},
        "/b66/quote/models": {
            "ok": True,
            "models": [{
                "model_id": MODEL_ID, "name": "Gemini 3.5 Flash Lite",
                "reasoning_levels": [{"value": "default", "label": "기본(제공자 기본값)"}],
            }],
            "default_model_id": None,
        },
        # No assigned CGI Skill: the customer is in the real AI-dialogue case.
        "/b66/saved-skills": {"ok": True, "skills": [], "limit": 20},
        "/b66/company-profile": {"ok": True, "company_profile": None},
        "/b66/quotes": {"ok": True, "quotes": [], "limit": 20},
        "/b66/guided-draft": {"ok": True, "state": None},
        "dialogues": [],
        "stored": {},
        "delaySeconds": {},
    }
    DialogueHandler.calls = []
    DialogueHandler.chat_requests = []


async def main() -> int:
    handler = functools.partial(DialogueHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    failures: list[str] = []
    report: dict = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        # The explicit delete asks the customer to confirm; accept it here.
        page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
        try:
            _reset_state()
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge && window.B66SafeMarkdown", timeout=20000)
            model = await page.evaluate(SELECT_MODEL_JS)
            report["model"] = model
            if not model:
                failures.append("model_not_selectable")
            await shot(page, "01-home")

            # 1) brand -> new empty conversation
            await page.click("#brandHome")
            await page.wait_for_timeout(150)
            empty = await page.evaluate(
                "() => document.getElementById('easyMessageList').children.length")
            report["brand_new_chat_empty"] = empty == 0
            if empty != 0:
                failures.append("brand_did_not_start_a_new_chat")

            # 2) ask -> real model path -> Markdown answer
            await page.click("#freeChatStarter")
            await page.fill("#easyComposer", "철근 견적을 설명해 주세요")
            await page.click("#easySend")
            await page.wait_for_function(
                "() => document.querySelectorAll('#easyMessageList .easy-assistant-message')"
                ".length >= 2", timeout=20000)
            await page.wait_for_timeout(200)
            answer = await page.evaluate(ASSISTANT_STATE_JS)
            report["first_answer"] = answer
            if not answer or answer["strong"] != ["한 번에 설명하기", "질문에 답하며 작성하기"]:
                failures.append("assistant_bold_not_rendered")
            if not answer or answer["listItems"] != 2:
                failures.append("assistant_steps_not_rendered")
            if answer and (answer["images"] or answer["scripts"]):
                failures.append("model_html_became_markup")
            if answer and "<img src=x onerror=alert(1)>" not in answer["text"]:
                failures.append("model_html_not_shown_as_literal_text")
            first_request = DialogueHandler.chat_requests[-1]
            report["first_chat_request_conversation_id"] = first_request.get("conversation_id")
            if first_request.get("conversation_id") is not None:
                failures.append("new_chat_named_a_conversation_id")
            await shot(page, "02-assistant-markdown")

            # 3) persistent left rail opens the same owner-scoped AI-dialogue list.
            #    It remains separate from the saved-quotation rail entry.
            await page.click("#brandHome")
            await page.wait_for_timeout(100)
            await page.click("#shellPreviousAiDialogue")
            await page.wait_for_selector("#easyDialogueResults .easy-dialogue-card", timeout=20000)
            cards = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["rail_cards"] = cards
            if cards != 1:
                failures.append("rail_did_not_list_the_conversation")
            await shot(page, "03-previous-dialogue-rail")

            await page.fill("#easyDialogueSearch", "철근")
            await page.wait_for_timeout(500)
            searched = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["rail_search_hits"] = searched
            if searched != 1:
                failures.append("rail_search_did_not_match")
            await page.fill("#easyDialogueSearch", "존재하지않는검색어")
            await page.wait_for_timeout(500)
            missing = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["rail_search_empty"] = missing
            if missing != 0:
                failures.append("rail_search_returned_an_unrelated_row")
            await page.fill("#easyDialogueSearch", "")
            await page.wait_for_timeout(500)

            # 4) open -> restore -> continue the same conversation
            await page.click("#easyDialogueResults .easy-dialogue-card button")
            await page.wait_for_function(
                "() => document.querySelectorAll('#easyMessageList .easy-message').length >= 2",
                timeout=20000)
            await page.wait_for_timeout(200)
            restored = await page.evaluate(
                "() => document.querySelectorAll('#easyMessageList .easy-message').length")
            report["restored_messages"] = restored
            if restored != 2:
                failures.append("restore_did_not_show_the_stored_transcript")
            await shot(page, "04-restored-dialogue")

            await page.fill("#easyComposer", "이어서 알려주세요")
            await page.click("#easySend")
            await page.wait_for_function(
                "() => document.querySelectorAll('#easyMessageList .easy-message').length >= 4",
                timeout=20000)
            await page.wait_for_timeout(200)
            continued = DialogueHandler.chat_requests[-1]
            report["continued_chat_conversation_id"] = continued.get("conversation_id")
            if continued.get("conversation_id") != DIALOGUE_ID:
                failures.append("continuation_did_not_use_the_stored_conversation_id")
            await shot(page, "05-continued-dialogue")

            # 5) brand clears the screen but keeps the stored dialogue
            await page.click("#brandHome")
            await page.wait_for_timeout(150)
            cleared = await page.evaluate(
                "() => document.getElementById('easyMessageList').children.length")
            report["brand_cleared_transcript"] = cleared == 0
            if cleared != 0:
                failures.append("brand_did_not_clear_the_transcript")
            await page.click("#aiDialogueStarter")
            await page.wait_for_selector("#easyDialogueResults .easy-dialogue-card", timeout=20000)
            still_there = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["stored_dialogue_survived_new_chat"] = still_there == 1
            if still_there != 1:
                failures.append("new_chat_deleted_the_stored_dialogue")

            # 6) explicit delete only on confirmation
            await page.evaluate(
                "() => document.querySelector('#easyDialogueResults .easy-dialogue-card button.danger').click()")
            await page.wait_for_timeout(400)
            gone = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["deleted_after_confirmation"] = gone == 0
            if gone != 0:
                failures.append("explicit_delete_did_not_remove_the_row")
            await shot(page, "06-deleted")

            # 6a) P0-C: an in-flight answer may not repopulate a new chat.
            DialogueHandler.state["delaySeconds"] = {"chat": 0.8}
            await page.click("#brandHome")
            await page.click("#freeChatStarter")
            await page.fill("#easyComposer", "늦게 도착할 질문")
            await page.click("#easySend")
            await page.wait_for_selector("text=답변을 작성하고 있습니다", timeout=20000)
            await page.click("#brandHome")
            await page.wait_for_timeout(300)
            cleared = await page.evaluate(
                "() => document.querySelectorAll('#easyMessageList .easy-message').length"
            )
            await page.wait_for_timeout(1200)
            late = await page.evaluate(
                """() => {
                     const nodes = Array.from(document.querySelectorAll('#easyMessageList *'));
                     return {
                       messages: document.querySelectorAll('#easyMessageList .easy-message').length,
                       answer: nodes.some(n => n.textContent.includes('늦게 도착한 답변')),
                       pending: nodes.some(n => n.textContent.includes('답변을 작성하고 있습니다'))
                     };
                   }"""
            )
            report["in_flight_answer_after_new_chat"] = late
            if cleared != 0 or late["messages"] != 0 or late["answer"] or late["pending"]:
                failures.append("late_answer_repopulated_new_chat")
            await shot(page, "06b-late-answer-discarded")

            # 6b) P0-B: a late restore may not overwrite a new chat either.
            DialogueHandler.state["delaySeconds"] = {"dialogue": 0.8}
            await page.click("#aiDialogueStarter")
            await page.wait_for_selector("#easyDialogueResults .easy-dialogue-card", timeout=20000)
            await page.click("#easyDialogueResults .easy-dialogue-card button")
            await page.wait_for_timeout(200)
            await page.click("#brandHome")
            await page.wait_for_timeout(1600)
            late_restore = await page.evaluate(
                """() => {
                     const nodes = Array.from(document.querySelectorAll('#easyMessageList *'));
                     return {
                       messages: document.querySelectorAll('#easyMessageList .easy-message').length,
                       restored: nodes.some(n => n.textContent.includes('늦게 도착한 질문'))
                     };
                   }"""
            )
            report["late_restore_after_new_chat"] = late_restore
            if late_restore["messages"] != 0 or late_restore["restored"]:
                failures.append("late_restore_overwrote_new_chat")
            await shot(page, "06c-late-restore-discarded")

            report["api_calls"] = sorted({f"{method} {path}"
                                          for method, path in DialogueHandler.calls})

            # 7) mobile width still renders the rail
            await page.set_viewport_size({"width": 390, "height": 844})
            _reset_state()
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge && window.B66SafeMarkdown", timeout=20000)
            await page.evaluate(SELECT_MODEL_JS)
            await page.click("#freeChatStarter")
            await page.fill("#easyComposer", "모바일 질문")
            await page.click("#easySend")
            await page.wait_for_function(
                "() => document.querySelectorAll('#easyMessageList .easy-assistant-message')"
                ".length >= 2", timeout=20000)
            await page.click("#brandHome")
            await page.click("#aiDialogueStarter")
            await page.wait_for_selector("#easyDialogueResults .easy-dialogue-card", timeout=20000)
            mobile_cards = await page.evaluate(
                "() => document.querySelectorAll('#easyDialogueResults .easy-dialogue-card').length")
            report["mobile_rail_cards"] = mobile_cards
            if mobile_cards != 1:
                failures.append("mobile_rail_did_not_render")
            await shot(page, "07-mobile-rail")

            report["mobile_api_calls"] = sorted({f"{method} {path}"
                                                 for method, path in DialogueHandler.calls})
        finally:
            await browser.close()
            server.shutdown()

    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        print("B66_DIALOGUE_UX_BROWSER=FAIL " + ",".join(failures))
        return 1
    print("B66_DIALOGUE_UX_BROWSER=PASS")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
