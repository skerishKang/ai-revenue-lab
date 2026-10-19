"""#3936: a Claw model HOLD must reach the user as a model refusal, not an Engine failure.

`/api/claw/general` refuses a tier with no executable model route (#3566/#3568)
before dispatch, with quota refunded, and the general route projects that family
as bounded ``503 tier_unavailable``. The composer previously discarded every
Claw error code and rendered the unverified-run state ("this run may already have
started"), which is a false claim for a refusal that provably never dispatched.

Network-free Node behavior runs the ACTUAL closed code→copy map and the ACTUAL
retry-box builder. Call-site wiring is asserted on source text, the pattern this
repo already uses for these DOM paths. No B14, Engine or provider call happens,
and no model/provider selection or routing is changed by this module.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.claw_general_routes import _MODEL_HOLD_USER_MESSAGE

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

NODE = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = process.argv[1];
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");

function assert(condition, label) { if (!condition) throw Error(label); }
function element(type) {
  return {
    tagName: type.toUpperCase(), children: [], textContent: "", className: "", handlers: {},
    append(...nodes) { this.children.push(...nodes); },
    addEventListener(kind, fn) { this.handlers[kind] = fn; },
    remove() {},
  };
}

// Evaluate the real map + helper + retry-box builder as one unit.
const start = app.indexOf("  const CLAW_BOUNDED_REFUSAL_COPY");
const end = app.indexOf("\n  function revealErrorState(", start);
assert(start >= 0 && end > start, "source locator");
let replays = 0;
let historyOpens = 0;
const history = { hidden: false, scrollIntoView() {}, querySelector: () => ({ focus() {} }) };
const context = {
  Object,
  window: { PadiemClawRecoveryTruth: { copy: (state) => "recovery:" + state } },
  document: {
    documentElement: { lang: "ko" },
    createElement: element,
    getElementById: (id) => (id === "clawRunHistory" ? history : null),
  },
  uiT: (key) => key,
  authState: { authenticated: true },
  openClawWorkspace() { historyOpens += 1; },
  conversationState: { setConversationId() {} },
  renderProjectState() {},
  requestAnswer: async () => { replays += 1; return false; },
  selectedAttachment: null,
  clearAttachment() {},
};
const api = vm.runInNewContext(
  "(function(){" + app.slice(start, end) + "\nreturn { clawGeneralFailure, buildRetryBox };\n})()",
  context,
);

// 1. The bounded pre-dispatch refusal owns its copy; nothing claims a dispatch.
const hold = api.clawGeneralFailure("tier_unavailable");
assert(hold.message === "claw-general-model-unavailable", "HOLD message key");
assert(hold.hint === "claw-general-model-unavailable-note", "HOLD next-step hint");

// 2. A real Engine failure keeps the previous unverified-run state unchanged.
const engine = api.clawGeneralFailure("engine_execution_failed");
assert(engine.message === "recovery:unknown", "engine failure copy unchanged");
assert(engine.hint === "claw-general-check-runs", "engine failure hint unchanged");

// 3. Fail-closed classification: only the closed map answers, anything else is
//    the existing unverified state. Object.prototype keys are never promoted.
for (const spoof of ["", null, undefined, 0, {}, "tier_hold", "max_tier_hold",
                    "tier_unavailable ", "toString", "constructor", "__proto__",
                    "engine_provider_rate_limited"]) {
  const result = api.clawGeneralFailure(spoof);
  assert(result.message === "recovery:unknown", "unlisted code stays unverified: " + String(spoof));
  assert(result.hint === "claw-general-check-runs", "unlisted hint stays run-history");
}
assert(Object.isFrozen(hold) && Object.isFrozen(engine), "projection is immutable");

// 4. Retry box: Claw never gets a replay affordance, HOLD replaces only the hint.
const args = ["message", { remove() {} }, [], "auto", null,
              { conversationId: null, project: null }];
const holdBox = api.buildRetryBox(...args, true, undefined, hold);
assert(holdBox.children[1].textContent === "message", "bounded message rendered");
assert(holdBox.children[2].textContent === "claw-general-model-unavailable-note", "HOLD hint");
assert(!holdBox.children.some((x) => x.className === "retry-button"), "no one-click replay");
holdBox.children[3].handlers.click();
assert(historyOpens === 1 && replays === 0, "history action is GET-only, never a re-POST");

const plainClaw = api.buildRetryBox(...args, true);
assert(plainClaw.children[2].textContent === "claw-general-check-runs", "default hint preserved");

// 5. Ordinary Padiem Chat behavior is untouched: its message and retry stand.
const chat = api.buildRetryBox(...args, false);
const chatRetry = chat.children.find((x) => x.tagName === "BUTTON");
assert(chat.children[1].textContent === "message" && chatRetry, "B62 copy and retry preserved");
chatRetry.handlers.click();
assert(replays === 1, "explicit B62 retry remains once only");

// 6. A HOLD frame from the live relay is classified by code only: the transport
//    never forwards a raw server string as the Claw category.
assert(app.includes('clawGeneralFailure(data && data.error ? data.error.code : "")'),
  "live SSE error frame classified by closed code");
console.log("CLAW_HOLD_BOUNDED_COPY=PASS");
console.log("ENGINE_FAILURE_COPY_UNCHANGED=PASS");
console.log("CLOSED_MAP_FAIL_CLOSED_NO_PROTOTYPE_KEYS=PASS");
console.log("NO_AUTO_RETRY_OR_FALLBACK=PASS");
console.log("B62_CHAT_RETRY_UNCHANGED=PASS");
"""


def _claw_frame_handler_source() -> str:
    """The live `error` frame branch, up to the sibling guard that follows it."""
    start = APP.index('        if (frame.event === "error") {')
    selection = APP.index('clawGeneralFailure(data && data.error', start)
    end = APP.index("\n        if (clawGeneralRequest && verifiedClawRecovery", selection)
    return APP[start:end]


def test_hold_copy_is_selected_only_after_a_verified_terminal_outranks_it():
    """#3935 recovery truth must keep priority over the #3936 bounded copy."""
    frame = _claw_frame_handler_source()
    guard = frame.index("verifiedClawRecovery.completionAllowed()")
    selection = frame.index('clawGeneralFailure(data && data.error')
    assert guard < selection, "verified failure/cancel/approval state still wins"
    # The verified-terminal guard returns before the classification is reached.
    outrank = frame[guard:selection]
    assert "showVerifiedClawRecovery(verifiedClawRecovery.state());" in outrank
    assert "return true;" in outrank
    assert "const message = clawGeneralRequest" in frame
    # Standalone Chat still renders its own bounded server copy; Claw does not.
    assert "data.error.message" in frame[frame.index("const message"):]


def test_closed_map_holds_only_the_public_refusal_code():
    region = APP[APP.index("  const CLAW_BOUNDED_REFUSAL_COPY"):]
    region = region[: region.index("\n  function buildRetryBox(")]
    assert 'tier_unavailable: Object.freeze({' in region
    for internal in ("tier_hold", "max_tier_hold", "engine_execution_failed", "upstream_timeout"):
        assert internal not in region, internal
    assert "Object.hasOwn(CLAW_BOUNDED_REFUSAL_COPY, code)" in region


def test_ambiguous_run_classifier_is_unchanged_by_the_hold_copy():
    """A HOLD must not enter the 'may already have dispatched' classifier."""
    classifier = APP[APP.index("function isAmbiguousClawFailure"):]
    classifier = classifier[: classifier.index("\n  }")]
    assert 'return status === 502 || code === "engine_execution_failed";' in classifier
    assert "tier_unavailable" not in classifier


def test_hold_copy_locale_parity_and_single_wording_authority():
    for key in ("claw-general-model-unavailable", "claw-general-model-unavailable-note"):
        # Exactly one Korean and one English label per key.
        assert LOCALE.count(f'"{key}":') == 2, key
    # The refusal sentence stays the server's own bounded wording; a second
    # invented copy here is how the two lanes would diverge again.
    assert f'"claw-general-model-unavailable": "{_MODEL_HOLD_USER_MESSAGE}"' in LOCALE
    for forbidden in ("tier_hold", "max_tier_hold", "kagent", "P01AdapterError"):
        assert forbidden not in LOCALE
        assert forbidden not in APP
        assert forbidden not in TRANSPORT


def test_bounded_copy_is_applied_at_every_claw_failure_surface():
    # Live SSE error frame, streamed-partial catch, and the caller catch are the
    # three places that previously collapsed every Claw failure to unknown.
    assert APP.count("clawGeneralFailure(") == 4  # 1 definition body reference + 3 call sites
    assert "renderStreamError(article, message, outboundMessages, skill, contextSnapshot, clawGeneralRequest, lifecycleForError(chatTransport.errorFor(data, message)), clawFailure)" in APP
    assert "renderStreamError(article, clawFailure.message," in APP
    assert "clawGeneralRequest && error?.clawFailureDetail === \"engine_provider_rate_limited\"" in APP
    # Standalone Chat's own path and message remain byte-for-byte what they were.
    assert "renderStreamError(article, error instanceof Error ? error.message : uiT(\"stream-continue-failed\")," in APP
    assert "(error instanceof Error ? error.message : uiT(\"try-again\"))" in APP


def test_claw_hold_copy_network_free_browser_behavior():
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the behavioral browser contract")
    result = subprocess.run(
        ["node", "-e", NODE, str(STATIC)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "CLAW_HOLD_BOUNDED_COPY=PASS",
        "ENGINE_FAILURE_COPY_UNCHANGED=PASS",
        "CLOSED_MAP_FAIL_CLOSED_NO_PROTOTYPE_KEYS=PASS",
        "NO_AUTO_RETRY_OR_FALLBACK=PASS",
        "B62_CHAT_RETRY_UNCHANGED=PASS",
    ):
        assert marker in result.stdout

# The real composer streaming renderer, evaluated in one shared VM context
# together with the real closed map, so a HOLD frame is proven to become bounded
# copy and an Engine failure is proven to keep claiming an unverified run.
NODE_RENDERER = r"""
const vm=require("vm"),fs=require("fs"),path=require("path");
const dir=process.argv[1];
const read=n=>fs.readFileSync(path.join(dir,n),"utf8");
const app=read("app.js");
function assert(v,m){if(!v)throw Error(m)}
function element(type){
  return {tagName:type.toUpperCase(),textContent:"",children:[],dataset:{},className:"",handlers:{},
    append(...xs){this.children.push(...xs)},appendChild(x){this.children.push(x)},
    replaceChildren(...xs){this.children=xs},setAttribute(k,v){this[k]=v},
    querySelector(){return null},remove(){},focus(){},scrollIntoView(){},
    addEventListener(kind,fn){this.handlers[kind]=fn}};
}
const win={};
const ctx={window:win,Object,JSON,Error,Promise,Date,console,
  document:{documentElement:{lang:"en"},createElement:element,getElementById:()=>null}};
vm.createContext(ctx);
vm.runInContext(read("claw-run-event-projection.js"),ctx);
vm.runInContext(read("claw-recovery-truth.js"),ctx);
vm.runInContext(read("chat-transport.js"),ctx);
assert(win.PadiemChatTransport&&win.PadiemClawRecoveryTruth,"browser modules loaded");

// Real closed map + selector, and the real lifecycle mapper, in the same context.
const mapStart=app.indexOf("  const CLAW_BOUNDED_REFUSAL_COPY");
const mapEnd=app.indexOf("\n  function buildRetryBox(",mapStart);
assert(mapStart>=0&&mapEnd>mapStart,"closed map located");
vm.runInContext(app.slice(mapStart,mapEnd),ctx);
const lifeStart=app.indexOf("  function lifecycleForError(");
const lifeEnd=app.indexOf("\n  function setNavActive(",lifeStart);
assert(lifeStart>=0&&lifeEnd>lifeStart,"lifecycle mapper located");
vm.runInContext(app.slice(lifeStart,lifeEnd),ctx);

const fnStart=app.indexOf("  async function requestStreamingAnswer(");
const fnEnd=app.indexOf("\n  function cancelActiveStream(",fnStart);
assert(fnStart>=0&&fnEnd>fnStart,"renderer located");

// Keep the transport's real errorFor (it owns the closed code); replace only I/O.
let sent=[];
ctx.chatTransport=Object.assign({},win.PadiemChatTransport,{
  requestClawGeneral:async()=>({}),
  requestStreaming:async()=>({}),
  readSseEvents:async(_r,fn)=>{for(const f of sent){if(await fn(f))break}},
});
ctx.uiT=k=>k;
ctx.MESSAGE_LIFECYCLE={FAILED:"failed",COMPLETED:"completed",TIMED_OUT:"timed_out",
  CANCELLED:"cancelled",WAITING_APPROVAL:"waiting_for_approval"};
ctx.PadiemChatLifecycle={set:(a,s)=>{a.dataset.lifecycle=s}};
ctx.revealErrorState=()=>{};
ctx.applyStreamDone=()=>{};
const calls=[];
ctx.renderStreamError=(a,message,_rm,_rs,_rc,claw,lifecycle,clawFailure)=>{
  // Mirror only what the real renderer does to the DOM so the arguments the real
  // call sites pass (copy, lifecycle, bounded descriptor) stay observable.
  a.content.appendChild({textContent:message});
  a.dataset.lifecycle=lifecycle||ctx.MESSAGE_LIFECYCLE.FAILED;
  calls.push({message,claw,lifecycle:a.dataset.lifecycle,
    failureMessage:clawFailure?clawFailure.message:null,
    failureHint:clawFailure?clawFailure.hint:null});
};
const renderer=vm.runInContext("("+app.slice(fnStart,fnEnd)+")",ctx);
assert(typeof renderer==="function","real renderer in scope");
assert(vm.runInContext("typeof clawGeneralFailure",ctx)==="function","real selector in scope");

function article(){
  const a={content:element("div"),marker:element("small"),body:element("div"),dataset:{},
    querySelector(q){return q===".assistant-content"?a.content
      :q==="[data-runtime-label]"?a.marker:q===".assistant-body"?a.body:null},
    scrollIntoView(){},remove(){},dispatchEvent(){}};
  return a;
}
const event=(kind,seq)=>({event:"p01_event",data:JSON.stringify({
  event_id:"evt_"+seq,run_id:"orch_1",trace_id:"trace_1",app_id:"b54-padiem-claw",
  kind,sequence:seq,timestamp_iso:"2026-10-13T00:10:00Z",delivery:"live",
  message:"SECRET_UNTRUSTED",metadata:{api_key:"SHOULD_NEVER_APPEAR"}})});
const delta=v=>({event:"delta",data:JSON.stringify({delta:v})});
const errFrame=value=>({event:"error",data:JSON.stringify({error:value})});
const HOLD=errFrame({code:"tier_unavailable",
  message:"선택한 AI 모델을 현재 사용할 수 없습니다. 다른 모델을 선택해 주세요.",
  raw:"SECRET_ENGINE_BODY"});
const ENGINE=errFrame({code:"engine_execution_failed",message:"SECRET_ENGINE_BODY"});

async function scenario(name,frames){
  sent=frames;
  calls.length=0;
  const a=article();
  let failure=null;
  const value=await renderer(a,{},[],"auto",{},null,{clawGeneral:true})
    .catch(e=>{failure=e;return "rejected"});
  const text=a.content.children.map(x=>x.textContent).join(" ")
    +" "+(failure?String(failure.message):"");
  assert(!text.includes("SECRET_UNTRUSTED"),name+" untrusted event message rendered");
  assert(!text.includes("SHOULD_NEVER_APPEAR"),name+" untrusted event metadata rendered");
  assert(!text.includes("SECRET_ENGINE_BODY"),name+" raw server body rendered");
  return {a,text,failure,value,calls:calls.slice()};
}

(async()=>{
  const started=event("run_started",1);

  // 1. HOLD with a partial answer: bounded model copy, and no claim that a run
  //    may already have started.
  const hold=await scenario("hold",[started,delta("partial-hold"),HOLD]);
  assert(hold.value===false,"hold settles as a bounded failure");
  assert(hold.text.includes("claw-general-model-unavailable"),"hold bounded copy "+hold.text);
  assert(!hold.text.includes("may already have executed"),"hold must not claim a dispatch");
  assert(hold.a.dataset.lifecycle==="failed","hold lifecycle failed");
  // The call site must hand the same bounded descriptor to the retry-box builder,
  // which is what replaces the run-history guidance (executed in probe 1).
  assert(hold.calls.length===1,"exactly one failure render");
  assert(hold.calls[0].failureMessage==="claw-general-model-unavailable","descriptor reaches the box");
  assert(hold.calls[0].failureHint==="claw-general-model-unavailable-note","hint descriptor");
  assert(hold.calls[0].claw===true,"Claw-only classification");

  // 2. With no partial output the renderer rejects, so the caller catch owns the
  //    presentation: the closed code must survive intact for that lookup.
  const bare=await scenario("bare hold",[started,HOLD]);
  assert(bare.failure&&bare.failure.code==="tier_unavailable","hold rejection keeps closed code");
  assert(bare.calls.length===0,"no in-stream render without a partial answer");

  // 3. A real Engine failure keeps the existing unverified-run wording.
  const engine=await scenario("engine",[started,delta("partial-502"),ENGINE]);
  assert(engine.text.includes("may already have executed"),"engine wording unchanged "+engine.text);
  assert(!engine.text.includes("claw-general-model-unavailable"),"engine failure is not a hold");
  assert(engine.calls[0].failureMessage.includes("may already have executed"),
    "engine descriptor keeps the unverified-run state");

  // 4. #3935 verified terminals still outrank the classification.
  const failed=await scenario("verified failed",[started,event("run_failed",2),HOLD]);
  assert(failed.text.includes("Execution failed"),"verified failure still wins "+failed.text);
  assert(!failed.text.includes("claw-general-model-unavailable"),"no hold copy over a verified failure");
  const paused=await scenario("verified approval",[started,event("approval_paused",2),HOLD]);
  assert(paused.text.includes("awaiting approval"),"approval pause state preserved "+paused.text);
  assert(paused.a.dataset.lifecycle==="waiting_for_approval","approval lifecycle");

  console.log("CLAW_3936_HOLD_RENDERS_BOUNDED_MODEL_COPY=PASS");
  console.log("CLAW_3936_ENGINE_FAILURE_UNVERIFIED_RUN_UNCHANGED=PASS");
  console.log("CLAW_3936_VERIFIED_TERMINAL_STILL_OUTRANKS=PASS");
  console.log("CLAW_3936_NO_RAW_SERVER_BODY_OR_EVENT_TEXT=PASS");
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


def test_actual_renderer_projects_hold_as_model_copy_with_node_vm():
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the behavioral browser contract")
    result = subprocess.run(
        ["node", "-e", NODE_RENDERER, str(STATIC)],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "CLAW_3936_HOLD_RENDERS_BOUNDED_MODEL_COPY=PASS",
        "CLAW_3936_ENGINE_FAILURE_UNVERIFIED_RUN_UNCHANGED=PASS",
        "CLAW_3936_VERIFIED_TERMINAL_STILL_OUTRANKS=PASS",
        "CLAW_3936_NO_RAW_SERVER_BODY_OR_EVENT_TEXT=PASS",
    ):
        assert marker in result.stdout
