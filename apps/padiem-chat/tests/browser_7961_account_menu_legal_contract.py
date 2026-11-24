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
VIEWPORTS = [(1440, 900), (1440, 768), (390, 844)]
SIGNED_IN = {
    "ready": True, "authenticated": True, "history_ready": True,
    "user": {"name": "검증 사용자", "email": "verify@example.local", "id": "usr_fixture", "picture": None},
}
GUEST = {"ready": True, "authenticated": False, "history_ready": True}
CONVS = {"ok": True, "conversations": [
    {"id": "c1", "title": "첫 인사와 안내", "pinned": True, "updated_at": "2026-11-18T09:00:00Z"},
    {"id": "c2", "title": "문서 요약 물어본 대화", "pinned": False, "updated_at": "2026-11-18T08:00:00Z"},
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
  const menu = document.querySelector('#utilNavButton');
  const calendar = document.querySelector('#calendarNavButton');
  const s = el => getComputedStyle(el);
  return {
    expected: s(menu).color,
    calendar: s(calendar).color,
    actual: s(link).color,
  };
}"""

RECT_JS = """() => {
  const legal = document.querySelector('.sidebar-legal');
  const account = document.querySelector('.sidebar-account');
  const bottom = document.querySelector('.sidebar-bottom');
  const tools = document.querySelector('.sidebar-bottom-tools');
  const row = document.querySelector('#historyList .history-row');
  const bg = getComputedStyle(bottom).backgroundColor.match(/[\\d.]+/g) || [];
  const rect = el => { const b = el.getBoundingClientRect(); return {top: b.top, bottom: b.bottom}; };
  return {
    legalBottom: legal.getBoundingClientRect().bottom,
    accountBottom: account.getBoundingClientRect().bottom,
    innerHeight: window.innerHeight,
    backgroundAlpha: bg.length === 3 ? 1 : Number(bg[3]),
    background: getComputedStyle(bottom).backgroundColor,
    pinnedChildren: [...bottom.children].map(el => el.className.split(' ')[0]),
    toolsPosition: getComputedStyle(tools).position,
    firstRow: row ? rect(row) : null,
    scrollTop: document.querySelector('.sidebar').scrollTop,
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
            page.wait_for_selector("#mobileMenu", state="visible", timeout=15_000)
            page.click("#mobileMenu", timeout=3000)
            page.wait_for_timeout(400)
        return ctx, page

    def set_theme(self, page, theme):
        page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
        page.wait_for_timeout(900)

    def test_sidebar_rows_share_one_inset_width_and_button_shape(self):
        """Computed geometry across themes, viewports and open/closed states."""
        geometry = """() => {
          const list = sel => [...document.querySelectorAll(sel)]
            .filter(el => el.getClientRects().length);
          const box = el => {
            const b = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return {x: Math.round(b.x), w: Math.round(b.width), h: Math.round(b.height),
                    pl: s.paddingLeft, r: s.borderRadius};
          };
          const legal = document.querySelector('.sidebar-legal');
          const ls = getComputedStyle(legal);
          return {
            nav: list('#workspaceNav .side-item').map(box),
            tools: list('.sidebar-bottom-tools .side-item').map(box),
            account: box(document.querySelector('.sidebar-account > .account-profile-toggle')),
            brand: box(document.querySelector('.brand-row')),
            legal: {font: ls.fontSize, gap: ls.marginTop,
                    links: list('.sidebar-legal a').map(box)},
          };
        }"""
        for width, height in ((1440, 900), (768, 1024), (390, 844)):
            for collapsed in (False, True):
                ctx = self.browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")
                page = ctx.new_page()
                try:
                    page.route("**/api/auth/status", lambda route: route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(SIGNED_IN)))
                    page.goto(f"http://127.0.0.1:{self.port}", wait_until="domcontentloaded")
                    if width <= 920 and not collapsed:
                        page.wait_for_selector("#mobileMenu", state="visible", timeout=15_000)
                        page.click("#mobileMenu", timeout=3000)
                    if collapsed and width > 920:
                        page.evaluate("() => document.querySelector('.app-shell').classList.add('sidebar-collapsed')")
                    page.wait_for_function(
                        "() => document.querySelector('.app-shell') !== null", timeout=3000)
                    for theme in THEMES:
                        self.set_theme(page, theme)
                        label = f"{theme} {width}x{height} collapsed={collapsed}"
                        measured = page.evaluate(geometry)
                        legal = measured["legal"]
                        self.assertEqual(legal["font"], "13px", label)
                        self.assertEqual(legal["gap"], "8px", label)
                        self.assertEqual(len(legal["links"]), 2, label)
                        for link in legal["links"]:
                            self.assertGreaterEqual(link["w"], 24, (label, link))
                            self.assertGreaterEqual(link["h"], 24, (label, link))
                        if collapsed and width > 920:
                            rail = page.evaluate(
                                "() => document.querySelector('.sidebar').getBoundingClientRect().width")
                            self.assertLessEqual(rail, 40, label)
                            self.assertTrue(page.locator(".sidebar-restore-button").is_visible(), label)
                            continue
                        rows = measured["nav"] + measured["tools"] + [measured["account"]]
                        self.assertGreaterEqual(len(rows), 4, label)
                        left, target_width = measured["brand"]["x"], measured["brand"]["w"]
                        for row in rows:
                            self.assertEqual(row["x"], left, (label, row))
                            self.assertEqual(row["w"], target_width, (label, row))
                            self.assertGreaterEqual(row["h"], 44, (label, row))
                            self.assertEqual(row["pl"], "12px", (label, row))
                            self.assertEqual(row["r"], "12px", (label, row))
                finally:
                    ctx.close()

    def test_legal_links_keep_a_24px_hit_area_without_moving_the_text(self):
        """Computed geometry only: tap area, font size and one-line layout."""
        geometry = """() => {
          const links = [...document.querySelectorAll('.sidebar-legal a')];
          const box = el => {
            const b = el.getBoundingClientRect();
            return {w: b.width, h: b.height, top: b.top,
                    font: getComputedStyle(el).fontSize};
          };
          return links.filter(el => el.getClientRects().length).map(box);
        }"""
        for width, height in ((390, 844), (1440, 900), (768, 1024)):
            ctx = self.browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")
            page = ctx.new_page()
            try:
                page.route("**/api/auth/status", lambda route: route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(GUEST)))
                page.goto(f"http://127.0.0.1:{self.port}", wait_until="domcontentloaded")
                page.locator(".sidebar-legal a").first.wait_for(state="visible", timeout=3000)
                for theme in THEMES:
                    page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
                    page.wait_for_function(
                        "t => document.documentElement.getAttribute('data-theme') === t "
                        "&& document.querySelectorAll('.sidebar-legal a').length === 2",
                        arg=theme, timeout=3000)
                    measured = page.evaluate(geometry)
                    label = f"{theme} {width}x{height}"
                    self.assertEqual(len(measured), 2, label)
                    for item in measured:
                        self.assertGreaterEqual(item["w"], 24, (label, item))
                        self.assertGreaterEqual(item["h"], 24, (label, item))
                        self.assertEqual(item["font"], "13px", (label, item))
                    self.assertEqual(measured[0]["top"], measured[1]["top"], label)
            finally:
                ctx.close()

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

    def test_legal_link_uses_upper_menu_colour_in_every_theme(self):
        ctx, page = self.page(1440, 900, SIGNED_IN)
        try:
            for theme in THEMES:
                self.set_theme(page, theme)
                colors = page.evaluate(LEGAL_JS)
                self.assertEqual(colors["actual"], colors["expected"], f"{theme}: {colors}")
                self.assertEqual(colors["calendar"], colors["expected"], f"{theme}: {colors}")
        finally:
            ctx.close()

    def test_pinned_area_stays_inside_every_viewport_and_is_opaque(self):
        for width, height in VIEWPORTS:
            for auth in (GUEST, SIGNED_IN):
                ctx, page = self.page(width, height, auth)
                try:
                    for theme in THEMES:
                        self.set_theme(page, theme)
                        rect = page.evaluate(RECT_JS)
                        label = f"{width}x{height} {theme}"
                        self.assertLessEqual(rect["legalBottom"], rect["innerHeight"], f"{label}: {rect}")
                        self.assertLessEqual(rect["accountBottom"], rect["innerHeight"], f"{label}: {rect}")
                        self.assertEqual(rect["backgroundAlpha"], 1, f"{label}: {rect}")
                        self.assertEqual(
                            rect["pinnedChildren"], ["sidebar-account", "sidebar-legal"],
                            f"{label}: 고정 영역에 도구 단추가 들어갔다",
                        )
                        self.assertEqual(rect["toolsPosition"], "static", f"{label}: {rect}")
                finally:
                    ctx.close()

    def test_first_conversation_and_legal_visible_without_scroll(self):
        for width, height in ((1440, 768), (390, 844)):
            ctx, page = self.page(width, height, SIGNED_IN)
            try:
                for theme in THEMES:
                    self.set_theme(page, theme)
                    rect = page.evaluate(RECT_JS)
                    label = f"{width}x{height} {theme}"
                    self.assertEqual(rect["scrollTop"], 0, f"{label}: 스크롤 없이 확인해야 한다")
                    self.assertIsNotNone(rect["firstRow"], f"{label}: 대화 행이 없다")
                    self.assertGreaterEqual(rect["firstRow"]["top"], 0, f"{label}: {rect}")
                    self.assertLessEqual(rect["firstRow"]["bottom"], rect["innerHeight"], f"{label}: {rect}")
                    self.assertLessEqual(rect["legalBottom"], rect["innerHeight"], f"{label}: {rect}")
            finally:
                ctx.close()


if __name__ == "__main__":
    unittest.main()
