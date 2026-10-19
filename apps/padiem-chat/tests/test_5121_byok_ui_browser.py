"""#5121 PADIEM Custom customer UI in a real Chromium at PC and mobile sizes.

The real product-capabilities.js and mode-presentation.css run in Chromium. All
API calls are intercepted by Playwright: no PADIEM backend, B14, Engine or
provider is contacted, and no paid provider call is made.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
FAKE_KEY = "test-5121-synthetic-key-0123456789abcdef"
PROVIDER = "opencode-go"
MODEL = "opencode-go/beam-free"
DISPLAY_NAME = "Padiem Custom (OpenCode Go)"
DEFAULT_ENDPOINT = "https://opencode.ai/inference/go/v1"
MANUAL_PROVIDER = "qa-manual"
MANUAL_DISPLAY_NAME = "QA Manual Provider"
MANUAL_MODELS = ["qa-model-1", "qa-model-2"]
CUSTOM_ENDPOINT = "https://gateway.example.test/v1"

HARNESS = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>#5121 BYOK UI harness</title>
<style>
  :root {
    --line: #d9dee5;
    --text: #1c2530;
    --muted: #5b6672;
    --panel: rgba(255, 255, 255, .96);
    --accent: #79bce7;
    --accent-strong: #2f6f99;
  }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    font-family: sans-serif;
    color: var(--text);
  }
  .composer { padding: 16px; border-top: 1px solid var(--line); }
  .composer-tools { display: flex; gap: 8px; }
  .model-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-height: 40px;
    padding: 0 12px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #fff;
  }
</style>
</head>
<body>
  <main class="composer">
    <div class="composer-tools">
      <button type="button" class="model-pill">
        <span class="status-spark" aria-hidden="true">S</span>
        <span>Padiem Free</span>
      </button>
    </div>
  </main>
  <script src="./product-capabilities.js"></script>
</body>
</html>
"""


@pytest.fixture(scope="module")
def static_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/harness.html":
                body = HARNESS.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            else:
                relative = path.lstrip("/")
                target = (STATIC / relative).resolve()
                if not target.is_relative_to(STATIC) or not target.is_file():
                    self.send_error(404)
                    return
                body = target.read_bytes()
                content_type = (
                    "text/javascript; charset=utf-8" if target.suffix == ".js"
                    else "text/css; charset=utf-8" if target.suffix == ".css"
                    else "application/octet-stream"
                )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as exc:  # browser binary absent in a lean CI image
            pytest.skip(f"Chromium is unavailable: {exc}")
        yield instance
        instance.close()


def _provider_rows() -> list[dict]:
    return [
        {
            "provider": PROVIDER,
            "display_name": DISPLAY_NAME,
            "model": MODEL,
            "models": [MODEL],
            "default_endpoint": DEFAULT_ENDPOINT,
            "supports_custom_endpoint": True,
            "supports_model_listing": False,
            "supports_connection_test": False,
            "manual_model": False,
        },
        {
            "provider": MANUAL_PROVIDER,
            "display_name": MANUAL_DISPLAY_NAME,
            "model": "",
            "models": [],
            "default_endpoint": "https://qa-provider.example.test/v1",
            "supports_custom_endpoint": True,
            "supports_model_listing": True,
            "supports_connection_test": True,
            "manual_model": True,
        },
    ]


def _open_harness(browser, base_url: str, *, viewport: dict, auth_mode: str = "signed_in"):
    state = {
        "credentials": {},
        "put_bodies": [],
        "delete_urls": [],
        "credential_gets": 0,
        "model_gets": [],
        "test_gets": [],
        "request_urls": [],
    }
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    page.on("request", lambda request: state["request_urls"].append(request.url))

    def handle(route, request):
        path = urlsplit(request.url).path
        if path == "/health":
            route.fulfill(status=200, json={"web_tools_ready": True, "deep_research_ready": True})
            return
        if path == "/api/auth/status":
            if auth_mode == "expired":
                route.fulfill(status=200, json={
                    "ready": True,
                    "authenticated": False,
                    "session_state": "expired",
                    "user": None,
                    "member_grade": "free",
                    "history_ready": False,
                    "project_files_ready": False,
                })
            else:
                route.fulfill(status=200, json={
                    "ready": True,
                    "authenticated": True,
                    "session_state": "signed_in",
                    "user": {"name": "테스터"},
                    "member_grade": "free",
                    "history_ready": True,
                    "project_files_ready": False,
                })
            return
        if path == "/api/b66/admin/me":
            route.fulfill(status=200, json={"ok": True, "admin": False})
            return
        if path == "/api/chat/custom/credential":
            if request.method == "GET":
                state["credential_gets"] += 1
                credentials = [
                    {
                        "provider": provider,
                        "key_last4": row["last4"],
                        "endpoint": row.get("endpoint", ""),
                        "endpoint_is_default": not row.get("endpoint"),
                    }
                    for provider, row in state["credentials"].items()
                ]
                route.fulfill(status=200, json={
                    "ok": True,
                    "credentials": credentials,
                    "providers": _provider_rows(),
                })
                return
            if request.method == "PUT":
                body = request.post_data or ""
                state["put_bodies"].append(body)
                payload = json.loads(body)
                provider = str(payload.get("provider", ""))
                state["credentials"][provider] = {
                    "last4": str(payload.get("api_key", ""))[-4:],
                    "endpoint": str(payload.get("endpoint", "")),
                }
                route.fulfill(status=200, json={
                    "ok": True,
                    "credential": {
                        "provider": provider,
                        "key_last4": state["credentials"][provider]["last4"],
                        "endpoint": state["credentials"][provider]["endpoint"],
                        "endpoint_is_default": not state["credentials"][provider]["endpoint"],
                    },
                })
                return
            if request.method == "DELETE":
                state["delete_urls"].append(request.url)
                provider = urlsplit(request.url).query.removeprefix("provider=")
                state["credentials"].pop(provider, None)
                route.fulfill(status=200, json={"ok": True, "deleted": True})
                return
        if path == "/api/chat/custom/models":
            provider = urlsplit(request.url).query.removeprefix("provider=")
            state["model_gets"].append(provider)
            route.fulfill(status=200, json={
                "ok": True,
                "provider": provider,
                "models": MANUAL_MODELS,
                "source": "provider",
            })
            return
        if path == "/api/chat/custom/credential/test":
            provider = urlsplit(request.url).query.removeprefix("provider=")
            state["test_gets"].append(provider)
            route.fulfill(status=200, json={
                "ok": True,
                "provider": provider,
                "models_count": len(MANUAL_MODELS),
                "source": "provider",
            })
            return
        route.fulfill(status=404, json={"error": {"code": "not_found"}})

    page.route("**/api/**", handle)
    page.goto(base_url + "/harness.html", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelector('.model-pill')?.dataset.modeControl === 'true'"
    )
    return page, state, context


def _open_picker(page) -> None:
    page.locator(".model-pill").click()
    expect(page.locator(".mode-presentation-panel")).to_be_visible()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('.mode-custom-section')).borderTopWidth === '1px'"
    )


def _assert_panel_inside_viewport(page, width: int, height: int) -> None:
    box = page.locator(".mode-presentation-panel").bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["y"] >= 0
    assert box["x"] + box["width"] <= width + 0.5
    assert box["y"] + box["height"] <= height + 0.5


def _assert_no_key_leak(page, key: str) -> None:
    assert page.evaluate("needle => document.documentElement.outerHTML.includes(needle)", key) is False
    storage = page.evaluate(
        "() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })"
    )
    assert key not in storage


def test_desktop_custom_key_save_replace_delete_and_selection(browser, static_server) -> None:
    page, state, context = _open_harness(browser, static_server, viewport={"width": 1280, "height": 900})
    try:
        _open_picker(page)
        _assert_panel_inside_viewport(page, 1280, 900)
        expect(page.locator("[data-mode-title]")).to_have_text("모델 선택")
        expect(page.locator("#modeCustomTitle")).to_have_text("내 API 키")
        expect(page.locator(".mode-custom-heading")).not_to_contain_text("(Padiem Custom)")
        assert page.locator(
            ".mode-custom-heading .status-spark, .mode-custom-heading svg,"
            " .mode-custom-heading img, .mode-custom-heading [aria-hidden='true']"
        ).count() == 0
        expect(page.locator(".mode-option-model")).to_have_text("모델 " + MODEL)
        panel_text = page.locator(".mode-presentation-panel").inner_text()
        assert "업데이트 내역" not in panel_text
        assert "연결 테스트" not in panel_text

        custom_option = page.locator('[data-mode-value="custom"]')
        assert custom_option.is_enabled()
        assert DISPLAY_NAME in custom_option.inner_text()
        assert "Padiem Free" in page.locator('[data-mode-value="free"]').inner_text()

        # Selecting without a key keeps the card open and focuses the key field.
        custom_option.click()
        key_input = page.locator("#modeCustomApiKey")
        expect(key_input).to_be_visible()
        expect(key_input).to_be_focused()

        key_input.fill(FAKE_KEY)
        page.locator(".mode-custom-save").click()
        expect(page.locator(".mode-custom-message")).to_have_text("API 키를 저장했습니다.")
        expect(page.locator(".mode-custom-status")).to_contain_text("등록된 키: ••••" + FAKE_KEY[-4:])

        assert len(state["put_bodies"]) == 1
        assert json.loads(state["put_bodies"][0]) == {"provider": PROVIDER, "api_key": FAKE_KEY}
        assert key_input.input_value() == ""
        _assert_no_key_leak(page, FAKE_KEY)
        assert page.locator(".mode-custom-save").inner_text().strip() == "키 교체"
        expect(page.locator(".mode-custom-delete")).to_be_visible()

        # The saved custom provider/model is the selection the Chat request uses.
        custom_option.click()
        expect(page.locator(".mode-presentation-panel")).to_be_hidden()
        assert page.locator(".model-pill").inner_text().strip().endswith("Padiem Custom")
        assert page.locator(".model-pill").get_attribute("data-model-selection") == "custom"
        selection = page.evaluate("() => window.PadiemCustomSelection.get()")
        assert selection == {"provider": PROVIDER, "model": MODEL}

        # Delete uses the provider query parameter and no request body.
        page.locator(".model-pill").click()
        page.locator(".mode-custom-delete").click()
        expect(page.locator(".mode-custom-message")).to_have_text("API 키를 삭제했습니다.")
        assert len(state["delete_urls"]) == 1
        deleted = urlsplit(state["delete_urls"][0])
        assert deleted.path == "/api/chat/custom/credential"
        assert deleted.query == f"provider={PROVIDER}"
        expect(page.locator(".mode-custom-status")).to_have_text("등록된 키가 없습니다.")
        _assert_no_key_leak(page, FAKE_KEY)

        # Every request stayed on the local harness: no provider endpoint at all.
        assert all(url.startswith(static_server) for url in state["request_urls"])
        assert all(FAKE_KEY not in url for url in state["request_urls"])
    finally:
        context.close()


def test_multi_provider_manual_model_endpoint_model_list_and_connection_test(
    browser, static_server
) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 1280, "height": 900}
    )
    try:
        _open_picker(page)
        provider_select = page.locator("#modeCustomProvider")
        expect(provider_select).to_be_visible()
        expect(provider_select.locator("option")).to_have_count(2)
        assert provider_select.locator("option").nth(0).get_attribute("value") == PROVIDER
        assert provider_select.locator("option").nth(1).get_attribute("value") == MANUAL_PROVIDER

        # The original OpenCode Go lane keeps its registry model select.
        expect(page.locator("#modeCustomModelSelect")).to_be_visible()
        expect(page.locator("#modeCustomModelInput")).to_be_hidden()

        provider_select.select_option(MANUAL_PROVIDER)
        expect(page.locator("#modeCustomModelInput")).to_be_visible()
        expect(page.locator("#modeCustomModelSelect")).to_be_hidden()
        expect(page.locator("#modeCustomEndpoint")).to_be_visible()
        assert page.locator("#modeCustomEndpoint").get_attribute("placeholder") == (
            "https://qa-provider.example.test/v1"
        )

        # A typed model is required before the custom lane can be selected.
        page.locator('[data-mode-value="custom"]').click()
        expect(page.locator(".mode-custom-message")).to_contain_text("모델 ID를 먼저")
        assert page.evaluate("() => window.PadiemCustomSelection.get()") is None

        model_input = page.locator("#modeCustomModelInput")
        model_input.fill(MANUAL_MODELS[0])
        page.locator("#modeCustomEndpoint").fill(CUSTOM_ENDPOINT)
        page.locator("#modeCustomApiKey").fill(FAKE_KEY)
        page.locator(".mode-custom-save").click()
        expect(page.locator(".mode-custom-message")).to_have_text("API 키를 저장했습니다.")

        saved = json.loads(state["put_bodies"][-1])
        assert saved == {
            "provider": MANUAL_PROVIDER,
            "api_key": FAKE_KEY,
            "endpoint": CUSTOM_ENDPOINT,
        }
        expect(page.locator(".mode-custom-status")).to_contain_text(CUSTOM_ENDPOINT)
        _assert_no_key_leak(page, FAKE_KEY)

        # The model list and the connection test are real server calls made
        # only after a key exists. No provider origin is contacted by the page.
        load_models = page.locator(".mode-custom-model-load")
        expect(load_models).to_be_visible()
        load_models.click()
        expect(page.locator(".mode-custom-message")).to_have_text(
            "공급사 모델 목록을 불러왔습니다."
        )
        assert state["model_gets"] == [MANUAL_PROVIDER]
        datalist = page.locator("#modeCustomModelOptions option")
        expect(datalist).to_have_count(len(MANUAL_MODELS))
        assert page.locator("#modeCustomModelInput").get_attribute("list") == (
            "modeCustomModelOptions"
        )

        test_button = page.locator(".mode-custom-test")
        expect(test_button).to_be_visible()
        test_button.click()
        expect(page.locator(".mode-custom-message")).to_have_text(
            "공급사 연결을 확인했습니다."
        )
        assert state["test_gets"] == [MANUAL_PROVIDER]

        page.locator('[data-mode-value="custom"]').click()
        expect(page.locator(".mode-presentation-panel")).to_be_hidden()
        selection = page.evaluate("() => window.PadiemCustomSelection.get()")
        assert selection == {"provider": MANUAL_PROVIDER, "model": MANUAL_MODELS[0]}
        assert page.locator(".model-pill").get_attribute("data-model-selection") == "custom"

        assert all(url.startswith(static_server) for url in state["request_urls"])
        assert all(FAKE_KEY not in url for url in state["request_urls"])
    finally:
        context.close()


def test_mobile_custom_key_form_fits_and_stays_touch_sized(browser, static_server) -> None:
    page, state, context = _open_harness(browser, static_server, viewport={"width": 390, "height": 844})
    try:
        _open_picker(page)
        _assert_panel_inside_viewport(page, 390, 844)

        page.locator('[data-mode-value="custom"]').click()
        key_input = page.locator("#modeCustomApiKey")
        expect(key_input).to_be_focused()

        box = page.locator(".mode-presentation-panel").bounding_box()
        assert box is not None
        assert box["width"] <= 390
        save_box = page.locator(".mode-custom-save").bounding_box()
        assert save_box is not None and save_box["height"] >= 44
        assert key_input.bounding_box()["height"] >= 44

        key_input.fill(FAKE_KEY)
        page.locator(".mode-custom-save").click()
        expect(page.locator(".mode-custom-message")).to_have_text("API 키를 저장했습니다.")
        assert key_input.input_value() == ""
        _assert_no_key_leak(page, FAKE_KEY)
        _assert_panel_inside_viewport(page, 390, 844)
    finally:
        context.close()


def test_mobile_picker_scrolls_internally_to_reach_the_key_actions(
    browser, static_server
) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 390, "height": 560}
    )
    try:
        _open_picker(page)
        page.locator('[data-mode-value="custom"]').click()
        expect(page.locator("#modeCustomApiKey")).to_be_focused()

        metrics = page.evaluate(
            """() => {
              const panel = document.querySelector('.mode-presentation-panel');
              const style = getComputedStyle(panel);
              return {
                scrollHeight: panel.scrollHeight,
                clientHeight: panel.clientHeight,
                overflowY: style.overflowY,
                overscroll: style.overscrollBehavior,
                pageY: window.scrollY,
              };
            }"""
        )
        assert metrics["overflowY"] == "auto"
        assert metrics["overscroll"] == "contain"
        assert metrics["scrollHeight"] > metrics["clientHeight"]
        assert metrics["pageY"] == 0

        page.evaluate(
            "() => { const panel = document.querySelector('.mode-presentation-panel'); panel.scrollTop = panel.scrollHeight; }"
        )
        assert page.evaluate(
            "() => document.querySelector('.mode-presentation-panel').scrollTop"
        ) > 0
        assert page.evaluate("() => window.scrollY") == 0

        save = page.locator(".mode-custom-save")
        save.scroll_into_view_if_needed()
        expect(save).to_be_visible()
        panel_box = page.locator(".mode-presentation-panel").bounding_box()
        save_box = save.bounding_box()
        assert panel_box is not None and save_box is not None
        assert save_box["y"] >= panel_box["y"] - 0.5
        assert save_box["y"] + save_box["height"] <= panel_box["y"] + panel_box["height"] + 0.5
        _assert_panel_inside_viewport(page, 390, 560)
        _assert_no_key_leak(page, FAKE_KEY)
    finally:
        context.close()


def test_dark_mode_keeps_the_picker_and_key_form_readable(browser, static_server) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 1280, "height": 900}
    )
    try:
        page.evaluate(
            """() => {
              document.documentElement.dataset.theme = 'dark';
              document.documentElement.style.setProperty('--text', '#eef2f7');
              document.documentElement.style.setProperty('--muted', '#a9b4c0');
            }"""
        )
        _open_picker(page)
        background = page.evaluate(
            "() => getComputedStyle(document.querySelector('.mode-presentation-panel')).backgroundColor"
        )
        assert "14, 18, 26" in background
        expect(page.locator("#modeCustomTitle")).to_be_visible()
        page.locator('[data-mode-value="custom"]').click()
        expect(page.locator("#modeCustomApiKey")).to_be_focused()
        expect(page.locator(".mode-custom-save")).to_be_visible()
    finally:
        context.close()


def test_expired_session_shows_the_login_state_without_opening_the_key_form(
    browser, static_server
) -> None:
    page, state, context = _open_harness(
        browser, static_server, viewport={"width": 1280, "height": 900}, auth_mode="expired"
    )
    try:
        _open_picker(page)
        custom_option = page.locator('[data-mode-value="custom"]')
        expect(custom_option).to_be_disabled()
        assert "세션 만료" in custom_option.inner_text()
        guest_note = page.locator(".mode-custom-guest-note")
        expect(guest_note).to_be_visible()
        expect(guest_note).to_contain_text("로그인이 만료되었습니다")
        expect(page.locator(".mode-custom-credential")).to_be_hidden()
        assert state["credential_gets"] == 0
    finally:
        context.close()
