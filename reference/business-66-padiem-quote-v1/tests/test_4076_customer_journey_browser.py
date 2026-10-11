"""#4076 first CGI customer MVP acceptance (offline, no provider, no Production).

Drives the real customer journey in a real browser against a loopback server,
in the order a first customer actually uses it:

1. sign in -> approved Saved Quote Skill + CompanyProfile runtime readiness
2. choose the exact AI model (manual only) and its reasoning level
3. Free-form quote **without a unit price** -> one specific follow-up question
   -> the same quote completes with the customer's own price, never an invented one
4. a complete Free-form quote -> authoritative draft + QuoteCore totals
5. Guided view shows the same quote, and editing it costs **0** model calls
6. the quote's mocked PDF endpoint is exercised (NOT native Sol parity)
7. reload -> mocked D1 recent-quote round-trip, and a foreign account sees nothing

Nothing here contacts a provider, Production, Secrets or a real identity: the
B14 interpreter is replaced by a scripted stub, exactly like the existing #3536
offline browser acceptance. Every value is synthetic and non-routable.

Usage:
    python test_4076_customer_journey_browser.py                 # assert + run
    B66_4076_EVIDENCE_DIR=<dir> python test_4076_...py            # + screenshots
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import os
from pathlib import Path
import threading

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE_DIR = os.environ.get("B66_4076_EVIDENCE_DIR")
EVIDENCE = Path(_EVIDENCE_DIR) if _EVIDENCE_DIR else None

SAVED_SKILL_ID = "b66skill_" + "0" * 32
QUOTE_HISTORY_ID = "b66quote_" + "1" * 32
MODEL_ID = "google/gemini-3.5-flash-lite"

# Synthetic, non-routable contact details only. No real person, phone or address.
DEMO = {
    "recipientCompany": "데모수신사",
    "recipientPerson": "데모담당",
    "email": "demo@example.test",
    "quoteNo": "DEMO-0001",
    "issueDate": "2026-10-10",
    "memo": "데모 견적입니다",
    "itemName": "데모 상품",
    "qty": 2,
    "unitPrice": 50000,
}


class JourneyHandler(http.server.SimpleHTTPRequestHandler):
    """Static B66 customer page + a scripted, deterministic B66 API stub."""

    state: dict = {}
    calls: list = []

    def log_message(self, *_args):  # pragma: no cover - keep output clean
        return

    def _json(self, payload, status=200, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
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

    def do_GET(self):
        path = self._route()
        if not path.startswith(("/auth/", "/b66/")):
            return super().do_GET()  # real static customer page asset
        type(self).calls.append(("GET", path))
        payload = type(self).state.get(path)
        if payload is None:
            return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
        return self._json(payload)

    def do_PUT(self):
        path = self._route()
        type(self).calls.append(("PUT", path))
        if path != "/b66/guided-draft":
            return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
        # Synthetic account-backed D1 slot for the offline #4076 browser journey.
        # Real D1 owner/workspace isolation is covered by test_b66_guided_draft.py.
        type(self).state[path] = {"ok": True, "state": self._read_json()}
        return self._json({"ok": True})

    def do_DELETE(self):
        path = self._route()
        type(self).calls.append(("DELETE", path))
        if path != "/b66/guided-draft":
            return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
        type(self).state[path] = {"ok": True, "state": None}
        return self._json({"ok": True})

    def do_POST(self):
        path = self._route()
        type(self).calls.append(("POST", path))
        state = type(self).state
        body = self._read_json()
        if path == "/b66/quote/interpret":
            script = state.get("interpretScript")
            if not script:
                return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 503)
            state.setdefault("interpretRequests", []).append(body)
            index = len(state["interpretRequests"]) - 1
            scripted = script[min(index, len(script) - 1)]
            if "__http_status" in scripted:
                return self._json(scripted["body"], scripted["__http_status"],
                                  scripted.get("headers"))
            return self._json(scripted)
        if path == "/b66/quote/pdf":
            state.setdefault("pdfRequests", []).append(body)
            payload = b"%PDF-1.4\n%certified-sol-stub\n%%EOF\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return None
        if path == "/b66/quotes":
            state.setdefault("savedQuotes", []).append(body)
            return self._json({"ok": True, "quote": {"ok": True}})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)


def complete_candidate(with_price: bool = True) -> dict:
    """A single-item quote; `with_price=False` omits the unit price on purpose."""
    item = {"name": DEMO["itemName"], "qty": DEMO["qty"]}
    if with_price:
        item["unitPrice"] = DEMO["unitPrice"]
    return {
        "recipient": {
            "company": DEMO["recipientCompany"],
            "person": DEMO["recipientPerson"],
            "email": DEMO["email"],
        },
        "quoteNo": DEMO["quoteNo"],
        "issueDate": DEMO["issueDate"],
        "taxMode": "EXCLUSIVE",
        "memo": DEMO["memo"],
        "items": [item],
        "missing": [] if with_price else ["items.unitPrice"],
    }


def interpret_response(candidate: dict) -> dict:
    return {
        "ok": True,
        "candidate": candidate,
        "company_profile": {
            "company": DEMO["recipientCompany"],
            "representative": DEMO["recipientPerson"],
            "email": DEMO["email"],
            "defaultValidityDays": 14,
            "defaultTaxMode": "EXCLUSIVE",
        },
        "execution": {"source_document_parse_calls": 0, "server_total_calculation": False},
    }


BUILD_FIXTURE_JS = """() => {
  const T = window.QuoteTemplate;
  const S = window.SavedQuoteSkill;
  const base = {
    id: "skill-cgi-mvp",
    name: "CGI 견적서",
    fixedDefaults: {
      sender: {
        company: "데모발주사", rep: "데모담당자",
        bizNo: "000-00-00000", address: "서울시 데모구 데로 1",
        phone: "000-000-0000", email: "sender@example.test", presetId: "saved-skill"
      },
      validDays: 14, taxMode: "EXCLUSIVE", memo: "데모 견적입니다"
    },
    variableSchema: {
      recipient: true, quoteNo: true, issueDate: true, items: true, memo: false, taxMode: true
    },
    internalTemplate: T.serializeTemplate(T.builtInTemplate()),
    provenance: {
      sourceKind: "file", sourceName: "cgi-quotation.pdf", sourceRef: "source:cgi-mvp",
      capturedAt: "2026-10-10T00:00:00.000Z", warnings: [], unknowns: [], evidence: []
    },
    createdAt: "2026-10-10T00:00:00.000Z",
    updatedAt: "2026-10-10T00:00:00.000Z"
  };
  const draft = S.buildSkill(base);
  if (!draft) return {ok: false, reason: 'draft_build_failed'};
  const approved = S.buildSkill(Object.assign({}, base, {approval: {
    schemaVersion: 1, status: 'approved', skillFingerprint: draft.fingerprint,
    approvedBy: 'central-cto', approvedAt: '2026-10-10T00:00:00.000Z', approvalRef: 'issue-4076'
  }}));
  if (!approved) return {ok: false, reason: 'approval_build_failed'};
  return {ok: true, skill: S.serializeSkill(approved), fingerprint: approved.fingerprint};
}"""

SELECT_MODEL_JS = """() => {
  const select = document.getElementById('padiemQuoteModelSelect');
  if (!select) return {count: 0, value: ''};
  const real = Array.from(select.options).find(option => option.value);
  if (!real) return {count: select.options.length, value: ''};
  select.value = real.value;
  select.dispatchEvent(new Event('change', {bubbles: true}));
  return {count: select.options.length, value: select.value};
}"""

READ_DRAFT_JS = "() => window.B66QuoteAppBridge.getDraft()"

MESSAGES_JS = """() => Array.from(
    document.querySelectorAll('#easyMessageList .easy-message-content'))
  .map(node => node.textContent || '')"""


async def shot(page, name: str) -> None:
    if EVIDENCE is None:
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(EVIDENCE / f"{name}.png"))


def prices(draft) -> list:
    if not isinstance(draft, dict):
        return []
    return [
        item["unitPrice"]
        for item in draft.get("items") or []
        if isinstance(item, dict) and isinstance(item.get("unitPrice"), (int, float))
    ]


async def open_session(page, base: str, skill: dict, fingerprint: str) -> dict:
    """Reload as the signed-in customer with an approved skill and profile."""
    JourneyHandler.state = {
        "/auth/status": {
            "ok": True,
            "authenticated": True,
            "session_state": "signed_in",
            "user": {"id": "demo-user", "email": DEMO["email"]},
            "methods": {"google": True, "password": False},
        },
        "/b66/quote/models": {
            "ok": True,
            "models": [
                {
                    "model_id": MODEL_ID,
                    "name": "Gemini 3.5 Flash Lite",
                    "reasoning_levels": [
                        {"value": "default", "label": "기본(제공자 기본값)"},
                        {"value": "low", "label": "낮음"},
                    ],
                }
            ],
            "default_model_id": None,
        },
        "/b66/company-profile": {
            "ok": True,
            "company_profile": {
                "company": DEMO["recipientCompany"],
                "representative": DEMO["recipientPerson"],
                "email": DEMO["email"],
                "defaultValidityDays": 14,
                "defaultTaxMode": "EXCLUSIVE",
            },
        },
        "/b66/saved-skills": {
            "ok": True,
            "skills": [{"saved_skill_id": SAVED_SKILL_ID, "skill_name": "CGI 견적서"}],
            "limit": 20,
        },
        f"/b66/saved-skills/{SAVED_SKILL_ID}": {
            "ok": True,
            "saved_skill": {
                "saved_skill_id": SAVED_SKILL_ID,
                "skill_id": skill["id"],
                "skill_name": skill["name"],
                "skill_fingerprint": fingerprint,
                "skill_version": skill["schemaVersion"],
                "skill": skill,
            },
        },
        "/b66/quotes": {"ok": True, "quotes": [], "limit": 20},
        "/b66/guided-draft": {"ok": True, "state": None},
        "interpretScript": [],
        "interpretRequests": [],
        "pdfRequests": [],
        "savedQuotes": [],
    }
    JourneyHandler.calls = []
    await page.goto(f"{base}/index.html", wait_until="load")
    await page.wait_for_function(
        "() => window.B66QuoteRuntimeBridge.readiness().ready === true", timeout=20000
    )
    readiness = await page.evaluate("() => window.B66QuoteRuntimeBridge.readiness()")
    selection = await page.evaluate(SELECT_MODEL_JS)
    reasoning = await page.evaluate(
        """() => {
             const select = document.getElementById('padiemQuoteReasoningSelect');
             if (!select) return [];
             return Array.from(select.options).map(option => option.value);
           }"""
    )
    sender = await page.evaluate(
        """() => {
             const profile = window.B66QuoteRuntimeBridge.getCompanyProfile();
             const draft = window.B66QuoteAppBridge.getDraft();
             const input = document.getElementById('senderCompany');
             return {
               matchesApprovedProfile: !!profile?.company &&
                 draft.sender.company === profile.company &&
                 input?.value === profile.company,
               profileReady: !!profile?.company,
               senderWasNotDemo: draft.sender.company !== '샘플 공급사'
             };
           }"""
    )
    return {"readiness": readiness, "model_selection": selection,
            "reasoning_options": reasoning, "sender_prefill": sender}


async def main() -> int:
    handler = functools.partial(JourneyHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    failures: list[str] = []
    report: dict = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66ShellLayout && window.SavedQuoteSkill", timeout=20000
            )
            built = await page.evaluate(BUILD_FIXTURE_JS)
            if not built.get("ok"):
                raise RuntimeError(f"Saved Quote Skill fixture build failed: {built}")
            skill = {**built["skill"], "approved": True}
            fingerprint = built["fingerprint"]

            # ===== session 1: incomplete quote -> follow-up -> complete ======
            session = await open_session(page, base, skill, fingerprint)
            report["session1"] = session
            if not session["readiness"].get("ready"):
                failures.append("runtime_not_ready")
            if not session["sender_prefill"].get("matchesApprovedProfile"):
                failures.append("new_direct_quote_sender_not_prefilled_from_company_profile")
            if session["model_selection"].get("value") != MODEL_ID:
                failures.append("manual_model_selection_failed")
            if "default" not in session["reasoning_options"]:
                failures.append("reasoning_default_option_missing")
            await shot(page, "01-signed-in-model-selected")

            # Step 1: the customer describes a quote without stating a price.
            JourneyHandler.state["interpretScript"] = [
                interpret_response(complete_candidate(with_price=False))
            ]
            await page.fill("#easyComposer", f"{DEMO['recipientCompany']} {DEMO['itemName']} {DEMO['qty']}개")
            await page.click("#easySend")
            await page.wait_for_timeout(1200)
            transcript = await page.evaluate(MESSAGES_JS)
            report["followup_transcript"] = transcript
            progress_marker = "CGI 기본 견적서로 작성하고 있습니다…"
            if progress_marker in transcript:
                failures.append("stale_processing_message_after_missing_field_question")
            # The bridge's own verdict is the product decision under test.
            probe = await page.evaluate(
                """async () => {
                     const bridge = window.B66QuoteRuntimeBridge;
                     const verdict = await bridge.interpret('데모 상품 1개 추가');
                     return {code: verdict.code, question: verdict.question || '',
                             missing: verdict.missing || []};
                   }"""
            )
            report["interpret_verdict_for_missing_price"] = probe
            asked = [line for line in transcript if "단가" in line]
            report["followup_question"] = asked[-1] if asked else probe.get("question", "")
            if not asked and not probe.get("question"):
                failures.append("missing_price_followup_not_asked")
            draft_after_question = await page.evaluate(READ_DRAFT_JS)
            report["no_price_before_answer"] = prices(draft_after_question)
            if any(value for value in prices(draft_after_question)):
                # A missing unit price must stay missing until the customer
                # states it; the product must never fill it in itself.
                failures.append("price_fabricated_before_customer_answered")
            await shot(page, "02-missing-price-question")

            # A real Production incident: the customer supplied a missing price,
            # but B14 timed out (502 + an allowlisted upstream_timeout header).
            # The existing pending quote must survive and the composer must ask
            # to retry only the answer, not the entire original request.
            before_timeout = await page.evaluate(
                "() => window.B66QuoteRuntimeBridge.pendingQuote()?.quoteNo"
            )
            calls_before_timeout = len(JourneyHandler.state["interpretRequests"])
            JourneyHandler.state["interpretScript"] = [{
                "__http_status": 502,
                "headers": {"X-B66-Upstream-Class": "upstream_timeout",
                            "X-B66-Interpret-Failure-Stage": "interpreter_exception"},
                "body": {"ok": False, "error": {
                    "code": "quote_interpretation_failed",
                    "message": "견적 요청을 해석하지 못했습니다."}},
            }]
            await page.fill("#easyComposer", f"단가는 {DEMO['unitPrice']:,}원입니다")
            await page.click("#easySend")
            await page.wait_for_function(
                "() => document.getElementById('easyMessageList')?.innerText.includes('시간 초과')",
                timeout=10000
            )
            await page.wait_for_function(
                "() => !document.getElementById('easyMessageList')?.innerText.includes('CGI 기본 견적서로 작성하고 있습니다…')",
                timeout=10000
            )
            after_timeout = await page.evaluate("""() => ({
                pendingQuoteNo: window.B66QuoteRuntimeBridge.pendingQuote()?.quoteNo,
                placeholder: document.getElementById('easyComposer').placeholder,
                enabled: !document.getElementById('easyComposer').disabled,
                reviewDisplayed: document.getElementById('easyMessageList')
                    .innerText.includes('견적이 준비되었습니다'),
                errorDisplayed: document.getElementById('easyMessageList')
                    .innerText.includes('시간 초과'),
            })""")
            report["502_pending_followup_browser"] = after_timeout
            if after_timeout["pendingQuoteNo"] != before_timeout:
                failures.append("timeout_dropped_pending_quote")
            if after_timeout["placeholder"] != "방금 답변을 다시 적어 주세요":
                failures.append("timeout_prompts_to_retype_whole_quote")
            if not after_timeout["enabled"] or not after_timeout["errorDisplayed"]:
                failures.append("timeout_composer_not_usable")
            if after_timeout["reviewDisplayed"]:
                failures.append("timeout_fabricated_successful_quote")
            if len(JourneyHandler.state["interpretRequests"]) != calls_before_timeout + 1:
                failures.append("timeout_triggered_hidden_model_retry")
            if any(prices(await page.evaluate(READ_DRAFT_JS))):
                failures.append("timeout_committed_unapproved_draft")
            await shot(page, "02b-timeout-pending-preserved")

            # Step 2: user explicitly resubmits their price; same quote completes.
            JourneyHandler.state["interpretScript"] = [
                interpret_response(complete_candidate(with_price=True))
            ]
            await page.fill("#easyComposer", f"단가는 {DEMO['unitPrice']:,}원입니다")
            await page.click("#easySend")
            await page.wait_for_timeout(1500)
            draft = await page.evaluate(READ_DRAFT_JS)
            report["completed_draft"] = draft
            completed_messages = await page.evaluate(MESSAGES_JS)
            if progress_marker in completed_messages:
                failures.append("stale_processing_message_after_completed_quote")
            if not any("견적이 준비되었습니다" in line for line in completed_messages):
                failures.append("completed_quote_confirmation_missing")
            final_prices = prices(draft)
            report["completed_unit_prices"] = final_prices
            if not final_prices:
                failures.append("quote_not_completed_after_followup")
            elif any(value != DEMO["unitPrice"] for value in final_prices):
                failures.append("fabricated_unit_price")
            if (draft or {}).get("recipient", {}).get("company") != DEMO["recipientCompany"]:
                failures.append("recipient_not_extracted")
            await shot(page, "03-followup-completed")

            # QuoteCore is the only calculation authority.
            totals = await page.evaluate(
                "() => window.QuoteCore.computeDraftTotals(window.B66QuoteAppBridge.getDraft())"
            )
            report["quote_core_totals"] = totals
            expected = DEMO["qty"] * DEMO["unitPrice"]
            if not totals or totals.get("subtotal") != expected:
                failures.append("quote_core_subtotal_mismatch")
            elif totals.get("vat") != round(expected * 0.1):
                failures.append("quote_core_vat_mismatch")
            elif totals.get("grand") != totals.get("supply", 0) + totals.get("vat", 0):
                failures.append("quote_core_grand_mismatch")

            # The exact model the customer chose is what reached the API.
            requests = JourneyHandler.state["interpretRequests"]
            report["interpret_request_models"] = [row.get("model_id") for row in requests]
            report["interpret_request_reasoning"] = [row.get("reasoning_level") for row in requests]
            if not requests or any(row.get("model_id") != MODEL_ID for row in requests):
                failures.append("model_id_not_preserved")
            if not requests or any(row.get("saved_skill_id") != SAVED_SKILL_ID for row in requests):
                failures.append("saved_skill_not_bound")

            # ===== Guided view: same quote, and edits cost 0 model calls =====
            await page.evaluate(
                "() => { const b = document.getElementById('directModeButton'); if (b) b.click(); }"
            )
            await page.wait_for_timeout(700)
            guided = await page.evaluate(
                """() => {
                     const text = id => { const node = document.getElementById(id);
                                          return node ? (node.textContent || '').trim() : ''; };
                     return {
                       directVisible: document.getElementById('directView')
                         ? document.getElementById('directView').offsetParent !== null : null,
                       company: text('pvRecipientCompany'),
                       quoteNo: text('pvQuoteNo'),
                       grand: text('pvGrand'),
                       items: document.querySelectorAll('#items .item-row').length,
                       firstItem: (document.querySelector('#items .item-row .item-name')||{}).value || '',
                       draftCompany: (window.B66QuoteAppBridge.getDraft().recipient || {}).company || ''
                     };
                   }"""
            )
            report["guided_preview"] = guided
            expected_total = f"{DEMO['qty'] * DEMO['unitPrice'] * 1.1:,.0f}"
            if DEMO["recipientCompany"] not in guided["company"]:
                failures.append("guided_recipient_missing")
            if DEMO["quoteNo"] not in guided["quoteNo"]:
                failures.append("guided_quote_no_missing")
            if not guided["items"]:
                failures.append("guided_items_missing")
            if expected_total.replace(",", "") not in guided["grand"].replace(",", ""):
                failures.append("guided_total_not_authoritative")
            calls_before_edit = len(requests)
            report["calls_after_view_switch"] = len(JourneyHandler.state["interpretRequests"])
            await page.fill("#items .item-row:first-child .item-qty", "3")
            await page.wait_for_timeout(900)
            report["calls_before_guided_edit"] = calls_before_edit
            report["interpret_calls_after_guided_edit"] = len(
                JourneyHandler.state["interpretRequests"]
            )
            if len(JourneyHandler.state["interpretRequests"]) != calls_before_edit:
                failures.append("guided_edit_used_model_call")
            await shot(page, "04-guided-preview")

            # ===== synthetic PDF endpoint (NOT live Sol-native proof) =======
            await page.evaluate(
                "() => { const b = document.getElementById('printPdf'); if (b) b.click(); }"
            )
            await page.wait_for_timeout(1200)
            pdf_requests = JourneyHandler.state["pdfRequests"]
            report["certified_pdf_requested"] = bool(pdf_requests)
            report["certified_pdf_call_paths"] = sorted(
                {f"{method} {path}" for method, path in JourneyHandler.calls if "pdf" in path}
            )
            if not pdf_requests:
                failures.append("certified_pdf_not_requested")
            await shot(page, "05-pdf")

            # ===== session 2: reopen, D1 round-trip, foreign account =========
            session2 = await open_session(page, base, skill, fingerprint)
            JourneyHandler.state["/b66/quotes"] = {
                "ok": True,
                "quotes": [
                    {
                        "quote_history_id": QUOTE_HISTORY_ID,
                        "quote_no": DEMO["quoteNo"],
                        "issue_date": DEMO["issueDate"],
                        "saved_skill_id": SAVED_SKILL_ID,
                        "created_at": "2026-10-10T00:00:00.000Z",
                        "updated_at": "2026-10-10T00:00:00.000Z",
                        "totals_authority": "quote-core",
                        "quote_core_recalculation_required": True,
                    }
                ],
                "limit": 20,
            }
            report["session2_readiness"] = session2["readiness"]
            listing = await page.evaluate(
                """async () => {
                     const server = window.B66QuoteHistoryServer;
                     if (!server || typeof server.listQuotes !== 'function') return null;
                     const result = await server.listQuotes({limit: 20});
                     return {ok: result.ok, count: (result.quotes || []).length,
                             quoteNo: (result.quotes || [])[0] ? result.quotes[0].quoteNo : ''};
                   }"""
            )
            report["d1_reopen"] = listing
            if not listing or not listing.get("ok") or not listing.get("count"):
                failures.append("d1_recent_quote_not_visible")
            await shot(page, "06-d1-recent")

            # A foreign account must see an empty history, never another
            # customer's rows. The server contract, not local storage, decides.
            JourneyHandler.state["/b66/quotes"] = {"ok": True, "quotes": [], "limit": 20}
            foreign = await page.evaluate(
                """async () => {
                     const server = window.B66QuoteHistoryServer;
                     const result = await server.listQuotes({limit: 20});
                     return {ok: result.ok, count: (result.quotes || []).length};
                   }"""
            )
            report["foreign_account_history"] = foreign
            if foreign.get("count"):
                failures.append("foreign_account_saw_data")
            await shot(page, "07-foreign-account-empty")

            # #4076 real product regression: in the approved CGI path the
            # guided sender question must match the CompanyProfile authority
            # that the final PDF actually uses. No ignored custom sender.
            await page.evaluate(
                "() => document.getElementById('guidedStarter').click()"
            )
            for answer in [
                "MVP 수신사", "없음", "MVP 품목", "2", "50000",
                "다음", "별도", "없음"
            ]:
                await page.fill("#easyComposer", answer)
                await page.click("#easySend")
            sender_proof = await page.evaluate(
                """() => {
                  const profile = window.B66QuoteRuntimeBridge.getCompanyProfile();
                  const prompt = document.getElementById('easyMessageList').innerText;
                  const chips = Array.from(document.querySelectorAll('#easyChipRow button'))
                    .map(e => e.textContent.trim());
                  return {
                    hasApprovedCompany: !!profile?.company && prompt.includes(profile.company),
                    onlyNext: chips.length === 1 && chips[0] === '다음으로',
                    hasMisleadingSenderEdit: chips.some(x => x.includes('상호 입력'))
                  };
                }"""
            )
            report["guided_sender_authority"] = sender_proof
            if not sender_proof.get("hasApprovedCompany") or not sender_proof.get("onlyNext") or sender_proof.get("hasMisleadingSenderEdit"):
                failures.append("guided_sender_does_not_match_approved_pdf_company")
            await page.click("#easyChipRow button")
            final_sender = await page.evaluate(
                """() => {
                  const profile = window.B66QuoteRuntimeBridge.getCompanyProfile();
                  return !!profile?.company &&
                    document.getElementById('easyMessageList').innerText.includes('보내는 곳: ' + profile.company);
                }"""
            )
            report["guided_sender_summary_matches_profile"] = final_sender
            if not final_sender:
                failures.append("guided_sender_summary_mismatches_approved_profile")

            report["api_calls"] = sorted({f"{method} {path}" for method, path in JourneyHandler.calls})
        finally:
            await browser.close()
            server.shutdown()

    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        print("JOURNEY=FAIL " + ",".join(failures))
        return 1
    print("JOURNEY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
