"""#8954-9 PC connected dot matches the shared composer success color."""
from __future__ import annotations
import http.server
import json
import os
import threading
from pathlib import Path
import pytest
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # minimal static CI jobs omit browser dependencies
    sync_playwright=None

STATIC=Path(__file__).resolve().parents[1]/"static"
THEMES=("light","dark","cinematic","padiem-glass","padiem-home")
AUTH={"ready":True,"authenticated":True,"history_ready":True,
      "user":{"email":"member@example.com","name":"Member","picture":""}}
PAIRINGS={"ok":True,"links":[{"id":"pairing-fixture","state":"active","online":True,"name":"PC"}],"codes":[]}

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(STATIC),**kwargs)
    def log_message(self,*args):
        pass

@pytest.fixture(scope="module")
def url():
    with http.server.ThreadingHTTPServer(("127.0.0.1",int(os.getenv("CGI_8954_PORT","0"))),Handler) as web:
        worker=threading.Thread(target=web.serve_forever,daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        finally:
            web.shutdown()
            worker.join(timeout=5)

@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("Playwright required for real browser")
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        try:
            yield b
        finally:
            b.close()

@pytest.mark.parametrize("width",[390,1440])
@pytest.mark.parametrize("theme",THEMES)
def test_connected_mark_matches_composer_green_without_changing_words(browser,url,width,theme):
    page=browser.new_page(viewport={"width":width,"height":844},reduced_motion="reduce")
    try:
        page.route("**/api/auth/status",lambda r:r.fulfill(
            status=200,content_type="application/json",body=json.dumps(AUTH)))
        page.route("**/api/pc/pairings",lambda r:r.fulfill(
            status=200,content_type="application/json",body=json.dumps(PAIRINGS)))
        page.goto(f"{url}?theme={theme}",wait_until="domcontentloaded")
        page.wait_for_function("""() => window.PadiemPcConnectFlow?.current?.().state === 'connected'
            && document.querySelector('#composerPcStatus')?.dataset.state === 'connected'""",timeout=10000)
        state=page.evaluate("""() => {
          const line=document.querySelector('#pcConnectStarter [data-pc-connect-state]');
          const mark=line.querySelector('[data-connected-dot]');
          const composer=document.querySelector('#composerPcStatus .composer-pc-status-dot');
          const dotColor=mark?getComputedStyle(mark).color:null;
          const composerBg=getComputedStyle(composer).backgroundColor;
          return {text:line.textContent,mark:mark?.textContent,color:dotColor,
                  composer:composerBg,other:mark?.nextElementSibling?.textContent,
                  originalColor:getComputedStyle(line).color};
        }""")
        assert state["text"].startswith("●"),(theme,width,state)
        assert state["mark"]=="●",(theme,width,state)
        assert state["color"]==state["composer"],(theme,width,state)
        assert state["other"]==state["text"][1:],(theme,width,state)
    finally:
        page.close()
