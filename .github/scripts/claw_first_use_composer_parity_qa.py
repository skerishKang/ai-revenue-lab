"""Visual first-use parity: Claw shares Chat geometry, composer and truthful switch faces.

#5561: the comparison also covers the vertical axis. This script compared x and
width only, so the Claw brand line sitting ~30px below the Chat one on the same
screen passed CI while the owner saw it. The row the brand line and the hero
start on is one shared token now (shared-six-panel-frame.css), and the Y parity
below is what keeps a product- or mode-specific inset from coming back.
"""
import os
from playwright.sync_api import sync_playwright

BASE=os.environ.get("B62_QA_BASE_URL","http://127.0.0.1:8765").rstrip("/")+"/"
# Measured on the shared-origin build (height 900, after #5561 unified the
# first-screen inset). The brand line and the hero row:
#   1440 -> 0.00   900 -> 7.67   390 -> 1.66
# The composer band: 0 / 8 / 8. The card row: 0 / 7.67 / 76.98, and that last
# number is a genuine content difference -- Claw's phone first screen is its own
# 2x2 connection grid, so it is reported, not pinned.
# The ceilings keep each shared row from drifting while the remaining layout-model
# difference (grid in Claw against block plus an inline first line in Chat) is
# unified next; the desktop row stays exact.
TOP_TOLERANCE={1440:{'eyebrow':2,'heading':2,'grid':2,'composer':2},
               900:{'eyebrow':8,'heading':8,'grid':8,'composer':8},
               390:{'eyebrow':2,'heading':2,'composer':8}}
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for width in (1440,900,390):
  page=b.new_page(viewport={"width":width,"height":900})
  page.goto(BASE,wait_until="domcontentloaded",timeout=20000)
  page.wait_for_timeout(450)
  def metrics():
   return page.evaluate("""() => {
    const visible=s=>{const n=document.querySelector(s);return !!(n && n.getClientRects().length)};
    const rect=s=>{const n=document.querySelector(s);if(!n)return null;const r=n.getBoundingClientRect();return [r.x,r.width,r.y,r.height]};
    return {eyebrow:rect('.eyebrow'),heading:rect('#emptyState h1'),grid:rect('.starter-grid'),
      composer:rect('.composer-wrap'),tools:getComputedStyle(document.querySelector('.composer-tools')).display,
      ownerStatus:visible('.composer-tier-trigger'),
      fileTool:visible('#attachmentButton'),
      modelPill:visible('.composer-tier-trigger'),
      entry:document.querySelector('#clawManualEntryBar')
        ? getComputedStyle(document.querySelector('#clawManualEntryBar')).display : 'missing',
      cards:[...document.querySelectorAll('.claw-home-card')].filter(e=>getComputedStyle(e).display!=='none').length,
      tracks:document.querySelectorAll('.claw-connection-track').length,
      cellH:(()=>{const n=document.querySelector('.starter-grid > .starter');return n&&n.getClientRects().length?Math.round(n.getBoundingClientRect().height):null})(),
      cardH:(()=>{const n=[...document.querySelectorAll('.claw-home-card')].find(e=>e.getClientRects().length);return n?Math.round(n.getBoundingClientRect().height):null})(),
      inlineLabels:[...document.querySelectorAll('.claw-home-card .claw-connection-label')].filter(e=>getComputedStyle(e).display!=='none').length,
      statusTopRight:[...document.querySelectorAll('.claw-home-card')].filter(c=>{
        const s=c.querySelector('.claw-card-status');if(!s||!c.getClientRects().length)return false;
        const cr=c.getBoundingClientRect(),sr=s.getBoundingClientRect();
        return sr.top-cr.top<26 && cr.right-sr.right<26}).length,
      toggleBottomRight:[...document.querySelectorAll('.claw-home-card .claw-connection-toggle')].filter(t=>{
        const card=t.closest('.claw-home-card');if(!card||!t.getClientRects().length)return false;
        const cr=card.getBoundingClientRect(),tr=t.getBoundingClientRect();
        return cr.bottom-tr.bottom<26 && cr.right-tr.right<26}).length,
      title:document.querySelector('#emptyState h1').innerText}
   }""")
  chat=metrics()
  if width<=920:page.locator("#mobileMenu").click()
  page.locator("#clawNavButton").click()
  page.wait_for_timeout(300)
  claw=metrics()
  for key in ("heading","grid","composer"):
   assert chat[key] is not None and claw[key] is not None,(width,key,chat,claw)
   for i in (0,1):
    assert abs(chat[key][i]-claw[key][i])<=2,(width,key,chat[key],claw[key])
   # The vertical row: 2px at desktop, the measured ceiling on the narrower
   # layouts, so a product-specific inset cannot move the shared first line.
   if key in TOP_TOLERANCE[width]:
    assert abs(chat[key][2]-claw[key][2])<=TOP_TOLERANCE[width][key],(width,key,chat[key],claw[key])
  assert chat["eyebrow"] is not None and claw["eyebrow"] is not None,(width,"eyebrow",chat,claw)
  assert abs(chat["eyebrow"][0]-claw["eyebrow"][0])<=2,(width,"eyebrow",chat,claw)
  assert abs(chat["eyebrow"][2]-claw["eyebrow"][2])<=TOP_TOLERANCE[width]["eyebrow"],(width,"eyebrow-top",chat["eyebrow"],claw["eyebrow"])
  assert claw["tools"]=="flex" and claw["entry"]=="none",(width,claw)
  assert claw["ownerStatus"] and chat["ownerStatus"],(width,"model-status",chat,claw)
  assert claw["fileTool"] and claw["modelPill"],(width,"shared-tools",claw)
  assert claw["cards"]==4 and claw["tracks"]==3,(width,claw)
  # The Claw connector cards and the Chat first-use cells are one surface: the
  # row must resolve to the same height in both, the truthful headline sits in
  # the top-right of every card, and the bottom-right holds the ON/OFF switch
  # alone (no inline "확인 불가" row stretching the card).
  assert chat["cellH"] is not None and claw["cardH"] is not None,(width,"row-height",chat,claw)
  assert abs(chat["cellH"]-claw["cardH"])<=2,(width,"row-height",chat["cellH"],claw["cardH"])
  assert claw["inlineLabels"]==0,(width,"inline-label",claw)
  assert claw["statusTopRight"]==3,(width,"status-placement",claw)
  assert claw["toggleBottomRight"]==3,(width,"toggle-placement",claw)
  assert "\uD074\uB85C" in claw["title"],(width,claw["title"])
  print(f"CLAW_FIRST_USE_COMPOSER_PARITY_{width}=PASS "
        f"eyebrowTopDelta={round(abs(chat['eyebrow'][2]-claw['eyebrow'][2]),2)} "
        f"headingTopDelta={round(abs(chat['heading'][2]-claw['heading'][2]),2)} "
        f"composerTopDelta={round(abs(chat['composer'][2]-claw['composer'][2]),2)}",flush=True)
  page.close()
 b.close()
