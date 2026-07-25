#!/usr/bin/env python3
"""Phase 3 Desktop + Mobile browser smoke for Korean AI Platform workspace."""

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


def _registry_json() -> str:
    return json.dumps([
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example",
            "timeout_seconds": 30,
            "models": [
                {
                    "model_id": "model-a-v1",
                    "upstream_model": "upstream-a",
                    "display_name": "Model A",
                    "enabled": True,
                }
            ],
        },
        {
            "provider_id": "provider-b",
            "display_name": "Provider B",
            "base_url": "https://api.provider-b.example",
            "timeout_seconds": 15,
            "models": [
                {
                    "model_id": "model-b-v1",
                    "upstream_model": "upstream-b",
                    "display_name": "Model B",
                    "enabled": True,
                }
            ],
        },
    ])


def start_server() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["BUSINESS14_PROVIDER_REGISTRY_JSON"] = _registry_json()
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
            urllib.request.urlopen(f"{BASE_URL}/", timeout=1)
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


def _stub_clipboard(page: Any) -> None:
    page.add_init_script("""
      if (!navigator.clipboard) {
        navigator.clipboard = { writeText: function() {} };
      }
      window.__clipboardTexts = [];
      const original = navigator.clipboard.writeText.bind(navigator.clipboard);
      navigator.clipboard.writeText = function(text) {
        window.__clipboardTexts.push(text);
        return Promise.resolve();
      };
    """)


def run_desktop(p: Any) -> dict[str, Any]:
    results: dict[str, Any] = {"passed": 0, "failed": 0, "errors": []}
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(f"{msg.type}:{msg.text}") if msg.type == "error" else None)

    failed_local: list[str] = []
    page.on("response", lambda resp: failed_local.append(resp.url) if resp.status >= 400 and resp.url.startswith(BASE_URL) else None)

    captured: list[dict[str, Any]] = []

    def route_handler(route: Any) -> None:
        req = route.request
        headers = req.headers
        body = {}
        if req.post_data:
            try:
                body = json.loads(req.post_data)
            except json.JSONDecodeError:
                body = {"raw": req.post_data}
        captured.append({"url": req.url, "headers": dict(headers), "body": body, "provider_key_header": headers.get("x-business14-provider-key")})
        idx = len(captured)
        if idx <= 2:
            resp = {
                "id": f"cmpl-d{idx}", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": f"데스크톱 응답 {idx}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "business14": {"provider": "provider-a", "model_route": "model-a-v1", "request_id": f"b14req_d{idx}", "latency_ms": 100, "estimated_krw": None},
            }
            route.fulfill(json=resp)
            return
        if idx == 3:
            route.fulfill(status=401, json={"error": {"code": "invalid_api_key", "message": "Invalid API key"}})
            return
        resp = {
            "id": f"cmpl-d{idx}", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "재전송 성공"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
            "business14": {"provider": "provider-b", "model_route": "model-b-v1", "request_id": f"b14req_d{idx}", "latency_ms": 90, "estimated_krw": None},
        }
        route.fulfill(json=resp)

    page.route("**/api/pilot/v1/chat/completions", route_handler)
    _stub_clipboard(page)

    # 1
    page.goto(BASE_URL + "/workspace", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    results["passed"] += 1

    # 2
    errs = [e for e in console_errors]
    results["console_errors_desktop"] = len(errs)
    assert len(errs) == 0, f"Console errors: {errs}"
    results["passed"] += 1

    # 3
    assert page.locator("#ws_chat").count() > 0
    results["passed"] += 1

    # 4
    page.locator("#ws_key").fill("my-test-key")
    results["passed"] += 1

    # 5
    page.locator("#ws_key_apply").click()
    results["passed"] += 1

    # 6
    assert page.locator("#ws_key").input_value() == ""
    results["passed"] += 1

    # 7
    page.locator("#ws_input").fill("첫 번째 질문")
    page.locator("#ws_send").click()
    page.wait_for_timeout(500)
    assert any("데스크톱 응답" in m.inner_text() for m in page.locator(".ws-msg").all())
    results["passed"] += 1

    # 8
    page.locator("#ws_input").fill("두 번째 질문")
    page.locator("#ws_send").click()
    page.wait_for_timeout(500)
    body2 = captured[1]["body"]
    messages2 = body2.get("messages", [])
    assert any(m.get("role") == "user" and m.get("content") == "첫 번째 질문" for m in messages2)
    results["passed"] += 1

    # 9
    page.locator("#ws_key").fill("bad-key")
    page.locator("#ws_key_apply").click()
    page.locator("#ws_input").fill("401 테스트")
    page.locator("#ws_send").click()
    page.wait_for_timeout(500)
    assert page.locator("#ws_send").is_enabled()
    results["passed"] += 1

    # 10
    page.locator("#ws_key").fill("good-key")
    page.locator("#ws_key_apply").click()
    page.locator("#ws_input").fill("재전송")
    page.locator("#ws_send").click()
    page.wait_for_timeout(500)
    assert any("재전송 성공" in m.inner_text() for m in page.locator(".ws-msg").all())
    results["passed"] += 1

    # 11
    page.select_option("#ws_model", "model-b-v1")
    page.wait_for_timeout(500)
    results["passed"] += 1

    # 12
    assert page.evaluate("window.Business14Workspace.state.apiKey === null")
    results["passed"] += 1

    # 13
    assert page.evaluate("window.Business14Workspace.state.messages.length === 0")
    results["passed"] += 1

    # 14
    page.locator("#ws_key").fill("provider-b-key")
    page.locator("#ws_key_apply").click()
    page.locator("#ws_input").fill("B 요청")
    page.locator("#ws_send").click()
    page.wait_for_timeout(500)
    b_reqs = [c for c in captured if c.get("body", {}).get("model") == "model-b-v1"]
    assert len(b_reqs) > 0
    results["passed"] += 1

    # 15
    assert not any(m.get("content") == "첫 번째 질문" for m in b_reqs[0]["body"].get("messages", []))
    results["passed"] += 1

    # 16
    page.locator("#ws_new_chat").click()
    assert page.locator("#ws_empty").count() > 0 and page.locator("#ws_empty").is_visible()
    results["passed"] += 1

    # 17
    page.locator("#ws_clear_chat").click()
    assert page.locator("#ws_empty").count() > 0 and page.locator("#ws_empty").is_visible()
    results["passed"] += 1

    # 18
    page.locator(".lang-switch-en").click()
    assert page.locator("html[lang=en]").count() > 0
    results["passed"] += 1

    # 19
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(300)
    assert page.locator("html[lang=en]").count() > 0
    results["passed"] += 1

    # 20
    page.locator(".lang-switch-ko").click()
    assert page.locator("html[lang=ko]").count() > 0
    results["passed"] += 1

    # 21
    page.locator("#ws_input").fill("<script>alert('xss')</script>")
    page.locator("#ws_send").click()
    page.wait_for_timeout(300)
    assert "<script>alert('xss')</script>" not in page.locator("#ws_chat").inner_text()
    results["passed"] += 1

    # 22
    failed_count = len([u for u in failed_local if u.startswith(BASE_URL) and "/api/pilot/v1/chat/completions" not in u])
    results["failed_requests_desktop"] = failed_count
    assert failed_count == 0, f"Failed local assets: {failed_count}"
    results["passed"] += 1

    # Docs copy regression
    page.goto(BASE_URL + "/docs", wait_until="domcontentloaded")
    page.wait_for_timeout(300)
    if page.locator(".copy-btn").count() > 0:
        page.locator(".copy-btn").first.click()
        page.wait_for_timeout(300)
        clips = page.evaluate("window.__clipboardTexts")
        assert len(clips) > 0
        assert "cURL" in clips[0] or "curl" in clips[0]
        assert page.locator(".copy-btn").first.inner_text() == "복사됨!"
        results["copy_passed"] = True
        results["passed"] += 1
    else:
        results["copy_passed"] = False
        results["errors"].append("No copy button found on /docs")

    context.close()
    browser.close()
    return results


def run_mobile(p: Any) -> dict[str, Any]:
    results: dict[str, Any] = {"passed": 0, "failed": 0, "errors": []}
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()

    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(f"{msg.type}:{msg.text}") if msg.type == "error" else None)

    failed_local: list[str] = []
    page.on("response", lambda resp: failed_local.append(resp.url) if resp.status >= 400 and resp.url.startswith(BASE_URL) else None)

    page.route("**/api/pilot/v1/chat/completions", lambda route: route.fulfill(json={
        "id": "cmpl-m", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "모바일 응답"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        "business14": {"provider": "provider-a", "model_route": "model-a-v1", "request_id": "b14req_m", "latency_ms": 100, "estimated_krw": None},
    }))

    page.add_init_script("""
      window.__clipboardTexts = [];
      navigator.clipboard.writeText = function(text) {
        window.__clipboardTexts.push(text);
        return Promise.resolve();
      };
    """)

    page.goto(BASE_URL + "/workspace", wait_until="domcontentloaded")
    page.wait_for_timeout(500)

    sw = page.evaluate("document.documentElement.scrollWidth")
    cw = page.evaluate("document.documentElement.clientWidth")
    results["scrollWidth"] = sw
    results["clientWidth"] = cw
    if sw == cw:
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["errors"].append(f"Horizontal overflow: scrollWidth={sw} clientWidth={cw}")

    checks = [
        ("sidebar", lambda: page.locator(".sidebar").count() > 0),
        ("sidebar-nav", lambda: page.locator(".sidebar-nav .nav-link").count() > 0),
        ("lang switch", lambda: page.locator(".lang-switch").count() > 0),
        ("model select", lambda: page.locator("#ws_model").count() > 0),
        ("api key input", lambda: page.locator("#ws_key").count() > 0),
        ("apply button", lambda: page.locator("#ws_key_apply").count() > 0),
        ("message input", lambda: page.locator("#ws_input").count() > 0),
        ("send button", lambda: page.locator("#ws_send").count() > 0),
        ("new chat", lambda: page.locator("#ws_new_chat").count() > 0),
        ("clear chat", lambda: page.locator("#ws_clear_chat").count() > 0),
        ("key clear", lambda: page.locator("#ws_key_clear").count() > 0),
    ]
    for name, fn in checks:
        try:
            assert fn()
            results["passed"] += 1
        except AssertionError as e:
            results["failed"] += 1
            results["errors"].append(name)

    # API key char input + apply
    page.locator("#ws_key").fill("m-key")
    page.locator("#ws_key_apply").click()
    page.wait_for_timeout(200)
    assert page.locator("#ws_key").input_value() == ""
    results["passed"] += 1

    # message input + send
    page.locator("#ws_input").fill("모바일 메시지")
    page.locator("#ws_send").click()
    page.wait_for_timeout(400)
    assert any("모바일 응답" in m.inner_text() for m in page.locator(".ws-msg").all())
    results["passed"] += 1

    # new chat + empty state
    page.locator("#ws_new_chat").click()
    assert page.locator("#ws_empty").count() > 0 and page.locator("#ws_empty").is_visible()
    results["passed"] += 1

    # clear chat + empty state
    page.locator("#ws_clear_chat").click()
    assert page.locator("#ws_empty").count() > 0 and page.locator("#ws_empty").is_visible()
    results["passed"] += 1

    # key clear
    page.locator("#ws_key").fill("x")
    page.locator("#ws_key_apply").click()
    page.locator("#ws_key_clear").click()
    assert page.locator("#ws_key").input_value() == ""
    results["passed"] += 1

    # Korean long text no clipping
    long_text = "한국어 긴 문구 테스트입니다. 이 문구가 화면을 벗어나지 않고 정상적으로 보여져야 하며, 가로 스크롤이 발생해서는 안 됩니다."
    page.locator("#ws_input").fill(long_text)
    page.locator("#ws_send").click()
    page.wait_for_timeout(300)
    chat_scroll = page.evaluate("document.getElementById('ws_chat').scrollWidth")
    chat_client = page.evaluate("document.getElementById('ws_chat').clientWidth")
    results["chat_scrollWidth"] = chat_scroll
    results["chat_clientWidth"] = chat_client
    if chat_scroll <= chat_client + 1:
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["errors"].append("Korean text chat area horizontal overflow")

    errs = [e for e in console_errors]
    results["console_errors_mobile"] = len(errs)
    assert len(errs) == 0, f"Mobile console errors: {errs}"
    results["passed"] += 1

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

        print("=== DESKTOP 1440x900 ===")
        print(f"Passed scenarios: {desktop['passed']}")
        print(f"Console errors: {desktop.get('console_errors_desktop', 'N/A')}")
        print(f"Failed local assets: {desktop.get('failed_requests_desktop', 'N/A')}")
        print(f"Copy regression passed: {desktop.get('copy_passed', 'N/A')}")

        print("\n=== MOBILE 390x844 ===")
        print(f"Passed scenarios: {mobile['passed']}")
        print(f"No horizontal scroll: {mobile.get('scrollWidth')} === {mobile.get('clientWidth')}")
        print(f"Console errors: {mobile.get('console_errors_mobile', 'N/A')}")
        print(f"Chat no overflow: {mobile.get('chat_scrollWidth')} <= {mobile.get('chat_clientWidth')}")

        if desktop.get("errors"):
            for e in desktop["errors"]:
                print(f"  DESKTOP FAIL: {e}")
        if mobile.get("errors"):
            for e in mobile["errors"]:
                print(f"  MOBILE FAIL: {e}")

        return 1 if (desktop["failed"] + mobile["failed"]) > 0 else 0
    finally:
        if proc:
            stop_server(proc)


if __name__ == "__main__":
    sys.exit(main())
