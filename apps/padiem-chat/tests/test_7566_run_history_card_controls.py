"""#7566 — a PC command confirmation card is not an approval handoff.

The card row waits for the owner's decision (`waiting_approval`), but the owner
answers it in its conversation. The run-history card must not offer the
approve/deny controls, which drive the approval handoff and would fail for it.
Runs the shipped module; no source-text pin.
"""
from pathlib import Path
import subprocess

STATIC = Path(__file__).resolve().parents[1] / "static"

NODE = r"""
const fs=require("fs"),path=require("path"),vm=require("vm");
const dir=process.argv[1];
function ok(x,message){if(!x)throw Error(message)}
class E {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={}}
 append(...values){this.children.push(...values)}
 appendChild(x){this.children.push(x)}
 addEventListener(){}
 setAttribute(k,v){this[k]=v}
}
const doc={documentElement:{lang:"ko"},createElement:t=>new E(t),getElementById:()=>null};
const win={};
vm.runInNewContext(fs.readFileSync(path.join(dir,"chat-run-history-module.js"),"utf8"),
 {document:doc,window:win,Date,Promise,Boolean,String,Number,Intl,Object});
const offered=[];
const deps={uiT:s=>s,clawT:key=>key,clawRunHistoryPdfControllers:new Set(),
 setClawRunHistoryStatus:()=>{},openSavedConversation:()=>{},downloadClawArtifact:()=>{},
 loadClawRunHistory:async()=>{},
 renderClawApprovalControls:(container,runId)=>{offered.push(runId)}};
const render=win.PadiemChatRunHistoryModule.create(deps).renderClawRunCard;
const controls=card=>card.children.filter(x=>String(x.className||"").includes("claw-run-approval-actions"));

const handoff=render({run_id:"run_handoff",status:"waiting_approval",action:"document",title:"t"});
ok(controls(handoff).length===1,"an approval handoff keeps its controls");
ok(offered.length===1&&offered[0]==="run_handoff","controls are wired to the handoff run");

const card=render({run_id:"run_card",status:"waiting_approval",action:"pc_command",title:"t"});
ok(controls(card).length===0,"a PC command card offers no approval controls");
ok(offered.length===1,"no approval control was created for the card");
ok(card.dataset.runState==="waiting_approval","the card still shows that it waits for the owner");

const ran=render({run_id:"run_ran",status:"pending",action:"pc_command",title:"t"});
ok(controls(ran).length===0,"a command that is running offers no controls either");
console.log("ok");
"""


def test_pc_command_card_offers_no_approval_controls():
    done = subprocess.run(
        ["node", "-e", NODE, str(STATIC)], capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"
