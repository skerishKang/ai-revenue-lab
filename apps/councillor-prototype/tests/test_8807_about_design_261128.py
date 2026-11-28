# -*- coding: utf-8 -*-
"""#8807 의원 소개 디자인 실측 회귀 — CTO 고칠 것 1~5."""
from pathlib import Path
import re
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static/styles.css").read_text(encoding="utf-8")
PAGES = ["index.html", "about.html", "activity.html", "policy.html",
         "media.html", "news.html", "404.html"]

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright unavailable")
    subprocess.run(["python", str(ROOT / "scripts/build-dist")], check=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        yield b
        b.close()

def open_page(browser, name="about.html", width=1440, theme="light"):
    page = browser.new_page(viewport={"width": width, "height": 844})
    page.goto((ROOT / "dist" / name).as_uri(), wait_until="load")
    page.evaluate("(theme) => { document.documentElement.dataset.theme = theme; localStorage.setItem('theme', theme); }", theme)
    return page

def metrics(page):
    return page.evaluate("""() => {
      const box = selector => { let r = document.querySelector(selector).getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}; };
      const photo = document.querySelector('.intro-photo');
      const bio = document.querySelector('.intro-bio p');
      const style = getComputedStyle(bio);
      return {photo:box('.intro-photo'),bio:box('.intro-bio p'),title:box('.section-title'),
        grid:getComputedStyle(document.querySelector('.intro-grid')).gridTemplateColumns,
        gap:getComputedStyle(document.querySelector('.intro-grid')).columnGap,
        bg:getComputedStyle(photo).backgroundColor, color:style.color,
        token:getComputedStyle(document.documentElement).getPropertyValue('--text').trim(),
        size:style.fontSize,lineHeight:style.lineHeight,maxWidth:style.maxWidth,
        video:box('.intro-video'),videoActual:document.querySelector('.intro-video video') ? box('.intro-video video') : null};
    }""")

@pytest.mark.parametrize("width,expected", [(1440,360),(820,280)])
def test_photo_side_by_side(browser,width,expected):
    page=open_page(browser,width=width)
    m=metrics(page)
    assert abs(m["photo"]["width"]-expected)<=1, m
    assert m["bio"]["x"]>=m["photo"]["x"]+expected, m
    assert abs(m["photo"]["height"]/m["photo"]["width"]-1.25)<.02, m
    if width==1440:
        assert abs(float(m["gap"].replace("px",""))-48)<1, m
    page.close()

def test_phone_first_line_visible(browser):
    page=open_page(browser,width=390)
    m=metrics(page)
    assert m["photo"]["height"]<=360.5, m
    assert abs(m["photo"]["height"]/m["photo"]["width"]-1.25)<.03, m
    assert m["title"]["bottom"]<m["photo"]["y"], m
    assert m["bio"]["y"] < 844, m
    page.close()

def test_photo_background_same_theme(browser):
    values=[]
    for theme in ("light","dark"):
        page=open_page(browser,width=820,theme=theme)
        values.append(metrics(page)["bg"])
        page.close()
    assert values[0]==values[1], values

@pytest.mark.parametrize("theme",["light","dark"])
def test_body_type(browser,theme):
    page=open_page(browser,theme=theme)
    m=metrics(page)
    token=page.evaluate("getComputedStyle(document.body).color")
    assert m["size"]=="17px", m
    assert abs(float(m["lineHeight"].replace("px",""))/17-1.75)<.02, m
    assert m["color"]==token, m
    assert m["bio"]["width"] <= 680.5, m
    page.close()

def test_video_width(browser):
    page=open_page(browser)
    page.evaluate("""() => { const el=document.querySelector(".intro-video"); el.hidden=false; if (!el.querySelector("video")) el.innerHTML="<video></video><p class=\\"intro-video-title\\">소개 영상</p><p class=\\"source-note\\">출처</p>"; }""")
    box=page.locator(".intro-video").bounding_box()
    assert box is not None
    assert box["width"]<=880.5,box
    assert abs(box["x"]-page.locator(".section-inner").bounding_box()["x"])<=1,box
    page.close()

@pytest.mark.parametrize("width",[481,820,1440])
def test_shared_header(browser,width):
    starts=[]
    for name in PAGES:
        page=open_page(browser,name,width)
        cta=page.locator(".topbar .top-cta")
        assert cta.count()==1,(name,cta.count())
        assert cta.is_visible(),(name,width)
        if page.locator(".top-nav").is_visible():
            starts.append((name,page.locator(".top-nav").bounding_box()["x"]))
        page.close()
    if starts:
        assert max(x for _,x in starts)-min(x for _,x in starts)<=1,starts

def test_no_new_important():
    assert CSS.count("!important")<=5
