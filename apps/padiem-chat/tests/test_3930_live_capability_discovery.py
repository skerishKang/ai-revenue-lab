"""#3930 capability discovery: server-owned and zero-dispatch."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import json
import subprocess
from pathlib import Path

from app.claw_general_routes import CLAW_LIVE_REQUEST_HEADER
from test_b54_claw_general_p01_routing import _client, _make_adapter

ROOT=Path(__file__).resolve().parents[1]
CAP="/api/claw/general/capabilities"
SUBJECT = "sub_" + "9" * 32



def _adapter(subject=True, stream=True):
    a=_make_adapter(subject_lane=subject)
    a._runner=SimpleNamespace(run_stream=(lambda *_args, **_kwargs: None)) if stream else None
    return a


@contextmanager
def _canary_client(adapter):
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT))))):
        with _client(adapter) as client:
            client.app.state.claw_live_sse_canary_subject_id = SUBJECT
            yield client

def test_capability_disabled_and_no_dispatch_or_quota():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        denied=client.get(CAP)
    assert denied.status_code==200
    assert denied.json()=={"live_events_available":False}
    assert "no-store" in denied.headers["cache-control"]
    adapter.execute.assert_not_awaited()


def test_capability_requires_signed_in_user_even_if_server_enabled():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        client.cookies.clear()
        denied=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_capability_requires_real_stream_runner():
    adapter=_adapter(stream=False)
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        denied=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_capability_follows_current_server_flag():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        allowed=client.get(CAP)
        client.app.state.claw_live_sse_enabled=False
        denied=client.get(CAP)
    assert allowed.json()=={"live_events_available":True}
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_canonical_subject_requires_real_current_session():
    adapter=_adapter(subject=True)
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", new=AsyncMock(return_value=None)):
            denied=client.get(CAP)
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", new=AsyncMock(return_value=SimpleNamespace(auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT))))):
            allowed=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    assert allowed.json()=={"live_events_available":True}
    adapter.execute.assert_not_awaited()


def test_server_flag_never_treats_browser_header_as_capability_authority():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=False
        resp=client.get(CAP, headers={CLAW_LIVE_REQUEST_HEADER:"p01-events-v1"})
    assert resp.json()=={"live_events_available":False}


def test_js_browser_probe_reuses_only_one_post_and_never_retries():
    transport=(ROOT/"static"/"chat-transport.js").read_text(encoding="utf-8")
    harness=r"""
const vm=require('vm');
const source=process.argv[1];
const results=[];
function response(ok=true, status=200, type="text/event-stream") {
 return {ok,status,headers:{get:(k)=>k==="content-type"?type:null},json:async()=>({error:{code:"claw_live_stream_unavailable"}})};
}
async function scenario(capability, postStatus=200, controller=null) {
 const calls=[];
 const signal=controller?.signal;
 const fetch=async (url,opt={})=>{
  calls.push({url,method:opt.method,headers:opt.headers,signal:opt.signal});
  if(url.endsWith("capabilities")) {
   if(capability==="network_error") throw new Error("offline");
   if(capability==="aborted") {const e=new Error("cancel");e.name="AbortError";throw e;}
   if(capability==="bad_response") return {ok:false};
   return {ok:true,json:async()=>({live_events_available:capability===true})};
  }
  return response(postStatus===200,postStatus,postStatus===200?"text/event-stream":"application/json");
 };
 const ctx={window:{},fetch,console,AbortController};
 vm.runInNewContext(source,ctx);
 let outcome="ok";
 try {await ctx.window.PadiemChatTransport.requestClawGeneral({messages:[{role:"user",content:"hello"}]},signal);}
 catch(e) {outcome=e.name==="AbortError"?"aborted":"error";}
 return {calls,outcome};
}
(async()=>{
 for(const c of [true,false,"network_error","bad_response","aborted"]) results.push({cap:c,...await scenario(c)});
 results.push({cap:"server_post_denies",...await scenario(true,503)});
 console.log(JSON.stringify(results));
})().catch(e=>{console.error(e);process.exit(1)});
"""
    result=subprocess.run(["node","-e",harness,transport],capture_output=True,text=True,encoding="utf-8",check=True)
    scenarios=json.loads(result.stdout)
    for record in scenarios:
        calls=record["calls"]
        assert calls[0]["url"]==CAP
        assert calls[0]["method"]=="GET"
        if record["cap"]=="aborted":
            assert record["outcome"]=="aborted"
            assert len(calls)==1
            continue
        assert len(calls)==2,record
        assert calls[1]["url"]=="/api/claw/general"
        assert calls[1]["method"]=="POST"
        assert calls[1]["headers"].get(CLAW_LIVE_REQUEST_HEADER)==("p01-events-v1" if record["cap"] is True or record["cap"]=="server_post_denies" else None)
        if record["cap"]=="server_post_denies":
            assert record["outcome"]=="error"
        else:
            assert record["outcome"]=="ok"
