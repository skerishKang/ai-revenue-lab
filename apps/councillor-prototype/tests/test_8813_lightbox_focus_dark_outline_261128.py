# -*- coding: utf-8 -*-
"""#8813: lightbox keyboard focus and the dark outlined-control contrast floor."""
from __future__ import annotations

import http.server
import os
import re
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
CHROME = next((v for v in (
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if v and Path(v).is_file()), None)
PAGES = ("index.html", "about.html", "activity.html", "policy.html",
         "media.html", "news.html", "404.html")
CONTROL = (".topbar .ghost, .detail-link, .share-btn, "
           ".btn.secondary, .col-tile, .policy-jump a, "
           ".home-search-go, .home-search-alt, "
           ".site-feedback-open, .site-feedback-again")
MODAL_TARGETS = ("lightboxClose", "lightboxPrev", "lightboxNext", "lightboxLink")


def parse_color(s):
    vals = list(map(float, re.findall(r"\d+(?:\.\d+)?", s)))
    assert len(vals) in (3, 4), s
    return vals[:3] + ([vals[3]] if len(vals) == 4 else [1.0])


def combine(top, bottom):
    return [top[k]*top[3]+bottom[k]*(1-top[3]) for k in range(3)]


def contrast(foreground, background):
    def lum(col):
        scaled = [n/255 for n in col[:3]]
        linear = [n/12.92 if n<=0.04045 else ((n+0.055)/1.055)**2.4 for n in scaled]
        return sum(x*w for x,w in zip(linear, (0.2126,0.7152,0.0722)))
    a,b = sorted((lum(foreground),lum(background)),reverse=True)
    return (a+0.05)/(b+0.05)


def contrast_of(border, background):
    bg = parse_color(background)[:3]
    fg = combine(parse_color(border), bg)
    return contrast(fg,bg)


@pytest.fixture(scope="module")
def site():
    if sync_playwright is None or CHROME is None:
        pytest.skip("Playwright/Chrome unavailable")
    subprocess.run([sys.executable, str(ROOT/"scripts"/"build-dist")], check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(ROOT/"dist"),**kwargs)
        def log_message(self,*args): pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1",0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True, executable_path=CHROME)
            try:
                yield browser,f"http://127.0.0.1:{server.server_port}"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def page_at(site,filename="media.html",width=1440,theme="dark"):
    browser,origin=site
    page=browser.new_page(viewport={"width":width,"height":844 if width<=600 else 900},
                          reduced_motion="reduce",color_scheme="light",
                          device_scale_factor=1)
    page.goto(f"{origin}/{filename}",wait_until="load")
    page.evaluate("(theme)=>document.documentElement.dataset.theme=theme",theme)
    page.evaluate("document.fonts.ready")
    return page


def focus_measure(page,id):
    page.keyboard.press("Tab")
    for _ in range(12):
        result=page.evaluate("""id => {
            const e=document.getElementById(id);
            if(document.activeElement!==e)return null;
            const style=getComputedStyle(e);
            const root=getComputedStyle(document.getElementById('mediaLightbox'));
            return {id,focused:true,keyboard:e.matches(':focus-visible'),
                    color:style.outlineColor,style:style.outlineStyle,
                    width:parseFloat(style.outlineWidth),
                    offset:parseFloat(style.outlineOffset),
                    background:root.backgroundColor};
        }""",id)
        if result:
            return result
        page.keyboard.press("Tab")
    raise AssertionError(f"Tab navigation never reached {id}")


@pytest.mark.parametrize("theme",["light","dark"])
@pytest.mark.parametrize("width",[390,1440])
def test_modal_keyboard_focus_close_prev_next_source_link(site,width,theme):
    page=page_at(site,width=width,theme=theme)
    try:
        page.locator("#mediaGrid [data-media-thumb]").first.click()
        page.locator("#mediaLightbox[open]").wait_for()
        for target in MODAL_TARGETS:
            m=focus_measure(page,target)
            assert m["keyboard"],(theme,width,m)
            assert m["style"]!="none" and m["width"]==2,(theme,width,m)
            assert m["offset"]==2,(theme,width,m)
            assert contrast_of(m["color"],m["background"])>=3,(theme,width,m)
    finally:page.close()


def measured_controls(page):
    return page.evaluate("""selector => {
      const targets=[...document.querySelectorAll(selector)];
      const rgba=s=>{const nums=(s.match(/[\\d.]+/g)||[]).map(Number);
          return [nums[0]||0,nums[1]||0,nums[2]||0,nums.length===4?nums[3]:1]};
      const composite=(over,below)=>[
        ...[0,1,2].map(i=>over[i]*over[3]+below[i]*(1-over[3])),1];
      const backing=e=>{
        let stack=[];
        for(let n=e;n;n=n.parentElement)stack.unshift(n);
        let result=[11,26,46,1];
        for(const n of stack)result=composite(rgba(getComputedStyle(n).backgroundColor),result);
        return 'rgb('+result.slice(0,3).map(x=>Math.round(x)).join(', ')+')';
      };
      return targets.filter(e=>{
          const s=getComputedStyle(e),r=e.getBoundingClientRect();
          return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;
      }).map(e=>({selector:e.className||e.id,
          text:(e.innerText||'').trim().slice(0,40),
          policyChip:e.matches('.policy-jump a'),
          border:getComputedStyle(e).borderTopColor,
          borderWidth:getComputedStyle(e).borderTopWidth,
          bg:backing(e)}));
    }""",CONTROL)


@pytest.mark.parametrize("filename",PAGES)
@pytest.mark.parametrize("width",[390,1440])
def test_every_visible_dark_outlined_control_border_at_least_3(site,filename,width):
    page=page_at(site,filename,width,"dark")
    try:
        if filename=="activity.html":
            page.locator("#activityList > .activity-item").first.click()
            page.wait_for_function("() => !document.querySelector('#activityDetail').hidden")
        controls=measured_controls(page)
        assert controls,(filename,width)
        for item in controls:
            assert float(item["borderWidth"].removesuffix("px"))>=1,(filename,width,item)
            assert contrast_of(item["border"],item["bg"])>=3,(filename,width,item)
        if filename=="index.html" and width==1440:
            assert any("col-tile" in x["selector"] for x in controls),controls
        if filename=="policy.html":
            assert any(x["policyChip"] for x in controls),controls
        if filename=="activity.html":
            assert any("share-btn" in x["selector"] for x in controls),controls
    finally:page.close()


@pytest.mark.parametrize("filename",PAGES)
def test_light_theme_outline_border_remains_original(site,filename):
    page=page_at(site,filename,1440,"light")
    try:
        if filename=="activity.html":
            page.locator("#activityList > .activity-item").first.click()
            page.wait_for_function("() => !document.querySelector('#activityDetail').hidden")
        data=measured_controls(page)
        expected={
            "ghost":"rgba(11, 26, 46, 0.12)",
            "detail-link":"rgb(0, 72, 132)",
            "share-btn":"rgb(0, 72, 132)",
            "col-tile":"rgba(11, 26, 46, 0.12)",
            "policy-jump":"rgba(11, 26, 46, 0.12)",
            "secondary":"rgba(11, 26, 46, 0.22)",
        }
        for element in data:
            for css, color in expected.items():
                if css in element["selector"]:
                    assert element["border"]==color,(filename,element)
    finally:page.close()


def test_no_added_important_or_new_stylesheets():
    css=(ROOT/"static"/"styles.css").read_text(encoding="utf-8")
    assert css.count("!important")<=5
