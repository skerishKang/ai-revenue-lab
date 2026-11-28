# -*- coding: utf-8 -*-
"""#8808 D1/D9: source-order glossary and mobile record affordance regressions."""
from __future__ import annotations

import functools
import http.server
import os
from pathlib import Path
from css_source import read_site_css
import subprocess
import sys
import threading

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
CHROME = next((x for x in [os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"] if x and Path(x).is_file()), None)

def order_positions(html: str):
    return (html.index('id="activityList"'), html.index('id="activityLegend"'),
            html.index('class="source-note"'))

def test_glossary_after_record_list_before_source_in_source_html():
    html = (ROOT / "activity.html").read_text(encoding="utf-8")
    listing, glossary, source = order_positions(html)
    assert listing < glossary < source

@pytest.fixture(scope="module")
def site():
    if sync_playwright is None or CHROME is None:
        pytest.skip("headless Chrome/Playwright unavailable")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build-dist")], check=True)
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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

def page_at(site, width=390, large=False, dark=False):
    browser, url = site
    page = browser.new_page(viewport={"width":width,"height":844}, color_scheme="light",
                            reduced_motion="reduce", device_scale_factor=1)
    page.goto(url, wait_until="load")
    page.evaluate("""([large,dark]) => {
        document.documentElement.dataset.theme=dark?'dark':'light';
        if (large) document.documentElement.dataset.textSize='large';
    }""", [large,dark])
    page.evaluate("document.fonts.ready")
    page.locator("#activityList > .activity-item").first.wait_for(state="visible")
    return page

def test_glossary_after_records_before_source_in_built_html(site):
    html = (ROOT / "dist" / "activity.html").read_text(encoding="utf-8")
    listing, glossary, source = order_positions(html)
    assert listing < glossary < source
    page = page_at(site)
    ids = page.evaluate("""() => {
      let list = document.querySelector('#activityList');
      let legend = document.querySelector('#activityLegend');
      let source = document.querySelector('main .source-note');
      return [Boolean(list.compareDocumentPosition(legend)&Node.DOCUMENT_POSITION_FOLLOWING),
        Boolean(legend.compareDocumentPosition(source)&Node.DOCUMENT_POSITION_FOLLOWING)];
    }""")
    page.close()
    assert ids == [True,True], ids

@pytest.mark.parametrize("large", [False,True])
def test_first_record_title_fully_inside_first_viewport(site, large):
    page = page_at(site, width=390, large=large)
    m = page.evaluate("""() => {
      const r = document.querySelector('#activityList .item-title').getBoundingClientRect();
      const list = document.querySelector('#activityList').getBoundingClientRect();
      return {top:r.top,bottom:r.bottom,listTop:list.top,viewport:innerHeight,
              overflow:document.documentElement.scrollWidth-innerWidth};
    }""")
    page.close()
    assert m["top"] >= 0 and m["bottom"] <= 844, m
    assert m["overflow"] <= 0, m

@pytest.mark.parametrize("dark,filter_value", [(False,"all"),(True,"위원회")])
def test_every_record_more_below_title_at_same_left_with_44px(site,dark,filter_value):
    page = page_at(site, width=390, dark=dark)
    if filter_value != "all":
        page.locator("#activityFilter").select_option(label=filter_value)
        page.wait_for_function("""() => {
          const nodes = [...document.querySelectorAll('#activityList > .activity-item')];
          return nodes.some(n=>n.offsetParent!==null) &&
                 nodes.filter(n=>n.offsetParent!==null).every(n=>n.querySelector('.item-tag')?.textContent.trim()==='위원회');
        }""")
    positions=page.evaluate("""() => [...document.querySelectorAll('#activityList > .activity-item')]
      .filter(row=>row.offsetParent!==null).map(row=>{
        const title=row.querySelector('.item-title');
        const more=row.querySelector('.item-more');
        const node=[...title.childNodes].find(n=>n.nodeType===Node.TEXT_NODE && n.textContent.trim());
        const range=document.createRange(); range.selectNodeContents(node);
        const fragments=[...range.getClientRects()];
        const bottom=Math.max(...fragments.map(r=>r.bottom));
        const x=Math.min(...fragments.map(r=>r.left));
        const m=more.getBoundingClientRect();
        return {title:node.textContent.trim(),textBottom:bottom,textX:x,
                moreTop:m.top,moreX:m.x,moreHeight:m.height,visible:getComputedStyle(more).display};
      })""")
    page.close()
    assert positions, "visible record cards required"
    assert all(p["moreTop"] >= p["textBottom"]-.5 and
               abs(p["moreX"]-p["textX"])<=1 and p["moreHeight"]>=44
               for p in positions), [p for p in positions if
               p["moreTop"] < p["textBottom"]-.5 or abs(p["moreX"]-p["textX"])>1 or p["moreHeight"]<44][:6]

def test_1440_glossary_four_columns_below_list(site):
    page=page_at(site,width=1440)
    value=page.evaluate("""() => {
      const legend=document.querySelector('#activityLegend');
      const list=document.querySelector('#activityList');
      const source=document.querySelector('main .source-note');
      const cs=getComputedStyle(legend);
      const items=[...legend.querySelectorAll('span')];
      const cols=cs.gridTemplateColumns.split(/\\s+/).filter(Boolean);
      const br=e=>e.getBoundingClientRect();
      return {cols:cols.length, terms:items.length,legendTop:br(legend).top,
         listBottom:br(list).bottom,sourceTop:br(source).top,
         display:cs.display,firstRowCount:items.filter(i=>Math.abs(br(i).top-br(items[0]).top)<1).length};
    }""")
    page.close()
    assert value["cols"]==4 and value["firstRowCount"]==4, value
    assert value["listBottom"] <= value["legendTop"] <= value["sourceTop"], value

def test_no_new_important():
    css=read_site_css()
    assert css.count("!important") <= 5
