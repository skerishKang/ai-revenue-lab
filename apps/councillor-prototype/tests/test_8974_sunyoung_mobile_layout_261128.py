# -*- coding: utf-8 -*-
"""#8974 순영 3회차: 600px 이하 사진 보기 창·정책자료 카드 실측 회귀."""
from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "design-8974" / "baseline.json"
CHROME = next((str(p) for p in (os.environ.get("B61_CHROME_PATH"),
               r"C:\Program Files\Google\Chrome\Application\chrome.exe")
               if p and Path(p).is_file()), None)


@pytest.fixture(scope="module")
def site():
    if sync_playwright is None or CHROME is None:
        pytest.skip("브라우저가 없는 CI에서는 정적 계약 시험만 실행")
    assert BASELINE.is_file(), "수정 전 직접 측정한 기준 파일 필요"
    subprocess.run([sys.executable,str(ROOT/"scripts"/"build-dist")],check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(ROOT/"dist"),**kwargs)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=CHROME)
            try:
                yield browser,f"http://127.0.0.1:{server.server_port}",json.loads(BASELINE.read_text(encoding="utf-8"))
            finally:browser.close()
    finally:
        server.shutdown();server.server_close()


def page_at(site,name,width,theme="light"):
    browser,origin,_baseline=site
    page=browser.new_page(viewport={"width":width,"height":844 if width<=600 else 900},
                          device_scale_factor=1,reduced_motion="reduce",color_scheme="light")
    page.goto(f"{origin}/{name}.html",wait_until="load")
    page.evaluate("(theme)=>document.documentElement.dataset.theme=theme",theme)
    page.evaluate("document.fonts.ready")
    return page


def lightbox(page):
    page.locator(".media-tile").nth(1).click()
    page.locator("#mediaLightbox[open]").wait_for()
    page.locator("#lightboxImg").evaluate("img=>img.decode()")
    return page.evaluate("""() => {
      const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();
          return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
      return {photo:rect('lightboxImg'),prev:rect('lightboxPrev'),
        next:rect('lightboxNext'),close:rect('lightboxClose'),link:rect('lightboxLink')};
    }""")


def policy_card(page):
    return page.evaluate("""() => {
      const card=document.querySelector('#policyForums .info-card');
      const video=document.querySelector('#policyVideos .info-card');
      const number=card.querySelector('.card-num'),title=card.querySelector('h3'),
            paragraph=card.querySelector('p:not(.policy-meta)'),meta=card.querySelector('.policy-meta');
      const font=e=>getComputedStyle(e).fontSize;
      return {height:card.getBoundingClientRect().height,
        number:parseFloat(font(number)),body:font(paragraph),title:font(title),
        meta:font(meta),paddingTop:parseFloat(getComputedStyle(card).paddingTop),
        paddingBottom:parseFloat(getComputedStyle(card).paddingBottom),
        videoNumber:parseFloat(font(video.querySelector('.card-num'))),
        videoPaddingTop:parseFloat(getComputedStyle(video).paddingTop),
        text:card.innerText,videoText:video.innerText,
        overflowX:document.documentElement.scrollWidth-innerWidth};
    }""")


@pytest.mark.parametrize("width,theme",[(390,"light"),(390,"dark"),(360,"light")])
def test_mobile_photo_full_width_below_navigation_and_focus_order(site,width,theme):
    page=page_at(site,"media",width,theme)
    try:
        result=lightbox(page)
        img=result["photo"]; prev=result["prev"];nxt=result["next"]
        assert img["width"] >= width - 33, result   # 화면 폭 - 32px (오차 1px)
        assert img["x"] >= 15 and img["right"] <= width - 15, result
        assert 0 <= img["y"] and img["bottom"] <= 844, result
        assert prev["y"] >= img["bottom"] + 1 and nxt["y"] >= img["bottom"] + 1, result
        assert abs(prev["y"]-nxt["y"]) < 2, result
        assert min(prev["width"],prev["height"],nxt["width"],nxt["height"]) >= 44, result
        gap=nxt["x"]-prev["right"]
        assert abs(gap-24) <= 2, (width,gap,result)
        assert result["link"]["bottom"] <= 844, result
        # 실제 키보드 탭 순서: 닫기 → 이전 → 다음 → 의회 원문 보기.
        page.locator("#lightboxClose").focus()
        order=[page.evaluate("document.activeElement.id")]
        for _ in range(3):
            page.keyboard.press("Tab")
            order.append(page.evaluate("document.activeElement.id"))
        assert order == ["lightboxClose","lightboxPrev","lightboxNext","lightboxLink"],order
    finally:page.close()


def test_390_policy_cards_shorter_with_smaller_numbers_and_same_text(site):
    page=page_at(site,"policy",390)
    try:
        result=policy_card(page)
        before=site[2]["policy"]["390"]
        assert result["height"] <= before["cardHeight"]-24,(before["cardHeight"],result["height"])
        assert result["number"] <= float(before["number"]["fontSize"].replace("px",""))*.62,result
        assert result["videoNumber"] <= float(before["videoNumber"]["fontSize"].replace("px",""))*.62,result
        assert abs(result["paddingTop"]-16) <= 2 and abs(result["paddingBottom"]-16) <= 2,result
        assert abs(result["videoPaddingTop"]-16) <= 2,result
        assert result["body"] == before["paragraph"]["fontSize"],result
        assert result["title"] == before["title"]["fontSize"],result
        assert result["meta"] == before["meta"]["fontSize"],result
        assert result["text"] == before["cardText"] and result["videoText"] == before["videoText"]
        assert result["overflowX"] <= 0,result
    finally:page.close()


@pytest.mark.parametrize("width",[820,1440])
def test_larger_photo_and_policy_card_unchanged(site,width):
    baseline=site[2]
    photo=page_at(site,"media",width)
    policy=page_at(site,"policy",width)
    try:
        current=lightbox(photo)
        previous=baseline["photos"][f"{width}-light"]
        for key in ("photo","prev","next","close","link"):
            for dim in ("x","y","width","height"):
                assert abs(current[key][dim] - previous[key][dim]) <= 1, (width,key,dim,current[key],previous[key])
        current_card=policy_card(policy)
        prior=baseline["policy"][str(width)]
        assert abs(current_card["height"]-prior["cardHeight"])<=1,(width,current_card,prior)
        assert current_card["number"]==float(prior["number"]["fontSize"].replace("px",""))
        assert current_card["body"]==prior["paragraph"]["fontSize"]
        assert current_card["title"]==prior["title"]["fontSize"]
        assert current_card["text"]==prior["cardText"]
        assert current_card["videoText"]==prior["videoText"]
    finally:
        photo.close();policy.close()
