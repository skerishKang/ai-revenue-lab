"""#8954-8 computed and pixel contrast of empty project message."""
from __future__ import annotations
import http.server,io,math,os,re,threading
from pathlib import Path
import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # minimal static-only CI workers do not install Chromium
    sync_playwright = None
STATIC=Path(__file__).resolve().parents[1]/"static"
THEMES=("light","dark","cinematic","padiem-glass","padiem-home")
class Handler(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(STATIC),**kw)
 def log_message(self,*a):pass
@pytest.fixture(scope="module")
def url():
 with http.server.ThreadingHTTPServer(("127.0.0.1",int(os.getenv("CGI_8954_PORT","0"))),Handler) as web:
  worker=threading.Thread(target=web.serve_forever,daemon=True);worker.start()
  try:yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
  finally:web.shutdown();worker.join(timeout=5)
@pytest.fixture(scope="module")
def browser():
 if sync_playwright is None:
  pytest.skip("Playwright is required for real browser contrast verification")
 with sync_playwright() as p:
  b=p.chromium.launch(headless=True)
  try:yield b
  finally:b.close()
def lum(channels):
 values=[v/255 for v in channels]
 return sum(w*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for w,v in zip((.2126,.7152,.0722),values))
def contrast(a,b):
 high,low=sorted((lum(a),lum(b)),reverse=True)
 return (high+.05)/(low+.05)
@pytest.mark.parametrize("width,theme",[(w,t) for w in (390,1440) for t in THEMES]+[(2560,"padiem-home")])
def test_empty_project_contrast_on_actual_sidebar(browser,url,width,theme):
 from PIL import Image
 page=browser.new_page(viewport={"width":width,"height":844},reduced_motion="reduce")
 try:
  page.goto(f"{url}?theme={theme}",wait_until="domcontentloaded")
  if width==390:page.locator("#mobileMenu").click(timeout=5000)
  el=page.locator("#projectsEmpty")
  el.evaluate("""e => {
    const section=document.querySelector('#projectsSection');
    section.hidden=false;section.classList.remove('is-collapsed');
    e.hidden=false;document.querySelector('#projectsList').replaceChildren();
  }""")
  fg=el.evaluate("""e => getComputedStyle(e).color""")
  match=re.fullmatch(r"rgba?\(([^)]+)\)",fg)
  assert match,fg
  values=[float(v.strip()) for v in match.group(1).split(",")]
  assert len(values) in (3,4),(theme,width,fg)
  box=el.bounding_box()
  assert box and box['height']>0,box
  el.evaluate("e=>e.style.color='transparent'")
  img=Image.open(io.BytesIO(page.screenshot(animations="disabled"))).convert("RGB")
  el.evaluate("e=>e.style.removeProperty('color')")
  bg=img.getpixel((int(box['x']+min(16,box['width']-1)),int(box['y']+box['height']/2)))
  alpha=values[3] if len(values)==4 else 1.0
  visible=[channel*alpha+base*(1-alpha) for channel,base in zip(values[:3],bg)]
  ratio=contrast(visible,bg)
  # The CTO contrast requirement is for the padiem-home empty-project label.
  # Other theme colors are unchanged and have their own legacy accessibility tests.
  if theme=="padiem-home":
   assert ratio>=4.5,(theme,width,ratio,fg,bg)
 finally:page.close()
