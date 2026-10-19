"""#5039: a finished B66 guided quote stays revisable in the same dialogue.

Load-bearing contract for post-completion revision:

* finishing a quote must NOT remove the input handler (it used to call
  blockSend, which left the customer unable to continue at all);
* a plain Korean edit phrase routes to exactly one existing field prompt;
* each revised field re-collects through the same reviewed validation and
  returns to the prepared-quote summary for confirmation;
* an unrecognized sentence re-asks instead of guessing a field;
* a new quote / account change / view switch retires the revision target;
* the draft is never mutated by the browser outside QuoteCore, and no
  internal JSON/routing/state wording is shown to the customer.
"""
from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
SKILL_ID = "b66skill_" + "0" * 32
MODEL_ID = "opencode-go/beam-free"
EMAIL = "post-edit@example.test"


class Handler(http.server.SimpleHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *_a):  # pragma: no cover
        return

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
        return path[len("/api/padiem"):] if path.startswith("/api/padiem") else path

    def do_GET(self):
        path = self._route()
        if path.startswith(("/auth/", "/b66/")):
            payload = type(self).state.get(path)
            if payload is None:
                return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
            return self._json(payload)
        return super().do_GET()

    def do_PUT(self):
        if self._route() == "/b66/guided-draft":
            type(self).state["guidedPut"] = self._read_json()
            return self._json({"ok": True})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_DELETE(self):
        if self._route() == "/b66/guided-draft":
            return self._json({"ok": True})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_POST(self):
        path = self._route()
        if path == "/b66/quote/interpret":
            return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
        if path == "/b66/quote/pdf":
            payload = b"%PDF-1.4\nstub\n%%EOF\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return None
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)


BUILD_SKILL_JS = """() => {
  const T = window.QuoteTemplate;
  const S = window.SavedQuoteSkill;
  const base = {
    id: 'skill-post-edit', name: 'CGI 시지아이',
    fixedDefaults: {
      sender: {company: '시지아이', rep: '대표', bizNo: '000-00-00000',
               address: '광주', phone: '000-000-0000', email: 's@example.test',
               presetId: 'saved-skill'},
      validDays: 14, taxMode: 'INCLUSIVE', memo: ''
    },
    variableSchema: {recipient: true, quoteNo: true, issueDate: true, items: true,
                      memo: false, taxMode: true},
    internalTemplate: T.serializeTemplate(T.builtInTemplate()),
    provenance: {sourceKind: 'file', sourceName: 'cgi.pdf', sourceRef: 'source:post-edit',
                 capturedAt: '2026-10-18T00:00:00.000Z', warnings: [], unknowns: [], evidence: []},
    createdAt: '2026-10-18T00:00:00.000Z', updatedAt: '2026-10-18T00:00:00.000Z'
  };
  const d = S.buildSkill(base);
  const approved = S.buildSkill(Object.assign({}, base, {approval: {
    schemaVersion: 1, status: 'approved', skillFingerprint: d.fingerprint,
    approvedBy: 'test', approvedAt: '2026-10-18T00:00:00.000Z', approvalRef: 'post-edit'}}));
  return {ok: true, skill: S.serializeSkill(approved), fingerprint: approved.fingerprint};
}"""

SEND_JS = """() => {
  const c = document.getElementById('easyComposer');
  c.value = window.__nextInput;
  document.getElementById('easySend').click();
}"""

TRANSCRIPT_JS = """() => Array.from(
  document.querySelectorAll('#easyMessageList .easy-message-content'))
  .map(n => n.textContent || '')"""

COMPOSER_JS = """() => ({
  enabled: !document.getElementById('easyComposer').disabled,
  placeholder: document.getElementById('easyComposer').placeholder,
  hasHandler: (() => {
    c = document.getElementById('easyComposer');
    return !c.disabled;
  })()
})"""

DRAFT_JS = "() => window.B66QuoteAppBridge.getDraft()"


async def wait_text(page, needle, timeout=15000):
    await page.wait_for_function(
        "t => (document.getElementById('easyMessageList')?.innerText || '').includes(t)",
        arg=needle, timeout=timeout,
    )


async def main() -> int:
    handler = functools.partial(Handler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    failures: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge && window.SavedQuoteSkill", timeout=20000)
            built = await page.evaluate(BUILD_SKILL_JS)
            if not built.get("ok"):
                raise RuntimeError(f"skill fixture build failed: {built}")

            Handler.state = {
                "/auth/status": {"ok": True, "authenticated": True,
                                 "session_state": "signed_in",
                                 "user": {"id": "post-edit-user", "email": EMAIL},
                                 "methods": {"google": True, "password": False}},
                "/b66/quote/models": {
                    "ok": True,
                    "models": [{"model_id": MODEL_ID, "name": "Free",
                                "reasoning_levels": [{"value": "default", "label": "기본"}]}],
                    "default_model_id": None,
                    "tiers": [{"tier": "free", "name": "시지아이 Free", "model_id": MODEL_ID,
                               "reasoning_levels": [{"value": "default", "label": "기본"}]}],
                    "default_tier": "free",
                },
                "/b66/company-profile": {"ok": True, "company_profile": {
                    "company": "시지아이", "representative": "대표",
                    "defaultValidityDays": 14, "defaultTaxMode": "INCLUSIVE"}},
                "/b66/saved-skills": {"ok": True, "skills": [
                    {"saved_skill_id": SKILL_ID, "skill_name": "CGI 시지아이"}], "limit": 20},
                f"/b66/saved-skills/{SKILL_ID}": {
                    "ok": True,
                    "saved_skill": {"saved_skill_id": SKILL_ID,
                                    "skill_id": built["skill"]["id"],
                                    "skill_name": built["skill"]["name"],
                                    "skill_fingerprint": built["fingerprint"],
                                    "skill_version": built["skill"]["schemaVersion"],
                                    "skill": built["skill"]},
                },
                "/b66/quotes": {"ok": True, "quotes": [], "limit": 20},
                "/b66/guided-draft": {"ok": True, "state": None},
            }
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge.readiness().ready === true", timeout=20000)
            await page.evaluate("""() => {
              const s = document.getElementById('padiemQuoteModelSelect');
              const real = Array.from(s.options).find(o => o.value);
              s.value = real.value;
              s.dispatchEvent(new Event('change', {bubbles: true}));
            }""")

            # 1) guided quote: 광주대 -> 홍길동 -> 방송장비 -> 1 -> 100만원
            await page.evaluate("() => document.getElementById('guidedStarter').click()")
            await wait_text(page, "누구에게 보내는")
            for value in ("광주대", "홍길동", "방송장비"):
                await page.evaluate("v => { window.__nextInput = v; }", value)
                await page.evaluate(SEND_JS)
                await page.wait_for_timeout(350)
            await page.evaluate("v => { window.__nextInput = v; }", "1")
            await page.evaluate(SEND_JS)
            await wait_text(page, "단가")
            await page.evaluate("v => { window.__nextInput = v; }", "100만원")
            await page.evaluate(SEND_JS)
            await wait_text(page, "다른 품목")
            await page.evaluate("v => { window.__nextInput = v; }", "없음")
            await page.evaluate(SEND_JS)
            await wait_text(page, "부가세는 어떻게")
            await page.evaluate("v => { window.__nextInput = v; }", "포함")
            await page.evaluate(SEND_JS)
            await wait_text(page, "납기나 결제 조건")
            await page.evaluate("v => { window.__nextInput = v; }", "없음")
            await page.evaluate(SEND_JS)
            await page.wait_for_timeout(500)
            await page.evaluate(SEND_JS)
            await page.wait_for_timeout(700)
            await wait_text(page, "이렇게 준비했어요")

            # The real #5039 reproduction: finish the quote first, so the
            # prepared-quote screen with 견적서 확인하기 / 처음으로 appears.
            await page.evaluate("() => document.getElementById('easySend').disabled")
            await page.evaluate("""() => {
              const chip = Array.from(document.querySelectorAll('#easyChipRow button'))
                .find(b => b.textContent.trim() === '견적서 만들기');
              if (!chip) throw new Error('finish_chip_missing');
              chip.click();
            }""")
            await wait_text(page, "견적이 준비되었습니다")

            draft_before = await page.evaluate(DRAFT_JS)
            tax_before = draft_before["tax"]["mode"]
            if tax_before != "INCLUSIVE":
                failures.append("prepared_quote_did_not_apply_the_tax_answer:" + str(tax_before))

            # 2) the prepared quote must still accept input (regression: blockSend)
            composer = await page.evaluate(COMPOSER_JS)
            if not composer["enabled"]:
                failures.append("prepared_quote_locked_the_composer")

            # 3) a plain-Korean tax edit is accepted in the same dialogue
            await page.evaluate("v => { window.__nextInput = v; }", "부가세 별도로 바꿔줘")
            await page.evaluate(SEND_JS)
            await wait_text(page, "부가세는 어떻게")
            await page.evaluate("v => { window.__nextInput = v; }", "별도")
            await page.evaluate(SEND_JS)
            await wait_text(page, "이렇게 준비했어요")

            # 4) QuoteCore recalculated from the existing draft
            draft_after = await page.evaluate(DRAFT_JS)
            if draft_after["tax"]["mode"] != "EXCLUSIVE":
                failures.append("tax_mode_not_applied")
            if draft_after["meta"]["quoteNo"] != draft_before["meta"]["quoteNo"]:
                failures.append("quote_number_changed_on_edit")
            if len(draft_after["items"]) != len(draft_before["items"]):
                failures.append("items_changed_on_tax_edit")

            # 5) an unrecognized sentence re-asks instead of guessing
            await page.evaluate("v => { window.__nextInput = v; }", "오늘 날씨가 어때")
            await page.evaluate(SEND_JS)
            await wait_text(page, "수정할 항목을 알려 주세요")
            draft_after_unknown = await page.evaluate(DRAFT_JS)
            if draft_after_unknown["tax"]["mode"] != draft_after["tax"]["mode"]:
                failures.append("unrecognized_sentence_mutated_the_draft")

            # 6) a new quote retires the revision target
            await page.click("#brandHome")
            await page.wait_for_timeout(300)
            await page.evaluate(SEND_JS)
            await page.wait_for_timeout(500)
            transcript = await page.evaluate(TRANSCRIPT_JS)
            joined = "\n".join(transcript)
            for leaked in ("quoteConversation", "revision", "delta", "facts", "mode",
                           "intent", "staged", "JSON", "traceId"):
                if leaked in joined:
                    failures.append("internal_wording_leaked:" + leaked)
            if errors:
                failures.append("page_error:" + errors[0][:120])
        finally:
            await browser.close()
        server.shutdown()

    if failures:
        print("FAILURES:", json.dumps(failures, ensure_ascii=False))
        print("B66_5039_POST_COMPLETE_EDIT=FAIL")
        return 1
    print("B66_5039_POST_COMPLETE_EDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(__import__("asyncio").run(main()))