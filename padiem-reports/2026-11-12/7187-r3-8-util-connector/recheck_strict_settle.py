#!/usr/bin/env python3
"""4개 콤보의 computed를 더 엄격한 정착(3회 연속 동일)으로 재측정한다."""
from __future__ import annotations

import functools
import http.server
import io
import json
import socketserver
import subprocess
import threading
from collections import Counter
from pathlib import Path

from PIL import Image
import numpy as np
from playwright.sync_api import sync_playwright

REPO = Path(r"E:\261106-3\wt-7187-r3-8")
CHAT = REPO / "apps/padiem-chat/static"
SHEETS = ("util-menu.css", "util-app.css", "util-tools.css", "util-chat-mode.css",
          "util-excel.css", "util-quote.css", "connector-pages.css", "capability-nav.css")
SIZES = {"1280x800": (1280, 800), "390x844": (390, 844)}
HASH = {"util-quote": "#util/quote", "util-home": "#util", "util-pdfmd": "#util/pdfmd"}
TARGETS = [("light", "1280x800", "util-quote"), ("dark", "390x844", "util-home"),
           ("cinematic", "1280x800", "util-pdfmd"), ("cinematic", "1280x800", "util-quote")]
STAB = "*,*::before,*::after{animation:none!important;transition:none!important}"

SIGS = """() => Array.from(document.querySelectorAll('*')).map(el =>
  el.tagName + (el.id ? '#' + el.id : '') + '.' +
  (typeof el.className === 'string' ? el.className.slice(0, 40) : ''))"""

SNAP = """() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    const props = {};
    for (let i = 0; i < cs.length; i += 1) {
      const n = cs[i];
      if (n.startsWith('--')) continue;
      props[n] = cs.getPropertyValue(n);
    }
    out.push([el.tagName + (el.id ? '#' + el.id : '') + '.' +
      (typeof el.className === 'string' ? el.className.slice(0, 40) : ''), props]);
  }
  return out;
}"""

STATE = """() => Array.from(document.querySelectorAll('li[class*="mcp-gateway-client"]'))
  .map(e => e.className).sort()"""


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


def key(item):
    return item[0], json.dumps(item[1], sort_keys=True)


def diff(a, b):
    if len(a) != len(b):
        return {"count": -1, "reason": "len", "detail": []}
    ca, cb = Counter(key(x) for x in a), Counter(key(x) for x in b)
    if ca == cb:
        return {"count": 0, "detail": []}
    detail = []
    for k in list((ca - cb).elements())[:4]:
        detail.append({"only_in_first": k[0], "props": json.loads(k[1])})
    for k in list((cb - ca).elements())[:4]:
        detail.append({"only_in_second": k[0], "props": json.loads(k[1])})
    return {"count": sum((ca - cb).values()), "detail": detail}


server, port = start_server(CHAT)
out = {}
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=["--force-color-profile=srgb", "--force-device-scale-factor=1"])

    def cap(theme, size, route, kind):
        ctx = br.new_context(viewport={"width": SIZES[size][0], "height": SIZES[size][1]},
                             device_scale_factor=1, reduced_motion="reduce")
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
        pg.evaluate("(t)=>{document.documentElement.dataset.theme=t;}", theme)
        pg.evaluate("(h)=>{location.hash=h;}", HASH[route])
        pg.wait_for_timeout(500)

        stable = 0
        prev = None
        for _ in range(20):
            pg.wait_for_timeout(300)
            cur = (pg.evaluate(SIGS), pg.evaluate(STATE))
            if cur == prev:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            prev = cur
        snap = pg.evaluate(SNAP)
        mcp = pg.evaluate(STATE)
        shot = pg.screenshot(animations="disabled")
        ctx.close()
        return shot, snap, mcp, stable

    for theme, size, route in TARGETS:
        b1, bs1, m1, s1 = cap(theme, size, route, "before")
        a1, as1, n1, t1 = cap(theme, size, route, "after")
        b2, bs2, m2, s2 = cap(theme, size, route, "before")
        a2, as2, n2, t2 = cap(theme, size, route, "after")
        ia = Image.open(io.BytesIO(b1)).convert("RGB")
        ib = Image.open(io.BytesIO(a1)).convert("RGB")
        px = int(np.count_nonzero(np.any(np.asarray(ia) != np.asarray(ib), axis=2)))
        key_ = f"{theme}__{size}__{route}"
        out[key_] = {
            "before_after": diff(bs1, as1),
            "within_before": diff(bs1, bs2),
            "within_after": diff(as1, as2),
            "pixel_before_after": px,
            "mcp_before": m1, "mcp_after": n1,
            "settle_before": s1, "settle_after": t1,
        }
        print(f"=== {key_} px={px} settle(b/a)={s1}/{t1}")
        print(f"    before/after : {out[key_]['before_after']['count']} {json.dumps(out[key_]['before_after']['detail'], ensure_ascii=False)[:300]}")
        print(f"    within before: {out[key_]['within_before']['count']}  within after: {out[key_]['within_after']['count']}")
        print(f"    mcp before={m1} after={n1}")
    br.close()
server.shutdown(); server.server_close()
Path(r"C:\Users\limone\AppData\Local\Temp\opencode\recheck4_r38.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")