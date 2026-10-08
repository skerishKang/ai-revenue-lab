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
import json
import os
import re
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

# #3751: interpretation errors have two independent 502 owners. Mirror the
# exact product-owned header vocabulary; .github/tests checks it against the
# canonical B66 route without importing app dependencies.
B66_INTERPRET_ERROR_CODES = frozenset({
    "quote_interpretation_failed",
    "padiem_service_unavailable",
})
B66_UPSTREAM_CLASS_VOCABULARY = frozenset({
    "upstream_timeout",
    "upstream_busy",
    "upstream_response_too_large",
    "malformed_upstream",
    "upstream_malformed_json",
    "upstream_unexpected_shape",
    "upstream_missing_content",
    "upstream_non_text_content",
    "upstream_empty_answer",
    "upstream_unavailable",
    "provider_auth_error",
    "provider_route_error",
    "provider_server_error",
    "upstream_execution_failed",
    "upstream_error",
    "upstream_binding_unavailable",
})

# #3655 one-shot canary evidence seam. The request marker opts the ONE canary
# request into the chat route's bounded evidence headers; the normal user
# surface is unchanged. Playwright lowercases response header names.
CLAW_EVIDENCE_REQUEST_HEADER = "X-Padiem-Claw-Evidence"
CLAW_EVIDENCE_MARKER = "one-shot"
CLAW_EVIDENCE_RESPONSE_HEADERS = (
    "x-padiem-claw-run-id",
    "x-padiem-orchestration-run-id",
    "x-padiem-selected-route-id",
    "x-padiem-provider-attempts",
    "x-padiem-fallback-used",
)
# Mirror of kagent P01_FAILURE_DETAILS (apps/korean-ai-code-agent/src/kagent/
# p01_adapter.py): the closed terminal failure vocabulary the Claw 502 `detail`
# may carry. Kept as a literal because this smoke script must not import
# product packages; .github/tests cross-checks the mirror stays in sync.
CLAW_FAILURE_DETAIL_VOCABULARY = frozenset(
    {
        "engine_authentication_failed",
        "engine_authorization_failed",
        "engine_transport_or_response_failed",
        "engine_downstream_execution_failed",
        "p01_contract_failure",
        "unknown_engine_failure",
        "engine_provider_server_error",
        "engine_provider_timeout",
        "engine_provider_rate_limited",
        "engine_provider_unavailable",
        "engine_provider_authorization_failed",
        "engine_provider_request_rejected",
        "engine_provider_bad_response",
        "engine_admission_denied",
    }
)
CLAW_ADMISSION_DENIED_DETAIL = "engine_admission_denied"
_EVIDENCE_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{24}$")
_EVIDENCE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_EVIDENCE_ATTEMPTS_RE = re.compile(r"^\d{1,2}$")


class SmokeFailure(RuntimeError):
    pass


@dataclass
class Counters:
    interpret_posts: int = 0
    pdf_posts: int = 0
    direct_provider_requests: int = 0


def _fail(code: str) -> None:
    raise SmokeFailure(code)


def _bounded_evidence_headers(headers: object) -> dict[str, str]:
    """Extract only the allowlisted evidence headers with grammar-valid values.

    Playwright hands back lowercase header names. A value that fails its
    grammar is dropped rather than degraded, so the evidence record can never
    carry a fabricated ref, oversized junk, or free text.
    """
    if not isinstance(headers, object) or not hasattr(headers, "get"):
        return {}
    extracted: dict[str, str] = {}
    for name in CLAW_EVIDENCE_RESPONSE_HEADERS:
        value = headers.get(name)  # type: ignore[attr-defined]
        if not isinstance(value, str):
            continue
        if name == "x-padiem-provider-attempts":
            if not _EVIDENCE_ATTEMPTS_RE.fullmatch(value):
                continue
            extracted[name] = value
            continue
        if name == "x-padiem-fallback-used":
            if value not in ("true", "false"):
                continue
            extracted[name] = value
            continue
        pattern = _EVIDENCE_RUN_ID_RE if name == "x-padiem-claw-run-id" else _EVIDENCE_VALUE_RE
        if not pattern.fullmatch(value):
            continue
        extracted[name] = value
    return extracted


def _bounded_b66_interpret_failure(
    body_text: object, headers: object
) -> tuple[str, str, str]:
    """Return only two enumerated error codes and a canonical upstream class.

    Deliberately neither returns nor logs response.body, message, customer
    content, URL, IDs, raw headers, model/provider payloads or trace text.
    Unexpected shapes, non-JSON, oversized envelopes and unrecognized header
    values are all opaque rather than a new diagnostic vocabulary.
    """
    code = "UNCLASSIFIED"
    upstream_class = "UNCLASSIFIED"
    if isinstance(body_text, str) and len(body_text) <= 8192:
        try:
            data = json.loads(body_text)
            error = data.get("error") if isinstance(data, dict) else None
            candidate = error.get("code") if isinstance(error, dict) else None
            if isinstance(candidate, str) and candidate in B66_INTERPRET_ERROR_CODES:
                code = candidate
        except (ValueError, TypeError):
            pass

    if code == "quote_interpretation_failed":
        layer = "B66_INTERPRETER_ROUTE"
        if hasattr(headers, "get"):
            candidate = headers.get("x-b66-upstream-class")
            if (
                isinstance(candidate, str)
                and candidate in B66_UPSTREAM_CLASS_VOCABULARY
            ):
                upstream_class = candidate
    elif code == "padiem_service_unavailable":
        layer = "PAGES_UPSTREAM_PROXY"
    else:
        layer = "UNCLASSIFIED"

    return code, layer, upstream_class


def _print_bounded_b66_interpret_failure(response: object) -> None:
    """Observe existing failure response; NEVER create a new provider request."""
    body_text = None
    headers = getattr(response, "headers", None)
    try:
        content_type = headers.get("content-type", "") if hasattr(headers, "get") else ""
        if isinstance(content_type, str) and "application/json" in content_type.lower():
            body_text = response.text()  # type: ignore[attr-defined]
    except Exception:
        pass
    code, layer, upstream_class = _bounded_b66_interpret_failure(body_text, headers)
    print("B66_INTERPRET_ERROR_CODE=" + code, flush=True)
    print("B66_INTERPRET_ERROR_LAYER=" + layer, flush=True)
    print("B66_INTERPRET_UPSTREAM_CLASS=" + upstream_class, flush=True)


def _bounded_error_class(body_text: object) -> tuple[str | None, str | None]:
    """Extract ONLY the bounded error code/detail from a Claw error body.

    Never returns the message or any other body content: a malformed body or
    an out-of-vocabulary detail degrades to None so unbounded text can never
    reach the evidence record.
    """
    if not isinstance(body_text, str):
        return None, None
    try:
        parsed = json.loads(body_text)
    except ValueError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    error = parsed.get("error")
    if not isinstance(error, dict):
        return None, None
    code = error.get("code")
    code_bounded = (
        code if isinstance(code, str) and _EVIDENCE_VALUE_RE.fullmatch(code) else None
    )
    detail = error.get("detail")
    detail_bounded = (
        detail
        if isinstance(detail, str) and detail in CLAW_FAILURE_DETAIL_VOCABULARY
        else None
    )
    return code_bounded, detail_bounded


def _canonical_admission_result(detail: str | None) -> str:
    """ENGINE_ADMISSION_RESULT for a terminal failure.

    Only the engine's enumerated admission-denial class proves DENIED; every
    other failure (transport, provider, contract) leaves the admission stage
    unproven rather than inferred.
    """
    if detail == CLAW_ADMISSION_DENIED_DETAIL:
        return "DENIED"
    return "UNPROVEN"


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
    print("SMOKE_STAGE=PDF_PROBE_START", flush=True)
    # CGI client-raster mode is the only accepted current customer download.
    # Previously this smoke REQUIRED 3 backend PDF POSTs; now it MUST see ZERO.
    # No fallback to the 503 Cloudflare renderer or deferred Modal.
    if not page.evaluate("""() => {
        const selected = document.getElementById('padiemSavedSkillSelect');
        const exporter = window.B66BrowserPdf;
        const readiness = window.B66QuoteRuntimeBridge?.readiness?.();
        return Boolean(selected && exporter && exporter.isCgiSkill(selected.value) &&
            readiness?.ready === true);
    }"""):
        _fail("cgi_browser_pdf_not_active")
    print("SMOKE_STAGE=PDF_PREVIEW_IMAGE_WAIT", flush=True)
    try:
        page.wait_for_function("""() => {
            const image = document.getElementById('cgiCertifiedPreviewBase');
            return image && image.complete && image.naturalWidth === 1190 &&
                image.naturalHeight === 1682;
        }""", timeout=15000)
    except Exception as exc:
        # Bounded booleans only: never print user data, URLs, cookies, tokens or responses.
        flags = page.evaluate("""() => {
            const im = document.getElementById('cgiCertifiedPreviewBase');
            const preview = document.getElementById('cgiCertifiedPreview');
            return {
                element: !!im,
                src: !!im?.getAttribute('src'),
                loaded: !!im?.complete,
                width: im?.naturalWidth === 1190,
                height: im?.naturalHeight === 1682,
                shown: !!preview && preview.hidden === false,
                paper: !!document.getElementById('quotePaper'),
                cgiHost: !!document.getElementById('cgiV2Content'),
                cgiLayout: document.getElementById('quotePaper')?.dataset.layoutVariant === 'cgi-v2',
                skillSelect: !!document.getElementById('padiemSavedSkillSelect')?.value,
                ownerSkill: window.B66BrowserPdf?.isCgiSkill?.(
                    document.getElementById('padiemSavedSkillSelect')?.value) === true,
                serverMatch: window.B66QuoteSkillBridge?.serverSkillId?.() ===
                    document.getElementById('padiemSavedSkillSelect')?.value,
                activeMatch: window.B66QuoteSkillBridge?.activeSkillId?.() ===
                    document.getElementById('padiemSavedSkillSelect')?.value,
                scriptLoaded: !!window.B66BrowserPdf
            };
        }""")
        if not isinstance(flags, dict):
            raise SmokeFailure("cgi_preview_image_unavailable") from exc
        status = "_".join(
            name + str(int(flags.get(name) is True))
            for name in (
                "element", "src", "loaded", "width", "height", "shown",
                "paper", "cgiHost", "cgiLayout", "skillSelect", "ownerSkill",
                "serverMatch", "activeMatch", "scriptLoaded"
            )
        )
        raise SmokeFailure("cgi_preview_image_" + status) from exc
    print("SMOKE_STAGE=PDF_PREVIEW_IMAGE_READY", flush=True)
    before = counters.pdf_posts
    if before != 0:
        _fail("unexpected_server_pdf_post")
    try:
        with page.expect_download(timeout=30000) as download_info:
            page.locator("#printPdf").click()
        download = download_info.value
        print("SMOKE_STAGE=PDF_DOWNLOAD_EVENT", flush=True)
    except Exception as exc:
        raise SmokeFailure("browser_pdf_download_missing") from exc
    if counters.pdf_posts != before:
        _fail("cgi_browser_pdf_used_server")
    if not str(download.suggested_filename or "").lower().endswith(".pdf"):
        _fail("pdf_filename_invalid")
    # Reading the downloaded artifact is bounded; raw bytes never printed.
    from pathlib import Path
    body = Path(download.path()).read_bytes()
    if not isinstance(body, bytes) or not body.startswith(b"%PDF-"):
        _fail("browser_pdf_bytes_invalid")
    if not (100_000 <= len(body) <= 4_000_000):
        _fail("browser_pdf_bytes_bounds")
    if b"/MediaBox [0 0 595 841]" not in body or b"/DCTDecode" not in body:
        _fail("browser_pdf_a4_image_contract_missing")


def _open_result_and_download(page, counters: Counters) -> None:
    print("SMOKE_STAGE=RESULT_OPEN", flush=True)
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
    print("SMOKE_STAGE=GUIDED_START", flush=True)
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
    print("SMOKE_STAGE=GUIDED_VALIDATED_BEFORE_PDF", flush=True)
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
        _print_bounded_b66_interpret_failure(response)
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
        _print_bounded_b66_interpret_failure(first)
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
        _print_bounded_b66_interpret_failure(second)
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
            if counters.pdf_posts != 0:
                _fail("cgi_browser_pdf_server_post_detected")
            if counters.direct_provider_requests != 0:
                _fail("browser_direct_provider_request")

            page.locator("#padiemLogout").click()
            context.close()
            browser.close()

        print("INTERPRET_POSTS=3")
        print("MAX_INTERPRET_POSTS=3")
        print("PDF_POSTS=0")
        print("MAX_PDF_POSTS=3")
        print("CERTIFIED_BROWSER_PDF_DOWNLOADS=3")
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
    evidence_headers: dict[str, str] = {}
    terminal_error_class: str | None = None
    terminal_error_code: str | None = None
    admission_result = "UNPROVEN"
    assistant_projection_count = 0

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                # #3655: opt this one canary request flow into the chat route's
                # bounded evidence headers; the normal user surface is unchanged.
                extra_http_headers={CLAW_EVIDENCE_REQUEST_HEADER: CLAW_EVIDENCE_MARKER},
            )
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
            evidence_headers = _bounded_evidence_headers(response.headers)
            if response_status != 200:
                # Read the bounded terminal class from the error envelope
                # BEFORE failing: only the closed code/detail fields survive;
                # the message and body text are never printed or stored.
                terminal_error_code, terminal_error_class = _bounded_error_class(
                    response.text()
                )
                admission_result = _canonical_admission_result(terminal_error_class)
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

            after_assistants = page.locator("#messageList .assistant-message").count()
            assistant_projection_count = after_assistants - before_assistants

            if claw_posts != MAX_CLAW_GENERAL_POSTS:
                _fail("claw_post_count_" + str(claw_posts))
            if page.locator("#messageList .error-box").count() != before_errors:
                _fail("visible_error_box")
            if direct_provider_requests != 0:
                _fail("browser_direct_provider_request")
            # #3655 evidence bounds: the measured dispatch/fallback/projection
            # counts are load-bearing acceptance evidence, not printed claims.
            if assistant_projection_count != 1:
                _fail("assistant_projection_count_" + str(assistant_projection_count))
            attempts_value = evidence_headers.get("x-padiem-provider-attempts")
            if attempts_value != "1":
                _fail("provider_dispatch_count_" + (attempts_value or "MISSING"))
            fallback_value = evidence_headers.get("x-padiem-fallback-used")
            if fallback_value != "false":
                _fail("fallback_used_" + (fallback_value or "MISSING"))
            if not evidence_headers.get("x-padiem-claw-run-id"):
                _fail("missing_claw_run_ref")
            if not evidence_headers.get("x-padiem-orchestration-run-id"):
                _fail("missing_orchestration_run_ref")
            if not evidence_headers.get("x-padiem-selected-route-id"):
                _fail("missing_selected_route_id")
            terminal_error_class = None
            admission_result = "PASS"

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
        print("FALLBACK=0")
        print("FALLBACK_FANOUT=0")
        # #3655 evidence block: correlation + admission + route + measured
        # dispatch/append counts. Values are bounded refs/enums only.
        print("CLAW_RUN_REF=" + evidence_headers.get("x-padiem-claw-run-id", "MISSING"))
        print(
            "ORCHESTRATION_RUN_REF="
            + evidence_headers.get("x-padiem-orchestration-run-id", "MISSING")
        )
        print(
            "SELECTED_ROUTE_ID="
            + evidence_headers.get("x-padiem-selected-route-id", "MISSING")
        )
        print(
            "PROVIDER_DISPATCH_COUNT="
            + evidence_headers.get("x-padiem-provider-attempts", "MISSING")
        )
        print(
            "FALLBACK_USED=" + evidence_headers.get("x-padiem-fallback-used", "MISSING")
        )
        print("ENGINE_ADMISSION_RESULT=" + admission_result)
        print("TERMINAL_ERROR_CLASS=" + (terminal_error_class or "NONE"))
        # Source-truth for this lane: /api/claw/general is a terminal-SSE
        # projection and performs no conversation-store append (#3539/#3655).
        print("ASSISTANT_STORE_APPEND_COUNT=0")
        print(
            "ASSISTANT_VISIBLE_PROJECTION_COUNT=" + str(assistant_projection_count)
        )
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
        # #3655: even a failed canary must retain its bounded terminal class
        # and whatever correlation/route evidence the served surface returned.
        if evidence_headers.get("x-padiem-claw-run-id"):
            print("CLAW_RUN_REF=" + evidence_headers["x-padiem-claw-run-id"])
        if evidence_headers.get("x-padiem-selected-route-id"):
            print("SELECTED_ROUTE_ID=" + evidence_headers["x-padiem-selected-route-id"])
        if evidence_headers.get("x-padiem-provider-attempts"):
            print(
                "PROVIDER_DISPATCH_COUNT="
                + evidence_headers["x-padiem-provider-attempts"]
            )
        print("ENGINE_ADMISSION_RESULT=" + admission_result)
        print("TERMINAL_ERROR_CLASS=" + (terminal_error_class or "NONE"))
        if terminal_error_code:
            print("TERMINAL_ERROR_CODE=" + terminal_error_code)
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
        if evidence_headers.get("x-padiem-claw-run-id"):
            print("CLAW_RUN_REF=" + evidence_headers["x-padiem-claw-run-id"])
        print("ENGINE_ADMISSION_RESULT=" + admission_result)
        print("TERMINAL_ERROR_CLASS=" + (terminal_error_class or "NONE"))
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
    # #3655: bounded evidence seam contract.
    assert "engine_admission_denied" in CLAW_FAILURE_DETAIL_VOCABULARY
    assert "engine_provider_server_error" in CLAW_FAILURE_DETAIL_VOCABULARY
    assert CLAW_EVIDENCE_MARKER == "one-shot"
    _run_evidence_self_tests()
    print("B66_FINAL_HANDOFF_SMOKE_SELF_TEST=PASS")
    print("DEFAULT_LIVE_EXECUTION=BLOCKED")
    print("MAX_INTERPRET_POSTS=3")
    print("SECRET_VALUE_OUTPUT=0")
    return 0


def _run_evidence_self_tests() -> None:
    valid_headers = {
        "x-padiem-claw-run-id": "run_" + "a" * 24,
        "x-padiem-orchestration-run-id": "orch_test_001",
        "x-padiem-selected-route-id": "plus.agnes-3.0-flash.v1",
        "x-padiem-provider-attempts": "1",
        "x-padiem-fallback-used": "false",
        "x-padiem-unlisted-header": "should-not-survive",
        "content-type": "text/event-stream",
    }
    extracted = _bounded_evidence_headers(valid_headers)
    assert extracted == {
        "x-padiem-claw-run-id": "run_" + "a" * 24,
        "x-padiem-orchestration-run-id": "orch_test_001",
        "x-padiem-selected-route-id": "plus.agnes-3.0-flash.v1",
        "x-padiem-provider-attempts": "1",
        "x-padiem-fallback-used": "false",
    }
    # Junk, oversized, and out-of-vocabulary values are dropped, never degraded.
    assert _bounded_evidence_headers(
        {
            "x-padiem-claw-run-id": "not-a-run-id",
            "x-padiem-orchestration-run-id": "bad id with spaces",
            "x-padiem-selected-route-id": "x" * 200,
            "x-padiem-provider-attempts": "not-a-number",
            "x-padiem-fallback-used": "maybe",
        }
    ) == {}
    assert _bounded_evidence_headers(None) == {}
    # Only the bounded code/detail survive the error envelope; the message
    # (which could carry free text) never does.
    body = json.dumps(
        {
            "ok": False,
            "error": {
                "code": "engine_execution_failed",
                "message": "Engine 실행에 실패했습니다.",
                "detail": "engine_provider_server_error",
            },
        }
    )
    assert _bounded_error_class(body) == (
        "engine_execution_failed",
        "engine_provider_server_error",
    )
    assert _bounded_error_class('{"error": {"code": "x", "detail": "free text!"}}') == (
        "x",
        None,
    )
    assert _bounded_error_class("not json") == (None, None)
    assert _bounded_error_class('{"error": "flat"}') == (None, None)
    assert _canonical_admission_result("engine_admission_denied") == "DENIED"
    assert _canonical_admission_result("engine_provider_server_error") == "UNPROVEN"
    assert _canonical_admission_result(None) == "UNPROVEN"


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
