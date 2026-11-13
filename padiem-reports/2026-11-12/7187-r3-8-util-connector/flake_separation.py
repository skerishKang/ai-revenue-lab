#!/usr/bin/env python3
"""nonzero 콤보가 CSS 차이인지 캡처 상태 흔들림인지 분리한다.

같은 kind를 두 번 캡처해 computed가 달라지면 그 콤보는 상태 흔들림이다.
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import socketserver
import subprocess
import threading
from pathlib import Path

from PIL import Image
import numpy as np
from playwright.sync_api import sync_playwright

REPO = Path(r"E:\261106-3\wt-7187-r3-8")
CHAT = REPO / "apps/padiem-chat/static"
SHEETS = ("util-menu.css", "util-app.css", "util-tools.css", "util-chat-mode.css",
          "util-excel.css", "util-quote.css", "connector-pages.css", "capability-nav.css")


def git(*a):
    return subprocess.check_output(["git", "-C", str(REPO), *a], text=True)


BASE = git("merge-base", "HEAD", "origin/main").strip()
BEFORE = {n: git("show", f"{BASE}:apps/padiem-chat/static/{n}") for n in SHEETS}
SIZES = {"1280x800": (1280, 800), "390x844": (390, 844)}
HASH = {"util-home": "#util", "connectors": "#connectors", "claw": "#claw", "home": ""}
TARGETS = [("cinematic", "1280x800", "claw"), ("cinematic", "1280x800", "home"),
           ("cinematic", "390x844", "connectors"), ("padiem-glass", "1280x800", "connectors"),
           ("light", "1280x800", "claw")]

STAB = """*,*::before,*::after{animation:none!important;animation-duration:0s!important;
transition:none!important;transition-duration:0s!important;caret-color:transparent!important}"""
COMPUTED = """() => {const sigs=[],maps=[];for(const el of document.querySelectorAll('*')){const cs=getComputedStyle(el);const rec={};for(let i=0;i<cs.length;i+=1){const n=cs[i];if(n.startsWith('--'))continue;rec[n]=cs.getPropertyValue(n);}sigs.push(el.tagName+(el.id?'#'+el.id:'')+'.'+(typeof el.className==='string'?el.className.slice(0,40):''));maps.push(rec);}return{sigs:sigs,maps:maps};}"""


def start_server(d):
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    s = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(d)))
    s.allow_reuse_address = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


def diff(a, b):
    ia, ib = Image.open(io.BytesIO(a)).convert("RGB"), Image.open(io.BytesIO(b)).convert("RGB")
    m = np.any(np.asarray(ia) != np.asarray(ib), axis=2)
    return int(np.count_nonzero(m))


def cmp(c1, c2):
    if c1["sigs"] != c2["sigs"]:
        return {"sig_mismatch": True}
    out = []
    for i, (x, y) in enumerate(zip(c1["maps"], c2["maps"])):
        bad = [k for k in set(x) | set(y) if x.get(k) != y.get(k)]
        if bad:
            out.append({"sig": c1["sigs"][i], "props": {k: [x.get(k), y.get(k)] for k in bad}})
    return {"elements": len(c1["maps"]), "count": len(out), "first": out[:6]}


server, port = start_server(CHAT)
res = {}
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=[
        "--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none",
        "--force-device-scale-factor=1", "--hide-scrollbars"])

    def cap(theme, size, route, kind):
        ctx = br.new_context(viewport={"width": SIZES[size][0], "height": SIZES[size][1]},
                             device_scale_factor=1, reduced_motion="reduce")
        pg = ctx.new_page()

        def rh(r):
            u = r.request.url
            if "127.0.0.1" not in u:
                r.abort(); return
            fn = u.rsplit("/", 1)[-1].split("?")[0]
            if fn in SHEETS and kind == "before":
                r.fulfill(status=200, content_type="text/css; charset=utf-8", body=BEFORE[fn])
                return
            r.continue_()

        pg.route("**/*", rh)
        pg.add_init_script(STAB)
        pg.add_init_script("Math.random=()=>0.5; Date.now=()=>1762900000000;")
        pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_function("document.fonts.status === 'loaded'", timeout=30000)
        pg.evaluate("(t)=>{document.documentElement.dataset.theme=t;}", theme)
        if HASH[route]:
            pg.evaluate("(h)=>{location.hash=h;}", HASH[route])
        pg.wait_for_timeout(500)
        prev = pg.screenshot(animations="disabled")
        for _ in range(5):
            pg.wait_for_timeout(250)
            cur = pg.screenshot(animations="disabled")
            if diff(prev, cur) == 0:
                break
            prev = cur
        computed = pg.evaluate(COMPUTED)
        ctx.close()
        return prev, computed

    for theme, size, route in TARGETS:
        b, bc = cap(theme, size, route, "before")
        a, ac = cap(theme, size, route, "after")
        b2, bc2 = cap(theme, size, route, "before")
        a2, ac2 = cap(theme, size, route, "after")
        key = f"{theme}__{size}__{route}"
        res[key] = {
            "across": {"pixel": diff(b, a), "computed": cmp(bc, ac)},
            "before_vs_before": {"pixel": diff(b, b2), "computed": cmp(bc, bc2)},
            "after_vs_after": {"pixel": diff(a, a2), "computed": cmp(ac, ac2)},
        }
        print("===", key)
        print("  across  :", json.dumps(res[key]["across"], ensure_ascii=False)[:700])
        print("  b~b     :", json.dumps(res[key]["before_vs_before"], ensure_ascii=False)[:700])
        print("  a~a     :", json.dumps(res[key]["after_vs_after"], ensure_ascii=False)[:700])

    br.close()
server.shutdown(); server.server_close()
Path(r"C:\Users\limone\AppData\Local\Temp\opencode\flake_r38.json").write_text(
    json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
