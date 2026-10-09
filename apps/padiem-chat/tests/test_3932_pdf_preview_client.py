"""#3932 real Claw result-card PDF UI, using actual shipped JavaScript."""
from __future__ import annotations

from pathlib import Path
import subprocess

STATIC = Path(__file__).resolve().parents[1] / "static"
SOURCE = (STATIC / "claw-pdf-preview.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

NODE = r"""
const fs=require("fs"),vm=require("vm"),path=require("path");
const source=fs.readFileSync(path.join(process.argv[1],"claw-pdf-preview.js"),"utf8");
function assert(cond,msg){if(!cond)throw new Error(msg)}
class Element {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.disabled=false;this.open=false;this.removed=false;this.focused=false;}
 addEventListener(k,fn){this.listeners[k]=fn;}
 append(...x){this.children.push(...x)}
 appendChild(x){this.children.push(x)}
 remove(){this.removed=true}
 setAttribute(k,v){this[k]=v}
 showModal(){this.open=true}
 close(){this.open=false;this.listeners.close?.()}
 focus(){this.focused=true}
}
const doc={documentElement:{lang:"ko"},body:new Element("body"),createElement:x=>new Element(x)};
const win={};
vm.runInNewContext(source,{window:win,document:doc,Blob,AbortController,URL,Uint8Array});
const P=win.PadiemClawPdfPreview;
const id="doc_"+"a".repeat(32);
const payload=Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n");
const artifact={document_id:id,filename:"quote.pdf",media_type:"application/pdf",byte_length:payload.length};
let requested=[],created=[],revoked=[],errors=[];
const fetcher=async (url,init)=>{requested.push({url,init});return {
 status:200,headers:{get:k=>k==="content-type"?"application/pdf":null},
 arrayBuffer:async()=>Uint8Array.from(payload).buffer
}};
const mount=new Element("section");
const ctrl=P.create({mount,doc,fetcher,onError:msg=>errors.push(msg),
 makeUrl:blob=>{assert(blob.type==="application/pdf","blob MIME");const u="blob:private/"+created.length;created.push(u);return u},
 revokeUrl:u=>revoked.push(u)});
(async()=>{
 assert(!ctrl.set({document_id:id,filename:"quote.docx",media_type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document",byte_length:80}),"DOCX download only");
 assert(mount.children.length===0,"DOCX has no extra preview action");
 assert(!ctrl.set({...artifact,media_type:"text/html"}),"wrong MIME blocked");
 assert(!ctrl.set({...artifact,document_id:"../../abc"}),"path forged");
 assert(!ctrl.set({...artifact,byte_length:11000000}),"too large");
 assert(ctrl.set(artifact),"real PDF should be eligible");
 assert(requested.length===0,"never fetch before user asks");
 assert(mount.children.length===1&&mount.children[0].textContent==="PDF 미리보기","KO label");
 assert(await ctrl.show(),"authorized same-origin PDF can open");
 assert(requested.length===1&&requested[0].url.endsWith("/"+id+"/preview"),"only canonical ID route");
 assert(requested[0].init.method==="GET"&&requested[0].init.credentials==="same-origin"&&requested[0].init.cache==="no-store","read-only private fetch");
 assert(doc.body.children.length===1&&doc.body.children[0].open,"native dialog visible");
 assert(doc.body.children[0].children[1].src===created[0],"PDF blob confined to dialog");
 doc.body.children[0].close();
 assert(revoked.length===1 && doc.body.children[0].removed,"on close revoke blob");
 assert(errors.length===0,"no false provider error");
 ctrl.clear();
 assert(mount.children[0].removed,"stale button removed");
 assert(!ctrl.set({...artifact,filename:"quote.xlsx"}),"XLSX preview cannot be fabricated");

 const denial=P.create({mount:new Element("div"),doc,
 fetcher:async()=>({status:404,headers:{get:()=> "application/json"}}),
 onError:msg=>errors.push(msg), makeUrl:()=>{throw Error("SHOULD_NOT_ALLOCATE")}});
 denial.set(artifact);
 assert(!(await denial.show()),"revoked/foreign access must deny");
 assert(errors.length===1&&!errors[0].includes("SECRET"),"safe denial text");

 const wrong=P.create({mount:new Element("div"),doc,
 fetcher:async()=>({status:200,headers:{get:()=> "application/json"},arrayBuffer:async()=>Uint8Array.from(payload).buffer}),
 onError:msg=>errors.push(msg), makeUrl:()=>{throw Error("SHOULD_NOT_ALLOCATE")}});
 wrong.set(artifact);
 assert(!(await wrong.show()),"false PDF response rejected");

 let release;
 const pending=new Promise(r=>release=r);
 const race=P.create({mount:new Element("div"),doc,
 fetcher:async() => pending,
 onError:msg=>errors.push(msg),
 makeUrl:()=>{throw Error("SHOULD_NOT_ALLOCATE")}});
 race.set(artifact);
 const show=race.show();
 race.clear();
 release({status:200,headers:{get:()=>"application/pdf"},arrayBuffer:async()=>Uint8Array.from(payload).buffer});
 assert(!(await show),"race cancelled");
 assert(errors.length===2,"clear avoids spurious errors");
 assert(doc.body.children.length===1,"no new modal after clear");
 console.log("PDF_PREVIEW_ACTUAL_BYTES=PASS");
 console.log("REVOKED_AND_MIME_FAIL_CLOSED=PASS");
 console.log("NO_REPLAY_NO_PREMATURE_FETCH=PASS");
 console.log("FOCUS_CLOSE_BLOB_REVOCATION=PASS");
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


def test_actual_pdf_modal_browser_code_with_node_vm():
    result = subprocess.run(["node", "-e", NODE, str(STATIC)],
                            text=True, encoding="utf-8", capture_output=True,
                            timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    for key in ("PDF_PREVIEW_ACTUAL_BYTES=PASS",
                "REVOKED_AND_MIME_FAIL_CLOSED=PASS",
                "NO_REPLAY_NO_PREMATURE_FETCH=PASS",
                "FOCUS_CLOSE_BLOB_REVOCATION=PASS"):
        assert key in result.stdout


def test_document_download_contract_and_script_order_unchanged():
    assert HTML.count('<script src="./claw-pdf-preview.js"></script>') == 1
    assert HTML.index("claw-pdf-preview.js") < HTML.index('<script src="./app.js">')
    assert "clawPdfPreviewController?.set(artifact)" in APP
    assert "clawPdfPreviewController?.clear()" in APP
    assert "downloadClawArtifact(docId, fname)" in APP
    assert "PadiemClawPdfPreview" in SOURCE
    for disallowed in ("innerHTML", "localStorage", "sessionStorage",
                       "window.open(", "location.href", "POST", "XMLHttpRequest"):
        assert disallowed not in SOURCE
