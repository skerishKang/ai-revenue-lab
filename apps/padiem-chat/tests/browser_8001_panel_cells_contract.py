"""#8001 한 판 원칙 — 실제 계산 색 계약(5테마)과 토큰 변조 시험.

판 안 칸 배경은 판의 토큰 하나(--card-bg), 호버는 판의 한 단계
(--control-wash-hover) 하나다. 호버 칸의 계산 색은 같은 자리에 같은 토큰을
칠한 검침(probe) 요소와 같아야 하고(토큰 사용 증명), 토큰을 빨강으로 바꾸면
칸 색이 따라 바뀌며 제어 쌍(호버하지 않은 칸·다른 판의 칸)은 그대로여야 한다.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ["padiem-glass", "light", "dark", "cinematic", "padiem-home"]

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

CELLS_JS = """(spec) => spec.map(({sel, label}) => ({
  label,
  values: [...document.querySelectorAll(sel)]
    .filter(e => !e.closest('[hidden]') && e.getBoundingClientRect().width > 0)
    .map(e => ({
      pressed: e.getAttribute('aria-pressed') === 'true',
      bg: getComputedStyle(e).backgroundColor,
      text: (e.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 12),
    })),
}))"""

PROBE_JS = """([sel, index, token, pressed]) => {
  const cells = [...document.querySelectorAll(sel)]
    .filter(e => !e.closest('[hidden]') && e.getBoundingClientRect().width > 0)
    .filter(e => (e.getAttribute('aria-pressed') === 'true') === pressed);
  const cell = cells[index];
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

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        routes = {
            "/api/auth/status": SIGNED_IN,
            "/api/conversations": CONVS,
            "/api/account/model-selection": SELECTION,
        }
        if path in routes:
            raw = json.dumps(routes[path]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/api/"):
            raw = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


class PanelCellsOneColorContract(unittest.TestCase):
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

    # ---- 설정 창 ----
    def open_settings(self, page):
        page.click("#accountProfileButton", timeout=4000)
        page.wait_for_timeout(180)
        page.click("#settingsButton", timeout=4000)
        page.wait_for_timeout(420)

    def close_settings(self, page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(260)
        page.click("#accountProfileButton", timeout=4000)
        page.wait_for_timeout(160)

    # ---- 모델·등급 선택 ----
    def open_mode_panel(self, page):
        page.click(".composer-tier-trigger", timeout=4000)
        page.wait_for_timeout(420)

    def close_mode_panel(self, page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(260)

    # ---- 대화 행 ⋮ 메뉴 ----
    def open_row_menu(self, page):
        more = page.query_selector(".history-row .history-more")
        more.hover(timeout=4000)
        page.wait_for_timeout(120)
        more.click(timeout=4000)
        page.wait_for_timeout(300)

    def close_row_menu(self, page):
        page.evaluate(
            "document.querySelectorAll('.history-actions[open]')"
            ".forEach(d => d.open = false)")
        page.wait_for_timeout(160)

    def hover_bg(self, page, selector, pressed=False):
        cells = page.query_selector_all(selector)
        for cell in cells:
            if cell.is_visible() and (
                cell.get_attribute("aria-pressed") == "true") == pressed:
                cell.hover(timeout=4000)
                # 칸에는 background .18s 전이가 있다 — 전이가 끝난 뒤 읽는다.
                page.wait_for_timeout(320)
                return cell.evaluate("e => getComputedStyle(e).backgroundColor")
        self.fail(f"호버 대상 칸이 없다: {selector} pressed={pressed}")

    def assert_uniform(self, values, label):
        distinct = sorted(set(values))
        self.assertEqual(len(distinct), 1, f"{label}: 칸 배경이 갈라졌다 {distinct}")

    def test_cells_share_one_background_and_hover_is_one_step_per_theme(self):
        ctx, page = self.page()
        try:
            for theme in THEMES:
                self.set_theme(page, theme)
                with self.subTest(theme=theme):
                    # 설정 창: 선택되지 않은 칸 + 보조 단추 + 닫기 단추가 한 색.
                    self.open_settings(page)
                    spec = [
                        {"sel": "#settingsDialog .settings-choice", "label": "칸"},
                        {"sel": "#settingsDialog .settings-action-secondary", "label": "보조"},
                        {"sel": "#settingsDialog .settings-close", "label": "닫기"},
                    ]
                    groups = page.evaluate(CELLS_JS, spec)
                    base = [c["bg"] for g in groups for c in g["values"] if not c["pressed"]]
                    self.assert_uniform(base, f"{theme} 설정창 칸 배경")
                    selected = [c["bg"] for g in groups[:1]
                                for c in g["values"] if c["pressed"]]
                    # 테마칸·언어칸 외에 glass 테마는 유리 변형 칸이 더 눌려 있다.
                    self.assertGreaterEqual(len(selected), 2, f"{theme}: 선택 칸 수")
                    # 호버는 한 단계 하나: 칸·보조·닫기 호버가 같고 선택 칸은 유지.
                    hover_choice = self.hover_bg(
                        page, "#settingsDialog .settings-choice")
                    self.assertNotEqual(hover_choice, base[0],
                                        f"{theme}: 호버가 변하지 않는다")
                    hover_secondary = self.hover_bg(
                        page, "#settingsDialog .settings-action-secondary")
                    self.assertEqual(hover_choice, hover_secondary,
                                     f"{theme}: 호버 색이 갈라졌다")
                    hover_close = self.hover_bg(page, "#settingsDialog .settings-close")
                    self.assertEqual(hover_choice, hover_close,
                                     f"{theme}: 닫기 호버가 갈라졌다")
                    hover_selected = self.hover_bg(
                        page, "#settingsDialog .settings-choice", pressed=True)
                    self.assertEqual(hover_selected, selected[0],
                                     f"{theme}: 선택 칸이 호버에 흔들린다")
                    self.close_settings(page)

                    # 모델·등급 선택: 칸 배경 한 색, 호버 한 단계, 선택 칸 유지.
                    self.open_mode_panel(page)
                    groups = page.evaluate(CELLS_JS, [
                        {"sel": ".mode-presentation-panel .mode-option", "label": "등급칸"}])
                    base_mode = [c["bg"] for g in groups for c in g["values"] if not c["pressed"]]
                    self.assert_uniform(base_mode, f"{theme} 모델칸 배경")
                    selected_mode = [c["bg"] for g in groups for c in g["values"] if c["pressed"]]
                    self.assertEqual(len(selected_mode), 1, f"{theme}: 선택 등급칸 수")
                    hover_mode = self.hover_bg(page, ".mode-presentation-panel .mode-option")
                    self.assertNotEqual(hover_mode, base_mode[0],
                                        f"{theme}: 모델칸 호버가 변하지 않는다")
                    hover_pressed = self.hover_bg(
                        page, ".mode-presentation-panel .mode-option", pressed=True)
                    self.assertEqual(hover_pressed, selected_mode[0],
                                     f"{theme}: 선택 등급칸이 호버에 흔들린다")
                    self.close_mode_panel(page)

                    # ⋮ 메뉴: 칸은 투명 한 색, 항목·삭제 호버가 같은 한 단계.
                    self.open_row_menu(page)
                    groups = page.evaluate(CELLS_JS, [
                        {"sel": ".history-actions-menu .history-menu-action", "label": "항목"},
                        {"sel": ".history-actions-menu .history-menu-delete", "label": "삭제"},
                    ])
                    base_menu = [c["bg"] for g in groups for c in g["values"]]
                    self.assert_uniform(base_menu, f"{theme} ⋮칸 배경")
                    hover_action = self.hover_bg(
                        page, ".history-actions-menu .history-menu-action")
                    hover_delete = self.hover_bg(
                        page, ".history-actions-menu .history-menu-delete")
                    self.assertNotEqual(hover_action, base_menu[0],
                                        f"{theme}: ⋮ 호버가 변하지 않는다")
                    self.assertEqual(hover_action, hover_delete,
                                     f"{theme}: 삭제 호버가 갈라졌다")
                    self.close_row_menu(page)
        finally:
            ctx.close()

    def test_hover_uses_the_panel_step_token_and_tamper_moves_cells(self):
        """호버 칸 == 같은 자리 검침(토큰 사용 증명). 변조: 토큰→빨강이면 칸이
        따라 바뀌고 제어 쌍(호버하지 않은 칸·다른 판 칸)은 그대로다."""
        ctx, page = self.page()
        try:
            self.set_theme(page, "light")
            # 검침 일치(토큰 사용 증명) — 세 판 각각. 호버 칸과 같은 자리에 같은
            # 토큰을 칠한 검침 요소와 계산 색이 같아야 한다.
            self.open_settings(page)
            # 바탕 검침은 호버 없는 상태에서 먼저 읽는다.
            base_settings = page.evaluate(
                PROBE_JS, ["#settingsDialog .settings-choice", 0, "--card-bg", False])
            self.assertEqual(base_settings["cellBg"], base_settings["probeBg"],
                             "설정칸 바탕 토큰 불일치")
            self.hover_bg(page, "#settingsDialog .settings-choice")
            got = page.evaluate(PROBE_JS, [
                "#settingsDialog .settings-choice", 0, "--control-wash-hover", False])
            self.assertEqual(got["cellBg"], got["probeBg"], "설정칸 호버 토큰 불일치")
            self.close_settings(page)

            self.open_mode_panel(page)
            self.hover_bg(page, ".mode-presentation-panel .mode-option")
            got = page.evaluate(PROBE_JS, [
                ".mode-presentation-panel .mode-option", 0, "--control-wash-hover", False])
            self.assertEqual(got["cellBg"], got["probeBg"], "모델칸 호버 토큰 불일치")
            self.close_mode_panel(page)

            self.open_row_menu(page)
            self.hover_bg(page, ".history-actions-menu .history-menu-action")
            got = page.evaluate(PROBE_JS, [
                ".history-actions-menu .history-menu-action", 0,
                "--control-wash-hover", False])
            self.assertEqual(got["cellBg"], got["probeBg"], "⋮칸 호버 토큰 불일치")
            self.close_row_menu(page)

            # 변조 1: --card-bg → 빨강. 설정 칸은 따라 바뀌고, 제어 쌍(모델칸·
            # ⋮칸)은 그대로다.
            before_mode = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                ".mode-presentation-panel .mode-option")
            before_menu = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                ".history-actions-menu .history-menu-action")
            page.evaluate(
                "document.documentElement.style.setProperty('--card-bg', 'red')")
            page.wait_for_timeout(120)
            after_choice = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                "#settingsDialog .settings-choice")
            self.assertEqual(after_choice, "rgb(255, 0, 0)",
                             f"변조가 칸에 반영되지 않았다: {after_choice}")
            self.assertEqual(
                page.evaluate("s => getComputedStyle(document.querySelector(s)).backgroundColor",
                              ".mode-presentation-panel .mode-option"),
                before_mode, "제어 쌍(모델칸)이 함께 변했다")
            page.evaluate("document.documentElement.style.removeProperty('--card-bg')")
            page.wait_for_timeout(120)

            # 변조 2: --control-wash-hover → 빨강. 호버 칸만 빨강 워시가 되고,
            # 호버하지 않은 칸은 그대로다.
            self.open_settings(page)
            untouched = page.evaluate(
                "s => getComputedStyle(document.querySelector(s)).backgroundColor",
                "#settingsDialog .settings-action-secondary")
            page.evaluate(
                "document.documentElement.style.setProperty("
                "'--control-wash-hover', 'red')")
            page.wait_for_timeout(120)
            hovered = self.hover_bg(page, "#settingsDialog .settings-choice")
            page.wait_for_timeout(200)
            self.assertNotEqual(hovered, untouched, "호버 변조가 칸에 반영되지 않았다")
            probe = page.evaluate(PROBE_JS, [
                "#settingsDialog .settings-choice", 0, "--control-wash-hover", False])
            self.assertEqual(hovered, probe["probeBg"],
                             "변조된 토큰이 호버에 그대로 쓰이지 않았다")
            self.assertEqual(
                page.evaluate("s => getComputedStyle(document.querySelector(s)).backgroundColor",
                              "#settingsDialog .settings-action-secondary"),
                untouched, "제어 쌍(호버하지 않은 보조 단추)이 함께 변했다")
            page.evaluate(
                "document.documentElement.style.removeProperty('--control-wash-hover')")
            self.close_settings(page)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
