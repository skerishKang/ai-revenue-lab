"""R1 step2: real session listeners preserve transition-only cleanup."""
from pathlib import Path
import shutil
import subprocess

# R5 0단계(R-01): 함수 경계는 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import definition_source

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_chat_and_claw_cleanup_follow_real_session_transitions(tmp_path):
    script = tmp_path / "cleanup.cjs"
    script.write_text(r'''
const assert = require('node:assert/strict');
const path = require('node:path');
const listeners = {};
const byId = {};
const ids = ['clawAutomation','clawAutomationList','clawWorkspace','clawRunHistory',
  'clawRunHistoryList','clawRunHistoryError','clawApprovedMemory','clawApprovedDisclosure',
  'clawApprovedList','clawApprovedError','clawApprovalActions','clawRunHistoryDisclosure'];
for (const id of ids) byId[id] = {hidden:false, open:true, children:['PRIVATE'], textContent:'PRIVATE',
  dataset:{view:'automation',state:'error'}, replaceChildren(){this.children=[];},
  removeAttribute(name){delete this.dataset[name.replace(/^data-/, '')];}};
const calls = {history:0, projects:0, reset:[], handoff:0, storage:0, approval:[], recovery:[], wait:0, pdf:0};
let handoff = true;
global.window = {
  addEventListener(type, fn){(listeners[type] ||= []).push(fn);},
  dispatchEvent(event){(listeners[event.type] || []).forEach(fn => fn(event));},
  PadiemClawPdfPreview:{revokeAll(){calls.pdf++;}}
};
global.document = {getElementById:id => byId[id] || null};
global.CustomEvent = class {constructor(type, init){this.type=type;this.detail=init.detail;}};
for (const file of ['auth-session.js','chat-session.js','claw-session.js']) require(path.join(process.argv[2],file));
window.PadiemChatSession.bind({
  clearHistoryUI(){calls.history++;}, clearProjectsUI(){calls.projects++;},
  resetConversationView(value){calls.reset.push(value);}, hasAndroidHandoff:()=>handoff,
  clearAndroidHandoff(){calls.handoff++;handoff=false;}, clearHandoffStorage(){calls.storage++;}
});
window.PadiemClawSession.bind({noteApprovalSession:value=>calls.approval.push(value),
  clearRecovery:options=>calls.recovery.push(options), clearWait(){calls.wait++;}});
const guest={ready:true,authenticated:false};
const signed={ready:true,authenticated:true,user:{email:'a@example.test',name:'Owner'}};
const update=(data, generation)=>window.PadiemAuthSession.update(data,generation);
update(guest,1);
assert.deepEqual(calls.reset, [], 'initial guest keeps draft and focus');
assert.equal(calls.storage,0);
assert.equal(calls.history,1);assert.equal(calls.projects,1);
assert.equal(calls.wait,1);assert.deepEqual(calls.recovery,[{syncControls:true}]);
const first=JSON.stringify(calls);
update({...guest},2);assert.equal(JSON.stringify(calls),first,'same guest performs no cleanup');
update(signed,3);
assert.equal(calls.handoff,1);assert.deepEqual(calls.approval,[false,true]);
assert.equal(calls.wait,1);assert.equal(calls.history,1);
// Repopulate the signed-in surfaces, as a completed request would do.
for (const id of ids) Object.assign(byId[id],{hidden:false,open:true,children:['PRIVATE'],textContent:'PRIVATE'});
update({...signed,user:{...signed.user}},4);
assert.equal(calls.handoff,1);assert.equal(calls.approval.length,2);
assert.equal(byId.clawRunHistoryList.children.length,1);
update(guest,5);
assert.deepEqual(calls.reset,[false]);assert.equal(calls.storage,1);
assert.equal(calls.history,2);assert.equal(calls.projects,2);
assert.equal(calls.wait,2);assert.equal(calls.pdf,2);
assert.deepEqual(calls.recovery,[{syncControls:true},{syncControls:true}]);
for(const id of ['clawAutomationList','clawRunHistoryList','clawApprovedList','clawApprovalActions'])
  assert.equal(byId[id].children.length,0,id);
for(const id of ['clawAutomation','clawRunHistory','clawApprovedMemory','clawApprovedDisclosure','clawApprovalActions','clawRunHistoryDisclosure'])
  assert.equal(byId[id].hidden,true,id);
assert.equal(byId.clawApprovedDisclosure.open,false);
for(const id of ['clawRunHistoryError','clawApprovedError']){
  assert.equal(byId[id].textContent,'');assert.equal(byId[id].hidden,true);
  assert.equal(byId[id].dataset.state,undefined);
}
assert.equal(byId.clawWorkspace.dataset.view,'general');
const final=JSON.stringify(calls);update(guest,6);assert.equal(JSON.stringify(calls),final);
const beforeLocale=JSON.parse(final);
window.dispatchEvent({type:'padiem:localechange'});
assert.deepEqual(calls,{...beforeLocale,projects:beforeLocale.projects+1},'guest locale updates only the project badge');
update(signed,7);
const signedBeforeLocale=JSON.stringify(calls);
window.dispatchEvent({type:'padiem:localechange'});
assert.equal(JSON.stringify(calls),signedBeforeLocale,'signed-in locale leaves session cleanup untouched');
assert.deepEqual(calls.reset,[false],'relogin must not clear new conversation');
assert.deepEqual(calls.approval,[false,true,false,true]);
''', encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(script), str(STATIC)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cleanup_bindings_are_bootstrap_only_not_auth_dialog_handlers():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # Binding on each dialog open would accumulate listeners and reset twice.
    # R5 0단계(R-01): openAuthDialog/closeAuthDialog의 실제 정의는 모듈에 있을 수
    # 있으므로 도우미로 정의 파일을 찾아 그 소스에서 경계를 잡는다.
    dialogs = definition_source("openAuthDialog")
    start = dialogs.index("function openAuthDialog(")
    end = dialogs.index("function closeAuthDialog(", start)
    assert "PadiemChatSession.bind" not in dialogs[start:end]
    assert "PadiemClawSession.bind" not in dialogs[start:end]
    for name in ["PadiemChatSession", "PadiemClawSession"]:
        assert app.count(f"window.{name}.bind({{") == 1
        assert app.index(f"window.{name}.bind({{") < app.index("const resetLinkOnLoad =")
