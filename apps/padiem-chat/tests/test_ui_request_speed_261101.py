"""Real JS controlled-delay regressions; these are not production timings."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess


TESTS = Path(__file__).parent
STATIC = TESTS.parent / "static"


def literal(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == name
                              for target in node.targets))
    return ast.literal_eval(assignment.value)


def function(name):
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    start = source.index("async function " + name + "(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(name)


def run_node(source, **environment):
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True,
                            encoding="utf-8", timeout=15, env={**os.environ, **environment})
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


PRELUDE = """
const assert=require('node:assert/strict');
const flush=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return {promise,resolve};};
"""

READ_CLOCK = """
const readTimers=new Map();let nextReadTimer=0;
global.setTimeout=(callback,ms)=>{assert.equal(ms,3000);const id=++nextReadTimer;readTimers.set(id,callback);return id};
global.clearTimeout=id=>readTimers.delete(id);
global.AbortController=class {
 constructor(){const listeners=[];this.signal={aborted:false,addEventListener(name,callback){if(name==='abort')listeners.push(callback)}};this.listeners=listeners}
 abort(){if(this.signal.aborted)return;this.signal.aborted=true;for(const callback of this.listeners)callback()}
};
const blockedRead=signal=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted'))));
const expireReads=()=>{for(const callback of [...readTimers.values()])callback()};
"""


def test_projects_and_history_start_in_parallel_without_holding_claw_panels():
    result = run_node(PRELUDE + function("loadAuthStatus") + """
let authState={};
const events=[], projects=deferred(), history=deferred();
const fetchAuthStatusOnce=async()=>({authenticated:true});
const applyAuthState=data=>{authState=data};
const scheduleSharedRefresh=()=>{};
const loadProjects=()=>{events.push('projects');return projects.promise};
const loadRecentConversations=()=>{events.push('history');return history.promise};
const syncApprovedMemoryVisibility=()=>events.push('memory');
const syncClawRunHistoryVisibility=()=>events.push('runs');
(async()=>{
const pending=loadAuthStatus();await flush();
assert.deepEqual(events,['projects','history','memory','runs']);
history.resolve();projects.resolve();await pending;
console.log(JSON.stringify({parallel:true,panelsStarted:2}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"parallel": True, "panelsStarted": 2}


def test_history_is_usable_before_optional_run_labels_and_discards_old_auth_reply():
    result = run_node(PRELUDE + function("loadRecentConversations") + """
let authViewEpoch=1,historyReadSequence=0,clawConversationLabelsRead=null;
let authState={authenticated:true,history_ready:true};
const clawConversationIds=new Set(), labels=deferred();
const id='chat_'+'a'.repeat(32);
const fetchRecentConversations=async()=>({conversations:[{id,title:'Existing conversation'}]});
const fetch=()=>labels.promise;
const el=()=>({children:[],append(...v){this.children.push(...v)},appendChild(v){this.children.push(v)},
 replaceChildren(...v){this.children=v},addEventListener(){},setAttribute(){},querySelectorAll(){return[]}});
const historyList=el(),historySection={},historyEmpty={};
const document={createElement:el,createTextNode:x=>x};
const window={};const uiT=x=>x;const sidebarActionIcon=el;
const renderHistorySkeleton=()=>historyList.replaceChildren();
const clearHistoryUI=()=>historyList.replaceChildren();
const renderHistoryLoadFailed=()=>{throw Error('unexpected failure')};
(async()=>{
let finished=false;const pending=loadRecentConversations().then(()=>{finished=true});
await flush();assert.equal(finished,true);assert.equal(historyList.children.length,1);
const button=historyList.children[0].children[0];assert.equal(button.textContent,'Existing conversation');
authViewEpoch++;authState.authenticated=false;clearHistoryUI();
labels.resolve({ok:true,json:async()=>({ok:true,runs:[{channel:'web',action:'general',status:'completed',session:{conversation_id:id}}]})});
await flush();await pending;
assert.equal(clawConversationIds.size,0);assert.equal(historyList.children.length,0);
assert.equal(button.textContent,'Existing conversation');
console.log(JSON.stringify({renderedBeforeLabels:true,oldAuthReplyDiscarded:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result["renderedBeforeLabels"] and result["oldAuthReplyDiscarded"]


def chip_harness():
    harness = literal(TESTS / "test_4139_claw_connection_card_reason.py", "_HARNESS")
    harness = harness[:harness.index("global.fetch =")]
    harness = harness.replace('global.window = {addEventListener() {}, location: {assign() {}}};', """
const listeners={};
global.window={addEventListener(name,handler){(listeners[name]??=[]).push(handler)},location:{assign(){}}};
const emit=(name,detail)=>{for(const handler of listeners[name]||[])handler({detail})};
""")
    return PRELUDE + harness


def test_opening_an_early_history_row_preserves_the_verified_claw_lane():
    result = run_node(PRELUDE + function("openSavedConversation") + """
let authViewEpoch=1,authState={authenticated:true},inFlight=false;
const labels=deferred(),id='chat_'+'b'.repeat(32),clawConversationIds=new Set();
let clawConversationLabelsRead={epoch:1,promise:labels.promise};
const fetch=async()=>({ok:true,json:async()=>({conversation:{id,messages:[]}})});
let conversationProduct='',activeProject=null,activeProjectFileCount=0,clawArtifactShownFor='';
const PRODUCT_CLAW='claw',PRODUCT_CHAT='chat';
const conversationState={resetProduct(){},setProduct(){},setConversationId(){},appendMessage(){}};
const messageList={replaceChildren(){}};const conversationArtifactContext=null;
const clearAttachment=()=>{},renderProjectState=()=>{},refreshActiveProjectFileCount=()=>{};
const openClawWorkspace=()=>{},showConversation=()=>{},resumeUnfinishedPcRun=()=>{};
const window={},input={focus(){}},closeSidebar=()=>{};
const uiT=x=>x,setNote=message=>{throw Error(message)};
(async()=>{
const pending=openSavedConversation(id);await flush();assert.equal(conversationProduct,'');
clawConversationIds.add(id);labels.resolve();assert.equal(await pending,true);
assert.equal(conversationProduct,'claw');assert.equal(clawArtifactShownFor,id);
console.log(JSON.stringify({verifiedClawLanePreserved:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"verifiedClawLanePreserved": True}


def test_fast_chips_paint_during_slow_github_and_refreshes_share_the_read():
    result = run_node(chip_harness() + """
const github=deferred(), calls=[];let staleRead=null;
global.fetch=async url=>{
 calls.push(url);
 if(staleRead)await staleRead.promise;
 if(url.endsWith('/github/status'))await github.promise;
 const data=url.endsWith('/devices')?payload:url.endsWith('/github/status')?{ok:true,state:'on'}:
 {workspace_state_authority:true,connectors:[{connector_id:'connector:google:drive@1',workspace_state:'connected'}]};
 return {ok:true,status:200,text:async()=>JSON.stringify(data)};
};
eval(require('node:fs').readFileSync(process.env.CLAW_CHIPS_MODULE,'utf8'));
(async()=>{
await flush();assert.equal(pcCard.dataset.pcPhase,'online');assert.equal(chipDrive.dataset.connectionState,'on');
emit('focus');emit('focus');await flush();assert.equal(calls.length,3);
github.resolve();await flush();staleRead=deferred();emit('focus');await flush();
assert.equal(chipPc.dataset.connectionStale,'true');assert.equal(chipPc.dataset.connectionState,'unknown');
emit('padiem:auth-state',{authenticated:false});
staleRead.resolve();await flush();assert.equal(chipPc.dataset.connectionState,'unknown');
assert.equal(pcCard.dataset.pcPhase,'unknown');assert.equal(chipPc.dataset.connectionStale,undefined);
console.log(JSON.stringify({fastCards:2,initialRequests:3,lateReplyDiscarded:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""", CLAW_CHIPS_MODULE=str(STATIC / "claw-connection-chips.js"), CLAW_CHIPS_PAYLOAD=json.dumps({
        "ok": True, "available": True, "ownerScoped": True,
        "devices": [{"deviceId": "synthetic", "state": "CONNECTED", "usable": True}],
    }))
    assert result == {"fastCards": 2, "initialRequests": 3, "lateReplyDiscarded": True}


def test_chip_display_deadline_covers_headers_and_body_without_retrying_work():
    result = run_node(chip_harness() + READ_CLOCK + """
let mode='ready';const calls=[];
global.fetch=async(url,options)=>{
 calls.push({url,method:options.method});assert.equal(options.method,'GET');
 if(mode==='headers')return blockedRead(options.signal);
 if(mode==='denied')return {ok:false,status:403,text:()=>{throw Error('must not read denial body')}};
 const data=url.endsWith('/devices')?payload:url.endsWith('/github/status')?{ok:true,state:'on',linked:true}:
 {workspace_state_authority:true,connectors:[{connector_id:'connector:google:drive@1',workspace_state:'connected'}]};
 return {ok:true,status:200,text:()=>mode==='body'?blockedRead(options.signal):Promise.resolve(JSON.stringify(data))};
};
eval(require('node:fs').readFileSync(process.env.CLAW_CHIPS_MODULE,'utf8'));
(async()=>{
await flush();assert.equal(readTimers.size,0);assert.equal(chipPc.dataset.connectionState,'on');
for(const blocked of ['headers','body']){
 mode=blocked;emit('focus');await flush();assert.equal(readTimers.size,3);
 const before=calls.length;expireReads();await flush();assert.equal(calls.length,before);assert.equal(readTimers.size,0);
 assert.equal(chipPc.dataset.connectionStale,'true');assert.equal(chipPc.dataset.connectionState,'unknown');
 assert.equal(chipPc.textContent,'ON');assert.equal(chipGithub.dataset.connectionLinked,undefined);
}
mode='denied';emit('focus');await flush();assert.equal(chipPc.dataset.connectionState,'unknown');
assert.equal(chipPc.dataset.connectionStale,undefined);assert.equal(readTimers.size,0);
console.log(JSON.stringify({deadlineMs:3000,keptPreviousDisplay:true,noAutomaticRetry:true,denialClears:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""", CLAW_CHIPS_MODULE=str(STATIC / "claw-connection-chips.js"), CLAW_CHIPS_PAYLOAD=json.dumps({
        "ok": True, "available": True, "ownerScoped": True,
        "devices": [{"deviceId": "synthetic", "state": "CONNECTED", "usable": True}],
    }))
    assert result == {"deadlineMs": 3000, "keptPreviousDisplay": True,
                      "noAutomaticRetry": True, "denialClears": True}


def inbox_harness():
    path = TESTS / "test_5034_notification_inbox.py"
    harness = literal(path, "_HARNESS").split("async function main() {", 1)[0]
    harness = harness.replace("process.argv[2]", json.dumps(str(STATIC / "notification-inbox.js")))
    harness = harness.replace("const recorder = makeFetch(spec.scripted);", "const recorder={fetch:fixtureFetch,calls:fetchCalls};")
    locales = literal(path, "LOCALES")
    for language in ("ko", "en"):
        locales[language]["notification-inbox-refreshing"] = "refreshing-previous"
        locales[language]["notification-inbox-stale"] = "stale-previous"
    return "const LOCALES=" + json.dumps(locales, ensure_ascii=False) + ";\n" + harness


def test_inbox_fast_list_paints_and_late_account_reply_is_ignored():
    result = run_node(inbox_harness() + """
const assert=require('node:assert/strict');
const fetchCalls=[];let releaseTasks;
const tasksWait=new Promise(r=>{releaseTasks=r});
const fixtureFetch=async url=>{
fetchCalls.push(url);if(url===TASKS_URL)await tasksWait;
return {ok:true,status:200,json:async()=>({ok:true,items:[url===ALERTS_URL?
{alert_id:'synthetic',title:'Fast alert',status:'active'}:{task_id:'old-task',title:'Old account task',status:'open'}]})};
};
(async()=>{
const ctx=run({signedIn:true});await flush();
assert.equal(read(ctx).groups[0].count,1);assert.equal(read(ctx).groups[1].count,0);
ctx.window.dispatchEvent(new CustomEvent('padiem:auth-state',{detail:{authenticated:false}}));
releaseTasks();await flush();assert.ok(read(ctx).groups.every(group=>group.count===0));
console.log(JSON.stringify({fastList:true,lateReplyDiscarded:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"fastList": True, "lateReplyDiscarded": True}


def test_inbox_stale_display_survives_read_failure_but_not_account_change():
    result = run_node(inbox_harness() + """
const assert=require('node:assert/strict');
const fetchCalls=[];let status=200;
const fixtureFetch=async url=>{fetchCalls.push(url);return {ok:status===200,status,
json:async()=>({ok:true,items:url===ALERTS_URL?[{alert_id:'synthetic',title:'Previous alert',status:'active'}]:[]})}};
(async()=>{
const ctx=run({signedIn:true});await flush();assert.equal(read(ctx).groups[0].count,1);
status=503;ctx.bell.click();await flush();
assert.equal(read(ctx).groups[0].count,1);assert.equal(read(ctx).statusTexts[0],'stale-previous');
ctx.window.dispatchEvent(new CustomEvent('padiem:account-changed',{detail:{authenticated:true}}));await flush();
assert.equal(read(ctx).groups[0].count,0);
console.log(JSON.stringify({staleVisible:true,accountChangeClears:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"staleVisible": True, "accountChangeClears": True}


def test_inbox_display_timeout_keeps_previous_rows_and_denial_clears_immediately():
    result = run_node(inbox_harness() + "const assert=require('node:assert/strict');\n" + READ_CLOCK + """
const fetchCalls=[];let mode='ready';
const fixtureFetch=async(url,options)=>{
fetchCalls.push(url);assert.equal(options.method,undefined);
if(mode==='headers')return blockedRead(options.signal);
if(mode==='denied')return {ok:false,status:401,json:()=>{throw Error('must not read denial body')}};
return {ok:true,status:200,json:()=>mode==='body'?blockedRead(options.signal):Promise.resolve({ok:true,
items:url===ALERTS_URL?[{alert_id:'synthetic',title:'Previous alert',status:'active'}]:[]})};
};
(async()=>{
const ctx=run({signedIn:true});await flush();assert.equal(read(ctx).groups[0].count,1);assert.equal(readTimers.size,0);
for(const blocked of ['headers','body']){
 mode=blocked;ctx.bell.click();await flush();assert.equal(readTimers.size,2);
 const before=fetchCalls.length;expireReads();await flush();assert.equal(fetchCalls.length,before);assert.equal(readTimers.size,0);
 assert.equal(read(ctx).groups[0].count,1);assert.equal(read(ctx).statusTexts[0],'stale-previous');
 ctx.bell.click();
}
mode='denied';ctx.bell.click();await flush();assert.equal(read(ctx).groups[0].count,0);assert.equal(readTimers.size,0);
console.log(JSON.stringify({deadlineMs:3000,keptPreviousRows:true,noAutomaticRetry:true,denialClears:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"deadlineMs": 3000, "keptPreviousRows": True,
                      "noAutomaticRetry": True, "denialClears": True}
