"""#3932 owner-scoped run-history PDF preview uses the actual browser code.

No live provider, auth credentials, or PDF generator: 200/404 are synthetic.
"""
from pathlib import Path
import subprocess

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
PDF = (STATIC / "claw-pdf-preview.js").read_text(encoding="utf-8")

NODE = r"""
const fs=require("fs"),path=require("path"),vm=require("vm");
const dir=process.argv[1];
const read=n=>fs.readFileSync(path.join(dir,n),"utf8");
function ok(x,message){if(!x)throw Error(message)}
class E {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.handlers={};this.dataset={};this.open=false;this.disabled=false;this.removed=false}
 append(...values){this.children.push(...values)}
 appendChild(x){this.children.push(x)}
 addEventListener(k,fn){this.handlers[k]=fn}
 setAttribute(k,v){this[k]=v}
 showModal(){this.open=true}
 close(){this.open=false;this.handlers.close?.()}
 remove(){this.removed=true}
 focus(){this.focused=true}
}
const doc={documentElement:{lang:"ko"},body:new E("body"),createElement:t=>new E(t)};
const win={}, sets=new Set(), failures=[], urls=[], revoked=[];
const id="doc_"+"a".repeat(32);
const pdf=Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n");
let status=200, calls=[];
const fetcher=async (url,opt)=>{calls.push({url,opt});return {
 status, headers:{get:k=>k==="content-type"?(status===200?"application/pdf":"application/json"):null},
 arrayBuffer:async()=>Uint8Array.from(pdf).buffer}};
const URLStub={createObjectURL:()=>{const u="blob:run-test/"+urls.length;urls.push(u);return u},revokeObjectURL:u=>revoked.push(u)};
vm.runInNewContext(read("claw-pdf-preview.js"),{window:win,document:doc,fetch:fetcher,
 URL:URLStub,Blob,AbortController,Uint8Array});
const P=win.PadiemClawPdfPreview;
const legacy={document_id:id,filename:"output.pdf",media_type:"application/pdf"};
ok(!P.validArtifact(legacy),"normal result needs a true byte length");
ok(P.validHistoricalArtifact(legacy),"historical owner-receipt can request a check");
ok(!P.validHistoricalArtifact({...legacy,filename:"output.xlsx"}),"non PDF rejected");
ok(!P.validHistoricalArtifact({...legacy,document_id:"../foreign"}),"ID must be canonical");
ok(!P.validHistoricalArtifact({...legacy,byte_length:11*1024*1024}),"oversize known blocked");
const app=read("app.js");
const start=app.indexOf("  function renderClawRunCard(run) {");
const end=app.indexOf("\n  // Unguarded fetch:",start);
ok(start>=0&&end>start,"actual run card source must be located");
const context={document:doc,window:win,clawRunHistoryPdfControllers:sets,
 setClawRunHistoryStatus:msg=>failures.push(msg),clawT:key=>key,clawRunStatusLabel:s=>s,
 openSavedConversation:()=>{throw Error("unexpected session open")},
 downloadClawArtifact:()=>{throw Error("unexpected download")},
 renderClawApprovalControls:()=>{throw Error("unexpected approval")}};
const render=vm.runInNewContext("("+app.slice(start,end).trim()+")",context);
(async()=>{
 const card=render({run_id:"run_x",status:"completed",title:"real historical run",artifact:legacy});
 const row=card.children.find(x=>x.className==="claw-run-card-artifact");
 ok(!!row&&row.children.length===3,"history card retains filename/download and adds PDF check");
 ok(row.children[2].textContent==="PDF 미리보기 확인","unknown length is visibly unverified");
 ok(calls.length===0,"no fetch before user click");
 row.children[2].handlers.click();
 await new Promise(setImmediate);
 ok(calls.length===1&&calls[0].url==="/api/claw/manual-intake/artifact/"+id+"/preview","only canonical existing route");
 ok(calls[0].opt.method==="GET"&&calls[0].opt.credentials==="same-origin","owner-authorized GET");
 ok(doc.body.children[0].open===true,"valid PDF is displayed");
 P.revokeAll();
 ok(doc.body.children[0].removed&&urls.length===revoked.length,"logout closes and revokes Blob");
 ok(sets.size===1,"one controller per bounded card");
 for(const ctrl of sets)ctrl.destroy();
 sets.clear();
 ok(row.children[2].removed&&sets.size===0,"history refresh removes stale preview");
 const docx=render({run_id:"run_b",status:"completed",artifact:{...legacy,filename:"x.docx",media_type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}});
 const docxRow=docx.children.find(x=>x.className==="claw-run-card-artifact");
 ok(docxRow.children.length===2,"DOCX keeps download only");
 status=404;
 const denied=render({run_id:"run_c",status:"failed",artifact:legacy});
 const deniedRow=denied.children.find(x=>x.className==="claw-run-card-artifact");
 ok(deniedRow.children.some(x=>x.className==="claw-run-card-partial-note"),"failed run is not falsely marked completed");
 const deniedPreview=deniedRow.children.find(x=>x.textContent==="PDF 미리보기 확인");
 ok(!!deniedPreview,"preview remains discoverable regardless of partial-note order");
 deniedPreview.handlers.click();
 await new Promise(setImmediate);
 ok(failures.length===1&&!failures[0].includes("SECRET"),"revoked PDF fails safely");
 ok(doc.body.children.length===1,"denied PDF must not open a new modal");
 for(const ctrl of sets)ctrl.destroy();
 console.log("HISTORY_PDF_USER_CLICK_AND_AUTHORIZED_GET=PASS");
 console.log("HISTORY_PDF_DENIAL_DOWNLOAD_ONLY=PASS");
 console.log("HISTORY_PDF_ABORT_BLOB_CLEANUP=PASS");
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""

def test_real_history_card_pdf_preview_node_vm():
    proc = subprocess.run(["node", "-e", NODE, str(STATIC)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=20, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for key in ("HISTORY_PDF_USER_CLICK_AND_AUTHORIZED_GET=PASS",
                "HISTORY_PDF_DENIAL_DOWNLOAD_ONLY=PASS",
                "HISTORY_PDF_ABORT_BLOB_CLEANUP=PASS"):
        assert key in proc.stdout

def test_history_cleanup_and_production_script_order():
    assert "clearClawRunHistoryPdfPreviews();" in APP
    assert "clawRunHistoryVisibilityEpoch += 1;" in APP
    assert "viewer?.setHistorical?.(artifact)" in APP
    assert "history && artifact.byte_length == null" in PDF
    assert "controllers.delete(instance)" in PDF
    assert "visibilityEpoch !== clawRunHistoryVisibilityEpoch" in APP
    assert "authState.authenticated !== true || clawRunHistory.hidden" in APP
