from playwright.sync_api import sync_playwright
import json
import os
URL=os.environ.get("B62_QA_BASE_URL","http://127.0.0.1:8765").rstrip("/")+"/?qa=claw-connection-chips"
def rows(state):
 return {"workspace_state_authority":True,"connectors":[{"connector_id":"connector:google:drive@1","workspace_state":state}]}
def setup(context,dr,pc):
 writes=[]
 state={"drive":dr}
 def status(route):
  route.fulfill(status=200,content_type="application/json",body=json.dumps(rows(state["drive"])))
 def devices(route):
  route.fulfill(status=200,content_type="application/json",body=json.dumps(pc))
 def disconnect(route):
  state["drive"]="not_connected"
  route.fulfill(status=200,content_type="application/json",body=json.dumps({"ok":True,"state":"off","revoked":True}))
 context.route("**/api/connectors/status",status)
 context.route("**/api/connectors/google/drive/disconnect",disconnect)
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
 # Drive ON is authorized but cannot be temporarily paused; never revoke
 # the existing OAuth grant from this status chip. Show management guidance.
 page.locator('[data-claw-connection="drive"]').click()
 assert page.locator("#clawConnectionGuide").evaluate("(e)=>e.open") is True
 after=page.locator('[data-claw-connection="drive"]').get_attribute("data-connection-state")
 assert after=="on" and not writes,(after,writes)
 page.close();ctx.close()
 ctx=b.new_context();writes=setup(ctx,"not_connected",{"ok":True,"available":True,"ownerScoped":True,"devices":[]})
 page=ctx.new_page(); c=check(page,{"pc":"off","drive":"off","github":"unknown"})
 # Drive OFF enters the existing trusted OAuth quick-connect path instead
 # of showing the obsolete connectorsDialog (Connectors is now a view).
 page.evaluate("""() => {
   window.__driveQuickConnects = 0;
   document.addEventListener("padiem:drive-quick-connect",
     () => window.__driveQuickConnects++, {capture:true});
 }""")
 page.locator('[data-claw-connection="drive"]').click()
 page.wait_for_function("() => window.__driveQuickConnects === 1",timeout=3000)
 assert not any("/api/connectors/google/drive/disconnect" in req for req in writes),writes
 page.close();ctx.close()
 ctx=b.new_context()
 ctx.route("**/api/connectors/status",lambda r:r.fulfill(status=503,content_type="application/json",body='{"error":"offline"}'))
 ctx.route("**/api/claw/local-access/devices",lambda r:r.fulfill(status=401,content_type="application/json",body='{"error":"login"}'))
 page=ctx.new_page(); d=check(page,{"pc":"unknown","drive":"unknown","github":"unknown"})
 page.close();ctx.close();b.close()
 print("CLAW_REAL_STATUS_CHIPS=PASS")
 print("DRIVE_ON_GRANT_RETAINED_NO_SILENT_REVOKE=PASS")
 print("DRIVE_OFF_CANONICAL_OAUTH_QUICK_CONNECT=PASS")
 print("UNKNOWN_FAIL_CLOSED=PASS")
 print("PRODUCTION_MUTATION=0")
