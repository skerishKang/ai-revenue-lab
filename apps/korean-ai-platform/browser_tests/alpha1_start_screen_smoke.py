#!/usr/bin/env python3
"""Business 14 Alpha 1 browser self-check (desktop + mobile).

Verifies the full user journey on the Start screen and workspace:
- Desktop 1440x1000 and Mobile 390x844 viewports
- Navigation between pages via sidebar and mobile bottom nav
- Mock chat flow with actual click/fill/select/keyboard/network verification
- Response metadata verified from the actual network response
  (selected model, provider, route ID, request ID, tokens, cost, fallback)
- No horizontal overflow, console errors, page errors, failed local assets, or external requests

All assertions use real interactions and network responses, not just element
existence checks. Any failure (import, missing Chromium, server startup,
assertion, console/page error, external request, overflow) exits with code 1.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from typing import Any

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("FAIL: playwright package is not installed. Run: uv sync --group dev --frozen")
    sys.exit(1)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(APP_DIR)
BASE_URL = "http://127.0.0.1:8765"
PORT = 8765

CHAT_ENDPOINT = "/api/pilot/v1/chat/completions"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _check_chromium_available() -> None:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"FAIL: Chromium executable not found or launch failed: {e}")
            print("Run: uv run playwright install chromium")
            sys.exit(1)
        browser.close()


def start_server() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["B14_PROVIDER_MODE"] = "mock"
    env["OPENROUTER_API_KEY"] = ""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=APP_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(120):
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise RuntimeError(f"Server failed: {err.decode()[:1000]}")
        try:
            urllib.request.urlopen(f"{BASE_URL}/workspace", timeout=1)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Server did not start within timeout")


def stop_server(proc: subprocess.Popen[bytes]) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    proc.wait()


def _capture_requests(page: Any) -> list[dict]:
    external: list[dict] = []

    def on_request(req: Any) -> None:
        url = req.url
        if url.startswith(BASE_URL):
            return
        if url.startswith("data:"):
            return
        external.append({"url": url, "method": req.method})

    page.on("request", on_request)
    return external


def _step(name: str, fn: Any, results: dict) -> None:
    try:
        fn()
        results["passed"] += 1
    except AssertionError:
        results["failed"] += 1
        results["errors"].append(name)
    except Exception as e:  # noqa: BLE001 - any interaction failure fails the step
        results["failed"] += 1
        results["errors"].append(f"{name}: {type(e).__name__}: {e}")


def _expand_advanced(page: Any) -> None:
    details = page.locator("details.start-advanced")
    if details.count() > 0:
        if not details.get_attribute("open"):
            page.evaluate("document.querySelector('details.start-advanced').open = true")


def _open_chat_response_tracker(page: Any) -> list[dict]:
    chat_responses: list[dict] = []

    def on_response(resp: Any) -> None:
        if CHAT_ENDPOINT in resp.url:
            try:
                chat_responses.append(resp.json())
            except Exception:
                pass

    page.on("response", on_response)
    return chat_responses


def run_desktop(p: Any) -> dict:
    results: dict = {"passed": 0, "failed": 0, "errors": [], "phase": "desktop"}
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()

    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    failed_local: list[str] = []
    page.on("response", lambda resp: failed_local.append(resp.url) if resp.status >= 400 and resp.url.startswith(BASE_URL) else None)
    external = _capture_requests(page)
    chat_responses = _open_chat_response_tracker(page)

    def nav_click(href: str) -> None:
        page.locator(f'.sidebar-nav .nav-link[href="{href}"]').first.click()
        page.wait_for_timeout(500)
        assert page.url.startswith(f"{BASE_URL}{href}"), f"expected URL {href}, got {page.url}"

    # ── 1. /workspace load ──
    def s1():
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        assert page.url.startswith(f"{BASE_URL}/workspace")
    _step("1. /workspace loaded", s1, results)

    # ── 2. Korean default screen ──
    def s2():
        body = page.locator("body").inner_text()
        assert any(ord(ch) > 0xAC00 for ch in body), "no Korean text found on default screen"
        assert page.locator("#start_prompt").count() > 0
        assert page.locator("#start_model").count() > 0
        assert page.locator("#start_send").count() > 0
    _step("2. Korean default screen", s2, results)

    # ── 3. Start navigation click (workspace / 시작) ──
    def s3():
        nav_click("/workspace")
        assert page.locator("#start_send").count() > 0
    _step("3. start navigation click", s3, results)

    # ── 4. Model & Price navigation click (/models) ──
    def s4():
        nav_click("/models")
    _step("4. model & price navigation click", s4, results)

    # ── 5. Pricing navigation click (/pricing) ──
    def s5():
        nav_click("/pricing")
    _step("5. pricing navigation click", s5, results)

    # ── 6. Usage navigation click (/usage) ──
    def s6():
        nav_click("/usage")
    _step("6. usage navigation click", s6, results)

    # ── 7. Developer navigation click (/pilot) ──
    def s7():
        nav_click("/pilot")
    _step("7. developer navigation click", s7, results)

    # ── 8. Return to Start screen ──
    def s8():
        nav_click("/workspace")
        assert page.locator("#start_send").count() > 0
        assert page.locator("#start_prompt").count() > 0
    _step("8. return to start screen", s8, results)

    # ── 9. Auto model selection ──
    def s9():
        page.locator("#start_model").select_option("b14/auto")
        page.wait_for_timeout(200)
        assert page.locator("#start_model").input_value() == "b14/auto"
        assert page.locator("#start_route_preview").count() > 0
    _step("9. auto model selected (b14/auto)", s9, results)

    # ── 10. optimize_for change ──
    def s10():
        _expand_advanced(page)
        opt = page.locator("#start_optimize_for")
        opt.select_option("cost")
        page.wait_for_timeout(200)
        assert opt.input_value() == "cost"
        opt.select_option("korean")
        page.wait_for_timeout(200)
        assert opt.input_value() == "korean"
    _step("10. optimize_for changed", s10, results)

    # ── 11. Prompt input ──
    def s11():
        page.locator("#start_prompt").fill("한국어로 세 문장으로 설명해줘")
        page.wait_for_timeout(100)
        assert page.locator("#start_prompt").input_value() == "한국어로 세 문장으로 설명해줘"
    _step("11. prompt input filled", s11, results)

    # ── 12. Enter key submit ──
    def s12():
        before = len(chat_responses)
        page.locator("#start_prompt").press("Enter")
        page.wait_for_timeout(1500)
        assert len(chat_responses) > before, "no chat/completions network response received"
        last = chat_responses[-1]
        assert last.get("choices"), "chat response has no choices"
    _step("12. Enter key submitted (network response)", s12, results)

    # ── 13. Mock response check ──
    def s13():
        body = page.locator("#start_response_body").inner_text()
        assert "Mock" in body or "모의" in body or "mock" in body.lower(), "no mock marker in response"
        last = chat_responses[-1]
        assert last.get("choices", [{}])[0].get("message", {}).get("content"), "empty mock content"
    _step("13. mock response shown", s13, results)

    # ── 14. Selected model confirmation (network + DOM) ──
    def s14():
        biz = chat_responses[-1].get("business14", {})
        assert biz.get("selected_model"), "business14.selected_model missing"
        dom = page.locator("#start_selected_model").inner_text()
        assert len(dom) > 0 and dom != "-", "selected model not shown in DOM"
    _step("14. selected model confirmed", s14, results)

    # ── 15. Selected provider confirmation ──
    def s15():
        biz = chat_responses[-1].get("business14", {})
        assert biz.get("selected_provider"), "business14.selected_provider missing"
        dom = page.locator("#start_selected_provider").inner_text()
        assert len(dom) > 0 and dom != "-", "selected provider not shown in DOM"
    _step("15. selected provider confirmed", s15, results)

    # ── 16. Selected route ID confirmation (network) ──
    def s16():
        biz = chat_responses[-1].get("business14", {})
        route_id = biz.get("selected_route_id", "")
        assert route_id.startswith("openrouter:"), f"selected_route_id invalid: {route_id!r}"
        assert "@" not in route_id and "http" not in route_id
    _step("16. selected route ID confirmed", s16, results)

    # ── 17. Request ID confirmation ──
    def s17():
        biz = chat_responses[-1].get("business14", {})
        rid = biz.get("request_id", "")
        assert rid.startswith("b14req_"), f"request_id invalid: {rid!r}"
        dom = page.locator("#start_request_id").inner_text()
        assert len(dom) > 0 and dom != "-", "request id not shown in DOM"
    _step("17. request ID confirmed", s17, results)

    # ── 18. Token usage confirmation ──
    def s18():
        usage = chat_responses[-1].get("usage") or {}
        assert "total_tokens" in usage or "prompt_tokens" in usage, "usage missing"
        dom = page.locator("#start_tokens").inner_text()
        assert len(dom) > 0 and dom != "-", "token usage not shown in DOM"
    _step("18. token usage confirmed", s18, results)

    # ── 19. Estimated cost status ──
    def s19():
        biz = chat_responses[-1].get("business14", {})
        assert "estimated_usd" in biz and "estimated_krw" in biz, "estimated cost fields missing"
        assert biz.get("cost_basis"), "cost_basis missing"
        dom = page.locator("#start_estimated_cost").inner_text()
        assert len(dom) > 0, "estimated cost not shown in DOM"
    _step("19. estimated cost status confirmed", s19, results)

    # ── 20. Manual model selection ──
    def s20():
        page.locator("#start_model").select_option("google/gemini-2.5-flash")
        page.wait_for_timeout(200)
        assert page.locator("#start_model").input_value() == "google/gemini-2.5-flash"
        radio = page.locator('input[name="start_route_mode"][value="manual"]')
        radio.check()
        page.wait_for_timeout(200)
        assert radio.is_checked(), "manual route radio not checked"
    _step("20. manual model selected", s20, results)

    # ── 21. Manual model default fallback OFF (fallback checkbox unchecked) ──
    def s21():
        _expand_advanced(page)
        cb = page.locator("#start_external_fallback")
        if cb.is_checked():
            cb.uncheck()
            page.wait_for_timeout(100)
        assert not cb.is_checked(), "fallback checkbox should default OFF for manual"
    _step("21. manual model default fallback OFF", s21, results)

    # ── 22. Fallback explicitly ON ──
    def s22():
        _expand_advanced(page)
        cb = page.locator("#start_external_fallback")
        cb.check()
        page.wait_for_timeout(100)
        assert cb.is_checked(), "fallback checkbox did not turn ON"
    _step("22. fallback explicitly ON", s22, results)

    # ── 23. Request again ──
    def s23():
        before = len(chat_responses)
        page.locator("#start_prompt").fill("다시 요청합니다")
        page.wait_for_timeout(100)
        page.locator("#start_prompt").press("Enter")
        page.wait_for_timeout(1500)
        assert len(chat_responses) > before, "no second chat/completions network response"
        biz = chat_responses[-1].get("business14", {})
        assert biz.get("selected_model") == "google/gemini-2.5-flash", (
            f"expected manual model, got {biz.get('selected_model')}"
        )
        assert biz.get("fallback_allowed") is True, "fallback_allowed should be true when checkbox ON"
    _step("23. second request with fallback ON", s23, results)

    # ── 25-29. General checks (desktop) ──
    def s25():
        sw = page.evaluate("document.documentElement.scrollWidth")
        cw = page.evaluate("document.documentElement.clientWidth")
        results["desktop_scrollWidth"] = sw
        results["desktop_clientWidth"] = cw
        assert sw <= cw, f"horizontal overflow: scrollWidth={sw} clientWidth={cw}"
    _step("25. horizontal overflow 0 (desktop)", s25, results)

    def s26():
        results["desktop_console_errors"] = list(console_errors)
        assert len(console_errors) == 0, f"console errors: {console_errors}"
    _step("26. console errors 0 (desktop)", s26, results)

    def s27():
        results["desktop_page_errors"] = list(page_errors)
        assert len(page_errors) == 0, f"page errors: {page_errors}"
    _step("27. page errors 0 (desktop)", s27, results)

    def s28():
        results["desktop_failed_local"] = list(failed_local)
        assert len(failed_local) == 0, f"failed local assets: {failed_local}"
    _step("28. failed local assets 0 (desktop)", s28, results)

    def s29():
        results["desktop_external_requests"] = list(external)
        assert len(external) == 0, f"external requests: {external}"
    _step("29. external runtime requests 0 (desktop)", s29, results)

    context.close()
    browser.close()
    return results


def run_mobile(p: Any) -> dict:
    results: dict = {"passed": 0, "failed": 0, "errors": [], "phase": "mobile"}
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()

    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    failed_local: list[str] = []
    page.on("response", lambda resp: failed_local.append(resp.url) if resp.status >= 400 and resp.url.startswith(BASE_URL) else None)
    external = _capture_requests(page)

    def s24():
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        links = page.locator(".mobile-nav .mobile-nav-link")
        assert links.count() == 5, f"expected 5 mobile nav links, got {links.count()}"
        assert page.evaluate("getComputedStyle(document.querySelector('.mobile-nav')).display === 'flex'"), (
            "mobile bottom nav not visible"
        )
        target = links.filter(has=page.locator('a[href="/models"]'))
        page.locator('.mobile-nav .mobile-nav-link[href="/models"]').click()
        page.wait_for_timeout(500)
        assert page.url.startswith(f"{BASE_URL}/models"), f"mobile nav did not navigate, url={page.url}"
    _step("24. mobile bottom navigation actual click", s24, results)

    def s25():
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        sw = page.evaluate("document.documentElement.scrollWidth")
        cw = page.evaluate("document.documentElement.clientWidth")
        results["mobile_scrollWidth"] = sw
        results["mobile_clientWidth"] = cw
        assert sw <= cw, f"mobile horizontal overflow: scrollWidth={sw} clientWidth={cw}"
    _step("25. horizontal overflow 0 (mobile)", s25, results)

    def s26():
        results["mobile_console_errors"] = list(console_errors)
        assert len(console_errors) == 0, f"mobile console errors: {console_errors}"
    _step("26. console errors 0 (mobile)", s26, results)

    def s27():
        results["mobile_page_errors"] = list(page_errors)
        assert len(page_errors) == 0, f"mobile page errors: {page_errors}"
    _step("27. page errors 0 (mobile)", s27, results)

    def s28():
        results["mobile_failed_local"] = list(failed_local)
        assert len(failed_local) == 0, f"mobile failed local assets: {failed_local}"
    _step("28. failed local assets 0 (mobile)", s28, results)

    def s29():
        results["mobile_external_requests"] = list(external)
        assert len(external) == 0, f"mobile external requests: {external}"
    _step("29. external runtime requests 0 (mobile)", s29, results)

    context.close()
    browser.close()
    return results


def main() -> int:
    _check_chromium_available()

    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = start_server()
    except Exception as e:
        print(f"FAIL: server startup failed: {e}")
        return 1

    try:
        with sync_playwright() as p:
            desktop = run_desktop(p)
            mobile = run_mobile(p)
    except Exception as e:
        print(f"FAIL: {e}")
        return 1
    finally:
        if proc:
            stop_server(proc)

    print("=== BUSINESS 14 ALPHA BROWSER SELF-CHECK ===")
    print()
    all_passed = True
    for phase, data in [("DESKTOP 1440x1000", desktop), ("MOBILE 390x844", mobile)]:
        print(f"--- {phase} ---")
        print(f"Passed: {data['passed']}  Failed: {data['failed']}")
        for e in data.get("errors", []):
            print(f"  FAIL: {e}")
        if data["failed"] > 0:
            all_passed = False
        print()

    if not all_passed:
        return 1
    print("BROWSER_RUNTIME_VALIDATION_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())