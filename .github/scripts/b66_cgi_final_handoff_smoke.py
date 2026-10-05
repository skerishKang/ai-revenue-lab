"""B66 CGI first-delivery Production browser smoke (#3521).

Runs only when explicitly authorized. Credentials are consumed from the GitHub
Production Environment and are never printed. The browser exercises the real
standalone B66 Production UI:

1) password login + assigned CGI Saved Quote Skill readiness
2) Guided quote path (AI/model interpret calls: zero)
3) complete free-form quote (one interpret POST)
4) partial free-form + bounded follow-up (two interpret POSTs)
5) QuoteCore totals + result view + print/PDF invocation

No retry, provider fanout, account creation, Saved Skill mutation, or raw
response logging is permitted.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

TARGET_URL = "https://quick-quote-kr.pages.dev/"
INTERPRET_PATH = "/api/padiem/b66/quote/interpret"
MAX_INTERPRET_POSTS = 3
RETRY = 0
FALLBACK = 0

COMPLETE_TEXT = "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도"
PARTIAL_TEXT = "대한건설에 배관 100미터, 부가세 별도"
FOLLOWUP_TEXT = "미터당 18000원"


class SmokeFailure(RuntimeError):
    pass


@dataclass
class Counters:
    interpret_posts: int = 0
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
    if locator.count() != 1:
        _fail("chip_not_unique_" + label)
    locator.click()


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


def _print_probe(page) -> None:
    page.evaluate(
        """() => {
          window.__b66FinalPrintCalls = 0;
          window.print = () => { window.__b66FinalPrintCalls += 1; };
        }"""
    )
    page.locator("#printPdf").click()
    page.wait_for_function("() => window.__b66FinalPrintCalls === 1", timeout=5000)


def _open_result_and_print(page) -> None:
    _click_chip(page, "견적서 확인하기")
    page.locator("#directView").wait_for(state="visible", timeout=10000)
    _print_probe(page)


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
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
    page.locator("#padiemAccountButton").click()
    page.locator("#padiemLoginForm").wait_for(state="visible", timeout=15000)
    page.locator("#padiemLoginIdentifier").fill(username)
    page.locator("#padiemLoginPassword").fill(password)
    page.locator("#padiemLoginSubmit").click()

    page.locator("#padiemAccountPanel").wait_for(state="visible", timeout=20000)
    _wait_runtime_ready(page)

    skill_count = page.locator("#padiemSavedSkillSelect option").count()
    if skill_count != 1:
        _fail("saved_skill_count_not_one")


def _guided(page, counters: Counters) -> None:
    before = counters.interpret_posts
    page.locator("#guidedStarter").click()

    for text in (
        "가이드테스트건설",
        "없음",
        "배관",
        "2",
        "10000",
        "다음",
        "별도",
        "없음",
        "현재",
    ):
        _send(page, text)

    _click_chip(page, "견적서 만들기")
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
    _open_result_and_print(page)
    print("GUIDED=PASS")
    print("GUIDED_INTERPRET_POSTS=0")
    print("GUIDED_QUOTECORE_TOTAL=PASS")
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
    _open_result_and_print(page)
    print("COMPLETE_FREEFORM=PASS")
    print("COMPLETE_QUOTECORE_TOTAL=1980000")
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

    _open_result_and_print(page)
    print("PARTIAL_FREEFORM=PASS")
    print("MISSING_UNIT_PRICE_QUESTION=PASS")
    print("FOLLOWUP_COMPLETE=PASS")
    print("FOLLOWUP_SAME_QUOTE_NO=YES")
    print("FOLLOWUP_SAME_ISSUE_DATE=YES")
    print("FOLLOWUP_DOUBLE_ALLOCATION=0")
    print("FOLLOWUP_QUOTECORE_TOTAL=1980000")
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
            if counters.direct_provider_requests != 0:
                _fail("browser_direct_provider_request")

            page.locator("#padiemLogout").click()
            context.close()
            browser.close()

        print("INTERPRET_POSTS=3")
        print("MAX_INTERPRET_POSTS=3")
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
    print("B66_FINAL_HANDOFF_SMOKE_SELF_TEST=PASS")
    print("DEFAULT_LIVE_EXECUTION=BLOCKED")
    print("MAX_INTERPRET_POSTS=3")
    print("SECRET_VALUE_OUTPUT=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-live-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.self_test:
        return self_test()
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
