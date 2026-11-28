# -*- coding: utf-8 -*-
"""#8811: media grid, first-viewport readability, shared beige portrait."""
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
CHROME = next((Path(x) for x in (
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if x and Path(x).exists()), None)


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
            browser = pw.chromium.launch(headless=True, executable_path=str(CHROME))
            try:
                yield browser, f"http://127.0.0.1:{server.server_port}"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def page_at(site, width=390, theme="light", filename="media.html"):
    browser, origin = site
    page = browser.new_page(viewport={"width":width,"height":844 if width <= 600 else 900},
                            reduced_motion="reduce", color_scheme="light",
                            device_scale_factor=1)
    page.goto(f"{origin}/{filename}", wait_until="load")
    page.evaluate("(theme) => document.documentElement.dataset.theme=theme", theme)
    page.locator("#mediaGrid .media-card").first.wait_for(state="visible") if filename=="media.html" else None
    return page


@pytest.mark.parametrize("width,columns",[(390,1),(600,1),(601,2),(820,2),(1100,2),(1101,3),(1440,3)])
def test_media_column_count_and_card_width(site,width,columns):
    page=page_at(site,width)
    try:
        data=page.evaluate("""() => {
            const grid=document.querySelector('#mediaGrid');
            const r=grid.getBoundingClientRect();
            const cards=[...grid.querySelectorAll('.media-card')].slice(0,3);
            return {cols:getComputedStyle(grid).gridTemplateColumns.split(/\\s+/).length,
                width:r.width, first:cards[0].getBoundingClientRect().width,
                overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
                photo:getComputedStyle(cards[0].querySelector('.tile-thumb')).aspectRatio};
        }""")
        assert data["cols"]==columns,(width,data)
        if columns==1:
            assert data["first"] >= data["width"]-1,(width,data)
            assert data["photo"]=="4 / 3",(width,data)
        assert data["overflow"]<=0,(width,data)
    finally:
        page.close()


def test_first_media_photo_and_title_visible_in_first_phone_viewport(site):
    page=page_at(site,390)
    try:
        value=page.evaluate("""() => {
            const card=document.querySelector('#mediaGrid .media-card');
            const img=card.querySelector('.tile-thumb').getBoundingClientRect();
            const title=card.querySelector('.tile-title').getBoundingClientRect();
            return {imgTop:img.top,imgBottom:img.bottom,titleTop:title.top,titleBottom:title.bottom,
                photoVisibility:getComputedStyle(card.querySelector('.tile-thumb')).visibility};
        }""")
        assert value["imgTop"]>=0 and value["imgBottom"]<=844,value
        assert value["titleTop"]>=value["imgBottom"] and value["titleBottom"]<=844,value
        assert value["photoVisibility"]=="visible",value
    finally:
        page.close()


@pytest.mark.parametrize("theme",["light","dark"])
@pytest.mark.parametrize("width",[390,820,1440])
def test_profile_media_beige_matches_about_background_without_crop(site,width,theme):
    media=page_at(site,width,theme)
    about=page_at(site,width,theme,"about.html")
    try:
        profile=media.locator('#mediaGrid .media-card:has(.tile-thumb[src*="profile-portrait"]) .tile-thumb')
        assert profile.count()==1,(width,theme)
        value=profile.evaluate("""img=>({background:getComputedStyle(img).backgroundColor,
            fit:getComputedStyle(img).objectFit,position:getComputedStyle(img).objectPosition,
            ratio:getComputedStyle(img).aspectRatio,src:img.currentSrc})""")
        about_bg=about.locator('.intro-photo').evaluate("e=>getComputedStyle(e).backgroundColor")
        assert value["background"]==about_bg,(width,theme,value,about_bg)
        assert value["fit"]=="contain",(width,theme,value)
        assert value["position"] in ("50% 50%", "center center"),(width,theme,value)
    finally:
        media.close();about.close()


def test_no_new_important():
    css=(ROOT/"static"/"styles.css").read_text(encoding="utf-8")
    assert css.count("!important")<=5


@pytest.mark.parametrize("width",[390,1440])
def test_new_profile_file_shared_and_opaque_person_pixels_unchanged(site,width):
    media=page_at(site,width)
    about=page_at(site,width,filename="about.html")
    try:
        current=media.locator('#mediaGrid .tile-thumb[src*="profile-portrait"]').evaluate("e=>e.currentSrc")
        intro=about.locator(".intro-photo").evaluate("e=>e.currentSrc")
        assert "profile-portrait-beige" in current,(width,current)
        assert "profile-portrait-beige" in intro,(width,intro)
        # 두 사진을 같은 origin의 캔버스로 디코딩해 알파 255 사람 화소를 정확히 비교.
        diff=media.evaluate("""async()=>{
          const load=async src=>{const img=new Image();img.src=src;await img.decode();return img;};
          const original=await load('./static/images/profile-portrait.webp');
          const cleaned=await load('./static/images/profile-portrait-beige.webp');
          const read=img=>{
            const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
            const cx=c.getContext('2d',{willReadFrequently:true});cx.drawImage(img,0,0);
            return cx.getImageData(0,0,c.width,c.height).data;
          };
          const a=read(original),b=read(cleaned);
          let opaque=0,changed=0;
          for(let i=0;i<a.length;i+=4){
            if(a[i+3]!==255)continue;
            opaque++;
            if(a[i]!==b[i]||a[i+1]!==b[i+1]||a[i+2]!==b[i+2])changed++;
          }
          return {opaque,changed};
        }""")
        assert diff["opaque"]>=200000,diff
        assert diff["changed"]==0,diff
    finally:
        media.close();about.close()

def test_shared_profile_json_does_not_corrupt_327th_speech():
    import json
    raw=(ROOT / "static" / "miraen.json").read_bytes()
    text=raw.decode("utf-8", errors="strict")
    assert b"\r" not in raw
    assert "\ufffd" not in text
    data=json.loads(text)
    item=next(v for v in data["policy"]["videos"]
              if v.get("title")=="제327회 5분자유발언")
    assert "진행한" in item["summary"]
    assert sum(m.get("thumb")=="./static/images/profile-portrait-beige.webp"
               for m in data["media"]["tiles"])==1
