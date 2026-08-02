#!/usr/bin/env python3
"""Business 14 Alpha 1 browser self-check (desktop + mobile).

Verifies:
- Start screen renders (prompt, model select, send button)
- Mock mode label visible
- Desktop 1440x1000 layout
- Mobile 390x844 layout, no horizontal overflow
- No console errors
- No page errors / failed local assets
- No unexpected external requests in mock mode
- Catalog model options present
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Any

from playwright.sync_api import sync_playwright

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(APP_DIR)
BASE_URL = "http://127.0.0.1:8765"
PORT = 8765


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


def run_desktop(p: Any) -> dict:
    results: dict = {"passed": 0, "failed": 0, "errors": []}
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

    def _check(name, fn):
        try:
            assert fn()
            results["passed"] += 1
        except AssertionError:
            results["failed"] += 1
            results["errors"].append(name)

    page.goto(BASE_URL + "/workspace", wait_until="domcontentloaded")
    page.wait_for_timeout(600)

    _check("start prompt", lambda: page.locator("#start_prompt").count() > 0)
    _check("start model select", lambda: page.locator("#start_model").count() > 0)
    _check("start send button", lambda: page.locator("#start_send").count() > 0)
    _check("start optimize select", lambda: page.locator("#start_optimize_for").count() > 0)
    _check("start external fallback", lambda: page.locator("#start_external_fallback").count() > 0)
    _check("start route preview", lambda: page.locator("#start_route_preview").count() > 0)
    _check("start response body", lambda: page.locator("#start_response_body").count() > 0)
    _check("mock label visible", lambda: "모의 응답" in page.locator(".mode-badge").inner_text())
    _check("b14/auto option", lambda: page.locator('#start_model option[value="b14/auto"]').count() > 0)
    _check("catalog model option", lambda: page.locator('#start_model option[value="google/gemini-2.5-flash"]').count() > 0)
    _check("preset chips", lambda: page.locator(".preset-chip").count() >= 4)
    _check("start js loaded", lambda: page.evaluate("window.Business14Start !== undefined"))
    _check("legacy workspace preserved", lambda: page.locator("#ws_chat").count() > 0)

    # Mock chat via UI
    page.locator("#start_prompt").fill("한국어로 세 문장으로 설명해줘")
    page.locator("#start_send").click()
    page.wait_for_timeout(800)
    _check("mock response shown", lambda: "Mock" in page.locator("#start_response_body").inner_text() or "모의" in page.locator("#start_response_body").inner_text())
    _check("response mode badge", lambda: "모의 응답" in page.locator("#start_response_mode").inner_text())

    # Desktop overflow
    sw = page.evaluate("document.documentElement.scrollWidth")
    cw = page.evaluate("document.documentElement.clientWidth")
    results["desktop_scrollWidth"] = sw
    results["desktop_clientWidth"] = cw
    _check("no horizontal overflow", lambda: sw <= cw)

    _check("no console errors", lambda: len(console_errors) == 0)
    _check("no page errors", lambda: len(page_errors) == 0)
    results["desktop_console_errors"] = len(console_errors)
    results["desktop_page_errors"] = len(page_errors)
    results["desktop_failed_local"] = len(failed_local)
    _check("no failed local assets", lambda: len(failed_local) == 0)
    _check("no unexpected external requests", lambda: len(external) == 0)
    results["desktop_external_requests"] = external

    context.close()
    browser.close()
    return results


def run_mobile(p: Any) -> dict:
    results: dict = {"passed": 0, "failed": 0, "errors": []}
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

    def _check(name, fn):
        try:
            assert fn()
            results["passed"] += 1
        except AssertionError:
            results["failed"] += 1
            results["errors"].append(name)

    page.goto(BASE_URL + "/workspace", wait_until="domcontentloaded")
    page.wait_for_timeout(600)

    _check("start prompt mobile", lambda: page.locator("#start_prompt").count() > 0)
    _check("start send mobile", lambda: page.locator("#start_send").count() > 0)
    _check("mock label mobile", lambda: "모의 응답" in page.locator(".mode-badge").inner_text())

    # Mobile overflow check
    sw = page.evaluate("document.documentElement.scrollWidth")
    cw = page.evaluate("document.documentElement.clientWidth")
    results["mobile_scrollWidth"] = sw
    results["mobile_clientWidth"] = cw
    _check("no mobile horizontal overflow", lambda: sw <= cw)

    # Mock chat on mobile
    page.locator("#start_prompt").fill("안녕하세요")
    page.locator("#start_send").click()
    page.wait_for_timeout(800)
    _check("mobile mock response", lambda: len(page.locator("#start_response_body").inner_text()) > 0)

    _check("no mobile console errors", lambda: len(console_errors) == 0)
    _check("no mobile page errors", lambda: len(page_errors) == 0)
    results["mobile_console_errors"] = len(console_errors)
    results["mobile_page_errors"] = len(page_errors)
    results["mobile_failed_local"] = len(failed_local)
    _check("no mobile failed local", lambda: len(failed_local) == 0)
    _check("no mobile external requests", lambda: len(external) == 0)
    results["mobile_external_requests"] = external

    context.close()
    browser.close()
    return results


def main() -> int:
    proc = None
    try:
        proc = start_server()
        with sync_playwright() as p:
            desktop = run_desktop(p)
            mobile = run_mobile(p)

        print("=== BUSINESS 14 ALPHA BROWSER SELF-CHECK ===")
        print()
        print("--- DESKTOP 1440x1000 ---")
        print(f"Passed: {desktop['passed']}  Failed: {desktop['failed']}")
        print(f"Scroll width: {desktop.get('desktop_scrollWidth')}  Client: {desktop.get('desktop_clientWidth')}")
        print(f"Console errors: {desktop.get('desktop_console_errors')}")
        print(f"Page errors: {desktop.get('desktop_page_errors')}")
        print(f"Failed local assets: {desktop.get('desktop_failed_local')}")
        print(f"External requests: {len(desktop.get('desktop_external_requests', []))}")
        for e in desktop.get("errors", []):
            print(f"  FAIL: {e}")

        print()
        print("--- MOBILE 390x844 ---")
        print(f"Passed: {mobile['passed']}  Failed: {mobile['failed']}")
        print(f"Scroll width: {mobile.get('mobile_scrollWidth')}  Client: {mobile.get('mobile_clientWidth')}")
        print(f"Console errors: {mobile.get('mobile_console_errors')}")
        print(f"Page errors: {mobile.get('mobile_page_errors')}")
        print(f"Failed local assets: {mobile.get('mobile_failed_local')}")
        print(f"External requests: {len(mobile.get('mobile_external_requests', []))}")
        for e in mobile.get("errors", []):
            print(f"  FAIL: {e}")

        return 1 if (desktop["failed"] + mobile["failed"]) > 0 else 0
    finally:
        if proc:
            stop_server(proc)


if __name__ == "__main__":
    sys.exit(main())
