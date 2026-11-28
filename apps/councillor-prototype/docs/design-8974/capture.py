# -*- coding: utf-8 -*-
"""#8974: 390/360 before-after headless Chrome captures and exact layout metrics.

Run on the CGI computer: python docs/design-8974/capture.py before|after
"""
from __future__ import annotations
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PHOTO_SAMPLES = [(390, "light"), (390, "dark"), (360, "light"), (820, "light"), (1440, "light")]
POLICY_SAMPLES = [390, 820, 1440]


def inspect_lightbox(page):
    return page.evaluate("""() => {
      const box = selector => {
        const e = document.querySelector(selector);
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,
                fontSize:s.fontSize,display:s.display};
      };
      const photo=box('#lightboxImg'),prev=box('#lightboxPrev'),next=box('#lightboxNext'),
        close=box('#lightboxClose'),link=box('#lightboxLink');
      return {photo,prev,next,close,link,viewport:{width:innerWidth,height:innerHeight},
              gap:next.x-prev.right,src:document.querySelector('#lightboxImg').getAttribute('src'),
              modalOpen:document.querySelector('#mediaLightbox').open,
              imageNaturalWidth:document.querySelector('#lightboxImg').naturalWidth,
              imageNaturalHeight:document.querySelector('#lightboxImg').naturalHeight};
    }""")


def inspect_policy(page):
    return page.evaluate("""() => {
      const card=document.querySelector('#policyForums .info-card');
      const video=document.querySelector('#policyVideos .info-card');
      const num=card.querySelector('.card-num');
      const title=card.querySelector('h3');
      const meta=card.querySelector('.policy-meta');
      const paragraph=card.querySelector('p:not(.policy-meta)');
      const style = e => {
        const s=getComputedStyle(e);
        return {fontSize:s.fontSize,lineHeight:s.lineHeight,paddingTop:s.paddingTop,
                paddingBottom:s.paddingBottom,overflow:s.overflow};
      };
      const rect=card.getBoundingClientRect();
      return {viewport:innerWidth,cardHeight:rect.height,cardWidth:rect.width,
        number:style(num),card:style(card),title:style(title),
        meta:style(meta),paragraph:style(paragraph),cardText:card.innerText,
        videoText:video.innerText,videoNumber:style(video.querySelector('.card-num')),
        videoPadding:style(video),
        overflowX:document.documentElement.scrollWidth-innerWidth};
    }""")


def run(phase):
    assert phase in ("before", "after")
    subprocess.run([sys.executable,str(ROOT/"scripts"/"build-dist")], check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(ROOT/"dist"),**kwargs)
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results={"photos":{},"policy":{}}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=CHROME)
            try:
                for width, theme in PHOTO_SAMPLES:
                    height = 844 if width <= 600 else 900
                    page=browser.new_page(viewport={"width":width,"height":height},
                        device_scale_factor=1,reduced_motion="reduce",color_scheme="light")
                    try:
                        page.goto(f"http://127.0.0.1:{server.server_port}/media.html",wait_until="load")
                        page.evaluate("(t)=>document.documentElement.dataset.theme=t",theme)
                        page.evaluate("document.fonts.ready")
                        page.locator(".media-tile").nth(1).click()
                        page.locator("#mediaLightbox[open]").wait_for()
                        page.locator("#lightboxImg").evaluate("img => img.decode()")
                        key=f"{width}-{theme}"
                        results["photos"][key]=inspect_lightbox(page)
                        if width<=600:
                            page.screenshot(path=str(OUT/f"photo-{width}-{theme}-{phase}.png"),
                                            animations="disabled")
                        print("PHOTO",phase,key,
                            "width=",round(results["photos"][key]["photo"]["width"],2),
                            "photoBottom=",round(results["photos"][key]["photo"]["bottom"],2),
                            "prevTop=",round(results["photos"][key]["prev"]["y"],2),
                            flush=True)
                    finally:page.close()
                for width in POLICY_SAMPLES:
                    height=844 if width<=600 else 900
                    page=browser.new_page(viewport={"width":width,"height":height},
                        device_scale_factor=1,reduced_motion="reduce",color_scheme="light")
                    try:
                        page.goto(f"http://127.0.0.1:{server.server_port}/policy.html",wait_until="load")
                        page.evaluate("document.fonts.ready")
                        results["policy"][str(width)]=inspect_policy(page)
                        if width==390:
                            page.screenshot(path=str(OUT/f"policy-first-390-light-{phase}.png"),
                                            animations="disabled")
                        print("POLICY",phase,width,
                              "height=",round(results["policy"][str(width)]["cardHeight"],2),
                              "number=",results["policy"][str(width)]["number"]["fontSize"],
                              "body=",results["policy"][str(width)]["paragraph"]["fontSize"],
                              flush=True)
                    finally:page.close()
            finally:browser.close()
    finally:
        server.shutdown();server.server_close()
    name="baseline.json" if phase=="before" else "after.json"
    (OUT/name).write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MEASUREMENTS_SAVED",name,flush=True)


if __name__=="__main__":
    assert len(sys.argv)==2
    run(sys.argv[1])
