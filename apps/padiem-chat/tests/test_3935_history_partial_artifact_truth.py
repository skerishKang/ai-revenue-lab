"""#3935 Hark: historical artifact reference never proves task completion.

Execute the shipped Claw run-card renderer (not a copy of its logic) using Node
against minimal DOM fixtures. No provider, authority, storage, or network use.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = STATIC / "app.js"
LOCALE = STATIC / "locale.js"
CSS = STATIC / "claw-workspace.css"

NODE = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const app = fs.readFileSync(process.argv[1], "utf8");
const start = app.indexOf("  function renderClawRunCard(run) {");
const end = app.indexOf("\n  // Unguarded fetch:", start);
assert(start >= 0 && end > start, "actual run-card source is located");
function el(tag) {
  return {
    tag, className:"", textContent:"", dataset:{}, children:[], listeners:{},
    setAttribute(name,value){this[name]=value},
    append(...elements){this.children.push(...elements)},
    appendChild(child){this.children.push(child);return child},
    addEventListener(name,fn){(this.listeners[name] ||= []).push(fn)},
    click(){(this.listeners.click || []).forEach(fn=>fn())},
  };
}
const downloads=[];
const strings={
  "claw-runs-download":"Download document again",
  "claw-runs-artifact-unverified":"This run is not marked complete. A recorded document does not prove task success; access is checked when downloading.",
};
const renderCard=vm.runInNewContext("("+app.slice(start,end).trim()+")",{
  document:{createElement:el},
  window:{PadiemClawPdfPreview:null},
  clawT:(key)=>strings[key] || key,
  clawRunStatusLabel:(status)=>status,
  clawRunHistoryPdfControllers:new Set(),
  setClawRunHistoryStatus:()=>{},
  downloadClawArtifact:(id,name)=>downloads.push([id,name]),
  openSavedConversation:()=>{throw Error("unexpected session open")},
  renderClawApprovalControls:()=>{},
});
const art={document_id:"doc_"+"a".repeat(32),filename:"output.docx",
   media_type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document"};
function nodes(root,predicate) {
  const all=[];
  function visit(n){if(predicate(n))all.push(n);(n.children||[]).forEach(visit)}
  visit(root);return all;
}
function render(status,artifact=art){
  return renderCard({run_id:"run.one", title:"Task", status, channel:"web",
    action:"document", created_at:"2026-10-10T00:00:00Z",
    result_summary:"bounded summary",artifact,session:null});
}
for (const status of ["failed","cancelled","waiting_approval","running","unknown"]) {
  const card=render(status);
  const notes=nodes(card,n=>n.className==="claw-run-card-partial-note");
  assert.equal(notes.length,1,status+" needs truthful note");
  assert.equal(notes[0].role,"note");
  assert(notes[0].textContent.includes("does not prove task success"));
  assert.equal(nodes(card,n=>n.className==="claw-run-card-badge")[0].textContent,status);
  const download=nodes(card,n=>n.className==="claw-run-card-download");
  assert.equal(download.length,1,status+" preserves one existing download");
  const before=downloads.length; download[0].click();
  assert.equal(downloads.length,before+1);
  assert.equal(downloads.at(-1)[0],art.document_id);
}
assert.equal(nodes(render("completed"),n=>n.className==="claw-run-card-partial-note").length,0,
             "completed does not gain misleading warning");
assert.equal(nodes(render("failed",null),n=>n.className==="claw-run-card-partial-note").length,0,
             "no file reference, no artifact warning");
const hostile=render("failed",{...art,filename:'<img src=x onerror=alert(1)>'});
const label=nodes(hostile,n=>n.className==="claw-run-card-filename");
assert.equal(label.length,1);assert.equal(label[0].textContent,'<img src=x onerror=alert(1)>',
                                   "untrusted filenames remain plain text");
assert.equal(downloads.length,5,"no automatic download/retry");
console.log("HARK_3935_FAILED_CANCELLED_PENDING_UNKNOWN=PASS");
console.log("HARK_3935_COMPLETED_NO_WARNING=PASS");
console.log("HARK_3935_DOWNLOAD_CLICK_ONLY=PASS");
console.log("HARK_3935_USER_FILENAME_TEXT_ONLY=PASS");
"""

def test_actual_run_card_failed_partial_artifact_truth():
    proc = subprocess.run(
        ["node", "-e", NODE, str(APP)], encoding="utf-8",
        text=True, capture_output=True, check=False, timeout=25,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for marker in (
        "HARK_3935_FAILED_CANCELLED_PENDING_UNKNOWN=PASS",
        "HARK_3935_COMPLETED_NO_WARNING=PASS",
        "HARK_3935_DOWNLOAD_CLICK_ONLY=PASS",
        "HARK_3935_USER_FILENAME_TEXT_ONLY=PASS",
    ):
        assert marker in proc.stdout


def test_two_locales_and_theme_preserve_warning_without_granting_authority():
    app = APP.read_text(encoding="utf-8")
    locale = LOCALE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    key = '"claw-runs-artifact-unverified"'
    assert app.count('clawT("claw-runs-artifact-unverified")') == 1
    assert locale.count(key) == 2
    ko, en = locale.split("en: {", 1)
    assert "전체 작업의 성공" in ko
    assert "does not prove task success" in en
    assert ".claw-run-card-partial-note" in css
    assert "var(--muted)" in css
    block = app.split("function renderClawRunCard(run) {", 1)[1].split("// Unguarded fetch:", 1)[0]
    for forbidden in ("fetch(", "POST", "localStorage", "sessionStorage", "approve(", "retry("):
        assert forbidden not in block
