"""#7073: the Chat first screen reads each owner-scoped list once.

The COM2 journal showed the first screen paying for the same reads several
times (pairings x3, devices x2, voice identity x2, runs x2, grade readiness
x2, admin role x2). These regressions pin the behaviours that removed the
repeats: an owner-scoped list is read once and shared, and a list that nothing
on the screen displays is not read until its surface opens.

They are controlled harnesses, not production timings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


TESTS = Path(__file__).parent
STATIC = TESTS.parent / "static"


def run_node(source, **environment):
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True,
                            encoding="utf-8", timeout=20, env={**os.environ, **environment})
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


PRELUDE = """
const assert=require('node:assert/strict');
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return {promise,resolve};};
"""


ADMIN_ENTRY = PRELUDE + """
const listeners={};const calls=[];let mode='authorized';
const link={hidden:false,dataset:{}};
const section={hidden:false};
global.document={getElementById:id=>id==='adminHubLink'?link:id==='adminSettingsSection'?section:null};
global.window={addEventListener(name,handler){(listeners[name]??=[]).push(handler)}};
const emit=(name,detail)=>{for(const handler of listeners[name]||[])handler({detail})};
global.fetch=async()=>{calls.push('/api/admin/session');
 if(mode==='guest')return {ok:false,status:401};
 return {ok:true,status:200,json:async()=>({authenticated:true,role:'owner'})};};
eval(require('node:fs').readFileSync(process.env.ADMIN_ENTRY_MODULE,'utf8'));
"""


def test_the_admin_role_is_checked_once_per_signed_in_session():
    result = run_node(ADMIN_ENTRY + """
(async()=>{
await flush();assert.equal(calls.length,1,'the boot check answers the first screen');
emit('padiem:auth-state',{authenticated:true});await flush();
assert.equal(calls.length,1,'the auth notification reuses the answered check');
assert.equal(link.hidden,false);
emit('padiem:auth-state',{authenticated:false});await flush();
assert.equal(link.hidden,true,'sign-out hides the entry at once');
emit('padiem:auth-state',{authenticated:true});await flush();
assert.equal(calls.length,2,'a new session is checked again');
console.log(JSON.stringify({bootRequests:1,perSession:1}));
})().catch(e=>{console.error(e);process.exitCode=1});
""", ADMIN_ENTRY_MODULE=str(STATIC / "admin-entry.js"))
    assert result == {"bootRequests": 1, "perSession": 1}


GRADE_LINE = PRELUDE + """
const listeners={};const calls=[];let tier='free';
const hint={textContent:'',closest:()=>({setAttribute(){},removeAttribute(){}})};
global.document={getElementById:id=>id==='clawVerifiedModelHint'?hint:null,readyState:'complete'};
global.window={addEventListener(name,handler){(listeners[name]??=[]).push(handler)},
 PadiemAuthGate:{authenticated:()=>true},
 PadiemTierSelection:{get:()=>tier},
 __padiemLocale:{text:key=>key}};
const emit=(name,detail)=>{for(const handler of listeners[name]||[])handler({detail})};
global.fetch=async()=>{calls.push('grade');
 return {ok:true,status:200,json:async()=>({ok:true,scope:'b14_tier_ready',
  complete_inventory:true,automatic_default:true,tier:typeof tier==='string'?tier:'free',available:true})};};
eval(require('node:fs').readFileSync(process.env.GRADE_MODULE,'utf8'));
"""


def test_the_grade_readiness_line_reads_once_within_its_window():
    result = run_node(GRADE_LINE + """
(async()=>{
await flush();assert.equal(calls.length,1);
emit('padiem:auth-state',{authenticated:true});
emit('padiem:localechange');
emit('padiem:tierchange');
await flush();
assert.equal(calls.length,1,'the same grade inside the window is answered from memory');
tier='plus';
emit('padiem:tierchange');await flush();
assert.equal(calls.length,2,'a different grade is a different question');
console.log(JSON.stringify({bootRequests:1,sameGradeShared:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""", GRADE_MODULE=str(STATIC / "claw-verified-model-choice.js"))
    assert result == {"bootRequests": 1, "sameGradeShared": True}


def claw_runs_source():
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    start = source.index("const CLAW_RUNS_READ_WINDOW_MS")
    # loadRecentConversations moved into chat-history-module.js (#7216 R5 step 3);
    # its one-line forwarder is the stable end boundary of the runs-read block.
    end = source.index("function loadRecentConversations(", start)
    return source[start:end]


def test_sidebar_labels_and_run_history_share_one_runs_read():
    result = run_node(PRELUDE + claw_runs_source() + """
const calls=[];
global.fetch=async url=>{calls.push(url);
 return {ok:true,status:200,json:async()=>({ok:true,runs:[{run_id:'sched_run_'+'a'.repeat(64)}]})};};
(async()=>{
const wide=await readClawRuns(30,7);
assert.equal(calls.length,1);
const narrow=await readClawRuns(10,7);
assert.equal(calls.length,1,'the wider answer contains the narrower one');
assert.equal(narrow.data.runs.length,wide.data.runs.length);
const widerAgain=await readClawRuns(30,7);
assert.equal(calls.length,1);
console.log(JSON.stringify({reads:1,reused:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"reads": 1, "reused": True}


def test_a_new_run_needs_a_wider_read_and_a_new_account_starts_over():
    result = run_node(PRELUDE + claw_runs_source() + """
const calls=[];
global.fetch=async url=>{calls.push(url);
 return {ok:true,status:200,json:async()=>({ok:true,runs:[]})};};
(async()=>{
await readClawRuns(10,7);assert.equal(calls.length,1);
await readClawRuns(30,7);assert.equal(calls.length,2,'30 pulls more rows than 10');
await readClawRuns(10,99);assert.equal(calls.length,3,'another account generation is another read');
await readClawRuns(10,99);assert.equal(calls.length,3,'and it keeps its own answer');
console.log(JSON.stringify({widerReads:true,perGeneration:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"widerReads": True, "perGeneration": True}


def test_the_pairing_card_is_not_read_until_the_connectors_surface_opens():
    source = (STATIC / "pc-pairing-card.js").read_text(encoding="utf-8")
    assert "const surfaceOpen = () => {" in source
    assert 'addEventListener("toggle", () => {' in source
    assert "if (surfaceOpen()) void load();" in source
    # The old unconditional boot/auth reads are gone.
    assert "window.addEventListener(\"padiem:auth-state\", () => { void load(true); });" not in source
    assert source.count("void load(true);") >= 1


def test_the_connection_chips_reuse_the_device_directory_read():
    chips = (STATIC / "claw-connection-chips.js").read_text(encoding="utf-8")
    manager = (STATIC / "claw-device-manager.js").read_text(encoding="utf-8")
    assert "window.PadiemClawDeviceDirectoryRead" in manager
    assert "window.PadiemClawDeviceDirectoryRead" in chips
    assert "DEVICES_SHARED_WINDOW_MS" in chips
    # The directory owner publishes what the chips need to keep the same truth.
    for field in ("usagePaused", "ownerScoped", "updatedAt", "usable"):
        assert field in manager


def test_the_quote_runtime_shares_the_connect_flow_read():
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "PadiemPcConnectFlow" in source
    assert "flow.read" in source
    flow = (STATIC / "pc-connect-flow.js").read_text(encoding="utf-8")
    assert "read: () => readPairings()" in flow
    assert "refresh: () => readPairings({ force: true })" in flow


def test_the_voice_identity_proof_is_single_flight():
    source = (STATIC / "voice-stt-wiring.js").read_text(encoding="utf-8")
    assert "if (identityInflight) return identityInflight;" in source
    assert "let identityInflight = null;" in source
    # Sign-out/sign-in happens in this page, so a changed signed-in state must
    # abandon the open read instead of announcing it for the new owner.
    assert "if (next !== lastSignedIn) {" in source
    assert "identityRefreshSeq += 1;" in source


def test_a_changed_owner_never_reuses_the_previous_pairing_read():
    source = (STATIC / "pc-connect-flow.js").read_text(encoding="utf-8")
    assert "if (signedIn !== lastSignedIn) {" in source
    assert "pairingsGeneration += 1;" in source
    assert "if (generation !== pairingsGeneration) return result;" in source
