# -*- coding: utf-8 -*-
"""#8810 정책자료 디자인 검증: 어둡게 검색, 제8대 펼침, 결과 없음 정렬."""
import http.server
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def rgb(value):
    match = re.match(r"rgba?\\(([^)]*)\\)", value)
    assert match, value
    nums = [float(x) for x in re.findall(r"\\d+(?:\\.\\d+)?",match.group(1))]
    return nums

def contrast(text, background):
    a, b = rgb(text), rgb(background)
    if len(a)==4:
        a = [a[i]*a[3]+b[i]*(1-a[3]) for i in range(3)]
    def lum(color):
        vals = [v/255 for v in color[:3]]
        vals = [v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in vals]
        return .2126*vals[0]+.7152*vals[1]+.0722*vals[2]
    x,y=sorted((lum(a),lum(b)),reverse=True)
    return (x+0.05)/(y+0.05)

@pytest.fixture(scope="module")
def site():
    subprocess.run([sys.executable,str(ROOT/"scripts"/"build-dist")],check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(ROOT/"dist"),**kwargs)
        def log_message(self,*args): pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True,executable_path=CHROME)
            try: yield browser,f"http://127.0.0.1:{server.server_port}"
            finally: browser.close()
    finally:
        server.shutdown()
        server.server_close()

def open_page(site, width=390, name="policy.html", theme="light"):
    browser,origin = site
    page = browser.new_page(viewport={"width":width,"height":844 if width==390 else 900},
                            reduced_motion="reduce",color_scheme="light")
    page.goto(origin+"/"+name,wait_until="load")
    page.evaluate("(t)=>document.documentElement.dataset.theme=t",theme)
    page.evaluate("document.fonts.ready")
    return page

def styles(page,selector):
    return page.evaluate("""s=>{
        const e=document.querySelector(s),c=getComputedStyle(e),p=getComputedStyle(e,'::placeholder'),
          x=getComputedStyle(e,'::-webkit-search-cancel-button');
        return {bg:c.backgroundColor,fg:c.color,border:c.borderColor,
                borderWidth:c.borderTopWidth,placeholder:p.color,
                outline:c.outlineColor,outlineWidth:c.outlineWidth,
                cancelBg:x.backgroundColor,cancelFilter:x.filter,cancelSize:x.width};
    }""",selector)

@pytest.mark.parametrize("width",[390,1440])
def test_dark_bill_search_uses_activity_input_tokens_and_contrast(site,width):
    policy = open_page(site,width,theme="dark")
    activity = open_page(site,width,name="activity.html",theme="dark")
    try:
        policy.locator("#billSearch").fill("조례")
        policy.locator("#billSearch").focus()
        activity.locator("#activitySearch").focus()
        p=styles(policy,"#billSearch"); a=styles(activity,"#activitySearch")
        assert p["bg"]==a["bg"],(width,p,a)
        assert p["fg"]==a["fg"] and p["border"]==a["border"],(width,p,a)
        assert p["borderWidth"]==a["borderWidth"],(width,p,a)
        assert p["outline"]==a["outline"] and p["outlineWidth"]==a["outlineWidth"],(width,p,a)
        assert contrast(p["fg"],p["bg"])>=4.5,(width,"text",p)
        assert contrast(p["placeholder"],p["bg"])>=4.5,(width,"placeholder",p)
        # The clear X is an independently painted icon, not inherited text alone.
        assert contrast(p["cancelBg"],p["bg"])>=3,(width,"clear X",p)
    finally:
        policy.close();activity.close()

@pytest.mark.parametrize("width",[390,1440])
def test_collapsed_8th_heading_disclosure_accessibility_and_full_row(site,width):
    page=open_page(site,width)
    try:
        group=page.locator('.bill-group[data-assembly="8"]')
        assert group.evaluate("e=>e.tagName")=="DETAILS"
        summary=group.locator("summary.bill-group-title")
        assert not group.evaluate("e=>e.open")
        assert summary.get_attribute("aria-expanded")=="false"
        indicator=summary.locator(".bill-toggle-indicator")
        assert indicator.count()==1
        assert indicator.inner_text()=="▾"
        assert summary.bounding_box()["height"]>=44
        before=summary.evaluate("e=>getComputedStyle(e).backgroundColor")
        summary.hover()
        hover=summary.evaluate("e=>getComputedStyle(e).backgroundColor")
        assert before!=hover,(before,hover)
        summary.focus()
        focused=summary.evaluate("""e=>({focusVisible:e.matches(':focus-visible'),
            outline:getComputedStyle(e).outlineStyle, width:parseFloat(getComputedStyle(e).outlineWidth)})""")
        assert focused["focusVisible"] and focused["outline"]!="none" and focused["width"]>=2,focused
        box=summary.bounding_box()
        summary.click(position={"x":box["width"]-6,"y":box["height"]/2})
        page.wait_for_function("""() => {
          const e=document.querySelector('.bill-group[data-assembly="8"]');
          return e.open && e.querySelector('summary').getAttribute('aria-expanded')==='true'
            && e.querySelector('.bill-toggle-indicator').textContent==='▴';
        }""")
        assert group.locator(".bill-row").count()==32
        assert summary.get_attribute("aria-expanded")=="true"
        assert indicator.inner_text()=="▴"
    finally:page.close()

@pytest.mark.parametrize("width",[390,1440])
def test_empty_search_two_groups_show_count_at_same_right_edge(site,width):
    page=open_page(site,width,theme="dark")
    try:
        page.locator("#billSearch").fill("zzzzzzzz")
        counts=page.evaluate("""() => [...document.querySelectorAll('#policyBills .bill-group')].map(g=>{
            const count=g.querySelector('.bill-count');
            const r=count.getBoundingClientRect(), h=g.querySelector('.bill-group-title').getBoundingClientRect();
            return {assembly:g.dataset.assembly,text:count.textContent.trim(),
                    right:r.right,headingRight:h.right,headingHeight:h.height};
        })""")
        assert len(counts)==2,counts
        assert all(x["text"]=="검색 결과 없음" for x in counts),counts
        assert abs(counts[0]["right"]-counts[1]["right"])<=1,counts
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    finally:page.close()

def test_9th_assembly_stays_readable_not_collapsible(site):
    page=open_page(site,1440)
    try:
        group=page.locator('.bill-group[data-assembly="9"]')
        assert group.evaluate("e=>e.tagName")=="SECTION"
        assert group.locator(".bill-row").count()==29
    finally:page.close()

def test_light_search_background_unchanged(site):
    page=open_page(site,1440)
    try:
        value=styles(page,"#billSearch")
        assert value["bg"]=="rgb(255, 255, 255)",value
    finally:page.close()
