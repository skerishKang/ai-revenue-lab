# -*- coding: utf-8 -*-
"""#8809: 의정활동 상세 제목 초점·본문 줄 폭·공식 링크/공유 단추."""
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
CHROME = next((p for p in (os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe") if p and Path(p).is_file()), None)

@pytest.fixture(scope="module")
def site():
    if sync_playwright is None or CHROME is None:
        pytest.skip("Playwright/Chrome unavailable")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build-dist")], check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=CHROME)
            try:
                yield browser, f"http://127.0.0.1:{server.server_port}/activity.html"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def open_detail(site, width=1440, theme="light"):
    browser,url=site
    page=browser.new_page(viewport={"width":width,"height":900 if width==1440 else 844},
        color_scheme="light", reduced_motion="reduce", device_scale_factor=1)
    page.goto(url, wait_until="load")
    page.evaluate("(theme)=>{document.documentElement.dataset.theme=theme}",theme)
    page.locator("#activityList > .activity-item").first.click()
    page.wait_for_function("""() => document.activeElement?.id==='detailTitle' &&
          !document.querySelector('#activityDetail').hidden""")
    page.evaluate("document.fonts.ready")
    return page


def details(page):
    return page.evaluate("""() => {
        const box=el=>{const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
        const cs=el=>getComputedStyle(el);
        const heading=document.querySelector('#detailTitle');
        const paragraph=document.querySelector('#detailBody p');
        const terms=document.querySelector('#detailTerms');
        const termLine=terms.querySelector('p');
        const meta=document.querySelector('#detailDate');
        const link=document.querySelector('#detailLink');
        const share=document.querySelector('#activityShare');
        const button=el=>({box:box(el), display:cs(el).display, border:cs(el).borderTopWidth,
          radius:cs(el).borderTopLeftRadius, weight:cs(el).fontWeight,
          decoration:cs(el).textDecorationLine, minHeight:cs(el).minHeight,
          color:cs(el).color, bg:cs(el).backgroundColor});
        const reading=el=>el?({box:box(el),maxWidth:cs(el).maxWidth,
          fontPx:parseFloat(cs(el).fontSize)}):null;
        return {active:document.activeElement?.id,tabindex:heading.getAttribute('tabindex'),
          outline:cs(heading).outlineStyle, outlineWidth:cs(heading).outlineWidth,
          heading:box(heading), container:box(document.querySelector('#activityDetail')),
          meta:reading(meta),paragraph:reading(paragraph),
          terms:reading(terms),termLine:reading(termLine),termsHidden:terms.hidden,
          link:button(link),share:button(share),
          overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
          textLink:link.textContent.trim(),textShare:share.textContent.trim()};
    }""")


def test_mouse_open_focuses_heading_but_without_outline_and_link_keeps_keyboard_outline(site):
    page=open_detail(site)
    try:
        state=details(page)
        assert state["active"]=="detailTitle",state
        assert state["tabindex"]=="-1",state
        assert state["outline"]=="none" or state["outlineWidth"]=="0px",state
        assert state["link"]["display"]!="none",state
        # 키보드 입력 뒤 제목이 다시 초점을 받아도 초점 네모는 없어야 한다.
        page.keyboard.press("Tab")
        page.locator("#detailTitle").focus()
        keyboard_heading=page.locator("#detailTitle").evaluate("""e => ({
            visible:e.matches(':focus-visible'), style:getComputedStyle(e).outlineStyle,
            width:getComputedStyle(e).outlineWidth})""")
        assert keyboard_heading["style"]=="none" or keyboard_heading["width"]=="0px",keyboard_heading
        # 제목으로 옮겨진 초점은 유지하고, Tab으로 실제 링크에 접근할 수 있어야 한다.
        page.keyboard.press("Tab")
        link=page.locator("#detailLink")
        assert page.evaluate("document.activeElement?.id")=="detailLink"
        focus=link.evaluate("""e=>({outline:getComputedStyle(e).outlineStyle,
            width:parseFloat(getComputedStyle(e).outlineWidth),
            focusVisible:e.matches(':focus-visible')})""")
        assert focus["focusVisible"] and focus["outline"]!="none" and focus["width"]>=2,focus
    finally:
        page.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_detail_reading_lines_at_most_40em_and_box_width_preserved(site,width):
    page=open_detail(site,width=width)
    try:
        m=details(page)
        assert m["paragraph"] is not None,m
        for name in ("paragraph","meta","terms","termLine"):
            line=m[name]
            if line is None: continue
            assert line["maxWidth"] != "none", (name,m)
            max_px=float(line["fontPx"])*40
            assert line["box"]["width"] <= max_px + 1,(name,max_px,line)
        assert m["container"]["width"] > 800 if width==1440 else m["container"]["width"]>250,m
        assert m["heading"]["width"] > 800 if width==1440 else m["heading"]["width"]>250,m
        assert m["overflow"]<=0,m
    finally:
        page.close()


@pytest.mark.parametrize("theme",["light","dark"])
@pytest.mark.parametrize("width", [390,1440])
def test_detail_actions_same_border_rounding_weight_height_and_spacing(site,theme,width):
    page=open_detail(site,width=width,theme=theme)
    try:
        state=details(page)
        link,share=state["link"],state["share"]
        assert state["textLink"] and state["textShare"],state
        for key in ("border","radius","weight"):
            assert link[key]==share[key],(theme,width,key,state)
        assert link["border"]=="1px",state
        assert link["radius"]=="999px",state
        assert link["weight"] in ("600","700"),state
        assert link["decoration"]=="none",state
        assert link["box"]["height"]>=44 and share["box"]["height"]>=44,state
        assert abs(link["box"]["height"]-share["box"]["height"])<=1,state
        gap=share["box"]["x"]-link["box"]["right"]
        assert 10 <= gap <=14,(theme,width,gap,state)
        assert state["overflow"]<=0,state
    finally:
        page.close()


def test_no_new_important_and_unchanged_header_list():
    css=(ROOT/"static"/"styles.css").read_text(encoding="utf-8")
    assert css.count("!important")<=5
    source=(ROOT/"activity.html").read_text(encoding="utf-8")
    assert 'id="detailTitle" tabindex="-1"' in source
