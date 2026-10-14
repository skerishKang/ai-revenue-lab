/* Claw connection state: the server alone is authoritative. */
(()=>{
"use strict";
const shell=document.querySelector(".app-shell"), owner=document.querySelector(".sidebar-account");
if(!shell||!owner)return;
const ids=["pc","drive","github"], values=new Map(ids.map(x=>[x,"unknown"]));
let generation=0;
const english=()=>document.documentElement.lang==="en";
const message=(ko,en)=>english()?en:ko;
const home=()=>shell.dataset.state==="claw"&&document.getElementById("clawWorkspace")?.dataset.view==="general";
const signedIn=()=>owner.dataset.accountState==="signed_in";
const chip=id=>document.querySelector('[data-claw-connection="'+id+'"]');
function set(id,value){
 if(!["on","off","unknown"].includes(value))value="unknown";
 values.set(id,value);
 const element=chip(id);if(!element)return;
 const display=value==="on"?"ON":value==="off"?"OFF":message("확인 불가","Unavailable");
 const label=element.querySelector(".claw-connection-label");
 if(label)label.textContent=display;else element.textContent=display;
 element.dataset.connectionState=value;
 element.setAttribute("aria-label",(id==="pc"?message("컴퓨터","Computer"):id==="drive"?"Google Drive":"GitHub")+" "+display);
}
const reset=()=>ids.forEach(id=>set(id,"unknown"));
const feedback=(ko,en)=>{const el=document.getElementById("clawConnectionFeedback");if(!el)return;el.textContent=message(ko,en);el.hidden=false;};
async function read(url){
 const r=await fetch(url,{method:"GET",credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
 if(!r.ok)throw Error("no authority");
 const s=await r.text();if(s.length>32768)throw Error("oversized");return JSON.parse(s);
}
async function refresh(){
 const current=++generation;if(!home()||!signedIn()){reset();return;}
 const result=await Promise.allSettled([read("/api/claw/local-access/devices"),read("/api/connectors/status")]);
 if(current!==generation||!home()||!signedIn())return;
 reset();
 if(result[0].status==="fulfilled"){
  const d=result[0].value;
  if(d?.ok===true&&d.available===true&&d.ownerScoped===true&&Array.isArray(d.devices)&&d.devices.length<=25){
   if(!d.devices.length)set("pc","off");
   else{
    const records=d.devices.map(x=>x?.projection&&typeof x.projection==="object"?x.projection:x);
    if(records.some(x=>x?.state==="CONNECTED"&&x.usable===true&&x.revoked!==true&&x.expired!==true))set("pc","on");
    else if(records.every(x=>x&&["PAIRING","OFFLINE","REVOKED","ACTION_REQUIRED"].includes(x.state)))set("pc","off");
   }
  }
 }
 if(result[1].status==="fulfilled"){
  const d=result[1].value;
  if(d?.workspace_state_authority===true&&Array.isArray(d.connectors)){
   const rows=d.connectors.filter(x=>x?.connector_id==="connector:google:drive@1");
   if(rows.length===1&&rows[0].workspace_state==="connected")set("drive","on");
   else if(rows.length===1&&rows[0].workspace_state==="not_connected")set("drive","off");
  }
 }
 // GitHub has no reviewed per-owner connection-state endpoint in B62.
 set("github","unknown");
}
ids.forEach(id=>chip(id)?.addEventListener("click",()=>{
 if(!home())return;
 const state=values.get(id);
 if(state==="on"){
  // No reviewed disconnect endpoint: report its absence without a misleading confirmation dialog.
  feedback("안전한 연결 해제 기능이 아직 제공되지 않습니다. 연결은 유지됩니다.",
    "A reviewed disconnect action is not available yet. The connection stays ON.");
  return;
 }
 if(!signedIn()){
  const login=document.getElementById("loginButton");
  if(login&&!login.hidden&&login.textContent?.trim())login.click();
  feedback("연결하려면 로그인해 주세요.","Sign in to connect.");
  return;
 }
 const target=id==="pc"?"clawComputerWorkspace":id==="drive"?"clawDriveWorkspace":"clawGithubWorkspace";
 document.getElementById(target)?.click();
 if(state==="unknown")feedback("연결 상태를 확인할 수 없습니다. 연결 관리에서 확인해 주세요.",
    "Connection status is unavailable. Please check Connectors.");
}));
const observer=new MutationObserver(()=>{++generation;reset();if(home()&&signedIn())void refresh();});
observer.observe(shell,{attributes:true,attributeFilter:["data-state"]});
observer.observe(owner,{attributes:true,attributeFilter:["data-account-state"]});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&home())void refresh();});
window.addEventListener("focus",()=>{if(home())void refresh();});
if(home()&&signedIn())void refresh();
})();