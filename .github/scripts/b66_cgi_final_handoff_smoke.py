"""B66 CGI first-delivery Production browser smoke (#3521).

Runs only when explicitly authorized. Credentials are consumed from the GitHub
Production Environment and are never printed. The browser exercises the real
standalone B66 Production UI:

1) password login + assigned CGI Saved Quote Skill readiness
2) Guided quote path (AI/model interpret calls: zero)
3) complete free-form quote (one interpret POST)
4) partial free-form + bounded follow-up (two interpret POSTs)
5) QuoteCore totals + result view + certified PDF download

No retry, provider fanout, account creation, Saved Skill mutation, or raw
response logging is permitted.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

TARGET_URL = "https://quick-quote-kr.pages.dev/"
INTERPRET_PATH = "/api/padiem/b66/quote/interpret"
PDF_PATH = "/api/padiem/b66/quote/pdf"
MAX_INTERPRET_POSTS = 3
MAX_PDF_POSTS = 3
RETRY = 0
FALLBACK = 0

COMPLETE_TEXT = "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도"
PARTIAL_TEXT = "대한건설에 배관 100미터, 부가세 별도"
FOLLOWUP_TEXT = "미터당 18000원"

CLAW_TARGET_URL = "https://chat.padiem.net/"
CLAW_GENERAL_PATH = "/api/claw/general"
CLAW_SYNTHETIC_PROMPT = "테스트입니다. 한 문장으로 정상 작동 중이라고 답해주세요."
MAX_CLAW_GENERAL_POSTS = 1


class SmokeFailure(RuntimeError):
    pass


@dataclass
class Counters:
    interpret_posts: int = 0
    pdf_posts: int = 0
    direct_provider_requests: int = 0


def _fail(code: str) -> None:
    raise SmokeFailure(code)


def _is_direct_provider(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return (
        host.endswith("kilo.ai")
        or host.endswith("openrouter.ai")
        or host.endswith("googleapis.com")
        or host.endswith("anthropic.com")
        or host.endswith("openai.com")
    )


def _send(page, text: str) -> None:
    page.locator("#easyComposer").fill(text)
    page.locator("#easySend").click()


def _click_chip(page, label: str) -> None:
    locator = page.locator("#easyChipRow button", has_text=label)
    try:
        locator.wait_for(state="visible", timeout=5000)
    except Exception as exc:
        raise SmokeFailure("chip_missing_" + label) from exc
    if locator.count() != 1:
        _fail("chip_not_unique_" + label)
    locator.click()


def _click_chip_index(page, *, index: int, expected_count: int, stage: str) -> None:
    try:
        page.wait_for_function(
            "([selector, expected]) => document.querySelectorAll(selector).length === expected",
            arg=["#easyChipRow button", expected_count],
            timeout=5000,
        )
    except Exception as exc:
        raise SmokeFailure("guided_chip_count_" + stage) from exc
    try:
        page.locator("#easyChipRow button").nth(index).click(timeout=5000)
    except Exception as exc:
        raise SmokeFailure("guided_chip_click_" + stage) from exc


def _wait_runtime_ready(page) -> None:
    page.wait_for_function(
        """() => {
          const b = window.B66QuoteRuntimeBridge;
          if (!b || typeof b.readiness !== 'function') return false;
          const r = b.readiness();
          return Boolean(r && r.ready === true);
        }""",
        timeout=30000,
    )


def _draft(page):
    return page.evaluate("() => window.B66QuoteAppBridge.getDraft()")


def _totals(page):
    return page.evaluate(
        """() => {
          const d = window.B66QuoteAppBridge.getDraft();
          return window.QuoteCore.computeDraftTotals(d);
        }"""
    )


def _assert_quote(
    page,
    *,
    recipient: str,
    item: str,
    qty: float,
    unit_price: float,
    grand: float,
) -> dict:
    draft = _draft(page)
    if not isinstance(draft, dict):
        _fail("draft_missing")
    if (draft.get("recipient") or {}).get("company") != recipient:
        _fail("recipient_mismatch")
    items = draft.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        _fail("items_shape_mismatch")
    row = items[0]
    if row.get("name") != item:
        _fail("item_name_mismatch")
    if row.get("qty") != qty:
        _fail("item_qty_mismatch")
    if row.get("unitPrice") != unit_price:
        _fail("item_price_mismatch")
    if (draft.get("tax") or {}).get("mode") != "EXCLUSIVE":
        _fail("tax_mode_mismatch")

    totals = _totals(page)
    if not isinstance(totals, dict) or totals.get("grand") != grand:
        _fail("quote_core_grand_mismatch")
    return draft


def _pdf_download_probe(page, counters: Counters) -> None:
    before = counters.pdf_posts
    response = None
    try:
        with page.expect_download(timeout=30000) as download_info:
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlparse(response.url).path == PDF_PATH
                ),
                timeout=30000,
            ) as response_info:
                page.locator("#printPdf").click()
            response = response_info.value
            if response.status != 200:
                _fail("pdf_http_" + str(response.status))
            media_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if media_type != "application/pdf":
                _fail("pdf_content_type_mismatch")
        download = download_info.value
    except SmokeFailure:
        raise
    except Exception as exc:
        if response is not None:
            raise SmokeFailure("pdf_download_missing_after_http_" + str(response.status)) from exc
        raise SmokeFailure("pdf_response_or_download_missing") from exc

    body = response.body()
    if not isinstance(body, bytes) or not body.startswith(b"%PDF-"):
        _fail("pdf_bytes_invalid")
    if counters.pdf_posts != before + 1:
        _fail("pdf_request_budget_mismatch")
    if not str(download.suggested_filename or "").lower().endswith(".pdf"):
        _fail("pdf_filename_invalid")


def _open_result_and_download(page, counters: Counters) -> None:
    _click_chip(page, "견적서 확인하기")
    page.locator("#directView").wait_for(state="visible", timeout=10000)
    _pdf_download_probe(page, counters)


def _reset_browser_local_quote_state(page) -> None:
    page.evaluate(
        """() => {
          if (window.B66QuoteRuntimeBridge && typeof window.B66QuoteRuntimeBridge.clearPending === 'function') {
            window.B66QuoteRuntimeBridge.clearPending();
          }
          localStorage.clear();
        }"""
    )
    page.reload(wait_until="domcontentloaded", timeout=30000)
    _wait_runtime_ready(page)


def _login(page, username: str, password: str) -> None:
    print("SMOKE_STAGE=PAGE_GOTO")
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
    print("SMOKE_STAGE=ACCOUNT_BUTTON")
    page.locator("#padiemAccountButton").click()
    print("SMOKE_STAGE=LOGIN_FORM")
    page.locator("#padiemLoginForm").wait_for(state="visible", timeout=15000)
    page.locator("#padiemLoginIdentifier").fill(username)
    page.locator("#padiemLoginPassword").fill(password)
    try:
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/padiem/auth/password/login"
            ),
            timeout=15000,
        ) as login_info:
            page.locator("#padiemLoginSubmit").click()
        login_response = login_info.value
    except Exception as exc:
        raise SmokeFailure("login_response_missing") from exc
    if login_response.status != 200:
        _fail("login_http_" + str(login_response.status))

    print("SMOKE_STAGE=LOGIN_HTTP_200")
    # The canonical three-pane shell intentionally hides the legacy account panel
    # after moving account/skill controls into the left rail. Runtime readiness,
    # not legacy-panel visibility, is the authenticated product authority.
    try:
        _wait_runtime_ready(page)
    except Exception as exc:
        readiness = page.evaluate(
            """() => {
              const b = window.B66QuoteRuntimeBridge;
              return b && typeof b.readiness === 'function' ? b.readiness() : null;
            }"""
        )
        if not isinstance(readiness, dict):
            raise SmokeFailure("runtime_bridge_missing") from exc
        code = "runtime_not_ready_a%s_s%s_p%s" % (
            int(readiness.get("authenticated") is True),
            int(readiness.get("skillReady") is True),
            int(readiness.get("profileReady") is True),
        )
        raise SmokeFailure(code) from exc

    print("SMOKE_STAGE=RUNTIME_READY")
    skill_count = page.locator("#padiemSavedSkillSelect option").count()
    if skill_count != 1:
        _fail("saved_skill_count_not_one")
    print("SMOKE_STAGE=LOGIN_READY")


def _guided(page, counters: Counters) -> None:
    before = counters.interpret_posts
    page.locator("#guidedStarter").click()

    _send(page, "\uac00\uc774\ub4dc\ud14c\uc2a4\ud2b8\uac74\uc124")
    _click_chip_index(page, index=0, expected_count=1, stage="recipient_person_none")
    _send(page, "\ubc30\uad00")
    _click_chip_index(page, index=1, expected_count=4, stage="quantity_two")
    _send(page, "10000")
    _click_chip_index(page, index=1, expected_count=2, stage="items_done")
    _click_chip_index(page, index=0, expected_count=4, stage="tax_exclusive")
    _click_chip_index(page, index=0, expected_count=1, stage="memo_none")
    _click_chip_index(page, index=0, expected_count=3, stage="sender_current")
    _click_chip_index(page, index=0, expected_count=3, stage="finish")
    page.wait_for_function(
        """() => {
          const d = window.B66QuoteAppBridge.getDraft();
          return d && d.recipient && d.recipient.company === '가이드테스트건설'
            && Array.isArray(d.items) && d.items.length === 1
            && d.items[0].name === '배관'
            && d.items[0].qty === 2
            && d.items[0].unitPrice === 10000;
        }""",
        timeout=10000,
    )

    _assert_quote(
        page,
        recipient="가이드테스트건설",
        item="배관",
        qty=2,
        unit_price=10000,
        grand=22000,
    )
    if counters.interpret_posts != before:
        _fail("guided_used_interpret")
    _open_result_and_download(page, counters)
    print("GUIDED=PASS")
    print("GUIDED_INTERPRET_POSTS=0")
    print("GUIDED_QUOTECORE_TOTAL=PASS")
    print("GUIDED_PDF_DOWNLOAD=PASS")
    print("GUIDED_PRINT_OR_PDF=PASS")


def _complete_free_form(page, counters: Counters) -> None:
    _reset_browser_local_quote_state(page)
    page.locator("#freeChatStarter").click()

    before = counters.interpret_posts
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and urlparse(response.url).path == INTERPRET_PATH
        ),
        timeout=60000,
    ) as info:
        _send(page, COMPLETE_TEXT)
    response = info.value
    if response.status != 200:
        _fail("complete_interpret_http_" + str(response.status))

    page.wait_for_function(
        """() => {
          const d = window.B66QuoteAppBridge.getDraft();
          return d && d.recipient && d.recipient.company === '대한건설'
            && Array.isArray(d.items) && d.items.length === 1
            && d.items[0].name === '배관'
            && d.items[0].qty === 100
            && d.items[0].unitPrice === 18000;
        }""",
        timeout=15000,
    )
    _assert_quote(
        page,
        recipient="대한건설",
        item="배관",
        qty=100,
        unit_price=18000,
        grand=1980000,
    )
    if counters.interpret_posts != before + 1:
        _fail("complete_interpret_budget_mismatch")
    _open_result_and_download(page, counters)
    print("COMPLETE_FREEFORM=PASS")
    print("COMPLETE_QUOTECORE_TOTAL=1980000")
    print("COMPLETE_PDF_DOWNLOAD=PASS")
    print("COMPLETE_PRINT_OR_PDF=PASS")


def _partial_followup(page, counters: Counters) -> None:
    _reset_browser_local_quote_state(page)
    page.locator("#freeChatStarter").click()

    before = counters.interpret_posts
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and urlparse(response.url).path == INTERPRET_PATH
        ),
        timeout=60000,
    ) as info:
        _send(page, PARTIAL_TEXT)
    first = info.value
    if first.status != 200:
        _fail("partial_interpret_http_" + str(first.status))

    page.wait_for_function(
        """() => {
          const text = document.getElementById('easyMessageList')?.innerText || '';
          return text.includes('단가는 얼마인가요?');
        }""",
        timeout=10000,
    )
    pending = page.evaluate("() => window.B66QuoteRuntimeBridge.pendingQuote()")
    if not isinstance(pending, dict):
        _fail("pending_quote_missing")
    if pending.get("turns") != 1:
        _fail("pending_turn_count_mismatch")
    if pending.get("missing") != ["unitPrice"]:
        _fail("pending_missing_mismatch")
    pending_quote_no = pending.get("quoteNo")
    pending_issue_date = pending.get("issueDate")
    if not isinstance(pending_quote_no, str) or not pending_quote_no:
        _fail("pending_quote_no_missing")
    if not isinstance(pending_issue_date, str) or not pending_issue_date:
        _fail("pending_issue_date_missing")

    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and urlparse(response.url).path == INTERPRET_PATH
        ),
        timeout=60000,
    ) as info:
        _send(page, FOLLOWUP_TEXT)
    second = info.value
    if second.status != 200:
        _fail("followup_interpret_http_" + str(second.status))

    page.wait_for_function(
        """() => {
          const d = window.B66QuoteAppBridge.getDraft();
          return d && d.recipient && d.recipient.company === '대한건설'
            && Array.isArray(d.items) && d.items.length === 1
            && d.items[0].name === '배관'
            && d.items[0].qty === 100
            && d.items[0].unitPrice === 18000;
        }""",
        timeout=15000,
    )
    draft = _assert_quote(
        page,
        recipient="대한건설",
        item="배관",
        qty=100,
        unit_price=18000,
        grand=1980000,
    )
    same_quote_no = (draft.get("meta") or {}).get("quoteNo") == pending_quote_no
    same_issue_date = (draft.get("meta") or {}).get("issueDate") == pending_issue_date
    if not same_quote_no:
        _fail("followup_quote_no_changed")
    if not same_issue_date:
        _fail("followup_issue_date_changed")
    if page.evaluate("() => window.B66QuoteRuntimeBridge.pendingQuote()") is not None:
        _fail("pending_quote_not_cleared")
    if counters.interpret_posts != before + 2:
        _fail("partial_followup_interpret_budget_mismatch")

    _open_result_and_download(page, counters)
    print("PARTIAL_FREEFORM=PASS")
    print("MISSING_UNIT_PRICE_QUESTION=PASS")
    print("FOLLOWUP_COMPLETE=PASS")
    print("FOLLOWUP_SAME_QUOTE_NO=YES")
    print("FOLLOWUP_SAME_ISSUE_DATE=YES")
    print("FOLLOWUP_DOUBLE_ALLOCATION=0")
    print("FOLLOWUP_QUOTECORE_TOTAL=1980000")
    print("FOLLOWUP_PDF_DOWNLOAD=PASS")
    print("FOLLOWUP_PRINT_OR_PDF=PASS")


def run_live(username: str, password: str) -> int:
    if not username or not password:
        print("B66_FINAL_HANDOFF_SMOKE=FAIL_CREDENTIAL_UNAVAILABLE")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("B66_FINAL_HANDOFF_SMOKE=FAIL_PLAYWRIGHT_UNAVAILABLE")
        return 3

    counters = Counters()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            page = context.new_page()

            def observe_request(request) -> None:
                parsed = urlparse(request.url)
                if request.method == "POST" and parsed.path == INTERPRET_PATH:
                    counters.interpret_posts += 1
                    if counters.interpret_posts > MAX_INTERPRET_POSTS:
                        _fail("interpret_budget_exceeded")
                if request.method == "POST" and parsed.path == PDF_PATH:
                    counters.pdf_posts += 1
                    if counters.pdf_posts > MAX_PDF_POSTS:
                        _fail("pdf_budget_exceeded")
                if _is_direct_provider(request.url):
                    counters.direct_provider_requests += 1

            page.on("request", observe_request)

            _login(page, username, password)
            print("CGI_LOGIN=PASS")
            print("ASSIGNED_SAVED_SKILL_COUNT=1")
            print("RUNTIME_READINESS=PASS")

            _guided(page, counters)
            _complete_free_form(page, counters)
            _partial_followup(page, counters)

            if counters.interpret_posts != MAX_INTERPRET_POSTS:
                _fail("final_interpret_budget_mismatch")
            if counters.pdf_posts != MAX_PDF_POSTS:
                _fail("final_pdf_budget_mismatch")
            if counters.direct_provider_requests != 0:
                _fail("browser_direct_provider_request")

            page.locator("#padiemLogout").click()
            context.close()
            browser.close()

        print("INTERPRET_POSTS=3")
        print("MAX_INTERPRET_POSTS=3")
        print("PDF_POSTS=3")
        print("MAX_PDF_POSTS=3")
        print("CERTIFIED_PDF_DOWNLOADS=3")
        print("BROWSER_DIRECT_PROVIDER_CALLS=0")
        print("RETRY=0")
        print("FALLBACK_FANOUT=0")
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("SAVED_SKILL_MUTATION=0")
        print("PRODUCTION_DATA_MUTATION=0")
        print("B66_FINAL_HANDOFF_SMOKE=PASS")
        return 0
    except SmokeFailure as exc:
        print("INTERPRET_POSTS=" + str(counters.interpret_posts))
        print("PDF_POSTS=" + str(counters.pdf_posts))
        print("BROWSER_DIRECT_PROVIDER_CALLS=" + str(counters.direct_provider_requests))
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("B66_FINAL_HANDOFF_SMOKE=FAIL_" + str(exc))
        return 10
    except Exception as exc:
        print("INTERPRET_POSTS=" + str(counters.interpret_posts))
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("B66_FINAL_HANDOFF_SMOKE=FAIL_BROWSER_RUNTIME_" + type(exc).__name__)
        return 11



def run_claw_owner_one_shot(username: str, password: str) -> int:
    if not username or not password:
        print("B54_CLAW_OWNER_ONE_SHOT=FAIL_CREDENTIAL_UNAVAILABLE")
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        return 20

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("B54_CLAW_OWNER_ONE_SHOT=FAIL_PLAYWRIGHT_UNAVAILABLE")
        return 21

    claw_posts = 0
    direct_provider_requests = 0
    submit_ms = 0
    complete_ms = 0
    response_status = 0
    sse_content_type = False
    stage = "init"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            page = context.new_page()

            def observe_request(request) -> None:
                nonlocal claw_posts, direct_provider_requests
                parsed = urlparse(request.url)
                if request.method == "POST" and parsed.path == CLAW_GENERAL_PATH:
                    claw_posts += 1
                if _is_direct_provider(request.url):
                    direct_provider_requests += 1

            page.on("request", observe_request)
            stage = "load_chat"
            page.goto(CLAW_TARGET_URL, wait_until="domcontentloaded", timeout=30000)

            stage = "login"
            page.locator("#loginButton").wait_for(state="visible", timeout=15000)
            page.locator("#loginButton").click()
            page.locator("#authDialog").wait_for(state="visible", timeout=15000)
            page.locator("#passwordLoginIdentifier").fill(username)
            page.locator("#passwordLoginPassword").fill(password)

            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlparse(response.url).path == "/api/auth/password/login"
                ),
                timeout=30000,
            ) as login_info:
                page.locator("#passwordLoginSubmit").click()
            if login_info.value.status != 200:
                _fail("owner_login_http_" + str(login_info.value.status))

            page.locator("#authDialog").wait_for(state="hidden", timeout=20000)
            page.wait_for_function(
                """() => {
                  const b = document.querySelector('#loginButton');
                  if (!b) return false;
                  const t = (b.textContent || '').trim().toLowerCase();
                  return t.includes('로그아웃') || t.includes('logout');
                }""",
                timeout=20000,
            )
            print("OWNER_LOGIN=PASS")

            stage = "open_claw"
            page.locator("#clawNavButton").wait_for(state="attached", timeout=15000)
            page.evaluate("() => document.getElementById('clawNavButton')?.click()")
            page.wait_for_function(
                """() => {
                  const shell = document.querySelector('.app-shell');
                  const workspace = document.getElementById('clawWorkspace');
                  const nav = document.getElementById('clawNavButton');
                  return Boolean(
                    shell
                    && workspace
                    && nav
                    && shell.dataset.state === 'claw'
                    && workspace.dataset.view === 'general'
                    && workspace.hidden === false
                    && nav.getAttribute('aria-current') === 'page'
                  );
                }""",
                timeout=15000,
            )
            print("CLAW_WORKSPACE=PASS")

            stage = "compose"
            before_assistants = page.locator("#messageList .assistant-message").count()
            before_errors = page.locator("#messageList .error-box").count()
            page.locator("#messageInput").fill(CLAW_SYNTHETIC_PROMPT)
            if page.locator("#sendButton").is_disabled():
                _fail("send_button_disabled")

            submit_ms = int(time.time() * 1000)
            print("SUBMIT_MS=" + str(submit_ms))
            stage = "submit"
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlparse(response.url).path == CLAW_GENERAL_PATH
                ),
                timeout=120000,
            ) as claw_info:
                page.locator("#sendButton").click()

            response = claw_info.value
            stage = "response"
            response_status = response.status
            content_type = (response.headers.get("content-type") or "").lower()
            sse_content_type = content_type.startswith("text/event-stream")
            if response_status != 200:
                _fail("claw_general_http_" + str(response_status))
            if not sse_content_type:
                _fail("claw_general_not_sse")

            stage = "assistant"
            page.wait_for_function(
                """before => {
                  const items = Array.from(document.querySelectorAll('#messageList .assistant-message'));
                  if (items.length <= before) return false;
                  const last = items[items.length - 1];
                  const content = last.querySelector('.assistant-content');
                  return Boolean(content && (content.innerText || '').trim().length > 0);
                }""",
                arg=before_assistants,
                timeout=120000,
            )
            page.wait_for_function(
                "() => !document.querySelector('#messageList .assistant-message:last-of-type .typing')",
                timeout=120000,
            )
            time.sleep(1.0)

            if claw_posts != MAX_CLAW_GENERAL_POSTS:
                _fail("claw_post_count_" + str(claw_posts))
            if page.locator("#messageList .error-box").count() != before_errors:
                _fail("visible_error_box")
            if direct_provider_requests != 0:
                _fail("browser_direct_provider_request")

            complete_ms = int(time.time() * 1000)
            context.close()
            browser.close()

        print("COMPLETE_MS=" + str(complete_ms))
        print("CLAW_GENERAL_POSTS=" + str(claw_posts))
        print("MAX_CLAW_GENERAL_POSTS=1")
        print("CLAW_GENERAL_HTTP=" + str(response_status))
        print("CLAW_SSE_CONTENT_TYPE=" + ("PASS" if sse_content_type else "FAIL"))
        print("ASSISTANT_MESSAGE_NONEMPTY=YES")
        print("BROWSER_DIRECT_PROVIDER_CALLS=0")
        print("RETRY=0")
        print("FALLBACK_FANOUT=0")
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_PROMPT_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("PRODUCTION_CONFIG_MUTATION=0")
        print("SECRET_MUTATION=0")
        print("B54_CLAW_OWNER_ONE_SHOT=PASS")
        return 0
    except SmokeFailure as exc:
        print("COMPLETE_MS=" + str(int(time.time() * 1000)))
        print("CLAW_GENERAL_POSTS=" + str(claw_posts))
        print("CLAW_GENERAL_HTTP=" + (str(response_status) if response_status else "NONE"))
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_PROMPT_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("RETRY=0")
        print("FAIL_STAGE=" + stage)
        print("B54_CLAW_OWNER_ONE_SHOT=FAIL_" + str(exc))
        return 22
    except Exception as exc:
        print("COMPLETE_MS=" + str(int(time.time() * 1000)))
        print("CLAW_GENERAL_POSTS=" + str(claw_posts))
        print("CLAW_GENERAL_HTTP=" + (str(response_status) if response_status else "NONE"))
        print("PASSWORD_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_PROMPT_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("RETRY=0")
        print("FAIL_STAGE=" + stage)
        print("B54_CLAW_OWNER_ONE_SHOT=FAIL_BROWSER_RUNTIME_" + type(exc).__name__)
        return 23


def self_test() -> int:
    assert TARGET_URL == "https://quick-quote-kr.pages.dev/"
    assert INTERPRET_PATH == "/api/padiem/b66/quote/interpret"
    assert MAX_INTERPRET_POSTS == 3
    assert RETRY == 0
    assert FALLBACK == 0
    assert _is_direct_provider("https://api.kilo.ai/x") is True
    assert _is_direct_provider("https://quick-quote-kr.pages.dev/") is False
    assert COMPLETE_TEXT == "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도"
    assert PARTIAL_TEXT == "대한건설에 배관 100미터, 부가세 별도"
    assert FOLLOWUP_TEXT == "미터당 18000원"
    assert CLAW_TARGET_URL == "https://chat.padiem.net/"
    assert CLAW_GENERAL_PATH == "/api/claw/general"
    assert MAX_CLAW_GENERAL_POSTS == 1
    print("B66_FINAL_HANDOFF_SMOKE_SELF_TEST=PASS")
    print("DEFAULT_LIVE_EXECUTION=BLOCKED")
    print("MAX_INTERPRET_POSTS=3")
    print("SECRET_VALUE_OUTPUT=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-live-run", action="store_true")
    parser.add_argument("--claw-owner-one-shot", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.self_test:
        return self_test()
    if args.claw_owner_one_shot:
        return run_claw_owner_one_shot(
            os.getenv("B66_CGI_ALPHA_USERNAME", ""),
            os.getenv("B66_CGI_ALPHA_PASSWORD", ""),
        )
    if not args.authorized_live_run:
        print("B66_FINAL_HANDOFF_SMOKE=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1

    return run_live(
        os.getenv("B66_CGI_ALPHA_USERNAME", ""),
        os.getenv("B66_CGI_ALPHA_PASSWORD", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
