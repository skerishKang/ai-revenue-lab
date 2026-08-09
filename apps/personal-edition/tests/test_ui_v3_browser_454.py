"""Real Chromium gate for B1 Personal Edition V3 / Issue #454."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright
from scripts.build_static_preview import main as build_static_preview

BASE_DIR = Path(__file__).resolve().parent.parent
DIST = BASE_DIR / "dist-preview"
VIEWPORTS = (("desktop",1440,1100),("tablet",768,1024),("mobile",390,844))
SCREENS = (
    ("owner-root","/","[data-owner-review-root='true']"),
    ("library","/preview/participant/published/",".v3-library"),
    ("write","/preview/participant/input/",".v3-write"),
    ("read","/preview/participant/editions/modal-preview-edition/",".v3-read"),
    ("feedback","/preview/participant/editions/modal-preview-edition/feedback/",".v3-feedback"),
    ("adaptation","/preview/participant/editions/modal-preview-edition/adaptation/",".v3-adaptation"),
    ("operator-queue","/admin/",".operator-queue-list-v2"),
    ("operator-review","/admin/review/modal-preview-edition/content/",".review-desk-v2"),
)

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

def browser_path() -> str:
    for p in (os.getenv("CHROME_PATH"),"/usr/bin/google-chrome","/usr/bin/google-chrome-stable","/usr/bin/chromium","/usr/bin/chromium-browser"):
        if p and Path(p).is_file(): return p
    raise AssertionError("Issue #454 requires system Chrome/Chromium")

def head_sha() -> str:
    event = os.getenv("GITHUB_EVENT_PATH")
    if event and Path(event).is_file():
        try:
            sha = json.loads(Path(event).read_text(encoding="utf-8")).get("pull_request",{}).get("head",{}).get("sha")
            if sha: return str(sha)
        except (OSError,json.JSONDecodeError): pass
    return subprocess.run(["git","rev-parse","HEAD"],cwd=BASE_DIR,capture_output=True,text=True,check=True).stdout.strip()

def sha256(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

@pytest.fixture(scope="module")
def server() -> tuple[str,Path]:
    build_static_preview()
    handler=partial(Quiet,directory=str(DIST))
    http=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
    host,port=http.server_address
    evidence=Path(os.getenv("RUNNER_TEMP",tempfile.gettempdir()))/f"personal-edition-v3-454-{head_sha()}"
    (evidence/"screenshots").mkdir(parents=True,exist_ok=True)
    try: yield f"http://{host}:{port}",evidence
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=3)

def test_issue_454_v3_exact_viewports_and_product_chrome(server: tuple[str,Path]) -> None:
    base,evidence=server; shots=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=browser_path(),args=["--no-sandbox"])
        try:
            for vp,w,h in VIEWPORTS:
                context=browser.new_context(viewport={"width":w,"height":h},reduced_motion="reduce")
                page=context.new_page(); external=[]; page_errors=[]; http_errors=[]
                page.on("request",lambda r: external.append(r.url) if not r.url.startswith(base) and not r.url.startswith(("data:","blob:")) else None)
                page.on("pageerror",lambda e: page_errors.append(str(e)))
                def on_response(r):
                    p=urlparse(r.url).path
                    if r.url.startswith(base) and r.status>=400 and p!="/favicon.ico": http_errors.append(f"{r.status} {p}")
                page.on("response",on_response)
                for name,path,marker in SCREENS:
                    response=page.goto(base+path,wait_until="networkidle",timeout=15000)
                    assert response is not None and response.status==200,(name,path)
                    assert page.locator(marker).count()>0,(name,marker)
                    metrics=page.evaluate("""() => ({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,rm:matchMedia('(prefers-reduced-motion: reduce)').matches,broken:Array.from(document.images).filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.src)})""")
                    assert metrics["sw"]<=metrics["cw"],(name,vp,metrics)
                    assert metrics["rm"] is True
                    assert metrics["broken"]==[]
                    page.evaluate("document.activeElement && document.activeElement.blur()")
                    page.keyboard.press("Tab")
                    focus=page.evaluate("""() => {const e=document.activeElement;if(!e||e===document.body)return false;const s=getComputedStyle(e);return (parseFloat(s.outlineWidth||'0')>0&&s.outlineStyle!=='none')||(s.boxShadow&&s.boxShadow!=='none')}""")
                    assert focus,(name,vp,"focus-visible")
                    if name=="owner-root":
                        assert page.locator(".preview-banner").evaluate("el => getComputedStyle(el).display") == "none"
                        assert "Personal Edition UI Preview" not in page.locator("main").inner_text()
                        assert "프리뷰 목록" not in page.locator("main").inner_text()
                    shot=evidence/"screenshots"/f"{name}-{vp}.png"; page.screenshot(path=str(shot),full_page=False)
                    shots.append({"screen":name,"viewport":vp,"width":w,"height":h,"sha256":sha256(shot)})
                context.close()
                assert external==[],external
                assert page_errors==[],page_errors
                assert http_errors==[],http_errors
        finally: browser.close()
    assert len(shots)==24
    assert len({x["sha256"] for x in shots})==24
    (evidence/"manifest.json").write_text(json.dumps({"issue":454,"head":head_sha(),"status":"pass","screenshots":shots},ensure_ascii=False,indent=2),encoding="utf-8")
    summary=os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a",encoding="utf-8") as f:
            f.write("\n## B1 Personal Edition V3 — Issue #454\n\n")
            f.write(f"- head: `{head_sha()}`\n- 3 viewports × 8 surfaces: **24/24**\n- root debug chrome hidden: **PASS**\n- overflow/assets/external requests/focus/reduced motion: **PASS**\n")

def test_issue_454_v3_has_meaningful_motion_and_reduced_equivalent(server: tuple[str,Path]) -> None:
    base,_=server
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=browser_path(),args=["--no-sandbox"])
        try:
            normal=browser.new_context(viewport={"width":1440,"height":1100},reduced_motion="no-preference").new_page()
            normal.goto(base+"/preview/intro/",wait_until="networkidle")
            animation=normal.locator(".v3-edition-object").evaluate("el => getComputedStyle(el).animationName")
            assert animation=="v3-bind"
            normal.context.close()
            reduced=browser.new_context(viewport={"width":1440,"height":1100},reduced_motion="reduce").new_page()
            reduced.goto(base+"/preview/intro/",wait_until="networkidle")
            duration=reduced.locator(".v3-edition-object").evaluate("el => getComputedStyle(el).animationDuration")
            assert duration in ("0.000001s","0.001ms") or float(duration.rstrip('s')) < .01
            reduced.context.close()
        finally: browser.close()
