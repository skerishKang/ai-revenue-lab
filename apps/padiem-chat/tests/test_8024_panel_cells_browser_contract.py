"""#8024 묶음-① — 실제 계산 색 계약(5테마)과 토큰 변조 시험.

밝은 테마(light·padiem-home·glass)의 프로젝트 창·첨부 칸은 같은 판의 토큰 바탕
(--panel·--card-bg)을 칠하고, dark·cinematic은 스코프된 어두운 스킨을 유지한다.
유틸 PDF→Markdown 내부 패널은 토큰을 따른다(#8023). 호버는 판의 한 단계
(--control-wash-hover) 하나다. 토큰을 빨강으로 바꾸면 칸이 따라 바뀌고 제어 쌍은
그대로여야 한다.

B62 Chat CI의 venv에는 playwright가 없다(uv.lock 미변경 규칙) — 그 레인에서는
이 모듈이 사유 표시 SKIP으로 수집되고, playwright가 설치된 실행기에서 실제로 돈다.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest

import pytest

pytest.importorskip(
    "playwright",
    reason="브라우저 계약은 playwright 설치 실행기에서 실제로 돈다(B62 CI venv는 미설치)",
)

from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ["padiem-glass", "light", "dark", "cinematic", "padiem-home"]
BRIGHT = ["padiem-glass", "light", "padiem-home"]

SIGNED_IN = {"ok": True, "ready": True, "authenticated": True,
             "user": {"name": "홍대표", "email": "rep@example.com"},
             "member_grade": "free", "history_ready": True,
             "project_files_ready": True, "shared_login_enabled": True,
             "shared_session_present": True, "session_state": "signed_in"}
SELECTION = {"ok": True, "selection": {"tier": "free"}, "restorable_tier": "free"}
CONVS = {"ok": True, "conversations": [
    {"id": "c1", "title": "첫 인사와 안내", "pinned": True, "updated_at": "2026-11-18T09:00:00Z"},
    {"id": "c2", "title": "문서 요약 물어본 대화", "pinned": False, "updated_at": "2026-11-18T08:00:00Z"},
]}
ROUTES = {
    "/api/auth/status": SIGNED_IN,
    "/api/conversations": CONVS,
    "/api/account/model-selection": SELECTION,
}

CHIP_HTML = (
    '<span class="attachment-chip">'
    '<span class="attachment-chip-icon">PDF</span>'
    '<span class="attachment-copy"><strong>계약서.pdf</strong><small>1.2MB</small></span>'
    '<button type="button" class="attachment-remove" aria-label="삭제">×</button>'
    '</span>'
)

PROBE_JS = """([sel, token]) => {
  const cell = document.querySelector(sel);
  if (!cell) return null;
  const probe = document.createElement('span');
  probe.style.background = `var(${token})`;
  probe.style.display = 'block';
  probe.style.width = '10px';
  probe.style.height = '10px';
  cell.parentElement.appendChild(probe);
  const probeBg = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return {cellBg: getComputedStyle(cell).backgroundColor, probeBg};
}"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ROUTES:
            return self._json(ROUTES[path])
        if path.startswith("/api/") or path == "/health":
            return self._json({"ok": True, "projects": [], "list": [], "items": []})
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._json({"ok": True, "project": {
            "id": "proj1", "name": "제주 가족여행", "instructions": ""}})


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def ensure_tray_open(page):
    """트레이는 첨부물이 있을 때만 열린다 — 스타일 계약은 표시 상태에서 읽는다."""
    page.evaluate("document.getElementById('attachmentTray').hidden = false")
    page.wait_for_timeout(150)


def ensure_util_submenu_open(page):
    if page.evaluate(
            "document.getElementById('utilSubmenu')"
            ".getBoundingClientRect().height === 0"):
        jclick(page, "#utilNavButton", 280)


def jclick(page, selector, wait=300):
    try:
        page.click(selector, timeout=2500)
    except Exception:
        page.evaluate(f"document.querySelector({selector!r}).click()")
    page.wait_for_timeout(wait)


def hover_bg(page, selector):
    el = page.query_selector(selector)
    if not el:
        return None
    try:
        el.hover(timeout=4000)
    except Exception:
        # actionability가 가림·표시 판정을 못 하면 실제 좌표로 마우스를 옮긴다.
        box = el.bounding_box()
        if not box or box["width"] <= 0:
            state = page.evaluate("""() => ({
              theme: document.documentElement.getAttribute('data-theme'),
              trayHidden: document.getElementById('attachmentTray').hidden,
              chipCount: document.querySelectorAll('.attachment-chip').length,
              state: document.querySelector('.app-shell').getAttribute('data-state'),
            })""")
            raise AssertionError(f"호버 대상이 화면에 없다: {selector} {state}")
            raise
        page.mouse.move(box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2)
    page.wait_for_timeout(320)
    return el.evaluate("e => getComputedStyle(e).backgroundColor")


class Bundle2PanelSurfacesContract(unittest.TestCase):
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

    def page(self):
        ctx = self.browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
        page = ctx.new_page()
        page.on("pageerror", lambda err: self.fail(f"page error: {err}"))
        page.goto(f"http://127.0.0.1:{self.port}/index.html", wait_until="load", timeout=45000)
        page.wait_for_timeout(2200)
        return ctx, page

    def set_theme(self, page, theme):
        page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
        page.wait_for_timeout(600)

    def open_project_dialog(self, page):
        # 유틸 도구 화면에서는 작곡판이 가려진다 — 새 채팅으로 먼저 복귀한다.
        if page.evaluate(
                "document.querySelector('.app-shell').getAttribute('data-state') == 'util'"):
            jclick(page, "#newChatButton", 400)
        jclick(page, "#projectCreateButton", 400)

    def close_project_dialog(self, page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)

    def add_chip(self, page):
        page.evaluate("() => {"
                      "  const list = document.getElementById('attachmentChipList');"
                      "  if (!list.children.length) {"
                      f"    list.insertAdjacentHTML('beforeend', `<li>{CHIP_HTML}</li>`);"
                      "  }"
                      "}")
        page.wait_for_timeout(120)

    def test_panel_surfaces_follow_their_theme_in_every_theme(self):
        ctx, page = self.page()
        try:
            for theme in THEMES:
                self.set_theme(page, theme)
                with self.subTest(theme=theme):
                    # 프로젝트 창: 밝은 테마는 판 토큰(--panel), 어두운 테마는
                    # 스코프된 어두운 스킨(rgba(8,9,11,.97)).
                    self.open_project_dialog(page)
                    got = page.evaluate(PROBE_JS, ["#projectDialog", "--panel"])
                    self.assertIsNotNone(got, "프로젝트 창이 없다")
                    dialog_bg = page.evaluate(
                        "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                        "#projectDialog")
                    form_bg = page.evaluate(
                        "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                        "#projectDialog .project-form")
                    if theme in BRIGHT:
                        self.assertEqual(dialog_bg, got["probeBg"],
                                         f"{theme}: 창 바탕이 --panel이 아니다")
                        self.assertNotEqual(form_bg, "rgba(8, 9, 11, 0.97)",
                                            f"{theme}: 어두운 스킨이 밝은 테마에 남았다")
                    else:
                        self.assertEqual(form_bg, "rgba(8, 9, 11, 0.97)",
                                         f"{theme}: 어두운 스킨이 흔들린다")
                    self.close_project_dialog(page)

                    # 첨부 칩: 밝은 테마는 --card-bg 하나, 어두운 테마는
                    # 스코프된 어두운 스킨(기존 흰 베일 .045)을 유지한다.
                    ensure_tray_open(page)
                    self.add_chip(page)
                    chip_bg = page.evaluate(
                        "s => getComputedStyle(document.querySelector(s))"
                        ".backgroundColor", ".attachment-chip")
                    if theme in BRIGHT:
                        got = page.evaluate(PROBE_JS,
                                            [".attachment-chip", "--card-bg"])
                        self.assertEqual(chip_bg, got["probeBg"],
                                         f"{theme}: 첨부 칩이 --card-bg가 아니다")
                    else:
                        self.assertEqual(chip_bg, "rgba(255, 255, 255, 0.043)",
                                         f"{theme}: 어두운 칩 스킨이 흔들린다")
                    chip_remove_hover = hover_bg(page, ".attachment-chip .attachment-remove")
                    got = page.evaluate(PROBE_JS,
                                        [".attachment-chip .attachment-remove", "--control-wash-soft"])
                    self.assertEqual(chip_remove_hover, got["probeBg"],
                                     f"{theme}: 칩 삭제 호버가 한 단계 토큰이 아니다")
                    page.evaluate("document.getElementById('attachmentTray').hidden = true")
                    page.evaluate(
                        "document.getElementById('attachmentChipList').replaceChildren()")

                    # 유틸 PDF→Markdown: 내부 판은 토큰을 따른다(#8023).
                    ensure_util_submenu_open(page)
                    page.evaluate("[...document.querySelectorAll('.util-submenu-item')]"
                                  ".find(e => e.textContent.includes('PDF')).click()")
                    page.wait_for_timeout(600)
                    token = ("--glass-card-surface" if theme == "padiem-glass"
                             else "--panel")
                    got = page.evaluate(PROBE_JS, [".pdfmd-input-col", token])
                    self.assertIsNotNone(got, "PDF→MD 입력판이 없다")
                    self.assertEqual(got["cellBg"], got["probeBg"],
                                     f"{theme}: PDF→MD 내부 판이 토큰을 따르지 않는다")
                    # 유틸 하위 메뉴 호버는 한 단계 하나.
                    item_hover = hover_bg(page, ".util-submenu-item")
                    got = page.evaluate(PROBE_JS,
                                        [".util-submenu-item", "--control-wash-hover"])
                    if theme != "padiem-glass":
                        self.assertEqual(item_hover, got["probeBg"],
                                         f"{theme}: 유틸 하위 메뉴 호버가 한 단계 토큰이 아니다")
                    jclick(page, "#newChatButton", 400)
        finally:
            ctx.close()

    def test_tampering_the_tokens_moves_the_cells_and_keeps_control_pairs(self):
        ctx, page = self.page()
        try:
            self.set_theme(page, "light")
            # 변조 1: --card-bg → 빨강. 첨부 칩과 창 입력칸이 따라 바뀌고,
            # 제어 쌍(정보 패널 — 다른 토큰)은 그대로다.
            self.open_project_dialog(page)
            jclick(page, "#attachmentButton", 300)
            self.add_chip(page)
            before_banner = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                "#projectBanner")
            page.evaluate(
                "document.documentElement.style.setProperty('--card-bg', 'red')")
            page.wait_for_timeout(120)
            chip_bg = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                ".attachment-chip")
            self.assertEqual(chip_bg, "rgb(255, 0, 0)",
                             f"변조가 칩에 반영되지 않았다: {chip_bg}")
            input_bg = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                "#projectDialog .project-form input")
            self.assertEqual(input_bg, "rgb(255, 0, 0)",
                             f"변조가 입력칸에 반영되지 않았다: {input_bg}")
            after_banner = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                "#projectBanner")
            self.assertEqual(before_banner, after_banner,
                             "제어 쌍(정보 패널)이 함께 변했다")
            page.evaluate(
                "document.documentElement.style.removeProperty('--card-bg')")
            self.close_project_dialog(page)

            # 변조 2: --control-wash-hover → 빨강. 유틸 하위 메뉴 호버만 빨강이
            # 되고, 호버하지 않은 항목은 그대로다.
            jclick(page, "#utilNavButton", 300)
            page.evaluate("[...document.querySelectorAll('.util-submenu-item')]"
                          ".find(e => e.textContent.includes('PDF')).click()")
            page.wait_for_timeout(500)
            untouched = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                ".util-submenu-item:nth-of-type(2)")
            page.evaluate(
                "document.documentElement.style.setProperty("
                "'--control-wash-hover', 'red')")
            page.wait_for_timeout(120)
            hovered = hover_bg(page, ".util-submenu-item")
            self.assertEqual(hovered, "rgb(255, 0, 0)",
                             f"호버 변조가 반영되지 않았다: {hovered}")
            after_untouched = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                ".util-submenu-item:nth-of-type(2)")
            self.assertEqual(after_untouched, untouched,
                             "제어 쌍(호버하지 않은 항목)이 함께 변했다")
            page.evaluate(
                "document.documentElement.style.removeProperty('--control-wash-hover')")
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
