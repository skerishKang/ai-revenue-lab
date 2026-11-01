/* Claw connection state: the server alone is authoritative. */
(()=>{
"use strict";
const shell=document.querySelector(".app-shell"), owner=document.querySelector(".sidebar-account");
if(!shell||!owner)return;
const ids=["pc","drive","github"], values=new Map(ids.map(x=>[x,"unknown"]));
let generation=0;
let refreshInFlight=null, refreshSequence=0;
const confirmed=new Set();
// Only display GETs use this deadline. Tool work and connector mutations do not.
const STATUS_READ_TIMEOUT_MS=3000;
const pendingDisconnect=new Set();
const english=()=>document.documentElement.lang==="en";
const message=(ko,en)=>english()?en:ko;
const home=()=>shell.dataset.state==="claw"&&document.getElementById("clawWorkspace")?.dataset.view==="general";
const signedIn=()=>owner.dataset.accountState==="signed_in";
const chip=id=>document.querySelector('[data-claw-connection="'+id+'"]');
// PC's headline is separate from its single two-position switch. Neither
// installation nor user OFF is inferred from a missing GET/heartbeat.
const pcCard=document.querySelector('[data-claw-card="computer"]');
const pcStatus=document.getElementById("clawPcCardStatus");
const pcTruth=(phase,ko,en)=>{
 if(!pcCard||!pcStatus)return;
 pcCard.dataset.pcPhase=phase;
 pcStatus.textContent=message(ko,en);
};
// Every connector card carries its truthful headline in the card's top-right
// corner, exactly like the PC card. The bottom-right keeps only the ON/OFF
// switch, so Drive/GitHub no longer stretch an "확인 불가" label under it.
const cardStatus={pc:pcStatus,drive:document.getElementById("clawDriveCardStatus"),github:document.getElementById("clawGithubCardStatus")};
const cardEl=id=>document.querySelector('[data-claw-card="'+(id==="pc"?"computer":id)+'"]');
const vocabStatus=(key,fallback)=>{const v=window.PadiemConnectorVocabulary;return v&&typeof v.status==="function"?(v.status(key)||fallback):fallback;};
const truthText=value=>value==="on"?vocabStatus("connected",message("연결되었습니다","Connected")):value==="off"?vocabStatus("disconnected",message("연결 끔","Off")):vocabStatus("checking",message("연결 확인 필요","Connection needs checking"));
const cardTruth=(id,value)=>{
 const card=cardEl(id);if(card)card.dataset.connectionPhase=value;
 const el=cardStatus[id];if(el)el.textContent=truthText(value);
};

function set(id,value){
 if(!["on","off","unknown"].includes(value))value="unknown";
 values.set(id,value);
 if(value==="unknown")confirmed.delete(id);else confirmed.add(id);
 const element=chip(id);if(!element)return;
 delete element.dataset.connectionStale;
 if(id==="github"&&value==="unknown")delete element.dataset.connectionLinked;
 if(id==="pc"){
  // The OFF light requires a separately verified user pause. Mere absence
  // of a heartbeat or an unenrolled device is never a red OFF selection.
  element.dataset.pcPaused="false";
 }
 const display=value==="on"?"ON":value==="off"?"OFF":message("확인 불가","Unavailable");
 const label=element.querySelector(".claw-connection-label");
 if(label)label.textContent=display;else element.textContent=display;
 element.dataset.connectionState=value;
 element.setAttribute("aria-label",(id==="pc"?message("컴퓨터","Computer"):id==="drive"?"Google Drive":"GitHub")+" "+display);
 cardTruth(id,value);
}
const reset=()=>{ids.forEach(id=>set(id,"unknown"));pcTruth("unknown",vocabStatus("checking","\uC5F0\uACB0 \uD655\uC778 \uD544\uC694"),"Connection needs checking");const gh=chip("github");if(gh)delete gh.dataset.connectionLinked;};
const guestHint=()=>{
 if(!home()||signedIn())return;
 pcTruth("login_required","\uB85C\uADF8\uC778\uD558\uC138\uC694","Sign in first");
 ["drive","github"].forEach(id=>{const el=cardStatus[id];if(el)el.textContent=message("\uB85C\uADF8\uC778\uD558\uC138\uC694","Sign in first");});
};
const feedback=(ko,en)=>{const el=document.getElementById("clawConnectionFeedback");if(!el)return;el.textContent=message(ko,en);el.hidden=false;};
async function read(url){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),STATUS_READ_TIMEOUT_MS);
 try{
  const r=await fetch(url,{method:"GET",credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"},signal:controller.signal});
  if(!r.ok){const error=Error("no authority");error.sessionDenied=r.status===401||r.status===403;throw error;}
  const s=await r.text();if(controller.signal.aborted)throw Error("read expired");
  if(s.length>32768)throw Error("oversized");return JSON.parse(s);
 }finally{clearTimeout(timer);}
}
function checking(id){
 if(!confirmed.has(id)){set(id,"unknown");return;}
 // Previous text is presentation only. A stale ON/OFF never chooses a
 // disconnect/pause action while the current canonical read is pending.
 values.set(id,"unknown");
 const element=chip(id);if(element){element.dataset.connectionState="unknown";element.dataset.connectionStale="true";}
 if(id==="pc"&&element)element.dataset.pcPaused="false";
 if(id==="github"&&element)delete element.dataset.connectionLinked;
 const copy=window.__padiemLocale?.text?.("connection-previous-checking");
 if(cardStatus[id])cardStatus[id].textContent=copy&&copy!=="connection-previous-checking"?copy:message("이전 상태 · 다시 확인 중","Previous status · checking again");
}
async function refresh({force=false}={}){
 if(!home()||!signedIn()){reset();guestHint();return;}
 if(refreshInFlight&&!force)return refreshInFlight;
 const current=generation, sequence=++refreshSequence;
 ids.forEach(checking);
 const paint=(index,value)=>{
 if(current!==generation||sequence!==refreshSequence||!home()||!signedIn())return;
 const result=[{status:"pending"},{status:"pending"},{status:"pending"}];
 result[index]={status:"fulfilled",value};
 if(result[0].status==="fulfilled"){
  const d=result[0].value;
  if(d?.ok===true&&d.available===true&&d.ownerScoped===true&&Array.isArray(d.devices)&&d.devices.length<=25){
   if(d.usagePaused===true&&d.devices.length){
    // The canonical Broker persisted the owner OFF choice and blocks
    // command enqueue/poll/admission; an offline heartbeat cannot fake it.
    set("pc","off");
    chip("pc").dataset.pcPaused="true";
    pcTruth("paused",vocabStatus("disconnected","\uC5F0\uACB0 \uAEBC\uC9D0"),"Connection off");
   }else if(!d.devices.length){
    set("pc","off");
    pcTruth("unregistered",vocabStatus("disconnected","C5F0-ACB0-D558-C138-C694"),vocabStatus("disconnected","Connect your computer"));
   }else{
    const records=d.devices.map(x=>x?.projection&&typeof x.projection==="object"?x.projection:x);
    if(records.some(x=>x?.state==="CONNECTED"&&x.usable===true&&x.revoked!==true&&x.expired!==true)){
     set("pc","on");
     pcTruth("online",vocabStatus("connected","C5F0-ACB0-B418-C5C8-C2B5-B2C8-B2E4"),vocabStatus("connected","Connected"));
    }else if(records.every(x=>x&&["PAIRING","OFFLINE","REVOKED","ACTION_REQUIRED"].includes(x.state))){
     // One generic line cannot help anyone: a revoked binding, an expired
     // credential, a PC that is simply offline and a Mesh target whose online
     // state was never observed are four different problems with four
     // different fixes. The server already distinguishes them, so the card
     // names the real one.
     set("pc","off");
     if(records.every(x=>x?.revoked===true)){
      pcTruth("revoked","연결이 철회되었습니다 · 다시 연결해 주세요","Connection revoked · reconnect needed");
     }else if(records.every(x=>x?.expired===true)){
      pcTruth("expired","인증이 만료되었습니다 · 다시 연결해 주세요","Credential expired · reconnect needed");
     }else if(records.every(x=>x?.state==="ACTION_REQUIRED")){
      pcTruth("executable","실행 대상 준비 · 온라인 상태 미확인","Execution target ready · online status unverified");
     }else{
      pcTruth("offline","\uC5F0\uACB0 \uD655\uC778 \uD544\uC694","Connection needs checking");
     }
    }
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
  if(github?.ok===true&&["on","off"].includes(github.state)){
   set("github",github.state);
   const gh=chip("github");if(gh)gh.dataset.connectionLinked=github.linked===true?"true":"false";
  }
 }
 };
 // Fast cards paint as soon as their own read finishes. One slow connector
 // cannot hold the PC or Drive card, and focus events share the current read.
 const reads=["/api/claw/local-access/devices","/api/connectors/status","/api/connectors/github/status"];
 const pending=Promise.allSettled(reads.map((url,index)=>read(url).then(value=>paint(index,value)).catch(error=>{
  if(current!==generation||sequence!==refreshSequence)return;
  const id=ids[index];
  if(error.sessionDenied)set(id,"unknown");
  else if(confirmed.has(id)){
   const copy=window.__padiemLocale?.text?.("connection-previous-stale");
   if(cardStatus[id])cardStatus[id].textContent=copy&&copy!=="connection-previous-stale"?copy:message("이전 상태 · 새로고침 필요","Previous status · refresh needed");
  }
 })));
 refreshInFlight=pending;
 try{await pending;}finally{if(refreshInFlight===pending)refreshInFlight=null;}
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
  await refresh({force:true}); // Only canonical GET may change the visible ON/OFF state.
  feedback("구글 드라이브 연결을 해제했습니다.","Google Drive was disconnected.");
 }catch(_error){
  await refresh({force:true});
  feedback("구글 드라이브 연결 해제에 실패했습니다. 연결 상태를 다시 확인해 주세요.",
    "Drive disconnect failed. Please check the connection status.");
 }finally{
  pendingDisconnect.delete("drive");
  if(button)button.disabled=false;
 }
}
async function setGithubUsage(enabled){
 if(pendingDisconnect.has("github"))return;
 pendingDisconnect.add("github");
 const button=chip("github");if(button)button.disabled=true;
 try{
  const response=await fetch(enabled?"/api/connectors/github/resume":"/api/connectors/github/pause",{
   method:"POST",credentials:"same-origin",cache:"no-store",
   headers:{Accept:"application/json","Content-Type":"application/json"}
  });
  const payload=await response.json();
  if(!response.ok||payload?.ok!==true||payload.state!==(enabled?"on":"off"))throw Error("github state not verified");
  await refresh({force:true});
  feedback(enabled?"GitHub 사용을 다시 시작했습니다.":"GitHub 사용을 일시 중지했습니다.",
           enabled?"GitHub resumed.":"GitHub paused.");
 }catch(_error){
  await refresh({force:true});
  feedback("GitHub 연결 해제에 실패했습니다. 연결 상태를 다시 확인해 주세요.","GitHub state change failed. Please check connection status.");
 }finally{
  pendingDisconnect.delete("github");if(button)button.disabled=false;
 }
}
async function setPcUsage(paused){
 if(pendingDisconnect.has("pc"))return;
 pendingDisconnect.add("pc");
 const button=chip("pc");
 if(button)button.disabled=true;
 pcTruth(paused?"stopping":"connecting",
   paused?"\uC5F0\uACB0 \uC911\uC9C0 \uC911...":"\uC5F0\uACB0 \uC911...",
   paused?"Stopping PC tasks...":"Resuming PC tasks...");
 try{
  const response=await fetch(paused?"/api/claw/local-access/devices/pause":
    "/api/claw/local-access/devices/resume",{
    method:"POST",mode:"same-origin",credentials:"same-origin",
    cache:"no-store",headers:{Accept:"application/json"}
  });
  if(!response.ok)throw Error("pc_usage_write_denied");
  const raw=await response.text();
  if(raw.length>4096)throw Error("pc_usage_oversize");
  const receipt=JSON.parse(raw);
  if(receipt?.ok!==true||receipt.usagePaused!==paused)
    throw Error("pc_usage_unverified");
  await refresh({force:true}); // Only the canonical Broker readback can illuminate OFF.
  if(chip("pc")?.dataset.pcPaused!==(paused?"true":"false"))
    throw Error("pc_usage_readback_mismatch");
  if(!paused&&values.get("pc")!=="on")
    document.getElementById("clawComputerWorkspace")?.click();
 }catch(_error){
  await refresh({force:true});
  feedback("\uCEF4\uD4E8\uD130 \uC5F0\uACB0 \uC124\uC815\uC744 \uD655\uC778\uD558\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4. \uAE30\uC874 \uC0C1\uD0DC\uB97C \uC720\uC9C0\uD569\uB2C8\uB2E4.",
    "PC setting could not be verified. Previous state retained.");
 }finally{
  pendingDisconnect.delete("pc");
  if(button)button.disabled=false;
 }
}
ids.forEach(id=>chip(id)?.addEventListener("click",event=>{
 // One PC switch, two visible labels. Its activation MUST NOT bubble to
 // the enclosing card and accidentally reconnect immediately after OFF.
 if(id==="pc"){
  event.preventDefault();
  event.stopPropagation();
  if(!home())return;
  if(!signedIn()){
   // Reuse the primary PC card's canonical login gate (and its visible note).
   document.getElementById("clawComputerWorkspace")?.click();
   return;
  }
  const state=values.get("pc");
  const paused=chip("pc")?.dataset.pcPaused==="true";
  // Keyboard activation toggles the single control; pointer hit targets
  // the explicit ON or OFF half without creating a second control.
  const target=event.detail===0?(paused?"on":state==="on"?"off":"on"):
    event.target?.closest?.(".claw-state-off")?"off":"on";
  if(target==="off"){
   if(!paused)void setPcUsage(true);
   return;
  }
  if(paused){void setPcUsage(false);return;}
  if(state==="on")return;
  pcTruth("connecting","\uC5F0\uACB0 \uC911...","Connecting...");
  document.getElementById("clawComputerWorkspace")?.click();
  return;
 }

 if(!home())return;
 const state=values.get(id);
 if(state==="on"&&id==="drive"){
  // OFF is a temporary pause, not credential revocation. The Google authority
  // has no reversible pause operation yet; never silently delete its grant.
  feedback("Google 권한은 잠시 멈출 수 없어요. 완전히 끊으려면 Google 계정 > 보안 > 타사 앱에서 해제하세요.",
    "Google permissions cannot be paused. To revoke them, open Google Account > Security > third-party apps.");
  const feedbackEl=document.getElementById("clawConnectionFeedback");
  if(feedbackEl){
   const revokeLink=document.createElement("a");
   revokeLink.href="https://myaccount.google.com/connections";
   revokeLink.target="_blank";
   revokeLink.rel="noopener noreferrer";
   revokeLink.textContent=message("Google 계정 보안 설정 열기","Open Google Account security");
   feedbackEl.append(document.createTextNode(" "),revokeLink);
  }
  return;
 }
 if(state==="on"&&id==="github"){
  if(signedIn())void setGithubUsage(false);
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
  if(chip("github")?.dataset.connectionLinked==="true")void setGithubUsage(true);
  else window.location.assign("/api/connectors/github/start");
  return;
 }
 const target=id==="pc"?"clawComputerWorkspace":"clawDriveWorkspace";
 document.getElementById(target)?.click();
 if(state==="unknown")feedback("연결 상태를 확인할 수 없습니다. 연결 관리에서 확인해 주세요.",
    "Connection status is unavailable. Please check Connectors.");
}));
const invalidate=event=>{
 ++generation;++refreshSequence;refreshInFlight=null;reset();
 if(event?.detail?.authenticated===false){guestHint();return;}
 if(home()&&signedIn())void refresh();else guestHint();
};
const observer=new MutationObserver(invalidate);
observer.observe(shell,{attributes:true,attributeFilter:["data-state"]});
observer.observe(owner,{attributes:true,attributeFilter:["data-account-state"]});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&home())void refresh();});
window.addEventListener("focus",()=>{if(home())void refresh();});
for(const name of ["padiem:auth-state","padiem:auth-changed","padiem:account-changed"])window.addEventListener(name,invalidate);
if(home())void refresh();
})();
