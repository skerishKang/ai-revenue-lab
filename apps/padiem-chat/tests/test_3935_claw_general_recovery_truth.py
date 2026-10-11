"""#3935: actual Claw General SSE renderer recovery behavior, Node-only fixtures.

Browser source code is executed in a network-free VM. No P01, B14, or provider
calls. Partial output and canonical run states are inspected after transport.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LIFECYCLE = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
RECOVERY = (STATIC / "claw-recovery-truth.js").read_text(encoding="utf-8")
EVENT = (STATIC / "claw-run-event-projection.js").read_text(encoding="utf-8")

NODE = r"""
const vm=require("vm"),fs=require("fs"),path=require("path");
const dir=process.argv[1];
const read=n=>fs.readFileSync(path.join(dir,n),"utf8");
const win={};
const ctx={window:win,queueMicrotask(){},document:{documentElement:{lang:"en"},createElement(type){
    return {tagName:type.toUpperCase(),textContent:"",children:[],setAttribute(k,v){this[k]=v},
      append(...xs){this.children.push(...xs)},appendChild(x){this.children.push(x)},
      remove(){this.removed=true},focus(){},querySelector(){return null}};
}}};
vm.runInNewContext(read("claw-run-event-projection.js"),ctx);
vm.runInNewContext(read("claw-recovery-truth.js"),ctx);
vm.runInNewContext(read("message-lifecycle.js"),{...ctx,CustomEvent:class{constructor(name,data){this.type=name;this.detail=data.detail}}});
const P=win.PadiemClawRecoveryTruth;
function assert(v,msg){if(!v)throw Error(msg)}
const x=P.create();assert(!x.seen(),"no synthetic state");
assert(!x.observe("tool_from_outside"),"unknown no action");
assert(x.observe("run_started"),"real start accepted");
assert(x.observe("approval_paused"),"approval accepted");
assert(x.state()==="waiting_for_approval"&&!x.completionAllowed(),"pending not complete");
assert(!x.observe("run_completed"),"approval cannot silently complete");
assert(x.observe("run_resumed"),"verified resume accepted");
assert(x.observe("run_completed")&&x.completionAllowed(),"resumed can finish");
assert(!x.observe("run_failed"),"cannot replace terminal completed");
const p=P.create();p.observe("run_started");p.observe("run_failed");
assert(p.state()==="failed"&&!p.completionAllowed(),"failure terminal");
const c=P.create();c.observe("run_started");c.observe("run_cancelled");
assert(c.state()==="cancelled"&&!c.completionAllowed(),"cancellation terminal");
assert(P.copy("unknown","en").includes("may already have executed"),"safe uncertainty");
assert(!P.copy("failed","ko").includes("PASSWORD"),"no external body");
const app=read("app.js");
const start=app.indexOf("  async function requestStreamingAnswer(");
const end=app.indexOf("\n  function cancelActiveStream(",start);
assert(start>=0&&end>start,"actual SSE handler located");
let sent=[],count=0,doneCalls=0;
function element(type){
 const e={tagName:type.toUpperCase(),textContent:"",children:[],dataset:{},
   append(...xs){this.children.push(...xs)},appendChild(x){this.children.push(x)},
   replaceChildren(...xs){this.children=xs},querySelector(q){return q===".typing"?this.children.find(n=>n.tagName==="SPAN"&&n.isTyping):null},
   remove(){this.removed=true},setAttribute(k,v){this[k]=v},scrollIntoView(){}};
 return e;
}
const actor={content:element("div"), marker:element("small"),body:element("div"),dataset:{},events:[],
 querySelector(q) {
   if(q===".assistant-content")return this.content;
   if(q==="[data-runtime-label]")return this.marker;
   if(q===".assistant-body")return this.body;
   return null;
 },scrollIntoView(){},dispatchEvent(e){this.events.push(e)}};
const transport={
 requestClawGeneral:async()=>({}),
 requestStreaming:async()=>({}),
 readSseEvents:async(_resp,fn)=>{for(const f of sent){if(await fn(f))break}},
 errorFor:(_data,msg)=>new Error(msg),
};
const serverEvent=(kind,seq,delivery="live")=>({
 event:"p01_event",
 data:JSON.stringify({event_id:"evt."+seq,run_id:"run.test",trace_id:"trace.test",
 app_id:"claw",kind,sequence:seq,timestamp_iso:"2026-10-10T01:00:00Z",delivery,
 message:"SECRET_UNTRUSTED",metadata:{api_key:"SHOULD_NEVER_APPEAR"}})
});
const delta=(v)=>({event:"delta",data:JSON.stringify({delta:v})});
const done=()=>({event:"done",data:JSON.stringify({done:true})});
const fail=(msg)=>({event:"error",data:JSON.stringify({error:{message:msg}})});
const fake={
 chatTransport:transport,document:ctx.document,window:win,uiT:k=>k,
 PadiemChatLifecycle:win.PadiemChatLifecycle,
 MESSAGE_LIFECYCLE:win.PadiemChatLifecycle.states,
 revealErrorState(){},applyStreamDone(article){doneCalls++;win.PadiemChatLifecycle.set(article,"completed")},
 renderStreamError(article,message){article.content.appendChild(Object.assign(element("p"),{textContent:message}));win.PadiemChatLifecycle.set(article,"failed")},
};
const fn=vm.runInNewContext("("+app.slice(start,end)+")",fake);
async function scenario(name,frames,expected,partial,success=false){
 const article=Object.assign({},actor,{content:element("div"),marker:element("small"),body:element("div"),dataset:{},events:[]});
 sent=frames;
 const before=doneCalls;
 const result=await fn(article,{},[],"auto",{},null,{clawGeneral:true});
 assert(result===success,name+" boolean "+result);
 assert(article.dataset.lifecycle===expected,name+" state "+article.dataset.lifecycle);
 const rendered=article.content.children.map(x=>x.textContent).join(" ");
 assert(rendered.includes(partial),name+" partial retained "+rendered);
 assert(!rendered.includes("SECRET_UNTRUSTED"),name+" secret leaked");
 assert(!rendered.includes("SHOULD_NEVER_APPEAR"),name+" metadata leaked");
 assert(doneCalls-before===(success?1:0),name+" exactly allowed applyStreamDone");
 return rendered;
}
(async()=>{
 const started=serverEvent("run_started",1);
 const failed=serverEvent("run_failed",2);
 const cancelled=serverEvent("run_cancelled",2);
 const paused=serverEvent("approval_paused",2);
 let text=await scenario("failed plus done",[started,delta("partial-work"),failed,done()],"failed","partial-work");
 assert(text.includes("Execution failed"),"failed bounded UX");
 text=await scenario("cancelled plus done",[started,delta("partial-cancel"),cancelled,done()],"cancelled","partial-cancel");
 assert(text.includes("cancelled"),"cancel bounded UX");
 text=await scenario("approval plus done",[started,delta("partial-approval"),paused,done()],"waiting_for_approval","partial-approval");
 assert(text.includes("awaiting approval"),"approval bounded UX");
 text=await scenario("failed without done",[started,delta("partial-no-done"),failed],"failed","partial-no-done");
 text=await scenario("approval without done",[started,paused],"waiting_for_approval","awaiting approval");
 text=await scenario("server error raw provider",[started,delta("partial-502"),fail("SECRET_PROVIDER_RAW")],"failed","partial-502");
 assert(!text.includes("SECRET_PROVIDER_RAW"),"provider body sanitised");
 await scenario("confirmed failure plus raw server error",[started,delta("partial-verified-fail"),failed,fail("RAW_SECRET")],"failed","partial-verified-fail");
 await scenario("cancelled plus transport error",[started,delta("partial-verified-cancel"),cancelled,fail("RAW_SECRET")],"cancelled","partial-verified-cancel");
 await scenario("approval plus transport error",[started,paused,fail("RAW_SECRET")],"waiting_for_approval","awaiting approval");
 await scenario("late delta after terminal ignored",[started,failed,delta("late-untrusted"),done()],"failed","Execution failed");
 await scenario("completed",[started,delta("real answer"),serverEvent("run_completed",2),done()],"completed","real answer",true);
 const invalid=serverEvent("run_failed",2);
 invalid.data=JSON.stringify({...JSON.parse(invalid.data),run_id:"foreign"});
 await scenario("forged foreign event ignored",[started,delta("valid"),invalid,done()],"completed","valid",true);
 console.log("CLAW_3935_CANONICAL_TERMINAL_OVERRIDES_DONE=PASS");
 console.log("CLAW_3935_PARTIAL_PRESERVED_AND_NO_AUTO_REPLAY=PASS");
 console.log("CLAW_3935_APPROVAL_NOT_SYNTHETIC=PASS");
 console.log("CLAW_3935_UNTRUSTED_PROVIDER_BODY_NOT_RENDERED=PASS");
 console.log("CLAW_3935_ORDINARY_COMPLETION_PRESERVED=PASS");
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


def test_recovery_source_loaded_before_application_and_no_retry_authority():
    assert INDEX.count('<script src="./claw-recovery-truth.js"></script>') == 1
    assert INDEX.index("claw-run-event-projection.js") < INDEX.index("claw-recovery-truth.js") < INDEX.index('<script src="./app.js">')
    assert 'PadiemClawRecoveryTruth?.create?.()' in APP
    assert 'verifiedClawRecovery?.observe(projected.kind)' in APP
    assert 'verifiedClawRecovery.completionAllowed()' in APP
    assert 'MESSAGE_LIFECYCLE.WAITING_APPROVAL' in APP
    assert 'WAITING_APPROVAL: "waiting_for_approval"' in LIFECYCLE
    assert "PadiemClawRecoveryTruth.copy" in APP
    for forbidden in ("fetch(", "setTimeout(", "setInterval(", "localStorage", "sessionStorage", "innerHTML", "EventSource", "new WebSocket", "approve(", "retry("):
        assert forbidden not in RECOVERY


def test_actual_renderer_terminal_and_raw_body_with_node_vm():
    cp = subprocess.run(["node", "-e", NODE, str(STATIC)], capture_output=True, text=True,
                        encoding="utf-8", check=False, timeout=25)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    for marker in (
        "CLAW_3935_CANONICAL_TERMINAL_OVERRIDES_DONE=PASS",
        "CLAW_3935_PARTIAL_PRESERVED_AND_NO_AUTO_REPLAY=PASS",
        "CLAW_3935_APPROVAL_NOT_SYNTHETIC=PASS",
        "CLAW_3935_UNTRUSTED_PROVIDER_BODY_NOT_RENDERED=PASS",
        "CLAW_3935_ORDINARY_COMPLETION_PRESERVED=PASS",
    ):
        assert marker in cp.stdout


def test_separate_generic_chat_retry_policy_preserved():
    assert "function buildRetryBox(" in APP
    assert "if (clawGeneralRequest)" in APP
    assert 'hint.textContent = uiT("claw-general-check-runs")' in APP
    assert 'requestAnswer(retryMessages, retrySkill' in APP
    assert "runClawExecution" in APP
