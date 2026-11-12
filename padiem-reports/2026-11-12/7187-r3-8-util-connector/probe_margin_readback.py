#!/usr/bin/env python3
""" Blink의 margin:auto computed readback 흔들림이 before/after 양쪽 모두에서
동일하게 일어나는지 확인한다(내 시트와 무관함을 증명)."""
from __future__ import annotations

import functools
import http.server
import socketserver
import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(r"E:\261106-3\wt-7187-r3-8")
CHAT = REPO / "apps/padiem-chat/static"
SHEETS = ("util-menu.css", "util-app.css", "util-tools.css", "util-chat-mode.css",
          "util-excel.css", "util-quote.css", "connector-pages.css", "capability-nav.css")
STAB = "*,*::before,*::after{animation:none!important;transition:none!important}"

JS = """() => {
  const el = document.querySelector('.conversation');
  const r = el.getBoundingClientRect();
  return {ml: getComputedStyle(el).marginLeft, rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]};
}"""


def git(*a):
    return subprocess.check_output(["git", "-C", str(REPO), *a], text=True)


BASE = git("merge-base", "HEAD", "origin/main").strip()
BEFORE = {n: git("show", f"{BASE}:apps/padiem-chat/static/{n}") for n in SHEETS}


def start_server(d):
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    s = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(d)))
    s.allow_reuse_address = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


server, port = start_server(CHAT)
out = {"before": [], "after": []}
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=["--force-color-profile=srgb", "--force-device-scale-factor=1"])
    for kind in ("before", "after"):
        for trial in range(6):
            ctx = br.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1, reduced_motion="reduce")
            pg = ctx.new_page()

            def rh(r):
                u = r.request.url
                if "127.0.0.1" not in u:
                    r.abort(); return
                fn = u.rsplit("/", 1)[-1].split("?")[0]
                if kind == "before" and fn in SHEETS:
                    r.fulfill(status=200, content_type="text/css; charset=utf-8", body=BEFORE[fn])
                    return
                r.continue_()

            pg.route("**/*", rh)
            pg.add_init_script(STAB)
            pg.add_init_script("Math.random=()=>0.5; Date.now=()=>1762900000000;")
            pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_function("document.fonts.status === 'loaded'", timeout=30000)
            pg.evaluate("()=>{document.documentElement.dataset.theme='light';}")
            pg.evaluate("()=>{const s=document.querySelector('.app-shell'); if(s) s.dataset.state='claw';}")
            pg.evaluate("()=>{location.hash='#claw';}")
            pg.wait_for_timeout(700)
            info = pg.evaluate(JS)
            out[kind].append(info)
            print(f"{kind:6s} trial {trial}: marginLeft={info['ml']:>6s} rect={info['rect']}")
            ctx.close()
    br.close()
server.shutdown(); server.server_close()

for kind in ("before", "after"):
    vals = sorted({i["ml"] for i in out[kind]})
    rects = {tuple(i["rect"]) for i in out[kind]}
    print(f"{kind}: marginLeft values seen = {vals}; rects seen = {rects}")