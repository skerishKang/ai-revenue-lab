# -*- coding: utf-8 -*-
"""#8815: news heading matches activity geometry, and news text stays readable."""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
CHROME = next((p for p in (
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if p and Path(p).is_file()), None)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if sync_playwright is None or CHROME is None:
        pytest.skip("Playwright/Chrome unavailable")
    out = tmp_path_factory.mktemp("8815-dist")
    result = subprocess.run([sys.executable, "scripts/build-dist", "--out", str(out)],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)
        def log_message(self, *_args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=CHROME)
            try:
                yield browser, f"http://127.0.0.1:{server.server_port}/"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def open_page(site, name, width=1440, theme="light", large=False):
    browser, url = site
    page = browser.new_page(viewport={"width":width,"height":900 if width==1440 else 844},
                            color_scheme="light", reduced_motion="reduce", device_scale_factor=1)
    page.add_init_script("localStorage.setItem('theme',"+repr(theme)+");")
    if large:
        page.add_init_script("localStorage.setItem('textSize','large');")
    page.goto(url+name+".html", wait_until="load")
    if large and page.locator("#textSizeToggle").get_attribute("aria-pressed")!="true":
        page.locator("#textSizeToggle").click()
    page.evaluate("document.fonts.ready")
    return page


def heading(page):
    return page.evaluate("""() => {
      const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};};
      const st=el=>getComputedStyle(el);
      const main=document.querySelector('main.section');
      const title=main.querySelector('h1.section-title');
      const lead=title.nextElementSibling;
      const eyebrow=title.previousElementSibling;
      return {title:box(title),titlePx:parseFloat(st(title).fontSize),
        eyebrowClass:eyebrow.className,eyebrowText:eyebrow.textContent.trim(),
        eyebrowBox:box(eyebrow), eyebrowMargin:parseFloat(st(eyebrow).marginBottom),
        leadClass:lead.className,lead:box(lead),leadColor:st(lead).color,
        leadMargin:parseFloat(st(lead).marginBottom),
        main:box(main),bodyOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
    }""")


@pytest.mark.parametrize("width,theme,large", [
    (1440,"light",False), (390,"dark",False), (1440,"light",True),
])
def test_news_header_matches_activity_with_approved_eyebrow_text(site,width,theme,large):
    news=open_page(site,"news",width,theme,large)
    activity=open_page(site,"activity",width,theme,large)
    try:
        a=heading(activity); n=heading(news)
        assert abs(n["title"]["y"]-a["title"]["y"])<=1, (width,theme,large,n,a)
        assert abs(n["titlePx"]-a["titlePx"])<=1, (width,theme,large,n,a)
        assert n["eyebrowClass"].split()[0]=="section-eyebrow", n
        assert n["eyebrowText"]=="알림",n
        assert n["eyebrowClass"]=="section-eyebrow",n
        assert news.locator("main .section-eyebrow").get_attribute("aria-hidden") is None
        assert n["leadClass"]=="section-lead",n
        assert n["leadColor"]==a["leadColor"],(width,theme,large,n,a)
        assert abs(n["leadMargin"]-a["leadMargin"])<=1,(width,theme,large,n,a)
        assert n["bodyOverflow"]<=1,n
    finally:
        news.close();activity.close()


@pytest.mark.parametrize("large",[False,True])
def test_news_text_at_most_40em_but_card_and_header_unchanged(site,large):
    page=open_page(site,"news",1440,"light",large)
    try:
        m=page.evaluate("""() => {
          const item=document.querySelector('.site-change');
          const li=item.querySelector('li');
          const title=item.querySelector('h2');
          const date=item.querySelector('time');
          const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
          const cs=getComputedStyle(li);
          return {card:box(item),line:box(li),title:box(title),date:box(date),
            lineFont:parseFloat(cs.fontSize),lineLimit:cs.maxWidth,
            horizontalOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
        }""")
        assert m["lineLimit"]!="none",m
        assert m["line"]["width"]<=40*m["lineFont"]+1,m
        assert m["card"]["width"]>=800,m
        assert m["title"]["width"]>0 and m["date"]["width"]>0,m
        assert m["horizontalOverflow"]<=1,m
    finally:
        page.close()
