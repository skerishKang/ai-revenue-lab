"""R1 step 2: outputs follow real auth-session events, not button mutations."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

STATIC = Path(__file__).resolve().parents[1] / "static"


@lru_cache(maxsize=1)
def _journey():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = {};
class Node {
  constructor(id = '') { this.id=id; this.children=[]; this.dataset={}; this.listeners={}; this.textContent=''; this.disabled=false; this.hidden=false; this.open=false; this.value=''; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { (this.listeners.click || []).forEach(fn => fn({target:this})); }
  setAttribute(name, value) { this[name]=value; }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children=nodes; }
  querySelectorAll() { return []; }
  closest() { return {dataset:{accountState:'signed_in'}}; }
  showModal() { this.open=true; }
  close() { this.open=false; }
  focus() {}
}
const document = {getElementById: id => nodes[id] ||= new Node(id),
  createElement: () => new Node(), querySelectorAll:()=>[], body:new Node()};
const listeners = {}, observers = [], pending = [], confirms = [];
const sandbox = {document, console, setTimeout, clearTimeout,
  MutationObserver: class {constructor(fn){this.fn=fn;} observe(node){observers.push({node,fn:this.fn});}},
  CustomEvent: class {constructor(type, init){this.type=type;this.detail=init.detail;}},
  addEventListener:(type, fn)=>(listeners[type] ||= []).push(fn),
  dispatchEvent:e=>(listeners[e.type] || []).forEach(fn=>fn(e)),
  fetch:url=>new Promise(resolve=>pending.push({url,resolve})),
  PadiemConfirmDialog:{confirm:()=>new Promise(resolve=>confirms.push(resolve))}};
sandbox.window=sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2]+'/auth-session.js','utf8'),sandbox);
const status=owner=>({ready:true,authenticated:!!owner,project_files_ready:true,user:owner?{email:owner,name:'Same name'}:null});
let gen=0;
const login=owner=>sandbox.PadiemAuthSession.update(status(owner),++gen);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const list=(title,cursor=null)=>({ok:true,status:200,json:async()=>({outputs:[{id:title,title}],next_cursor:cursor})});
const detail=title=>({ok:true,status:200,json:async()=>({output:{id:title,title,content:title}})});
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
login('owner-a@example.test');
vm.runInContext(fs.readFileSync(process.argv[2]+'/outputs.js','utf8'),sandbox);
(async()=>{
 const checks={};
 pending[0].resolve(list('OWNER_A')); await flush();
 checks.initial=pending.length===1 && text(nodes.outputsList).includes('OWNER_A');
 const row=nodes.outputsList.children[0];
 login('owner-a@example.test');
 sandbox.PadiemAuthSession.update({...status('owner-a@example.test'),project_files_ready:false,user:{email:'owner-a@example.test',name:'Renamed'}},++gen);
 sandbox.dispatchEvent({type:'padiem:localechange'});
 nodes.loginButton.textContent='Log out';
 observers.filter(o=>o.node===nodes.loginButton).forEach(o=>o.fn());
 await flush();
 checks.same_owner=pending.length===1 && nodes.outputsList.children[0]===row;
 checks.no_auth_observer=observers.length===1 && observers[0].node===nodes.messageList;
 row.click();
 login('owner-b@example.test');
 checks.switch_clear=nodes.outputsList.children.length===0 && pending.length===3;
 pending[1].resolve(detail('STALE_A_DETAIL')); await flush();
 checks.stale_detail=!nodes.savedOutputDialog.open;
 pending[2].resolve(list('OWNER_B')); await flush();
 checks.switch_fresh=text(nodes.outputsList).includes('OWNER_B') && !text(nodes.outputsList).includes('OWNER_A');
 login('owner-c@example.test');
 login('owner-d@example.test');
 pending[4].resolve(list('OWNER_D','cursor-next')); await flush();
 pending[3].resolve(list('STALE_C')); await flush();
 checks.stale_list=text(nodes.outputsList).includes('OWNER_D') && !text(nodes.outputsList).includes('STALE_C');
 nodes.outputsList.children.find(n=>n.id==='outputsMore').click();
 login('owner-e@example.test');
 pending[5].resolve(list('STALE_D_PAGE')); await flush();
 checks.stale_page=nodes.outputsList.children.length===0;
 login(null);
 pending[6].resolve(list('STALE_E')); await flush();
 sandbox.dispatchEvent({type:'padiem:localechange'});
 checks.logout=nodes.outputsList.children.length===0 && !nodes.savedOutputDialog.open && nodes.outputsNavButton.disabled;
 login('owner-f@example.test');
 pending[7].resolve(list('OWNER_F')); await flush();
 checks.relogin=pending.length===8 && text(nodes.outputsList).includes('OWNER_F');
 nodes.outputsList.children[0].click();
 pending[8].resolve(detail('OWNER_F')); await flush();
 nodes.savedOutputTitleInput.value='Renamed';
 nodes.savedOutputRename.click();
 login('owner-g@example.test');
 pending[10].resolve(list('OWNER_G')); await flush();
 pending[9].resolve(detail('STALE_RENAME_F')); await flush();
 checks.stale_rename=pending.length===11 && !nodes.savedOutputDialog.open && text(nodes.outputsList).includes('OWNER_G');
 nodes.outputsList.children[0].click();
 pending[11].resolve(detail('OWNER_G')); await flush();
 nodes.savedOutputDelete.click();
 login('owner-h@example.test');
 confirms[0](true); await flush();
 checks.stale_confirm=pending.length===13 && pending[12].url==='/api/outputs';
 console.log(JSON.stringify(checks));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    with tempfile.TemporaryDirectory(prefix="r1-outputs-") as directory:
        harness = Path(directory) / "journey.cjs"
        harness.write_text(script, encoding="utf-8")
        result = subprocess.run([shutil.which("node") or "node", str(harness), str(STATIC)],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_outputs_same_owner_keeps_dom_without_auth_mutation_observer():
    result = _journey()
    assert result["initial"] and result["same_owner"] and result["no_auth_observer"], result


def test_outputs_owner_switch_clears_rows_and_rejects_stale_list_and_detail():
    result = _journey()
    assert result["switch_clear"] and result["switch_fresh"] and result["stale_list"] and result["stale_detail"], result


def test_outputs_logout_rejects_stale_page_and_relogin_loads_fresh_rows():
    result = _journey()
    assert result["stale_page"] and result["logout"] and result["relogin"], result


def test_outputs_previous_owner_mutation_completion_and_confirmation_are_ignored():
    result = _journey()
    assert result["stale_rename"] and result["stale_confirm"], result
