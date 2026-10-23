/* Claw connection state: the server alone is authoritative. */
(()=>{
"use strict";
const shell=document.querySelector(".app-shell"), owner=document.querySelector(".sidebar-account");
if(!shell||!owner)return;
const ids=["pc","drive","github"], values=new Map(ids.map(x=>[x,"unknown"]));
let generation=0;
const pendingDisconnect=new Set();
const locale=()=>window.__padiemLocale?.getCurrent?.()||document.documentElement.lang||"ko";
// #4807: ja/zh fall back to Korean, the same canonical source the locale packs use.
const message=(ko,en,ja,zh)=>{const l=locale();return l==="en"?en:l==="ja"?(ja??ko):l==="zh-CN"?(zh??ko):ko;};
const home=()=>shell.dataset.state==="claw"&&document.getElementById("clawWorkspace")?.dataset.view==="general";
const signedIn=()=>owner.dataset.accountState==="signed_in";
const chip=id=>document.querySelector('[data-claw-connection="'+id+'"]');
// PC's headline is separate from its single two-position switch. Neither
// installation nor user OFF is inferred from a missing GET/heartbeat.
const pcCard=document.querySelector('[data-claw-card="computer"]');
const pcStatus=document.getElementById("clawPcCardStatus");
const PHASE_COPY={
 unknown:["연결 확인 필요","Connection needs checking","接続を確認してください","需要确认连接"],
 login_required:["로그인하세요","Sign in first","ログインしてください","请先登录"],
 paused:["연결 꺼짐","Connection off","接続を停止しました","连接已暂停"],
 unregistered:["연결하세요","Connect your computer","コンピューターを接続","请连接电脑"],
 online:["연결되었습니다","Connected","接続済みです","已连接"],
 revoked:["연결이 철회되었습니다 · 다시 연결해 주세요","Connection revoked · reconnect needed","接続が取り消されました · 再接続が必要です","连接已被撤销 · 需要重新连接"],
 expired:["인증이 만료되었습니다 · 다시 연결해 주세요","Credential expired · reconnect needed","認証の有効期限が切れました · 再接続が必要です","凭据已过期 · 需要重新连接"],
 executable:["실행 대상 준비 · 온라인 상태 미확인","Execution target ready · online status unverified","実行対象は準備完了 · オンライン状態は未確認","执行目标已就绪 · 在线状态未确认"],
 offline:["연결 확인 필요","Connection needs checking","接続を確認してください","需要确认连接"],
 stopping:["연결 중지 중...","Stopping PC tasks...","PCタスクを停止しています…","正在停止电脑任务..."],
 resuming:["연결 중...","Resuming PC tasks...","PCタスクを再開しています…","正在恢复电脑任务..."],
 connecting:["연결 중...","Connecting...","接続中…","连接中…"],
};
const pcTruth=(phase)=>{
 if(!pcCard||!pcStatus)return;
 pcCard.dataset.pcPhase=phase;
 const copy=PHASE_COPY[phase];
 if(copy)pcStatus.textContent=message(...copy);
};
// Every connector card carries its truthful headline in the card's top-right
// corner, exactly like the PC card. The bottom-right keeps only the ON/OFF
// switch, so Drive/GitHub no longer stretch an "확인 불가" label under it.
const cardStatus={pc:pcStatus,drive:document.getElementById("clawDriveCardStatus"),github:document.getElementById("clawGithubCardStatus")};
const cardEl=id=>document.querySelector('[data-claw-card="'+(id==="pc"?"computer":id)+'"]');
const truthText=value=>value==="on"?message("연결되었습니다","Connected","接続済みです","已连接"):value==="off"?message("연결 끔","Off","OFF","已断开"):message("연결 확인 필요","Connection needs checking","接続を確認してください","需要确认连接");
const cardTruth=(id,value)=>{
 const card=cardEl(id);if(card)card.dataset.connectionPhase=value;
 const el=cardStatus[id];if(el)el.textContent=truthText(value);
};

function set(id,value){
 if(!["on","off","unknown"].includes(value))value="unknown";
 values.set(id,value);
 const element=chip(id);if(!element)return;
 if(id==="pc"){
  // The OFF light requires a separately verified user pause. Mere absence
  // of a heartbeat or an unenrolled device is never a red OFF selection.
  element.dataset.pcPaused="false";
 }
 const display=value==="on"?"ON":value==="off"?"OFF":message("확인 불가","Unavailable","確認できません","无法确认");
 const label=element.querySelector(".claw-connection-label");
 if(label)label.textContent=display;else element.textContent=display;
 element.dataset.connectionState=value;
 element.setAttribute("aria-label",(id==="pc"?message("컴퓨터","Computer","コンピューター","电脑"):id==="drive"?"Google Drive":"GitHub")+" "+display);
 cardTruth(id,value);
}
const reset=()=>{ids.forEach(id=>set(id,"unknown"));pcTruth("unknown");const gh=chip("github");if(gh)delete gh.dataset.connectionLinked;};
const guestHint=()=>{
 if(!home()||signedIn())return;
 pcTruth("login_required");
 ["drive","github"].forEach(id=>{const el=cardStatus[id];if(el)el.textContent=message("로그인하세요","Sign in first","ログインしてください","请先登录");});
};
const feedback=(ko,en,ja,zh)=>{const el=document.getElementById("clawConnectionFeedback");if(!el)return;el.textContent=message(ko,en,ja,zh);el.hidden=false;};
async function read(url){
 const r=await fetch(url,{method:"GET",credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
 if(!r.ok)throw Error("no authority");
 const s=await r.text();if(s.length>32768)throw Error("oversized");return JSON.parse(s);
}
async function refresh(){
 const current=++generation;if(!home()||!signedIn()){reset();guestHint();return;}
 const result=await Promise.allSettled([read("/api/claw/local-access/devices"),read("/api/connectors/status"),read("/api/connectors/github/status")]);
 if(current!==generation||!home()||!signedIn())return;
 reset();
 if(result[0].status==="fulfilled"){
  const d=result[0].value;
  if(d?.ok===true&&d.available===true&&d.ownerScoped===true&&Array.isArray(d.devices)&&d.devices.length<=25){
   if(d.usagePaused===true&&d.devices.length){
    // The canonical Broker persisted the owner OFF choice and blocks
    // command enqueue/poll/admission; an offline heartbeat cannot fake it.
    set("pc","off");
    chip("pc").dataset.pcPaused="true";
    pcTruth("paused");
   }else if(!d.devices.length){
    set("pc","off");
    pcTruth("unregistered");
   }else{
    const records=d.devices.map(x=>x?.projection&&typeof x.projection==="object"?x.projection:x);
    if(records.some(x=>x?.state==="CONNECTED"&&x.usable===true&&x.revoked!==true&&x.expired!==true)){
     set("pc","on");
     pcTruth("online");
    }else if(records.every(x=>x&&["PAIRING","OFFLINE","REVOKED","ACTION_REQUIRED"].includes(x.state))){
     // One generic line cannot help anyone: a revoked binding, an expired
     // credential, a PC that is simply offline and a Mesh target whose online
     // state was never observed are four different problems with four
     // different fixes. The server already distinguishes them, so the card
     // names the real one.
     set("pc","off");
     if(records.every(x=>x?.revoked===true)){
      pcTruth("revoked");
     }else if(records.every(x=>x?.expired===true)){
      pcTruth("expired");
     }else if(records.every(x=>x?.state==="ACTION_REQUIRED")){
      pcTruth("executable");
     }else{
      pcTruth("offline");
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
  await refresh();
  feedback(enabled?"GitHub 사용을 다시 시작했습니다.":"GitHub 사용을 일시 중지했습니다.",
           enabled?"GitHub resumed.":"GitHub paused.",
           enabled?"GitHubの利用を再開しました。":"GitHubの利用を一時停止しました。",
           enabled?"已恢复使用 GitHub。":"已暂停使用 GitHub。");
 }catch(_error){
  await refresh();
  feedback("GitHub 연결 해제에 실패했습니다. 연결 상태를 다시 확인해 주세요.","GitHub state change failed. Please check connection status.","GitHubの状態変更に失敗しました。接続状態をもう一度確認してください。","GitHub 状态更改失败。请重新检查连接状态。");
 }finally{
  pendingDisconnect.delete("github");if(button)button.disabled=false;
 }
}
async function setPcUsage(paused){
 if(pendingDisconnect.has("pc"))return;
 pendingDisconnect.add("pc");
 const button=chip("pc");
 if(button)button.disabled=true;
 pcTruth(paused?"stopping":"resuming");
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
  await refresh(); // Only the canonical Broker readback can illuminate OFF.
  if(chip("pc")?.dataset.pcPaused!==(paused?"true":"false"))
    throw Error("pc_usage_readback_mismatch");
  if(!paused&&values.get("pc")!=="on")
    document.getElementById("clawComputerWorkspace")?.click();
 }catch(_error){
  await refresh();
  feedback("컴퓨터 연결 설정을 확인하지 못했습니다. 기존 상태를 유지합니다.",
    "PC setting could not be verified. Previous state retained.",
    "PCの設定を確認できませんでした。以前の状態を維持します。",
    "无法确认电脑设置。已保留之前的状态。");
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
  pcTruth("connecting");
  document.getElementById("clawComputerWorkspace")?.click();
  return;
 }

 if(!home())return;
 const state=values.get(id);
 if(state==="on"&&id==="drive"){
  // OFF is a temporary pause, not credential revocation. The Google authority
  // has no reversible pause operation yet; never silently delete its grant.
  feedback("Google Drive 일시 중지는 아직 준비 중입니다. 연결 삭제는 커넥터 관리에서 선택해 주세요.",
    "Google Drive pause is not available yet. Remove authorization in Connectors.",
    "Google Driveの一時停止はまだ利用できません。認証の削除は Connectors で選択してください。",
    "Google Drive 暂不支持暂停。请在 Connectors 中移除授权。");
  return;
 }
 if(state==="on"&&id==="github"){
  if(signedIn())void setGithubUsage(false);
  else feedback("연결하려면 로그인해 주세요.","Sign in to manage connections.","接続を管理するにはログインしてください。","请登录以管理连接。");
  return;
 }
 if(state==="on"){
  // PC currently lacks a reviewed disconnect endpoint.
  feedback("안전한 연결 해제 기능이 아직 제공되지 않습니다. 연결은 유지됩니다.",
    "A reviewed disconnect action is not available yet. The connection stays ON.",
    "安全な切断機能はまだありません。接続は維持されます。",
    "尚无安全的断开功能。连接将保持。");
  return;
 }
 if(!signedIn()){
  const login=document.getElementById("loginButton");
  if(login&&!login.hidden&&login.textContent?.trim())login.click();
  feedback("연결하려면 로그인해 주세요.","Sign in to connect.","接続するにはログインしてください。","请登录后连接。");
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
    "Connection status is unavailable. Please check Connectors.",
    "接続状態を確認できません。Connectors で確認してください。",
    "无法确认连接状态。请在 Connectors 中查看。");
}));
const observer=new MutationObserver(()=>{++generation;reset();if(home()&&signedIn())void refresh();else guestHint();});
observer.observe(shell,{attributes:true,attributeFilter:["data-state"]});
observer.observe(owner,{attributes:true,attributeFilter:["data-account-state"]});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&home())void refresh();});
window.addEventListener("focus",()=>{if(home())void refresh();});
// #4807: a locale switch repaints the stored states in place. It never
// triggers a server read; the next refresh keeps its usual authority.
window.addEventListener("padiem:localechange",()=>{
 ids.forEach(id=>set(id,values.get(id)));
 const phase=pcCard?.dataset.pcPhase;
 if(phase&&PHASE_COPY[phase])pcTruth(phase);
 if(!home()||!signedIn())guestHint();
});
if(home())void refresh();
})();