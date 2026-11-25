# -*- coding: utf-8 -*-
"""#7575 batch two — measured layout, not string presence.

Playwright drives the shipped static entry with a stubbed auth-status response,
then reads boxes and computed styles at 1440 / 768 / 390.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def rgb(value):
    # Chromium serialises color-mix() as color(srgb r g b) with 0..1 channels.
    if value.startswith("color("):
        return [round(float(n) * 255) for n in
                value.replace("color(srgb", "").replace(")", "").split()[:3]]
    return [int(float(n)) for n in value.replace("rgba(", "").replace("rgb(", "")
            .replace(")", "").split(",")[:3]]


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def translate_path(self, path):
        # The entry's absolute /static/... references must resolve inside this app.
        if path.startswith("/static/"):
            path = path[len("/static"):]
        elif path.startswith("/static"):
            path = "/index.html"
        elif path == "/" or path == "/index.html" or not path.startswith("/api"):
            path = "/index.html"
        return super().translate_path(path)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()


def _ready(page, url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/auth/status", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"authenticated":true,"methods":{"password":true},"member_grade":"free"}'))
    page.route("**/api/chat/stream", lambda route: route.fulfill(
        status=200, content_type="text/event-stream",
        body='event: delta\ndata: {"delta":"초안이 준비됐습니다."}\n\nevent: done\ndata: {"done":true}\n\n'))
    page.goto(url, wait_until="load")
    page.wait_for_selector("#councilHeroTitle")
    page.wait_for_timeout(250)


def _open(page, tool):
    page.locator('.council-card-select[data-tool="%s"]' % tool).click()
    page.wait_for_timeout(200)


def test_9_one_header_and_visible_first_field(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height, ceiling in ((1440, 900, 400), (390, 844, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            try:
                _ready(page, url, width, height)
                _open(page, "speech")
                m = page.evaluate("""() => {
                  const card = document.querySelector('.council-card.active');
                  const field = document.querySelector('#councilSpeechForm input');
                  const hidden = (sel) => getComputedStyle(card.querySelector(sel)).display === 'none';
                  return {firstTop: Math.round(field.getBoundingClientRect().top),
                    banner: !document.getElementById('councilWorkspaceBar').hidden,
                    h2Hidden: hidden('h2'), buttonHidden: hidden('.council-card-select'),
                    exits: document.querySelectorAll('#councilBack').length};
                }""")
                assert m["firstTop"] <= ceiling, (width, m)
                assert m["banner"] and m["h2Hidden"] and m["buttonHidden"] and m["exits"] == 1, m
            finally:
                page.close()
        browser.close()


def test_10_entry_width_and_result_columns(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            _ready(page, url, 1440, 900)
            _open(page, "speech")
            before = page.evaluate("""() => {const r=document.getElementById('councilSpeechForm').getBoundingClientRect();
              return {w:Math.round(r.width), left:Math.round(r.left), right:Math.round(r.right), resultHidden:document.getElementById('councilSpeechResult').hidden};}""")
            assert before["resultHidden"] and 600 <= before["w"] <= 760, before
            page.fill('#councilSpeechForm [name=event]', "넓은 화면 확인")
            page.click("#councilSpeechGenerate")
            page.wait_for_timeout(300)
            after = page.evaluate("""() => {const f=document.getElementById('councilSpeechForm').getBoundingClientRect();
              const r=document.getElementById('councilSpeechResult').getBoundingClientRect();
              return {formRight:Math.round(f.right), resultLeft:Math.round(r.left), resultVisible:!document.getElementById('councilSpeechResult').hidden};}""")
            assert after["resultVisible"] and after["resultLeft"] >= after["formRight"], after
        finally:
            page.close()
        browser.close()


def test_11_result_grows_and_sns_has_one_view(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            _ready(page, url, 390, 844)
            _open(page, "meeting")
            page.evaluate("() => document.getElementById('councilMeetingResult').hidden = false")
            page.evaluate("""() => {const t=document.getElementById('councilMeetingOutput');
              t.value=Array(40).fill('긴 결과 문단입니다.').join('\\n');t.dispatchEvent(new Event('input'));}""")
            grown = page.evaluate("""() => {const t=document.getElementById('councilMeetingOutput');
              return {scroll:t.scrollHeight, client:t.clientHeight, h:Math.round(t.getBoundingClientRect().height)};}""")
            assert grown["h"] > 160 and grown["scroll"] <= grown["client"] + 2, grown
            page.click("#councilBack")
            page.wait_for_timeout(150)
            _open(page, "sns")
            page.fill('#councilSnsForm [name=event]', "미리보기 확인")
            page.fill('#councilSnsForm [name=content]', "확인 내용")
            page.click("#councilSnsGenerate")
            page.wait_for_timeout(300)
            preview = page.evaluate("""() => ({preview:!document.getElementById('councilSnsPreview').hidden,
              text:!document.getElementById('councilSnsOutput').hidden})""")
            assert preview == {"preview": True, "text": False}, preview
            page.click("#councilSnsEdit")
            edited = page.evaluate("""() => ({preview:!document.getElementById('councilSnsPreview').hidden,
              text:!document.getElementById('councilSnsOutput').hidden})""")
            assert edited == {"preview": False, "text": True}, edited
        finally:
            page.close()
        browser.close()


def test_14_nav_contrast_is_numeric(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            _ready(page, url, 1440, 900)
            ratio = page.evaluate("""() => {
              const ink = getComputedStyle(document.querySelector('.council-nav-item')).color;
              const bg = getComputedStyle(document.querySelector('.council-nav')).backgroundColor;
              const lum = (s) => {const [r,g,b]=s.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)});return .2126*r+.7152*g+.0722*b};
              const a=lum(ink), b=lum(bg); return Math.round(((Math.max(a,b)+.05)/(Math.min(a,b)+.05))*100)/100;
            }""")
            assert ratio >= 4.5, ratio
        finally:
            page.close()
        browser.close()


def test_15_styles_are_visibly_distinct(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        seen = {}
        try:
            _ready(page, url, 1440, 900)
            for style in ("classic", "modern", "minimal"):
                page.evaluate("(s) => document.documentElement.setAttribute('data-style', s)", style)
                page.wait_for_timeout(80)
                seen[style] = page.evaluate("""() => {
                  const h=document.getElementById('councilHeroTitle');
                  const card=document.querySelector('.council-card');
                  const rgb=(s)=>s.match(/[\\d.]+/g).slice(0,3).map(Number);
                  return {face:getComputedStyle(h).fontFamily.split(',')[0],
                          panel:getComputedStyle(document.documentElement).getPropertyValue('--panel').trim(),
                          cardBg:getComputedStyle(card).backgroundColor,
                          cardFilter:getComputedStyle(card).filter,
                          cardFont:getComputedStyle(card.querySelector('h2')).fontFamily.split(',')[0]};}""")
            assert len({v["cardBg"] for v in seen.values()}) == 3, seen
            classic = rgb(seen["classic"]["cardBg"])
            assert classic[0] > classic[1] > classic[2], ("paper tone", seen["classic"])
            assert "grayscale" in seen["minimal"]["cardFilter"], seen["minimal"]
            assert seen["classic"]["cardFont"] != seen["modern"]["cardFont"], seen
        finally:
            page.close()
        browser.close()


def test_16_move_buttons_are_grouped_and_44(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            _ready(page, url, 390, 844)
            _open(page, "meeting")
            m = page.evaluate("""() => {const wrap=document.createElement('span');wrap.className='council-record-moves';
              const e=document.createElement('button');e.className='council-record-move';wrap.appendChild(e);document.body.appendChild(wrap);
              const s=getComputedStyle(e), r=e.getBoundingClientRect();const out={w:Math.round(r.width),h:Math.round(r.height),display:getComputedStyle(wrap).display};wrap.remove();return out;}""")
            assert m["w"] >= 44 and m["h"] >= 44 and m["display"] == "inline-flex", m
        finally:
            page.close()
        browser.close()


def test_small_required_marker_and_phone_cta_gutter(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            _ready(page, url, 390, 844)
            marked = page.evaluate("""() => [...document.querySelectorAll('#councilSpeechForm label')]
              .filter(l => l.querySelector('[required]')).every(l => l.textContent.includes('(필수)'))""")
            cta = page.evaluate("""() => {const r=document.getElementById('councilHeroCta').getBoundingClientRect();
              return {left:Math.round(r.left), right:Math.round(innerWidth-r.right)};}""")
            assert marked is True and cta["left"] >= 16 and cta["right"] >= 16, (marked, cta)
        finally:
            page.close()
        browser.close()
