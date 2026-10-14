from playwright.sync_api import sync_playwright
import json
import os
URL=os.environ.get("B62_QA_BASE_URL","http://127.0.0.1:8765").rstrip("/")+"/?qa=claw-connection-chips"
def rows(state):
 return {"workspace_state_authority":True,"connectors":[{"connector_id":"connector:google:drive@1","workspace_state":state}]}
def setup(context,dr,pc):
 writes=[]
 def status(route):
  route.fulfill(status=200,content_type="application/json",body=json.dumps(rows(dr)))
 def devices(route):
  route.fulfill(status=200,content_type="application/json",body=json.dumps(pc))
 context.route("**/api/connectors/status",status)
 context.route("**/api/claw/local-access/devices",devices)
 context.on("request",lambda req: writes.append(req.method+" "+req.url) if req.method not in ("GET","HEAD") else None)
 return writes
def check(page,expected):
 page.goto(URL,wait_until="domcontentloaded",timeout=20000)
 page.wait_for_timeout(2200)
 page.evaluate("document.getElementById('clawNavButton').click()")
 page.evaluate("document.querySelector('.sidebar-account').dataset.accountState='signed_in'")
 page.wait_for_function("""expected => ['pc','drive','github'].every(k =>
    document.querySelector('[data-claw-connection="'+k+'"]')?.dataset.connectionState===expected[k])""",arg=expected,timeout=8000)
 vals=page.evaluate("""() => Object.fromEntries(['pc','drive','github'].map(x=>[x,document.querySelector('[data-claw-connection="'+x+'"]').dataset.connectionState]))""")
 assert vals==expected,(vals,expected)
 return vals
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 ctx=b.new_context()
 writes=setup(ctx,"connected",{"ok":True,"available":True,"ownerScoped":True,"devices":[{"state":"CONNECTED","usable":True,"expired":False,"revoked":False}]})
 page=ctx.new_page()
 a=check(page,{"pc":"on","drive":"on","github":"unknown"})
 page.on("dialog",lambda dialog:dialog.accept())
 page.locator('[data-claw-connection="drive"]').click()
 page.wait_for_function("() => document.querySelector('[data-claw-connection=\"drive\"]').dataset.connectionState === 'on'",timeout=7000)
 after=page.locator('[data-claw-connection="drive"]').get_attribute("data-connection-state")
 assert after=="on" and len(writes)==0,(after,writes)
 assert len(page.locator("#clawConnectionFeedback").inner_text().strip()) > 10
 page.close();ctx.close()
 ctx=b.new_context();writes=setup(ctx,"not_connected",{"ok":True,"available":True,"ownerScoped":True,"devices":[]})
 page=ctx.new_page(); c=check(page,{"pc":"off","drive":"off","github":"unknown"})
 page.locator('[data-claw-connection="drive"]').click()
 assert page.locator("#connectorsDialog").evaluate("(e)=>e.open") is True
 assert len(writes)==0,writes
 page.close();ctx.close()
 ctx=b.new_context()
 ctx.route("**/api/connectors/status",lambda r:r.fulfill(status=503,content_type="application/json",body='{"error":"offline"}'))
 ctx.route("**/api/claw/local-access/devices",lambda r:r.fulfill(status=401,content_type="application/json",body='{"error":"login"}'))
 page=ctx.new_page(); d=check(page,{"pc":"unknown","drive":"unknown","github":"unknown"})
 page.close();ctx.close();b.close()
 print("CLAW_REAL_STATUS_CHIPS=PASS")
 print("ON_CONFIRM_NO_FAKE_DISCONNECT=PASS")
 print("OFF_CANONICAL_CONNECT_DIALOG=PASS")
 print("UNKNOWN_FAIL_CLOSED=PASS")
 print("PRODUCTION_MUTATION=0")
