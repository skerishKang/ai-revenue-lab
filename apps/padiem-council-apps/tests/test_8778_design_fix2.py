# -*- coding: utf-8 -*-
"""#8778 second-pass A-H browser-measured regression + seven approved texts."""
from __future__ import annotations

import http.server
import json
import mimetypes
from pathlib import Path
import re
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
THEMES = ROOT.parent / "padiem-chat" / "static"
STYLES = ("light", "classic", "modern", "dark", "minimal")
PORT = 9461  # CGI lane 4461 + 5000, confirmed outside reserved ranges
ANSWER = "시민과 함께합니다.\n\n주민의 뜻을 살피겠습니다."
LONG_ANSWER = "\n".join([f"{i+1}. 주민 의견을 살펴 다음 회의에서 검토합니다." for i in range(30)])


class StaticHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/apps/council", "/apps/council/"):
            target = STATIC / "index.html"
        elif path.startswith("/apps/council/static/"):
            target = STATIC / path.partition("/static/")[2]
        elif path in ("/padiem-tokens.css", "/padiem-themes.css"):
            target = THEMES / path.lstrip("/")
        else:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/chat/stream":
            self.send_error(404)
            return
        time.sleep(2)
        content = ("data: " + json.dumps({"delta": ANSWER}, ensure_ascii=False)
                   + '\n\nevent: done\ndata: {"done":true}\n\n').encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def local_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), StaticHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{PORT}/apps/council/"
    server.shutdown()
    server.server_close()


def rgba(value):
    value = value.strip().lower()
    if value == "transparent":
        return [0, 0, 0, 0]
    vals = [float(v) for v in re.findall(r"[-+]?(?:\d*\.)?\d+", value)]
    if value.startswith("color(srgb"):
        return [*vals[:3], vals[3] if len(vals) > 3 else 1]
    assert value.startswith(("rgb(", "rgba(")), value
    return [*[v / 255 for v in vals[:3]], vals[3] if len(vals) > 3 else 1]


def composite(ink, background):
    return [ink[i] * ink[3] + background[i] * (1 - ink[3]) for i in range(3)]


def ratio(fg, bg):
    def lum(rgb):
        def channel(v):
            return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
        return sum(c * channel(v) for c, v in zip((.2126, .7152, .0722), rgb))
    x, y = lum(fg), lum(bg)
    return (max(x, y) + .05) / (min(x, y) + .05)


def contrast(ink, surface, under="rgb(255, 255, 255)"):
    bg = composite(rgba(surface), composite(rgba(under), [1, 1, 1]))
    return ratio(composite(rgba(ink), bg), bg)


def open_case(browser, local_url, *, width=390, signed=True, stream="success", many=False):
    ctx = browser.new_context(viewport={"width": width, "height": 900 if width == 1440 else 844},
                              locale="ko-KR", reduced_motion="reduce")
    ctx.add_init_script("localStorage.removeItem('padiem-council-tool')")
    def api(route):
        path = route.request.url.split("?", 1)[0].split("://", 1)[-1].partition("/")[2]
        if path == "api/chat/stream":
            if stream == "slow":
                route.continue_()
                return
            if stream == "error":
                route.fulfill(status=503, content_type="application/json", body='{"error":{"code":"server_unavailable"}}')
                return
            content = LONG_ANSWER if stream == "long" else ANSWER
            body = ("data: " + json.dumps({"delta": content}, ensure_ascii=False)
                    + '\n\nevent: done\ndata: {"done":true}\n\n')
            route.fulfill(status=200, content_type="text/event-stream", body=body)
            return
        if path == "api/auth/status":
            payload = {"authenticated": signed, "member_grade": "pro", "user": {"name": "시험"}}
        elif path == "api/account/model-selection":
            payload = {"allowed_tiers": ["free", "plus", "pro"], "restorable_tier": "pro"}
        elif path == "api/projects":
            payload = {"projects": [{"id": "test-council", "name": "의원3종"}]}
        elif path == "api/projects/test-council/files":
            payload = {"files": [
                {"id": f"r{i}", "name": f"지역 회의 기록 {i}.txt", "doc_kind": "meeting",
                 "media_type": "text/plain", "content_chars": 200}
                for i in range(4)
            ] if many else []}
        elif path.startswith("api/projects/test-council/files/"):
            payload = {"file": {"name": "지역 회의 기록", "content": "회의 일시: 2026-11-17T14:00\n\n의견을 확인했습니다."}}
        elif path == "api/pc/pairings":
            payload = {"links": []}
        else:
            payload = {"ok": True, "items": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
    ctx.route("**/api/**", api)
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.goto(local_url, wait_until="load")
    page.wait_for_timeout(350)
    return ctx, page


def set_style(page, style):
    page.locator("#councilThemeTrigger").click()
    page.locator(f'#councilStyleGroup button[data-style="{style}"]').click()
    page.locator("#councilThemeTrigger").click()


def open_tool(page, tool):
    page.locator(f'#council-{tool} .council-card-select').click()
    page.wait_for_timeout(200)


def test_A_busy_success_and_failure_have_distinct_status_and_busy_button(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_case(browser, local_url, stream="slow")
        try:
            open_tool(page, "speech")
            page.locator('#councilSpeechForm [name=event]').fill("주민 행사")
            original = page.locator("#councilSpeechGenerate").inner_text()
            page.locator("#councilSpeechGenerate").click()
            busy = page.locator("#councilSpeechGenerate")
            assert "생성 중" in busy.inner_text() and busy.is_disabled(), original
            assert busy.get_attribute("aria-busy") == "true"
            assert busy.locator(".council-loading-spinner").count() == 1
            notice = page.locator("#councilSpeechNotice")
            assert notice.is_visible()
            status = page.evaluate("""() => {
              const s=getComputedStyle(document.querySelector('#councilSpeechNotice'));
              return {border:s.borderTopWidth, background:s.backgroundColor, cls:document.querySelector('#councilSpeechNotice').className};
            }""")
            assert float(status["border"].replace("px", "")) == 0 and status["background"] in ("rgba(0, 0, 0, 0)", "transparent"), status
            assert "council-notice-busy" in status["cls"]
            page.wait_for_function("document.querySelector('#councilSpeechGenerate').getAttribute('aria-busy') !== 'true'", timeout=8000)
            assert busy.inner_text() == original
            assert "council-notice-success" in notice.get_attribute("class")
            # #8778 A: decorative check lives in ::before; aria-live text stays unchanged.
            assert "✓" in page.locator("#councilSpeechNotice").evaluate("e=>getComputedStyle(e, '::before').content")
        finally:
            ctx.close()
        ctx, page = open_case(browser, local_url, stream="error")
        try:
            open_tool(page, "speech")
            page.locator('#councilSpeechForm [name=event]').fill("오류 확인")
            page.locator("#councilSpeechGenerate").click()
            page.locator("#councilSpeechNotice[data-tone=error]").wait_for()
            assert "council-notice-error" in page.locator("#councilSpeechNotice").get_attribute("class")
            assert page.locator("#councilSpeechGenerate").get_attribute("aria-busy") == "false"
        finally:
            ctx.close()
            browser.close()


def test_B_form_notice_result_and_saved_lists_share_one_720px_column(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for tool in ("speech", "sns", "meeting"):
            ctx, page = open_case(browser, local_url, width=1440)
            try:
                open_tool(page, tool)
                page.evaluate("""(tool) => {
                  document.getElementById('council'+tool+'Result').hidden=false;
                  const notice=document.getElementById('council'+tool+'Notice');
                  notice.textContent='안내'; notice.hidden=false;
                }""", tool.capitalize())
                names = ["#" + "council" + tool.capitalize() + "Form",
                         "#" + "council" + tool.capitalize() + "Result",
                         "#" + "council" + tool.capitalize() + "Notice",
                         "#councilMeetingArchive" if tool == "meeting" else "#council" + tool.capitalize() + "Saved"]
                boxes = page.evaluate("""(selectors) => selectors.map(s=>{
                  const e=document.querySelector(s),r=e.getBoundingClientRect();
                  return [s,r.left,r.width,getComputedStyle(e).display];
                })""", names)
                for label, x, w, display in boxes:
                    assert display != "none" and w <= 722 and abs(x - (1440 - w) / 2) <= 5, (tool, boxes)
                assert boxes[1][1] >= boxes[0][1] - 5, boxes
            finally:
                ctx.close()
        browser.close()


def test_C_same_44px_result_button_surface_in_five_styles(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_case(browser, local_url, width=390)
        try:
            open_tool(page, "sns")
            page.evaluate("""() => {
              document.querySelector('#councilSnsResult').hidden=false;
            }""")
            for style in STYLES:
                set_style(page, style)
                buttons = page.evaluate("""() => [...document.querySelectorAll('#councilSnsResult .council-actions button, #councilSnsEdit')].map(e=>{
                  const s=getComputedStyle(e),r=e.getBoundingClientRect();
                  return {id:e.id,cls:e.className, w:r.width,h:r.height,border:s.borderTopWidth,shape:s.borderRadius};
                })""")
                assert len(buttons) == 7, (style, buttons)
                for b in buttons:
                    assert "council-result-action" in b["cls"] and b["h"] >= 44, (style, buttons)
                    assert float(b["border"].replace("px", "")) >= 1 and b["shape"] == buttons[0]["shape"], (style, buttons)
        finally:
            ctx.close()
            browser.close()


def test_D_truly_empty_status_strips_never_paint(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_case(browser, local_url)
        try:
            open_tool(page, "speech")
            page.evaluate("""() => {const n=document.querySelector('#councilSpeechNotice'); n.hidden=false;n.textContent='';}""")
            assert page.locator("#councilSpeechNotice").evaluate("(e)=>getComputedStyle(e).display") == "none"
            assert page.locator("#councilSpeechResult").is_hidden()
        finally:
            ctx.close()
            browser.close()


def test_E_short_answer_has_no_large_blank_space_but_long_answer_grows(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx, page = open_case(browser, local_url)
        try:
            open_tool(page, "speech")
            page.evaluate("""() => {
              const r=document.querySelector('#councilSpeechResult'), t=document.querySelector('#councilSpeechOutput');
              r.hidden=false; t.value='한 줄 안내'; t.dispatchEvent(new Event('input'));
            }""")
            small=page.locator("#councilSpeechOutput").evaluate("(t)=>({height:t.getBoundingClientRect().height, scroll:t.scrollHeight, client:t.clientHeight})")
            assert small["height"] <= 125 and small["scroll"] <= small["client"] + 3, small
            page.evaluate("""() => {
              const t=document.querySelector('#councilSpeechOutput');
              t.value=Array(40).fill('긴 답변입니다.').join('\\n'); t.dispatchEvent(new Event('input'));
            }""")
            large=page.locator("#councilSpeechOutput").evaluate("(t)=>({height:t.getBoundingClientRect().height, scroll:t.scrollHeight, client:t.clientHeight})")
            assert large["height"] >= 500 and large["scroll"] <= large["client"] + 3, (small,large)
        finally:
            ctx.close()
            browser.close()


def test_F_active_tool_nav_is_filled_bold_and_readable_in_five_styles(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for width in (390, 1440):
            ctx, page = open_case(browser, local_url, width=width)
            try:
                open_tool(page, "sns")
                for style in STYLES:
                    set_style(page, style)
                    nav = ".council-tool-nav" if width == 390 else ".council-nav"
                    selected = page.locator(nav + ' [aria-current="page"][data-nav=sns]')
                    assert selected.count() == 1, (width,style)
                    result = selected.evaluate("""(e) => {
                      const s=getComputedStyle(e), r=e.getBoundingClientRect();
                      const n=getComputedStyle(e.closest('nav'));
                      return {weight:s.fontWeight,background:s.backgroundColor,color:s.color,
                        border:s.borderTopWidth,navBackground:n.backgroundColor, visible:r.width>0 && r.height>0};
                    }""")
                    assert result["visible"] and int(result["weight"]) >= 700, (width,style,result)
                    assert rgba(result["background"])[3] >= 0.95, (width,style,result)
                    assert contrast(result["color"],result["background"]) >= 4.5, (width,style,result)
                    if width == 1440 and style == "light":
                        assert rgba(result["navBackground"])[3] >= 0.95, result
            finally:
                ctx.close()
        browser.close()


def test_G_minimal_card_is_bright_and_primary_buttons_are_dark(local_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,local_url,width=390)
        try:
            set_style(page,"minimal")
            result=page.locator("#council-speech").evaluate("""(e)=>{
              const s=getComputedStyle(e), text=getComputedStyle(e.querySelector('h2'));
              return {bg:s.backgroundColor,border:s.borderTopWidth,ink:text.color,filter:s.filter};
            }""")
            rgb=rgba(result["bg"])
            assert sum(rgb[:3])/3 > .90 and float(result["border"].replace("px","")) >= 1, result
            assert contrast(result["ink"],result["bg"])>=4.5, result
            assert result["filter"]=="none", result
            open_tool(page,"meeting")
            btn=page.locator("#councilMeetingGenerate").evaluate("""(e)=>{
              const s=getComputedStyle(e);return {bg:s.backgroundColor,fg:s.color};
            }""")
            assert sum(rgba(btn["bg"])[:3])/3 < .3 and contrast(btn["fg"],btn["bg"])>=4.5, btn
        finally:
            ctx.close()
            browser.close()


def test_H_small_labels_photo_button_and_active_theme_across_five_styles(local_url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,local_url,width=1440)
        try:
            for style in STYLES:
                set_style(page,style)
                texts=page.evaluate("""() => ({
                   eyebrow:getComputedStyle(document.querySelector('.council-eyebrow')).fontSize,
                   quote:getComputedStyle(document.querySelector('.council-hero-quote small')).fontSize,
                   tier:getComputedStyle(document.querySelector('.council-tier')).fontSize,
                   title:getComputedStyle(document.querySelector('.council-theme-legend')).fontSize,
                   legendSpace:getComputedStyle(document.querySelector('.council-eyebrow')).letterSpacing
                })""")
                for name in ("eyebrow","quote","tier","title"):
                    assert float(texts[name].replace("px","")) >= 13, (style,texts)
                page.locator("#councilThemeTrigger").click()
                selected=page.locator(f'#councilStyleGroup button[data-style="{style}"]')
                assert selected.get_attribute("aria-checked")=="true"
                decoration=selected.evaluate("""e=>({border:getComputedStyle(e).borderTopWidth,
                  check:getComputedStyle(e,'::after').content})""")
                assert float(decoration["border"].replace("px",""))>=2 and "✓" in decoration["check"],(style,decoration)
                page.locator("#councilThemeTrigger").click()
            open_tool(page,"sns")
            for style in STYLES:
                set_style(page,style)
                m=page.locator("#councilSnsPhotoAdd").evaluate("""e=>{const s=getComputedStyle(e);
                    return {fg:s.color,bg:s.backgroundColor,under:getComputedStyle(e.parentElement.parentElement).backgroundColor};
                }""")
                assert contrast(m["fg"],m["bg"],m["under"])>=4.5,(style,m)
                note=page.locator("#councilSnsPhotoNote").evaluate("e=>getComputedStyle(e).fontSize")
                assert float(note.replace("px",""))>=13,(style,note)
        finally:
            ctx.close()
            browser.close()


def test_I_seven_owner_approved_wording_changes_only():
    html=(STATIC/"index.html").read_text(encoding="utf-8")
    js=(STATIC/"council-app.js").read_text(encoding="utf-8")
    assert "의원실 AI 업무 스튜디오" in html and "국회 AI 업무 스튜디오" not in html
    # #8778 I-2: speech/SNS both call the same reference section; the approved copy is defined once.
    assert js.count("PADIEM PC 연결 프로그램으로 이 컴퓨터에 있는 예전 글을 가져옵니다.") == 1
    assert "PADIEM PC 연결 프로그램으로 이 컴퓨터에 있는 회의 메모를 가져옵니다." in js
    assert "컴퓨터 연결하기" in js
    assert "내 기록에 저장" in js and '\"저장\"' not in (js[js.index("function resultPanel"):js.index("function wireCopy")])
    assert '\"저장된 회의 기록\"' in js
    assert "council-theme-note" not in html
    assert "초안을 만든 뒤 저장하면 여기 모입니다." in js
    assert "인스타그램은 사진을 글과 따로 올립니다. 미리보기에서 사진 순서를 확인하세요." in js


def test_C_speech_meeting_and_activity_book_actions_share_result_controls(local_url):
    # #8778 C: cover the common control contract beyond SNS, across all five styles.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for tool in ("speech", "meeting"):
            ctx, page = open_case(browser, local_url, width=1440, many=(tool == "meeting"))
            try:
                open_tool(page, tool)
                result_ids = ["#councilSpeechResult"] if tool == "speech" else [
                    "#councilMeetingResult", "#councilBookResult",
                ]
                if tool == "meeting":
                    page.locator("#councilBookResult").wait_for(state="attached")
                page.evaluate("""(ids) => ids.forEach(id=>{document.querySelector(id).hidden=false;})""", result_ids)
                for style in STYLES:
                    set_style(page, style)
                    for result_id in result_ids:
                        controls = page.locator(result_id + " .council-actions button")
                        assert controls.count() == 6, (tool, style, result_id)
                        boxes = controls.evaluate_all("""els=>els.map(e=>{
                          const s=getComputedStyle(e),r=e.getBoundingClientRect();
                          return {id:e.id,cls:e.className,height:r.height,border:s.borderTopWidth,radius:s.borderRadius};
                        })""")
                        for b in boxes:
                            assert "council-result-action" in b["cls"], (tool,style,boxes)
                            assert b["height"] >= 44 and b["border"] == "1px", (tool,style,boxes)
                            assert b["radius"] == boxes[0]["radius"], (tool,style,boxes)
            finally:
                ctx.close()
        browser.close()
