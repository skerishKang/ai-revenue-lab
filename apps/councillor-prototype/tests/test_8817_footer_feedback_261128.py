# -*- coding: utf-8 -*-
"""#8817 footer feedback visual and accessible browser contracts."""
import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("B61_CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    out = tmp_path_factory.mktemp("8817-dist")
    subprocess.run([sys.executable, "scripts/build-dist", "--out", str(out)],
                   cwd=ROOT, check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)
        def log_message(self, *_args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            yield browser, f"http://127.0.0.1:{server.server_port}/"
        finally:
            browser.close()
            server.shutdown()
            server.server_close()


def open_feedback(site, width=390, theme="light", capture=None):
    browser, url = site
    context = browser.new_context(viewport={"width": width, "height": 844 if width == 390 else 900},
                                  reduced_motion="reduce", color_scheme="light", device_scale_factor=1)
    context.add_init_script("(theme) => localStorage.setItem('theme',theme)".replace("(theme)", "()").replace("theme)", repr(theme) + ")"))
    page = context.new_page()
    # Never contact the live feedback endpoint, for ANY test state.
    def route_handler(route):
        if capture is not None:
            capture.append(route.request.post_data)
        route.fulfill(status=500, content_type="application/json", body='{"ok":false}',
                      headers={"access-control-allow-origin":"*"})
    page.route("**/api/site-feedback", route_handler)
    page.goto(url, wait_until="load")
    page.locator("#siteFeedbackOpen").click()
    page.evaluate("document.fonts.ready")
    return context, page


def measure(page):
    return page.evaluate("""() => {
      const body=document.querySelector('#siteFeedbackBody');
      const text=document.querySelector('#siteFeedbackStatus');
      const near=document.querySelector('#siteFeedbackError') || text;
      const tab=document.querySelector('.mobile-tabbar');
      const footer=document.querySelector('.site-footer');
      const box=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};
      const css=e=>getComputedStyle(e);
      return {invalid:body.getAttribute('aria-invalid'), describedby:body.getAttribute('aria-describedby'),
        notice:near.textContent.trim(),noticeId:near.id, noticeBox:box(near),
        noticeWeight:css(near).fontWeight,noticeColor:css(near).color,
        border:css(body).borderTopColor,bodyBox:box(body),footerBg:css(footer).backgroundColor,
        statusBox:box(text), statusText:text.textContent.trim(), tabBox:box(tab),
        footerPadding:parseFloat(css(footer).paddingBottom), sendBox:box(document.querySelector('.site-feedback-send'))};
    }""")


def contrast(a, b):
    def rgb(s):
        import re
        channels=[int(x) for x in re.findall(r"\d+", s)[:3]]
        def channel(x):
            x=x/255
            return x/12.92 if x<=0.04045 else ((x+0.055)/1.055)**2.4
        return sum(w*channel(v) for w,v in zip((.2126,.7152,.0722),channels))
    x,y=rgb(a),rgb(b)
    return (max(x,y)+.05)/(min(x,y)+.05)


def test_external_mark_is_once_next_to_link(site):
    context,page=open_feedback(site,1440)
    try:
        result=page.evaluate("""() => {
          const a=[...document.querySelectorAll('.site-feedback-office a')].find(e=>e.textContent.includes('의회 홈페이지로'));
          const p=a.parentElement;
          const after=getComputedStyle(a,'::after').content;
          return {text:p.innerText,link:a.textContent, after, html:p.innerHTML};
        }""")
        count=result["text"].count("↗") + (1 if "↗" in result["after"] else 0)
        assert count == 1, result
        assert result["link"].startswith("의회 홈페이지로"),result
    finally: context.close()


@pytest.mark.parametrize("width,theme",[(390,"light"),(1440,"dark")])
def test_empty_submit_warning_and_input_clears(site,width,theme):
    context,page=open_feedback(site,width,theme)
    try:
        page.locator(".site-feedback-send").click()
        m=measure(page)
        assert m["invalid"]=="true",m
        assert m["describedby"] and m["noticeId"] in m["describedby"].split(),m
        assert m["notice"]=="내용을 적어 주세요.",m
        assert 0 <= m["noticeBox"]["top"]-m["bodyBox"]["bottom"] <= 40,m
        assert contrast(m["border"],m["footerBg"])>=3,m
        assert contrast(m["noticeColor"],m["footerBg"])>=3,m
        assert int(m["noticeWeight"])>=700,m
        page.locator("#siteFeedbackBody").fill("시험")
        after=measure(page)
        assert after["invalid"] is None and after["notice"]!="내용을 적어 주세요.",after
    finally: context.close()


@pytest.mark.parametrize("theme",["light","dark"])
def test_failed_delivery_bottom_clear_of_tab(site,theme):
    called=[]
    context,page=open_feedback(site,390,theme,called)
    try:
        page.locator("#siteFeedbackBody").fill("시험 의견")
        page.locator(".site-feedback-send").click()
        page.wait_for_function("() => document.querySelector('#siteFeedbackStatus').textContent.includes('보내지 못했습니다')")
        page.evaluate("window.scrollTo(0,document.documentElement.scrollHeight)")
        page.wait_for_timeout(100)
        m=measure(page)
        assert len(called)==1,m
        assert m["sendBox"]["bottom"]<m["tabBox"]["top"]-8,m
        assert m["statusBox"]["bottom"]<m["tabBox"]["top"]-8,m
        assert m["footerPadding"]>=m["tabBox"]["height"]+24,m
    finally: context.close()
