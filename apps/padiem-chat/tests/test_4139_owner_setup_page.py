"""Real product-owner browser setup: active B54 session, exact routes, no cache."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from app import connector_owner_setup_page as setup
from app.app_factory import create_app
from app.config import Settings
from app.connector_owner_runtime_mount import compose_owner_enrollment_from_worker
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME as I,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME as B,
)


class PrivateBinding:
    def __getattr__(self, name):
        if name in {
            "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
            "resolve_connector_enrollment_consent_for_device",
            "bind_connector_enrollment_challenge", "authorize_connector_enrollment_redeem",
            "issue_enrollment_challenge", "get_enrollment_binding",
            "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
        }:
            async def placeholder(*args, **kwargs):
                raise AssertionError("no private RPC in GET page")
            return placeholder
        raise AttributeError(name)


def app():
    env = {
        "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
        I: PrivateBinding(), B: PrivateBinding(),
    }
    settings = replace(Settings.from_env(), public_base_url="https://chat.padiem.net")
    return create_app(settings=settings, connector_owner_enrollment=compose_owner_enrollment_from_worker(env))


def get(application, path):
    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.get(path)
    return asyncio.run(call())


def signed():
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="canonical.owner.1",
        ),
        issued_at=now-timedelta(minutes=1),
        expires_at=now+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )


def test_browser_setup_requires_canonical_signed_owner(monkeypatch):
    application = app()
    assert get(application, setup.SETUP_PATH).status_code == 401
    monkeypatch.setattr(setup, "auth_ready", lambda request: True)
    monkeypatch.setattr(setup, "current_user_id", lambda request: "product.owner.1")
    async def other(request):
        return SimpleNamespace(product_user_id="product.owner.2", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", other)
    assert get(application, setup.SETUP_PATH).status_code == 401

    async def verified(request):
        return SimpleNamespace(product_user_id="product.owner.1", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", verified)
    response = get(application, setup.SETUP_PATH)
    assert response.status_code == 200
    assert "Padiem Connector" in response.text
    assert "setup.js" in response.text
    assert 'id="verify" disabled' in response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_script_does_not_persist_pairing_code_or_use_untrusted_owner_scope():
    application = app()
    script = get(application, setup.SCRIPT_PATH)
    assert script.status_code == 200
    assert script.headers["cache-control"].startswith("no-store")
    assert "localStorage.setItem" not in script.text
    assert "sessionStorage" not in script.text
    assert "console.log" not in script.text
    assert "navigator.clipboard" not in script.text
    assert "credentials: \"same-origin\"" in script.text
    assert "consent/grant" in script.text and "enrollments/issue" in script.text
    assert "enrollments/redeem" not in script.text
    assert "pagehide" in script.text
    assert "/api/claw/local-access/devices" in script.text
    assert "ownerScoped" in script.text
    assert 'matched.state === "OFFLINE"' in script.text
    assert 'matched.state === "CONNECTED"' in script.text
    assert "verify.disabled" in script.text


def test_default_product_app_has_no_setup_page_or_script():
    ordinary = create_app(settings=replace(Settings.from_env(), public_base_url="https://chat.padiem.net"))
    assert not any(getattr(r, "path", "") in {setup.SETUP_PATH, setup.SCRIPT_PATH} for r in ordinary.routes)


def test_signed_owner_page_has_single_native_launch_not_an_account_login():
    # The page is still owner-session gated by the existing tests above.
    assert 'id="native-launch"' in setup._HTML
    assert 'id="operator-restore"' in setup._HTML
    assert setup._HTML.index('id="native-launch"') < setup._HTML.index('id="operator-restore"')
    assert 'padiem-connector://start' in setup._SCRIPT
    assert '"padiem-connector://start"' in setup._SCRIPT
    assert 'location.href' in setup._SCRIPT
    assert 'padiem-connector://start?' not in setup._SCRIPT
    assert 'padiem-connector://start#' not in setup._SCRIPT
    assert 'id="secret" hidden' in setup._HTML
    assert '"enrollments/redeem"' not in setup._SCRIPT
    assert "navigator.clipboard" not in setup._SCRIPT
    assert "localStorage.setItem" not in setup._SCRIPT


def test_native_browser_launch_script_has_real_javascript_syntax_if_node_available():
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node not present; script syntax checked in Node-enabled CI")
    process = subprocess.run(
        ["node", "--check"], input=setup._SCRIPT, text=True,
        capture_output=True, timeout=15, check=False,
    )
    assert process.returncode == 0, process.stderr


def test_setup_page_forwards_pc_offer_to_original_claw_tab_without_post_or_approval():
    """Setup GET transports same-browser correlation only, not consent."""
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node unavailable")

    script = r"""
const assert=require("node:assert/strict");
const fs=require("node:fs");
const source=fs.readFileSync(0,"utf8");
const hooks={};
const fields={};
const forwarded=[];
const ref="link."+"a".repeat(32);
function field(id) {
  if(!fields[id]) fields[id]={
    hidden:id==="pending-pc",disabled:false,textContent:"",value:"",checked:false,
    addEventListener(evt,fn){hooks[id+":"+evt]=fn}
  };
  return fields[id];
}
globalThis.document={getElementById:field};
globalThis.window={location:{href:"https://chat.padiem.net/api/claw/connector/enrollments/setup?request_ref="+ref},addEventListener(){}};
globalThis.BroadcastChannel=class {
  constructor(name){assert.equal(name,"padiem-claw-pc-connect-v1");}
  postMessage(message){forwarded.push(message);}
  close(){}
};
let posts=0;
globalThis.fetch=async (_url,options)=>{if(options?.method==="POST")posts++;throw Error("setup must not fetch");};
eval(source);
assert.equal(field("pending-pc").hidden,false);
assert.equal(field("native-launch").hidden,true);
assert.equal(field("operator-restore").hidden,true);
assert.deepEqual(forwarded,[{type:"pc_offer_ready",request_ref:ref}]);
assert.equal(posts,0);
assert.equal("pending-approve:click" in hooks,false);
assert.equal("pending-consent:change" in hooks,false);
window.location.href="https://chat.padiem.net/api/claw/connector/enrollments/setup?request_ref=link.bad";
eval(source);
assert.equal(forwarded.length,1,"invalid offer ref is never forwarded");
assert.equal(posts,0);
"""
    outcome = subprocess.run(["node", "-e", script], input=setup._SCRIPT,
                             capture_output=True, text=True, timeout=15, check=False)
    assert outcome.returncode == 0, outcome.stderr


def test_setup_page_has_no_extra_consent_or_approve_control():
    assert 'id="pending-pc" hidden' in setup._HTML
    assert 'id="pending-approve"' not in setup._HTML
    assert 'id="pending-consent"' not in setup._HTML
    assert 'query.size === 1' in setup._SCRIPT
    assert 'new BroadcastChannel("padiem-claw-pc-connect-v1")' in setup._SCRIPT
    assert 'channel.postMessage({ type: "pc_offer_ready", request_ref: linkRef })' in setup._SCRIPT
    assert 'pendingApproval' not in setup._SCRIPT
    assert '/api/claw/connector/enrollments/approve-link' not in setup._SCRIPT
    assert 'padiem-connector://start?' not in setup._SCRIPT
    assert 'localStorage.setItem' not in setup._SCRIPT

def test_claw_original_click_approves_exactly_once_with_real_login_dom():
    """The Claw CTA, not setup GET, owns the single authenticated owner POST."""
    from pathlib import Path
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node unavailable")
    source = (Path(__file__).parents[1] / "static" / "claw-home-choices.js").read_text(encoding="utf-8")
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(0,'utf8');
const listeners={};let opens=0,posts=[],channels=[];
const node=(id)=>({dataset:{},hidden:false,disabled:false,
  addEventListener(e,fn){listeners[id+':'+e]=fn;},
  click(){},querySelector(){return null},focus(){},scrollIntoView(){},hasAttribute(){return true}});
const nodes={
  clawComputerWorkspace:node('clawComputerWorkspace'),
  clawWorkspace:Object.assign(node('clawWorkspace'),{dataset:{view:'general'}}),
  connectorsNavButton:node('connectorsNavButton'),
  connectorsDialog:Object.assign(node('connectorsDialog'),{open:true}),
  clawComputerLiveStatus:node('clawComputerLiveStatus'),
  clawComputerDeviceStatusButton:Object.assign(node('clawComputerDeviceStatusButton'),{disabled:true}),
};
const shell={dataset:{state:'claw'}};
const account={dataset:{accountState:'signed_in'}};
globalThis.document={
  readyState:'complete',documentElement:{lang:'en'},
  getElementById(id){return nodes[id]||null;},
  querySelector(s){return s==='.app-shell'?shell:s==='.sidebar-account'?account:
    s==='[data-claw-connection="pc"]'?{dataset:{connectionState:'off'}}:null;}
};
globalThis.window={addEventListener(){},location:{assign(){opens++;}},
  BroadcastChannel:class{constructor(n){assert.equal(n,'padiem-claw-pc-connect-v1');channels.push(this);}
    close(){};}};
globalThis.fetch=async (url,options)=>{
  posts.push({url,options});
  return {ok:true,text:async()=>JSON.stringify({ok:true,state:'awaiting_device_confirmation',
    device_id:'pc.1',connected:false,registered:false,dispatch_authorized:false})};
};
eval(source);
(async()=>{
  const ref='link.'+'a'.repeat(32);
  assert.equal(opens,0);assert.equal(posts.length,0);
  listeners['clawComputerWorkspace:click']();
  assert.equal(opens,1);assert.equal(channels.length,1);
  channels[0].onmessage({data:{type:'pc_offer_ready',request_ref:ref}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/api/claw/connector/enrollments/approve-link');
  assert.equal(posts[0].options.credentials,'same-origin');
  assert.deepEqual(JSON.parse(posts[0].options.body),{request_ref:ref});
  channels[0].onmessage({data:{type:'pc_offer_ready',request_ref:ref}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(posts.length,1,'duplicate must not approve');
  account.dataset.accountState='signed_out';
  listeners['clawComputerWorkspace:click']();
  assert.equal(opens,1,'signed out must not launch');
})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script], input=source, capture_output=True,
                            text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr


def test_claw_owner_approval_records_only_allowlisted_http_outcomes():
    """One real original-click path, bounded response classes, no raw error logging."""
    from pathlib import Path
    import subprocess
    import shutil
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node unavailable")
    source = (Path(__file__).parents[1] / "static" / "claw-home-choices.js").read_text(encoding="utf-8")
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(0,'utf8');
const tests=[
 {name:'denied403',status:403,body:{ok:false,error:{code:'connector_enrollment_csrf_denied'}},
  expected:['approve_http_403','approve_denied_connector_enrollment_csrf_denied','approve_failed']},
 {name:'denied_unknown',status:503,body:{ok:false,error:{code:'SECRETS_MUST_NOT_LOG'}},
  expected:['approve_http_503','approve_denied_unclassified','approve_failed']},
 {name:'transport',failure:'fetch',expected:['approve_fetch_rejected','approve_failed']},
 {name:'bad_json',status:200,raw:'not-json',
  expected:['approve_http_200','approve_receipt_json_invalid','approve_failed']},
 {name:'bad_receipt',status:200,body:{ok:true,state:'bogus'},
  expected:['approve_http_200','approve_receipt_contract_invalid','approve_failed']},
 {name:'success',status:200,body:{ok:true,state:'awaiting_device_confirmation',
    connected:false,registered:false,dispatch_authorized:false},
  expected:['approve_http_200','approve_receipt_valid']}
];
(async()=>{
for(const tc of tests) {
 const messages=[],listeners={},channels=[],calls=[];
 function el(id){return {dataset:id==='clawWorkspace'?{view:'general'}:{},hidden:false,
   disabled:id==='clawComputerDeviceStatusButton',click(){},
   addEventListener(event,fn){listeners[id+':'+event]=fn;}};}
 const nodes=Object.fromEntries(['clawComputerWorkspace','clawWorkspace','connectorsNavButton',
   'connectorsDialog','clawComputerLiveStatus','clawComputerDeviceStatusButton']
   .map(id=>[id,el(id)]));
 nodes.connectorsDialog.open=true;
 const document={
  readyState:'complete',documentElement:{lang:'en'},
  querySelector(selector){
   if(selector==='.app-shell')return {dataset:{state:'claw'}};
   if(selector==='.sidebar-account')return {dataset:{accountState:'signed_in'}};
   if(selector==='[data-claw-connection="pc"]')return {dataset:{connectionState:'off'}};
   return null;
  },
  getElementById(id){return nodes[id]||null;}
 };
 class Channel{constructor(){channels.push(this)}close(){}}
 const context=vm.createContext({document,console:{info:(line)=>messages.push(line)},
    window:{addEventListener(){},location:{assign(){}},BroadcastChannel:Channel},
    fetch:async(url,opts)=>{
      calls.push({url,method:opts.method,credentials:opts.credentials});
      if(tc.failure==='fetch')throw Error('TOKEN_MUST_NOT_LOG');
      return {ok:tc.status===200,status:tc.status,text:async()=>
        tc.raw!==undefined?tc.raw:JSON.stringify(tc.body)};
    }});
 vm.runInContext(source,context);
 assert.equal(channels.length,0,tc.name);
 listeners['clawComputerWorkspace:click']();
 assert.equal(channels.length,1,tc.name);
 vm.runInContext('void 0',context);
 const callback=channels[0].onmessage;
 const event=vm.runInContext("({data:{type:'pc_offer_ready',request_ref:'link.'+'a'.repeat(32)}})",context);
 callback(event);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,1,tc.name);
 assert.equal(calls[0].url,'/api/claw/connector/enrollments/approve-link');
 assert.equal(calls[0].method,'POST');
 assert.equal(calls[0].credentials,'same-origin');
 const actual=messages.filter(m=>m.startsWith('PADIEM_4139_STAGE=')).map(m=>m.slice(18));
 for(const code of tc.expected)assert(actual.includes(code),tc.name+':'+JSON.stringify(actual));
 assert(!messages.join('').includes('SECRETS_MUST_NOT_LOG'),tc.name);
 assert(!messages.join('').includes('TOKEN_MUST_NOT_LOG'),tc.name);
 const saved=context.window.__padiemPcConnectStages;
 for(const code of tc.expected)assert(saved.includes(code),tc.name+' buffer '+code);
 assert(!JSON.stringify(saved).includes('SECRETS_MUST_NOT_LOG'),tc.name);
 assert(!JSON.stringify(saved).includes('TOKEN_MUST_NOT_LOG'),tc.name);
}
})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1});
"""
    proc = subprocess.run(["node", "-e", script], input=source, capture_output=True,
                          text=True, check=False, timeout=15)
    assert proc.returncode == 0, proc.stderr
