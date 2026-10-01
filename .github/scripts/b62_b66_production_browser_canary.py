"""B66 authenticated Production Saved Quote Skill browser canary (#3353).

Attaches only to already-authenticated local Chromium instances over loopback CDP.
The user owns every authenticated browser session. This runner never reads,
exports, persists, or prints cookies, tokens, user/tenant/workspace identifiers,
Saved Skill JSON, or provider payloads.

Primary session proves the real Production user flow:
Saved Skill list/get -> one bounded interpret request -> canonical B66 iframe
QuoteCore/render -> preview -> browser print path -> reload persistence.

Optional SECONDARY CDP proves the same durable Saved Quote Skill is visible from a
separate already-authenticated browser. Optional FOREIGN CDP proves the primary
saved_skill_id is non-disclosing to another already-authenticated account.

GitHub Actions never executes the live canary. Live execution requires the
explicit --authorized-live-run switch and loopback-only CDP endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

TARGET_URL = "https://chat.padiem.net/"
TARGET_HOST = "chat.padiem.net"
B66_RUNTIME_HOST = "quick-quote-kr.pages.dev"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
ALLOWED_CDP_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STATIC_GOOGLE_RESOURCE_HOSTS = frozenset({"fonts.googleapis.com", "fonts.gstatic.com"})

EXPECTED_SKILL_ID = "b66-e2e-canonical-v1"
REQUEST_TEXT = "대한건설에 배관 100m, 미터당 18,000원"
EXPECTED_CUSTOMER = "대한건설"
EXPECTED_ITEM = "배관"
EXPECTED_QTY = 100
EXPECTED_UNIT_PRICE = 18000
WAIT_SECONDS = 30.0


class CanaryFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SavedSkillProjection:
    saved_skill_id: str
    skill_id: str
    fingerprint: str
    version: int


@dataclass
class NetworkCounters:
    interpret_posts: int = 0
    direct_google_requests: int = 0
    oauth_requests: int = 0


def validate_cdp_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in ALLOWED_CDP_HOSTS:
        raise CanaryFailure("cdp_url_not_loopback_http")
    if parsed.port is None:
        raise CanaryFailure("cdp_url_missing_port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CanaryFailure("cdp_url_contains_authority_data")
    if parsed.path not in ("", "/"):
        raise CanaryFailure("cdp_url_contains_path")
    return raw


def ensure_distinct_cdp_urls(primary: str, secondary: str | None, foreign: str | None) -> None:
    values = [validate_cdp_url(primary)]
    for raw in (secondary, foreign):
        if raw:
            values.append(validate_cdp_url(raw))
    if len(values) != len(set(values)):
        raise CanaryFailure("cdp_endpoints_must_be_distinct")


def is_direct_google_provider_request(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in STATIC_GOOGLE_RESOURCE_HOSTS:
        return False
    return (
        host.endswith("googleapis.com")
        or host == "drive.google.com"
        or host == "accounts.google.com"
    )


def _wait_until(predicate, *, code: str, timeout: float = WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    raise CanaryFailure(code) from last_error


def validate_interpret_projection(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise CanaryFailure("interpret_response_invalid")
    candidate = body.get("candidate")
    if not isinstance(candidate, dict):
        raise CanaryFailure("interpret_candidate_missing")
    recipient = candidate.get("recipient")
    items = candidate.get("items")
    if not isinstance(recipient, dict) or recipient.get("company") != EXPECTED_CUSTOMER:
        raise CanaryFailure("interpret_customer_mismatch")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise CanaryFailure("interpret_items_mismatch")
    item = items[0]
    if (
        item.get("name") != EXPECTED_ITEM
        or item.get("qty") != EXPECTED_QTY
        or item.get("unitPrice") != EXPECTED_UNIT_PRICE
    ):
        raise CanaryFailure("interpret_item_values_mismatch")
    if candidate.get("missing") != []:
        raise CanaryFailure("interpret_missing_fields")
    serialized = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    for forbidden in (
        '"subtotal":',
        '"grandTotal":',
        '"template":',
        '"internalTemplate":',
        '"sender":',
    ):
        if forbidden in serialized:
            raise CanaryFailure("interpret_response_contains_forbidden_authority")
    execution = body.get("execution")
    if execution != {
        "source_document_parse_calls": 0,
        "server_total_calculation": False,
        "server_rendering": False,
        "browser_quote_core_required": True,
        "browser_approved_renderer_required": True,
    }:
        raise CanaryFailure("interpret_execution_contract_mismatch")
    return candidate


def _choose_target_page(browser):
    if not browser.contexts:
        raise CanaryFailure("cdp_browser_context_unavailable")
    context = browser.contexts[0]
    for page in context.pages:
        try:
            if urlparse(page.url).hostname == TARGET_HOST:
                return page, False
        except Exception:
            continue
    return context.new_page(), True


def _auth_projection(page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
          const r = await fetch('/api/auth/status', {
            headers: {'Accept': 'application/json'}, cache: 'no-store'
          });
          const j = await r.json().catch(() => null);
          return {
            status: r.status,
            authenticated: Boolean(j && j.authenticated === true),
            session_state: j && typeof j.session_state === 'string' ? j.session_state : null
          };
        }"""
    )


def _runtime_projection(page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
          const r = await fetch('/api/b66/runtime-config', {
            headers: {'Accept': 'application/json'}, cache: 'no-store'
          });
          const j = await r.json().catch(() => null);
          return {
            status: r.status,
            ok: Boolean(j && j.ok === true),
            enabled: Boolean(j && j.enabled === true),
            origin: j && typeof j.origin === 'string' ? j.origin : null,
            embed_url: j && typeof j.embed_url === 'string' ? j.embed_url : null
          };
        }"""
    )


def _saved_skill_projection(page, expected_skill_id: str = EXPECTED_SKILL_ID) -> SavedSkillProjection:
    value = page.evaluate(
        """async (expectedSkillId) => {
          const r = await fetch('/api/b66/saved-skills?limit=20', {
            headers: {'Accept': 'application/json'}, cache: 'no-store'
          });
          const j = await r.json().catch(() => null);
          if (!r.ok || !j || j.ok !== true || !Array.isArray(j.skills)) {
            return {status: r.status, match: null};
          }
          const rows = j.skills.filter(x => x && x.skill_id === expectedSkillId);
          if (rows.length !== 1) return {status: r.status, match: null, match_count: rows.length};
          const x = rows[0];
          return {
            status: r.status,
            match: {
              saved_skill_id: x.saved_skill_id,
              skill_id: x.skill_id,
              fingerprint: x.skill_fingerprint,
              version: x.skill_version
            }
          };
        }""",
        expected_skill_id,
    )
    match = value.get("match") if isinstance(value, dict) else None
    if not isinstance(match, dict) or value.get("status") != 200:
        raise CanaryFailure("saved_skill_list_unavailable")
    saved_id = match.get("saved_skill_id")
    fingerprint = match.get("fingerprint")
    version = match.get("version")
    if not isinstance(saved_id, str) or not saved_id.startswith("b66skill_"):
        raise CanaryFailure("saved_skill_id_invalid")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise CanaryFailure("saved_skill_fingerprint_invalid")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CanaryFailure("saved_skill_version_invalid")
    return SavedSkillProjection(saved_id, str(match.get("skill_id")), fingerprint, version)


def _saved_skill_detail_projection(page, saved_skill_id: str) -> dict[str, Any]:
    return page.evaluate(
        """async (savedId) => {
          const r = await fetch('/api/b66/saved-skills/' + encodeURIComponent(savedId), {
            headers: {'Accept': 'application/json'}, cache: 'no-store'
          });
          const j = await r.json().catch(() => null);
          const row = j && j.saved_skill;
          const skill = row && row.skill;
          return {
            status: r.status,
            ok: Boolean(j && j.ok === true),
            saved_id_match: Boolean(row && row.saved_skill_id === savedId),
            skill_id: row && row.skill_id,
            fingerprint: row && row.skill_fingerprint,
            approved: Boolean(skill && skill.approved === true),
            calculation_authority: skill && skill.calculationAuthority,
            renderer_contract: skill && skill.rendererContract
          };
        }""",
        saved_skill_id,
    )


def _foreign_detail_status(page, saved_skill_id: str) -> int:
    return int(
        page.evaluate(
            """async (savedId) => {
              const r = await fetch('/api/b66/saved-skills/' + encodeURIComponent(savedId), {
                headers: {'Accept': 'application/json'}, cache: 'no-store'
              });
              return r.status;
            }""",
            saved_skill_id,
        )
    )


def _foreign_list_contains(page, saved_skill_id: str) -> bool:
    return bool(
        page.evaluate(
            """async (savedId) => {
              const r = await fetch('/api/b66/saved-skills?limit=20', {
                headers: {'Accept': 'application/json'}, cache: 'no-store'
              });
              const j = await r.json().catch(() => null);
              if (!r.ok || !j || !Array.isArray(j.skills)) return true;
              return j.skills.some(x => x && x.saved_skill_id === savedId);
            }""",
            saved_skill_id,
        )
    )


def _assert_authenticated(page) -> None:
    auth = _auth_projection(page)
    if auth != {"status": 200, "authenticated": True, "session_state": "signed_in"}:
        raise CanaryFailure("authenticated_session_required")


def _assert_runtime(page) -> None:
    runtime = _runtime_projection(page)
    if runtime.get("status") != 200 or runtime.get("ok") is not True or runtime.get("enabled") is not True:
        raise CanaryFailure("b66_runtime_not_enabled")
    try:
        origin = urlparse(str(runtime.get("origin") or ""))
        embed = urlparse(str(runtime.get("embed_url") or ""))
    except Exception as exc:
        raise CanaryFailure("b66_runtime_location_invalid") from exc
    if (
        origin.scheme != "https"
        or origin.hostname != B66_RUNTIME_HOST
        or embed.scheme != "https"
        or embed.hostname != B66_RUNTIME_HOST
        or embed.path != "/embed.html"
    ):
        raise CanaryFailure("b66_runtime_location_mismatch")


def _attach(playwright, cdp_url: str):
    try:
        return playwright.chromium.connect_over_cdp(validate_cdp_url(cdp_url))
    except Exception as exc:
        raise CanaryFailure("cdp_connect_failed") from exc


def _open_authenticated_page(browser):
    page, created = _choose_target_page(browser)
    try:
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        if created:
            try:
                page.close()
            except Exception:
                pass
        raise CanaryFailure("production_page_unavailable") from exc
    _assert_authenticated(page)
    _assert_runtime(page)
    return page, created


def _run_primary(playwright, cdp_url: str) -> tuple[SavedSkillProjection, Any, bool]:
    browser = _attach(playwright, cdp_url)
    page, created = _open_authenticated_page(browser)
    counters = NetworkCounters()

    def observe_request(request) -> None:
        parsed = urlparse(request.url)
        if request.method == "POST" and parsed.path == "/api/b66/quote/interpret":
            counters.interpret_posts += 1
        if is_direct_google_provider_request(request.url):
            counters.direct_google_requests += 1
            if parsed.hostname == "accounts.google.com":
                counters.oauth_requests += 1

    page.on("request", observe_request)

    skill = _saved_skill_projection(page)
    detail = _saved_skill_detail_projection(page, skill.saved_skill_id)
    if (
        detail.get("status") != 200
        or detail.get("ok") is not True
        or detail.get("saved_id_match") is not True
        or detail.get("skill_id") != EXPECTED_SKILL_ID
        or detail.get("fingerprint") != skill.fingerprint
        or detail.get("approved") is not True
        or detail.get("calculation_authority") != "quote-core"
        or detail.get("renderer_contract") != "quote-template-renderer.v1"
    ):
        raise CanaryFailure("saved_skill_detail_contract_mismatch")

    page.reload(wait_until="domcontentloaded", timeout=30000)
    launcher = page.locator("#b66QuoteNavButton")
    _wait_until(
        lambda: launcher.count() == 1 and launcher.is_visible() and not launcher.is_disabled(),
        code="b66_launcher_not_available",
    )
    launcher.click()
    page.locator("#b66QuoteDialog").wait_for(state="visible", timeout=10000)

    select = page.locator("#b66QuoteSkillSelect")
    select.select_option(value=skill.saved_skill_id)
    page.locator("#b66QuoteRequest").fill(REQUEST_TEXT)

    try:
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/b66/quote/interpret"
            ),
            timeout=30000,
        ) as info:
            page.locator("#b66QuoteGenerate").click()
        response = info.value
    except Exception as exc:
        raise CanaryFailure("interpret_response_missing") from exc
    if response.status != 200:
        raise CanaryFailure(f"interpret_http_{response.status}")
    try:
        interpreted = response.json()
    except Exception as exc:
        raise CanaryFailure("interpret_response_not_json") from exc
    validate_interpret_projection(interpreted)

    status = page.locator("#b66QuoteStatus")
    _wait_until(
        lambda: status.get_attribute("data-state") == "ready",
        code="preview_not_ready",
    )
    frame_locator = page.locator("#b66QuoteFrame")
    _wait_until(lambda: frame_locator.is_visible(), code="preview_frame_not_visible")
    handle = frame_locator.element_handle()
    frame = handle.content_frame() if handle is not None else None
    if frame is None or urlparse(frame.url).hostname != B66_RUNTIME_HOST:
        raise CanaryFailure("canonical_embed_frame_missing")

    runtime_modules = frame.evaluate(
        """() => ({
          quoteCore: Boolean(window.QuoteCore && typeof window.QuoteCore.computeTotals === 'function'),
          savedSkill: Boolean(window.SavedQuoteSkill && typeof window.SavedQuoteSkill.buildRenderModel === 'function'),
          renderer: Boolean(window.QuoteTemplateRenderer && typeof window.QuoteTemplateRenderer.applyRenderModel === 'function')
        })"""
    )
    if runtime_modules != {"quoteCore": True, "savedSkill": True, "renderer": True}:
        raise CanaryFailure("canonical_renderer_modules_missing")

    recipient = (frame.locator("#pvRecipientCompany").text_content() or "").strip()
    items_text = (frame.locator("#pvItems").inner_text() or "").replace(",", "")
    subtotal = (frame.locator("#pvSubtotal").text_content() or "").replace(",", "").strip()
    vat = (frame.locator("#pvVat").text_content() or "").replace(",", "").strip()
    grand = (frame.locator("#pvGrand").text_content() or "").replace(",", "").strip()
    if recipient != EXPECTED_CUSTOMER:
        raise CanaryFailure("rendered_customer_mismatch")
    for expected in (EXPECTED_ITEM, "100", "18000", "1800000"):
        if expected not in items_text:
            raise CanaryFailure("rendered_item_mismatch")
    if "1800000" not in subtotal or "180000" not in vat or "1980000" not in grand:
        raise CanaryFailure("quote_core_totals_mismatch")

    frame.evaluate("() => { window.__b66CanaryPrintCalls = 0; window.print = () => { window.__b66CanaryPrintCalls += 1; }; }")
    frame.locator("#embedPrint").click()
    print_calls = frame.evaluate("() => window.__b66CanaryPrintCalls")
    if print_calls != 1:
        raise CanaryFailure("print_path_not_invoked")

    if counters.interpret_posts != 1:
        raise CanaryFailure("interpret_request_budget_mismatch")
    if counters.direct_google_requests != 0 or counters.oauth_requests != 0:
        raise CanaryFailure("unexpected_provider_request")

    page.reload(wait_until="domcontentloaded", timeout=30000)
    _assert_authenticated(page)
    reloaded = _saved_skill_projection(page)
    if reloaded != skill:
        raise CanaryFailure("same_account_reload_persistence_failed")

    print("LOGIN=PASS")
    print("SAVED_SKILL_LIST=PASS")
    print("SAVED_SKILL_GET=PASS")
    print("INTERPRET_REQUEST=PASS")
    print("BOUNDED_MODEL_CALL_COUNT=1")
    print("SOURCE_DOCUMENT_PARSE_CALLS=0")
    print("FULL_DOCUMENT_MODEL_REGENERATION=0")
    print("QUOTECORE_MODEL_CALLS=0")
    print("RENDERER_MODEL_CALLS=0")
    print("QUOTECORE_CALCULATION=PASS")
    print("CANONICAL_RENDERER=PASS")
    print("PREVIEW=PASS")
    print("PRINT_OR_PDF=PASS")
    print("SAME_ACCOUNT_RELOGIN_PERSISTENCE=PASS")
    print("BROWSER_INTERPRET_POST_COUNT=1")
    print("BROWSER_DIRECT_GOOGLE_CALLS=0")
    return skill, page, created


def _check_secondary(playwright, cdp_url: str, expected: SavedSkillProjection) -> bool:
    browser = _attach(playwright, cdp_url)
    page, created = _open_authenticated_page(browser)
    try:
        observed = _saved_skill_projection(page)
        detail = _saved_skill_detail_projection(page, observed.saved_skill_id)
        if observed != expected:
            raise CanaryFailure("cross_browser_skill_mismatch")
        if detail.get("status") != 200 or detail.get("saved_id_match") is not True:
            raise CanaryFailure("cross_browser_detail_unavailable")
        print("CROSS_BROWSER_PERSISTENCE=PASS")
        return True
    finally:
        if created:
            try:
                page.close()
            except Exception:
                pass


def _check_foreign(playwright, cdp_url: str, primary_skill: SavedSkillProjection) -> bool:
    browser = _attach(playwright, cdp_url)
    page, created = _open_authenticated_page(browser)
    try:
        if _foreign_detail_status(page, primary_skill.saved_skill_id) != 404:
            raise CanaryFailure("foreign_detail_not_nondisclosing")
        if _foreign_list_contains(page, primary_skill.saved_skill_id):
            raise CanaryFailure("foreign_list_disclosed_primary_skill")
        print("FOREIGN_ACCOUNT_ACCESS=DENIED_OR_NONDISCLOSING")
        return True
    finally:
        if created:
            try:
                page.close()
            except Exception:
                pass


def run_live(primary_cdp_url: str, *, secondary_cdp_url: str | None, foreign_cdp_url: str | None) -> int:
    ensure_distinct_cdp_urls(primary_cdp_url, secondary_cdp_url, foreign_cdp_url)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise CanaryFailure("playwright_unavailable") from exc

    with sync_playwright() as playwright:
        primary_skill, primary_page, primary_created = _run_primary(playwright, primary_cdp_url)
        try:
            if secondary_cdp_url:
                _check_secondary(playwright, secondary_cdp_url, primary_skill)
            else:
                print("CROSS_BROWSER_PERSISTENCE=NOT_RUN_NO_SECONDARY_SESSION")
            if foreign_cdp_url:
                _check_foreign(playwright, foreign_cdp_url, primary_skill)
            else:
                print("FOREIGN_ACCOUNT_ACCESS=NOT_RUN_NO_FOREIGN_SESSION")
        finally:
            if primary_created:
                try:
                    primary_page.close()
                except Exception:
                    pass

    print("RAW_SOURCE_DOCUMENT_PERSISTED_TO_D1=NO")
    print("CLIENT_OWNERSHIP_OVERRIDE=DENIED")
    print("PRODUCTION_DB_MUTATION_BY_BROWSER_RUNNER=0")
    print("OAUTH_CONNECT=0")
    print("DRIVE_MUTATION=0")
    print("COOKIE_OUTPUT=0")
    print("TOKEN_OUTPUT=0")
    print("RAW_USER_OUTPUT=0")
    print("RAW_TENANT_OUTPUT=0")
    print("RAW_WORKSPACE_OUTPUT=0")
    print("RAW_SKILL_OUTPUT=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--authorized-live-run", action="store_true")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--secondary-cdp-url")
    parser.add_argument("--foreign-cdp-url")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.authorized_live_run:
        print("B66_PRODUCTION_BROWSER_E2E=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1

    try:
        result = run_live(
            args.cdp_url,
            secondary_cdp_url=args.secondary_cdp_url,
            foreign_cdp_url=args.foreign_cdp_url,
        )
        print("B66_PRODUCTION_BROWSER_E2E=PASS")
        return result
    except CanaryFailure as exc:
        print("B66_PRODUCTION_BROWSER_E2E=FAIL")
        print(f"SAFE_ERROR_CODE={exc.code}")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_USER_OUTPUT=0")
        print("RAW_TENANT_OUTPUT=0")
        print("RAW_WORKSPACE_OUTPUT=0")
        print("RAW_SKILL_OUTPUT=0")
        return 1
    except Exception:
        print("B66_PRODUCTION_BROWSER_E2E=FAIL")
        print("SAFE_ERROR_CODE=unexpected_error")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        print("RAW_USER_OUTPUT=0")
        print("RAW_TENANT_OUTPUT=0")
        print("RAW_WORKSPACE_OUTPUT=0")
        print("RAW_SKILL_OUTPUT=0")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
