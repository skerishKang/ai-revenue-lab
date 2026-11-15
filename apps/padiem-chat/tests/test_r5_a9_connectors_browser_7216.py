"""#7216 R5 A9 (connectors) — 실제 Chromium에서 커넥터 화면 클릭 전환 회귀.

index.html을 통째로 로드해(chat-connectors-module.js 로드 순서 포함) 앱 부팅을
그대로 재현한 뒤, #connectorsNavButton 클릭 한 번으로 독립 커넥터 화면으로
전환되는지 검증한다. 모든 /api 는 결정적 스텁(운영 접근 없음, 로그인 없음):

- 첫 클릭: shell 상태 전환, 뷰 노출, 카드 상태 산출(스텁 projection), 상태
  읽기 1회(전송 헬퍼 경유), 내비 aria, 콘솔/페이지 오류 0건.
- 다시 클릭: 그리드가 중복 마운트되지 않고(마운트 가드), 상태 읽기만 한 번 더
  행해진다(열 때마다 최신 상태를 읽는 것이 제품 계약).
- 390 폭: 접힌 사이드바 안의 같은 버튼 요소로 동일 리스너 경로를 진다.
"""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

STATIC = Path(__file__).resolve().parents[1] / "static"

API_401_BODY = {"ok": False, "error": {"code": "unauthorized", "message": "boot stub"}}
AUTH_STATUS_GUEST_BODY = {
    "ready": True,
    "authenticated": False,
    "history_ready": True,
    "user": None,
    "model_requires_session": True,
    "session_state": "guest",
    "methods": {"google": False, "password": True},
}
# test_b54의 statusDocument와 같은 서버 소유 projection(5개 검토 커넥터).
CONNECTORS_STATUS_BODY = {
    "static_support_vs_workspace_state_separated": True,
    "send_write_authorized": False,
    "connectors": [
        {"connector_id": "connector:google:drive@1", "read_availability": "complete", "workspace_state": "not_connected"},
        {"connector_id": "connector:google:gmail@1", "read_availability": "complete", "workspace_state": "not_connected"},
        {"connector_id": "connector:telegram:bot@1", "read_availability": "deferred", "workspace_state": "unverified"},
        {"connector_id": "connector:slack:workspace@1", "read_availability": "deferred", "workspace_state": "unverified"},
        {"connector_id": "connector:google:calendar@1", "read_availability": "complete", "workspace_state": "connected"},
    ],
}
EXPECTED_CARDS = {
    "google-drive": "not_connected",
    "gmail": "not_connected",
    "telegram": "unverified",
    "slack": "unverified",
}
EXPECTED_SUPPORT_KEYS = {
    "google-drive": "connectors-support-complete",
    "gmail": "connectors-support-complete",
    "telegram": "connectors-support-deferred",
    "slack": "connectors-support-deferred",
    "google-calendar": "connectors-support-complete",
}


def test_connectors_nav_click_transitions_to_the_standalone_view(tmp_path) -> None:
    seen_api: list[str] = []

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(STATIC)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    console_errors: list[str] = []
    page_errors: list[str] = []

    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                page.on("pageerror", lambda err: page_errors.append(str(err)))

                def route(route) -> None:
                    req = route.request
                    path = req.url.split("?", 1)[0].split(f":{server.server_port}", 1)[-1] or "/"
                    if req.url != base + "/" and not req.url.startswith(base + "/") and req.url.startswith("http"):
                        route.abort()
                        return
                    if path == "/favicon.ico":
                        route.fulfill(status=204)
                        return
                    if path == "/api/auth/status":
                        route.fulfill(json=AUTH_STATUS_GUEST_BODY)
                        return
                    if path == "/api/connectors/status":
                        seen_api.append(path)
                        route.fulfill(json=CONNECTORS_STATUS_BODY)
                        return
                    if path.startswith("/api/"):
                        route.fulfill(status=401, json=API_401_BODY)
                        return
                    route.continue_()

                page.route("**/*", route)
                page.goto(f"{base}/index.html", wait_until="load")
                page.wait_for_selector("#connectorsNavButton", state="visible", timeout=15000)
                page.wait_for_timeout(600)

                before = page.evaluate(
                    """() => ({
                      state: document.querySelector('.app-shell').dataset.state || '',
                      viewHidden: document.getElementById('connectorsView').hidden,
                    })"""
                )
                assert before["state"] != "connectors", before
                assert before["viewHidden"] is True, before
                assert seen_api == [], seen_api

                page.click("#connectorsNavButton")
                page.wait_for_timeout(900)

                after = page.evaluate(
                    """() => {
                      const view = document.getElementById('connectorsView');
                      const grid = view.querySelectorAll('.capability-grid').length;
                      const cards = [...view.querySelectorAll('[data-connector-id]')].map((card) => ({
                        slug: card.dataset.connector,
                        status: card.dataset.connectorStatus || '',
                        supportKey: card.querySelector('[data-connector-support]')?.dataset.localeKey || '',
                        workspaceKey: card.querySelector('[data-connector-workspace]')?.dataset.localeKey || '',
                      }));
                      return {
                        state: document.querySelector('.app-shell').dataset.state || '',
                        viewHidden: view.hidden,
                        grids: grid,
                        navExpanded: document.getElementById('connectorsNavButton').getAttribute('aria-expanded'),
                        cards,
                      };
                    }"""
                )
                assert after["state"] == "connectors", after
                assert after["viewHidden"] is False, after
                assert after["grids"] == 1, after
                assert after["navExpanded"] == "false", after
                statuses = {card["slug"]: card["status"] for card in after["cards"]}
                for slug, expected in EXPECTED_CARDS.items():
                    assert statuses.get(slug) == expected, (slug, after)
                assert statuses.get("google-calendar") == "connected", after
                support_keys = {card["slug"]: card["supportKey"] for card in after["cards"]}
                for slug, expected in EXPECTED_SUPPORT_KEYS.items():
                    assert support_keys.get(slug) == expected, (slug, after)
                calendar_workspace = next(
                    card["workspaceKey"] for card in after["cards"] if card["slug"] == "google-calendar"
                )
                # Calendar는 workspace가 connected일 때 OAuth 전용 문구를 쓴다
                # (일반 커넥터 문구와 축을 구분하는 제품 계약).
                assert calendar_workspace == "connectors-calendar-oauth-connected", after
                assert seen_api == ["/api/connectors/status"], seen_api

                # 다시 클릭: 마운트 가드(그리드 1개 유지) + 열 때마다 상태 1회 재판정.
                page.click("#connectorsNavButton")
                page.wait_for_timeout(900)
                repeat = page.evaluate(
                    """() => ({
                      state: document.querySelector('.app-shell').dataset.state || '',
                      grids: document.getElementById('connectorsView').querySelectorAll('.capability-grid').length,
                    })"""
                )
                assert repeat["state"] == "connectors", repeat
                assert repeat["grids"] == 1, repeat
                assert seen_api == ["/api/connectors/status", "/api/connectors/status"], seen_api

                # 390 폭: 접힌 사이드바 안의 같은 버튼 요소로 동일 리스너 경로를
                # 직접 진다(클릭 적중이 아니라 리스너 계약이 대상).
                page.set_viewport_size({"width": 390, "height": 844})
                page.evaluate("() => document.getElementById('connectorsNavButton').click()")
                page.wait_for_timeout(900)
                mobile = page.evaluate(
                    """() => ({
                      state: document.querySelector('.app-shell').dataset.state || '',
                      viewHidden: document.getElementById('connectorsView').hidden,
                    })"""
                )
                assert mobile["state"] == "connectors", mobile
                assert mobile["viewHidden"] is False, mobile
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    # 스텁 환경의 부산물(의도적 401·외부 리소스 차단·정적 자산 404)은 브라우저가
    # 콘솔에 기록한다. 회귀 대상은 앱 로직 오류이므로 리소스 로드 노이즈는
    # 제외하고, 나머지 콘솔 오류와 페이지 오류(미처리 예외)는 0건이어야 한다.
    app_console_errors = [
        text for text in console_errors
        if not text.startswith("Failed to load resource")
    ]
    assert app_console_errors == [], app_console_errors
    assert page_errors == [], page_errors
