"""#7961 CTO recapture contract — menu cells, legal-link token colour and the
390px pinned account/legal area, verified from real computed styles.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ["padiem-glass", "light", "dark", "cinematic", "padiem-home"]
SIGNED_IN = {
    "ready": True, "authenticated": True, "history_ready": True,
    "user": {"name": "검증 사용자", "email": "verify@example.local", "id": "usr_fixture", "picture": None},
}
GUEST = {"ready": True, "authenticated": False, "history_ready": True}
CONVS = {"ok": True, "conversations": [
    {"id": "c1", "title": "첫 인사와 안내", "pinned": True, "updated_at": "2026-11-18T09:00:00Z"},
    {"id": "c2", "title": "문서 요약 물어본 대화", "pinned": False, "updated_at": "2026-11-18T08:00:00Z"},
    {"id": "c3", "title": "표 정리 요청", "pinned": False, "updated_at": "2026-11-18T07:00:00Z"},
]}

MENU_JS = """() => {
  const m = document.getElementById('profileMenu');
  const items = [...m.querySelectorAll('.settings-button,.side-item,.home-link,.profile-menu-logout')]
    .filter(e => !e.hidden);
  const boxes = items.filter(e => {
    const s = getComputedStyle(e);
    return s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.borderTopColor !== 'rgba(0, 0, 0, 0)';
  });
  return {count: items.length, boxes: boxes.length};
}"""

LEGAL_JS = """() => {
  const link = document.querySelector('.sidebar-legal a');
  const probe = document.createElement('span');
  probe.style.cssText = 'color:var(--sidebar-text, var(--text))';
  document.body.appendChild(probe);
  const expected = getComputedStyle(probe).color;
  probe.remove();
  return {expected, actual: getComputedStyle(link).color};
}"""

RECT_JS = """() => {
  const legal = document.querySelector('.sidebar-legal');
  const account = document.querySelector('.sidebar-account');
  return {
    legalBottom: legal.getBoundingClientRect().bottom,
    accountBottom: account.getBoundingClientRect().bottom,
    innerHeight: window.innerHeight,
  };
}"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


class AccountMenuAndLegalContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.port = serve()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def page(self, width, height, auth):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")
        page = ctx.new_page()
        page.on("pageerror", lambda err: self.fail(f"page error: {err}"))

        def auth_route(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(auth))

        def conv_route(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(CONVS))

        page.route("**/api/auth/status", auth_route)
        page.route("**/api/conversations", conv_route)
        page.goto(f"http://127.0.0.1:{self.port}", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        if width == 390:
            page.click("#mobileMenu", timeout=3000)
            page.wait_for_timeout(400)
        return ctx, page

    def set_theme(self, page, theme):
        page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
        page.wait_for_timeout(150)

    def test_account_menu_has_no_box_in_every_theme(self):
        ctx, page = self.page(1440, 900, SIGNED_IN)
        try:
            for theme in THEMES:
                self.set_theme(page, theme)
                page.click("#accountProfileButton", timeout=3000)
                page.wait_for_timeout(120)
                state = page.evaluate(MENU_JS)
                self.assertGreaterEqual(state["count"], 3)
                self.assertEqual(state["boxes"], 0, f"{theme}: 기본 상태 박스 {state['boxes']}개")
                page.click("#accountProfileButton", timeout=3000)
                page.wait_for_timeout(120)
            for theme in THEMES:
                self.set_theme(page, theme)
                page.click("#accountProfileButton", timeout=3000)
                page.hover("#profileMenu .settings-button", timeout=3000)
                page.wait_for_timeout(150)
                state = page.evaluate(MENU_JS)
                self.assertEqual(state["boxes"], 1, f"{theme}: 호버 박스 {state['boxes']}개")
                page.click("#accountProfileButton", timeout=3000)
                page.wait_for_timeout(120)
        finally:
            ctx.close()

    def test_legal_link_uses_sidebar_token_in_every_theme(self):
        ctx, page = self.page(1440, 900, SIGNED_IN)
        try:
            for theme in THEMES:
                self.set_theme(page, theme)
                colors = page.evaluate(LEGAL_JS)
                self.assertEqual(colors["actual"], colors["expected"], f"{theme}: {colors}")
        finally:
            ctx.close()

    def test_390_keeps_account_and_legal_inside_viewport(self):
        for auth in (GUEST, SIGNED_IN):
            ctx, page = self.page(390, 844, auth)
            try:
                for theme in THEMES:
                    self.set_theme(page, theme)
                    rect = page.evaluate(RECT_JS)
                    self.assertLessEqual(rect["legalBottom"], rect["innerHeight"], f"{theme}: {rect}")
                    self.assertLessEqual(rect["accountBottom"], rect["innerHeight"], f"{theme}: {rect}")
            finally:
                ctx.close()


if __name__ == "__main__":
    unittest.main()
