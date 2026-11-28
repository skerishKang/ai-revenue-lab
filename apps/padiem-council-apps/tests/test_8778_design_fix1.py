# -*- coding: utf-8 -*-
"""#8778 first repair: browser geometry + shipped JS harness contracts."""
import http.server
import json
import mimetypes
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from _council_module import run

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CHAT_STYLE = ROOT.parent / "padiem-chat" / "static"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/apps/council", "/apps/council/"):
            target = STATIC / "index.html"
        elif path.startswith("/apps/council/static/"):
            target = STATIC / path.partition("/static/")[2]
        elif path in ("/padiem-tokens.css", "/padiem-themes.css"):
            target = CHAT_STYLE / path.lstrip("/")
        else:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        blob = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.end_headers()
        self.wfile.write(blob)


@pytest.fixture(scope="module")
def url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 15061), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:15061/apps/council/"
    server.shutdown()
    server.server_close()


def open_page(browser, url, *, signed=False, width=390, with_records=False):
    ctx = browser.new_context(viewport={"width": width, "height": 844}, reduced_motion="reduce", locale="ko-KR")
    def mock(route):
        path = route.request.url.split("?", 1)[0]
        if path.endswith("/api/auth/status"):
            result = {"authenticated": signed, "member_grade": "pro", "methods": {"password": True}}
        elif path.endswith("/api/account/model-selection"):
            result = {"allowed_tiers": ["free", "plus", "pro"], "restorable_tier": "pro"}
        elif path.endswith("/api/projects"):
            result = {"projects": [{"id": "test-council", "name": "의원3종"}]}
        elif path.endswith("/api/projects/test-council/files"):
            result = {"files": [
                {"id": "m" + str(i), "name": "2026년_아주_긴_지역주민협력_회의제목_후속점검_준비사항_" + str(i) + ".txt",
                 "doc_kind": "meeting", "media_type": "text/plain", "content_chars": 500}
                for i in range(8)
            ] if with_records else []}
        elif "/api/projects/test-council/files/" in path:
            result = {"file": {"content": "회의 일시: 2026-11-18T14:00\\n\\n검토 의견입니다."}}
        elif path.endswith("/api/auth/password/login"):
            route.fulfill(status=401, content_type="application/json",
                          body='{"error":{"message":"이메일 또는 비밀번호가 올바르지 않습니다."}}')
            return
        else:
            result = {"links": [], "items": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(result, ensure_ascii=False))
    ctx.route("**/api/**", mock)
    page = ctx.new_page()
    page.goto(url, wait_until="load")
    page.wait_for_timeout(350)
    return ctx, page


@pytest.mark.parametrize("signed", (False, True))
def test_mobile_header_order_and_theme_visible(url, signed):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_page(browser, url, signed=signed)
        try:
            m = page.evaluate("""() => {
              const r=(selector)=>{const el=document.querySelector(selector);const x=el.getBoundingClientRect();
                return {x:x.left,y:x.top,right:x.right,bottom:x.bottom,w:x.width,h:x.height,display:getComputedStyle(el).display}};
              return {brand:r('.council-brand'),theme:r('#councilThemeTrigger'),
                auth:r('#councilAuthAction'),nav:r('#councilToolNav'),
                header:r('.council-topbar'),tier:r('#councilTierWrap'),
                scrollWidth:document.documentElement.scrollWidth};
            }""")
            assert m["brand"]["right"] <= m["theme"]["x"] + 1, m
            assert m["theme"]["w"] >= 44 and m["theme"]["h"] >= 44, m
            assert m["theme"]["right"] <= 390 and m["theme"]["x"] >= 0, m
            assert m["auth"]["y"] >= m["brand"]["bottom"] - 1, m
            assert m["nav"]["y"] >= m["header"]["bottom"] - 1, m
            assert m["scrollWidth"] <= 390, m
            if signed:
                assert page.locator("#councilAuthAction").inner_text() != "로그인"
                assert m["tier"]["y"] >= m["brand"]["bottom"] - 1, m
            else:
                assert page.locator("#councilAuthAction").inner_text() == "로그인"
            page.locator("#councilThemeTrigger").click()
            assert page.locator("#councilThemePanel").is_visible()
        finally:
            ctx.close()
            browser.close()


def test_login_panel_failure_close_and_scroll(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_page(browser, url)
        try:
            page.locator("#councilAuthAction").click()
            assert page.locator("#councilAuthClose").is_visible()
            assert page.locator("#councilAuthClose").bounding_box()["width"] >= 44
            page.locator("#councilLoginForm [name=identifier]").fill("test@example.invalid")
            page.locator("#councilLoginForm [name=password]").fill("wrong")
            page.locator("#councilLoginForm button[type=submit]").click()
            page.wait_for_timeout(200)
            m = page.evaluate("""() => {
             const panel=document.querySelector('#councilAuthPanel'), status=document.querySelector('#councilAuthStatus'),
              submit=document.querySelector('#councilLoginForm button[type=submit]'), signup=document.querySelector('.council-auth-signup');
             return {panel:panel.getBoundingClientRect().toJSON(),notice:status.getBoundingClientRect().toJSON(),
              submit:submit.getBoundingClientRect().toJSON(),signup:signup.getBoundingClientRect().toJSON(),
              statusVisible:!status.hidden, scrollable:panel.scrollHeight>panel.clientHeight,
              bottomPadding:parseFloat(getComputedStyle(panel).paddingBottom)};
            }""")
            assert m["statusVisible"] and m["notice"]["y"] < m["submit"]["y"], m
            assert m["panel"]["top"] >= 16 and m["panel"]["bottom"] <= 844-16, m
            assert m["bottomPadding"] >= 24, m
            page.locator("#councilAuthClose").click()
            assert page.locator("#councilAuthPanel").is_hidden()
            page.locator("#councilAuthAction").click()
            page.keyboard.press("Escape")
            assert page.locator("#councilAuthPanel").is_hidden()
        finally:
            ctx.close()
            browser.close()


def test_long_archive_name_two_lines_and_vertical_arrows(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_page(browser, url, signed=True, with_records=True)
        try:
            page.locator('#council-meeting .council-card-select').click()
            page.locator('.council-archive-item').first.wait_for()
            m = page.evaluate("""() => {
              const item=document.querySelector('.council-archive-item'),
               title=item.querySelector('.council-archive-name'), date=item.querySelector('.council-archive-count'),
               arrows=item.querySelectorAll('.council-record-move'), tr=title.getBoundingClientRect(),
               dr=date.getBoundingClientRect(),u=arrows[0].getBoundingClientRect(),d=arrows[1].getBoundingClientRect();
              return {clamp:getComputedStyle(title).webkitLineClamp,title:tr.toJSON(),date:dr.toJSON(),
                      up:u.toJSON(),down:d.toJSON(),scroll:document.documentElement.scrollWidth};
            }""")
            assert m["clamp"] == "2", m
            assert m["date"]["top"] >= m["title"]["bottom"] - 2, m
            assert m["down"]["top"] >= m["up"]["bottom"] - 1, m
            assert m["scroll"] <= 390, m
        finally:
            ctx.close()
            browser.close()


def test_collision_choice_resets_label_has_cancel_and_filename_title():
    obs=run("conflict")
    # #8778 I-3: representative-approved result action name; PC save label is separate.
    assert obs["saveLabelWhileChoice"] == "내 기록에 저장", obs
    assert obs["choiceHasCancel"] is True, obs
    assert obs["filenameTitle"] == obs["firstName"][0], obs
    assert obs["cancelLeavesFilesUnchanged"] and obs["cancelRemovesChoice"], obs

# #8945 CTO follow-up: mobile topbar sits on a solid page background.
# Read the actual browser-computed colors, including alpha backgrounds.
import re


def _rgba(css_color):
    css_color = css_color.strip().lower()
    if css_color == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    nums = [float(n) for n in re.findall(r"[-+]?(?:\d*\.)?\d+", css_color)]
    if css_color.startswith("color(srgb"):
        assert len(nums) >= 3, css_color
        return (*nums[:3], nums[3] if len(nums) > 3 else 1.0)
    if css_color.startswith(("rgb(", "rgba(")):
        assert len(nums) >= 3, css_color
        return (*(x / 255 for x in nums[:3]), nums[3] if len(nums) > 3 else 1.0)
    raise AssertionError(f"unknown computed browser color: {css_color}")


def _onto(foreground, background):
    alpha = foreground[3]
    return tuple(alpha * foreground[i] + (1.0 - alpha) * background[i] for i in range(3))


def _contrast(text_color, surface_color):
    def lum(rgb):
        def c(v):
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return sum(weight * c(v) for weight, v in zip((0.2126, 0.7152, 0.0722), rgb))
    a, b = lum(text_color), lum(surface_color)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize("signed", (False, True))
def test_mobile_topbar_ink_contrast_all_five_styles(url, signed):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_page(browser, url, signed=signed, width=390)
        try:
            for style in ("light", "classic", "modern", "dark", "minimal"):
                page.locator("#councilThemeTrigger").click()
                page.locator(f'#councilStyleGroup button[data-style="{style}"]').click()
                page.locator("#councilThemeTrigger").click()
                measured = page.evaluate("""() => {
                  const css = (selector) => {
                    const el = document.querySelector(selector);
                    const s = getComputedStyle(el);
                    return {color:s.color, bg:s.backgroundColor, visible:el.getClientRects().length > 0};
                  };
                  return {header:css('.council-topbar'), action:css('#councilAuthAction'),
                    tier:css('#councilTierWrap'), picker:css('#councilTier'),
                    status:css('#councilTierStatus'), style:document.documentElement.dataset.style};
                }""")
                assert measured["style"] == style, measured
                assert measured["action"]["visible"], measured
                header_bg = _onto(_rgba(measured["header"]["bg"]), (1.0, 1.0, 1.0))
                # The control can have a translucent background; blend it with the solid bar.
                for part in (("action", "tier", "picker", "status") if signed else ("action",)):
                    widget = measured[part]
                    if part == "tier":
                        assert widget["visible"], (style, measured)
                    target_bg = _onto(_rgba(widget["bg"]), header_bg)
                    text_rgb = _onto(_rgba(widget["color"]), target_bg)
                    ratio = _contrast(text_rgb, target_bg)
                    assert ratio >= 4.5, (signed, style, part, round(ratio, 2), measured)
        finally:
            ctx.close()
            browser.close()
