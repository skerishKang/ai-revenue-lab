"""Visual first-use parity: Claw shares Chat geometry, composer and truthful switch faces."""
import os
from playwright.sync_api import sync_playwright

BASE=os.environ.get("B62_QA_BASE_URL","http://127.0.0.1:8765").rstrip("/")+"/"
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for width in (1440,900,390):
  page=b.new_page(viewport={"width":width,"height":900})
  page.goto(BASE,wait_until="domcontentloaded",timeout=20000)
  page.wait_for_timeout(450)
  def metrics():
   return page.evaluate("""() => {
    const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.x,r.width]};
    return {eyebrow:rect('.eyebrow'),heading:rect('#emptyState h1'),grid:rect('.starter-grid'),
      composer:rect('.composer-wrap'),tools:getComputedStyle(document.querySelector('.composer-tools')).display,
      ownerStatus:Boolean(document.querySelector('.composer-tier-trigger')?.getClientRects().length),
      fileTool:document.querySelector('#attachmentButton').getClientRects().length>0,
      modelPill:document.querySelector('.composer-tier-trigger').getClientRects().length>0,
      entry:getComputedStyle(document.querySelector('#clawManualEntryBar')).display,
      cards:[...document.querySelectorAll('.claw-home-card')].filter(e=>getComputedStyle(e).display!=='none').length,
      tracks:document.querySelectorAll('.claw-connection-track').length,
      title:document.querySelector('#emptyState h1').innerText}
   }""")
  chat=metrics()
  if width<=920:page.locator("#mobileMenu").click()
  page.locator("#clawNavButton").click()
  page.wait_for_timeout(300)
  claw=metrics()
  for key in ("heading","grid","composer"):
   for i in (0,1):
    assert abs(chat[key][i]-claw[key][i])<=2,(width,key,chat[key],claw[key])
  assert abs(chat["eyebrow"][0]-claw["eyebrow"][0])<=2,(width,"eyebrow",chat,claw)
  assert claw["tools"]=="flex" and claw["entry"]=="none",(width,claw)
  assert claw["ownerStatus"] and chat["ownerStatus"],(width,"model-status",chat,claw)
  assert claw["fileTool"] and claw["modelPill"],(width,"shared-tools",claw)
  assert claw["cards"]==4 and claw["tracks"]==3,(width,claw)
  assert "작업하는 클로입니다." in claw["title"],(width,claw["title"])
  print(f"CLAW_FIRST_USE_COMPOSER_PARITY_{width}=PASS",flush=True)
  page.close()
 b.close()
