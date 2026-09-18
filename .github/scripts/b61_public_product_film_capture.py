from __future__ import annotations
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET="https://storymemory-padiem-567.pages.dev/"
OUT=Path(".tmp/b61-public-product-film"); RAW=OUT/"raw"
OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
console_errors=[]; page_errors=[]; interactions=[]

def click_text(page, labels):
    for label in labels:
        loc=page.get_by_text(label, exact=False)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                interactions.append(label)
                page.wait_for_timeout(2500)
                return True
        except Exception:
            pass
    return False

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={"width":1440,"height":900},device_scale_factor=1,locale="ko-KR",timezone_id="Asia/Seoul",record_video_dir=str(RAW),record_video_size={"width":1440,"height":900})
    page=context.new_page()
    page.on("console",lambda msg: console_errors.append(msg.text) if msg.type=="error" else None)
    page.on("pageerror",lambda exc: page_errors.append(str(exc)))
    response=page.goto(TARGET,wait_until="domcontentloaded",timeout=45000)
    if response is None or response.status>=400: raise RuntimeError(f"StoryMemory load failed: {response.status if response else 'NO_RESPONSE'}")
    try: page.wait_for_load_state("networkidle",timeout=20000)
    except Exception: pass
    page.wait_for_timeout(4000)
    if not page.url.startswith(TARGET): raise RuntimeError(f"Capture left approved latest host: {page.url}")
    body=page.locator("body")
    if not body.is_visible(): raise RuntimeError("StoryMemory body is not visible")
    initial_text=body.inner_text()
    if len(initial_text.strip())<40: raise RuntimeError("StoryMemory public UI has insufficient visible content")

    page.wait_for_timeout(3000)
    click_text(page,["성경","Bible","도서관","Library"])
    click_text(page,["창세기","Genesis","마태복음","Matthew"])
    click_text(page,["1장","Chapter 1","읽기","이어읽기"])
    page.wait_for_timeout(4000)

    # Demonstrate the real page vertically without fabricating state.
    page.mouse.wheel(0,500); page.wait_for_timeout(3000)
    page.mouse.wheel(0,-500); page.wait_for_timeout(2500)

    page.screenshot(path=str(OUT/"storymemory-product-still-v1.png"),full_page=False)
    visible_text=body.inner_text()
    visible_email=bool(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",visible_text,re.I))
    if visible_email: raise RuntimeError("Privacy guard found a visible email")
    evidence={"target":TARGET,"final_url":page.url,"title":page.title(),"viewport":{"width":1440,"height":900},"interactions":interactions,"visible_email":visible_email,"login_performed":False,"console_errors":console_errors,"page_errors":page_errors}
    (OUT/"capture-evidence.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    video=page.video
    context.close()
    if video is None: raise RuntimeError("Playwright did not create capture video")
    video.save_as(str(OUT/"storymemory-product-film-v1.webm"))
    browser.close()
