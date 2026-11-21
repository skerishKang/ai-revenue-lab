"""#8211 + #7962 — 연결 화면 입구·PC별 도우미 상태·만료 전환의 실행 시험.

문자열을 비교하지 않고 실제 페이지에서 일어나는 일을 관찰한다:
  * 첫 화면 '내 컴퓨터' 카드를 누르면 연결 화면(#padiem-connectors)의 PC 카드
    (상세)가 열리고 주소도 따라간다;
  * 이미 열린 탭에서 주소 해시가 바뀌면 화면이 따라가고(재적재 없음),
    1440·390 두 폭에서 같다;
  * 연결된 PC별 도우미 상태(정상 / 도우미 없음 / 옛 버전)가 행 배지로 보이고,
    도우미가 없는 행의 단추가 같은 원클릭 설치 모달을 연다;
  * 설치 파일의 남은 시간이 0이 되면 판이 '만료 · 다시 받기'로 바뀌고
    '확인 중'에 머무르지 않는다(#7962 — 카드와 모달 두 표면).
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

SIGNED_STATUS = {
    "ready": True, "authenticated": True,
    "user": {"email": "qa@padiem.local", "name": "QA"},
    "session_state": "active", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": True, "project_files_ready": True,
    "model_requires_session": False,
}


def _links():
    """정상 / 도우미 없음 / 옛 버전 한 대씩 — 서버가 내려 주는 모양 그대로."""
    return [
        {"link_id": "link_ready", "label": "PC-A", "state": "active", "online": True,
         "command_ready": "ready", "command_ready_reason": None,
         "helper_state": "current", "mesh_node_id": "mesh_ready"},
        {"link_id": "link_missing", "label": "PC-B", "state": "active", "online": True,
         "command_ready": "not_ready", "command_ready_reason": "helper_missing",
         "helper_state": "missing", "mesh_node_id": "mesh_missing"},
        {"link_id": "link_outdated", "label": "PC-C", "state": "active", "online": True,
         "command_ready": "not_ready", "command_ready_reason": "helper_stopped",
         "helper_state": "outdated", "mesh_node_id": "mesh_outdated"},
    ]


def _fetch_stub():
    return """
(() => {
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const JSON_HEADERS = { 'content-type': 'application/json' };
  const answer = (body, status) => Promise.resolve(new Response(JSON.stringify(body), {
    status: status, statusText: 'OK', headers: JSON_HEADERS,
  }));
  const offline = () => Promise.resolve(new Response('{"ok":false}', {
    status: 404, statusText: 'Not Found', headers: JSON_HEADERS,
  }));
  const AUTH = __AUTH__;
  const LINKS = __LINKS__;
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return realFetch ? realFetch(input, init) : offline();
    if (url.includes('/api/auth/status')) return answer(AUTH, 200);
    if (url.includes('/api/pc/pairings/install-exe')) {
      const expires = new Date(Date.now() + 1200).toISOString();
      return Promise.resolve(new Response(new Uint8Array([80, 65]), {
        status: 200, statusText: 'OK',
        headers: { 'content-type': 'application/octet-stream',
                   'x-pc-pairing-code-id': 'code_test_0000000000000000000000',
                   'x-pc-pairing-expires-at': expires },
      }));
    }
    if (url.includes('/api/pc/pairings')) {
      return answer({ ok: true, links: LINKS, codes: [], admin: false }, 200);
    }
    return offline();
  };
})();
""".replace("__AUTH__", json.dumps(SIGNED_STATUS)).replace("__LINKS__", json.dumps(_links()))


@pytest.fixture(scope="module")
def site():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _page(playwright, url, theme="padiem-glass", width=1440, height=950):
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": width, "height": height},
                            reduced_motion="reduce")
    page.route("**/*", lambda route_obj: route_obj.continue_()
               if "127.0.0.1" in route_obj.request.url else route_obj.abort())
    page.add_init_script(_fetch_stub())
    page.goto(f"{url}?theme={theme}", wait_until="load")
    page.wait_for_timeout(2200)
    return browser, page


VIEW_VISIBLE = "() => document.getElementById('connectorsView')?.hidden === false"


@pytest.mark.parametrize("width,height", [(1440, 950), (390, 844)])
def test_the_computer_card_opens_the_connection_screen_and_its_pc_card(site, width, height):
    """'내 컴퓨터' 카드 → 연결 화면의 PC 카드(상세) + 주소 따라가기."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site, width=width, height=height)
        try:
            page.click("#pcConnectStarter")
            page.wait_for_function(VIEW_VISIBLE, timeout=4000)
            assert page.evaluate(
                "document.querySelector('.app-shell').dataset.state") == "connectors"
            assert page.evaluate("window.PadiemConnectorPages.current()") == "computer"
            assert page.evaluate("window.location.hash") == "#connectors/computer"
        finally:
            browser.close()


def test_the_hash_change_opens_the_screen_without_a_reload(site):
    """이미 열린 탭에서 해시가 바뀌면 화면이 따라간다 — 재적재 없이."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.evaluate("window.__same_document = 42")
            assert page.evaluate(
                "document.getElementById('connectorsView').hidden") is True
            page.evaluate("window.location.hash = '#padiem-connectors'")
            page.wait_for_function(VIEW_VISIBLE, timeout=4000)
            assert page.evaluate("window.__same_document") == 42
        finally:
            browser.close()


def test_helper_state_badges_and_the_reinstall_button(site):
    """PC별 도우미 상태 배지(정상은 기존 문구 유지, 도우미 없음·옛 버전 표시)와
    도우미 없는 행의 단추가 같은 원클릭 설치 모달을 연다. 행 배지는 PC 카드
    상세 페이지(타일의 한 줄이 아닌)에서 관찰한다."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.evaluate("window.location.hash = '#padiem-connectors'")
            page.wait_for_function(VIEW_VISIBLE, timeout=4000)
            page.evaluate("window.PadiemConnectorPages.open('computer')")
            page.wait_for_selector(".connector-detail-body .pc-pairing-link "
                                   ".pc-pairing-state[data-state]", timeout=6000)
            badges = page.evaluate(
                """() => [...document.querySelectorAll(
                      '.pc-pairing-link .pc-pairing-state')].map(b => b.textContent)""")
            assert len(badges) == 3, badges
            # 정상(PC-A): 연결됨 · 명령 가능 / 도우미 없음(PC-B) / 옛 버전(PC-C).
            assert any("명령 가능" in b for b in badges), badges
            assert any(b == "도우미 없음" for b in badges), badges
            assert any(b == "옛 버전" for b in badges), badges
            # 도우미 없는 행의 단추: 같은 원클릭 설치 모달을 연다.
            page.click(".pc-helper-reinstall")
            page.wait_for_selector(".pc-connect-modal:not([hidden])", timeout=4000)
            assert page.evaluate(
                "document.querySelector('.pc-connect-modal').hidden") is False
        finally:
            browser.close()


def test_the_first_screen_modal_flips_to_expired_instead_of_waiting(site):
    """모달(같은 원클릭 설치): 남은 시간이 0이 되면 만료 문구·다시 받기로
    바뀌고 '확인 중'에 머무르지 않는다(#7962)."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.click("#pcConnectStarter")
            page.wait_for_function(VIEW_VISIBLE, timeout=4000)
            page.click("#connectorDetailConnect")
            page.wait_for_selector(".pc-connect-modal:not([hidden])", timeout=4000)
            page.click(".pc-connect-install:not([hidden])")
            page.wait_for_selector(".pc-connect-expired-copy:not([hidden])",
                                   timeout=8000)
            assert page.evaluate(
                "document.querySelector('.pc-connect-redownload').hidden") is False
            assert page.evaluate(
                "document.querySelector('.pc-connect-wait').hidden") is True
        finally:
            browser.close()


def test_reinstall_button_copy_stays_locale_driven(site):
    """한국어·영어 모두에서 단추가 locale 그룹의 문구를 따른다."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.evaluate("window.location.hash = '#padiem-connectors'")
            page.wait_for_function(VIEW_VISIBLE, timeout=4000)
            page.evaluate("window.PadiemConnectorPages.open('computer')")
            page.wait_for_selector(".pc-helper-reinstall", timeout=6000)
            ko = page.evaluate(
                "document.querySelector('.pc-helper-reinstall').textContent")
            page.evaluate(
                "document.documentElement.lang = 'en';"
                "document.dispatchEvent(new Event('padiem:localechange'));")
            page.wait_for_timeout(400)
            en = page.evaluate(
                "document.querySelector('.pc-helper-reinstall').textContent")
            assert ko and en and ko != en, (ko, en)
        finally:
            browser.close()
