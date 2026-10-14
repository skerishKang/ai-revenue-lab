/* Claw connection state: the server alone is authoritative. */
(()=>{
"use strict";
const shell=document.querySelector(".app-shell"), owner=document.querySelector(".sidebar-account");
if(!shell||!owner)return;
const ids=["pc","drive","github"], values=new Map(ids.map(x=>[x,"unknown"]));
let generation=0;
const pendingDisconnect=new Set();
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
 const result=await Promise.allSettled([read("/api/claw/local-access/devices"),read("/api/connectors/status"),read("/api/connectors/github/status")]);
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
 if(result[2].status==="fulfilled"){
  const github=result[2].value;
  if(github?.ok===true&&["on","off"].includes(github.state))set("github",github.state);
 }
}
async function disconnectDrive(){
 if(pendingDisconnect.has("drive"))return;
 pendingDisconnect.add("drive");
 const button=chip("drive");
 if(button)button.disabled=true;
 try{
  const response=await fetch("/api/connectors/google/drive/disconnect",{
   method:"POST",credentials:"same-origin",cache:"no-store",
   headers:{Accept:"application/json","Content-Type":"application/json"}
  });
  const payload=await response.json();
  if(!response.ok||payload?.ok!==true||payload.state!=="off")throw Error("disconnect not certified");
  await refresh(); // Only canonical GET may change the visible ON/OFF state.
  feedback("구글 드라이브 연결을 해제했습니다.","Google Drive was disconnected.");
 }catch(_error){
  await refresh();
  feedback("구글 드라이브 연결 해제에 실패했습니다. 연결 상태를 다시 확인해 주세요.",
    "Drive disconnect failed. Please check the connection status.");
 }finally{
  pendingDisconnect.delete("drive");
  if(button)button.disabled=false;
 }
}
async function disconnectGithub(){
 if(pendingDisconnect.has("github"))return;
 pendingDisconnect.add("github");
 const button=chip("github");if(button)button.disabled=true;
 try{
  const response=await fetch("/api/connectors/github/disconnect",{
   method:"POST",credentials:"same-origin",cache:"no-store",
   headers:{Accept:"application/json","Content-Type":"application/json"}
  });
  const payload=await response.json();
  if(!response.ok||payload?.ok!==true||payload.state!=="off")throw Error("not disconnected");
  await refresh();
  feedback("GitHub 연결을 해제했습니다.","GitHub was disconnected.");
 }catch(_error){
  await refresh();
  feedback("GitHub 연결 해제에 실패했습니다. 연결 상태를 다시 확인해 주세요.","GitHub disconnect failed. Please check connection status.");
 }finally{
  pendingDisconnect.delete("github");if(button)button.disabled=false;
 }
}
ids.forEach(id=>chip(id)?.addEventListener("click",()=>{
 if(!home())return;
 const state=values.get(id);
 if(state==="on"&&id==="drive"){
  if(signedIn())void disconnectDrive();
  else feedback("연결을 관리하려면 로그인해 주세요.","Sign in to manage connections.");
  return;
 }
 if(state==="on"&&id==="github"){
  if(signedIn())void disconnectGithub();
  else feedback("연결하려면 로그인해 주세요.","Sign in to manage connections.");
  return;
 }
 if(state==="on"){
  // PC currently lacks a reviewed disconnect endpoint.
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
 if(id==="github"){
  window.location.assign("/api/connectors/github/start");
  return;
 }
 const target=id==="pc"?"clawComputerWorkspace":"clawDriveWorkspace";
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