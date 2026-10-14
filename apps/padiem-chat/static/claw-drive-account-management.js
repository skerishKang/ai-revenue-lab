/* CLAW Google Drive account removal lives in Connectors, never the ON/OFF switch. */
(() => {
  "use strict";
  const dialog = document.getElementById("connectorsDialog");
  const card = dialog?.querySelector('[data-connector-id="connector:google:drive@1"]');
  const remove = document.getElementById("connectorDriveRemove");
  const feedback = document.getElementById("connectorDriveFeedback");
  if (!dialog || !card || !remove || !feedback) return;
  const en=()=>document.documentElement.lang==="en";
  const tr=(ko,english)=>en()?english:ko;
  let pending=false;
  let confirmed=false;
  const show=(el,value)=>{el.hidden=!value;};
  const copy=(el,text)=>{el.textContent=text;};
  const connected=()=>card.dataset.connectorStatus==="connected";
  const render=()=>{
    show(remove,connected());
    remove.disabled=pending;
    if(!connected())confirmed=false;
    copy(remove,confirmed?tr("연결 삭제 확인","Confirm removal"):tr("연결 삭제","Remove connection"));
  };
  async function disconnect() {
    const response=await fetch("/api/connectors/google/drive/disconnect",{
      method:"POST",credentials:"same-origin",cache:"no-store",
      headers:{"Accept":"application/json"}
    });
    const body=await response.json().catch(()=>null);
    if(!response.ok||body?.ok!==true||body.state!=="off")throw Error("disconnect not verified");
  }
  remove.addEventListener("click",async()=>{
    if(pending||!connected())return;
    if(!confirmed){
      confirmed=true;
      copy(feedback,tr("연결 정보를 삭제하면 다음 사용 시 Google 로그인이 필요합니다. 한 번 더 누르면 삭제합니다.",
                       "Removing authorization requires signing in again. Click again to confirm."));
      show(feedback,true);
      render();
      return;
    }
    pending=true;render();
    try{
      await disconnect();
      confirmed=false;
      document.dispatchEvent(new Event("padiem:refresh-connector-status"));
      window.dispatchEvent(new Event("focus"));
      copy(feedback,tr("계정 연결을 삭제했습니다. 드라이브의 파일은 그대로 유지됩니다.",
                       "Connection removed. Your Drive files were not deleted."));
      show(feedback,true);
    }catch(_){
      copy(feedback,tr("연결 삭제에 실패했습니다. 상태를 다시 확인해 주세요.",
                       "Could not remove the connection. Check its status."));
      show(feedback,true);
    }finally{pending=false;confirmed=false;render();}
  });
  new MutationObserver(render).observe(card,{attributes:true,attributeFilter:["data-connector-status"]});
  dialog.addEventListener("close",()=>{confirmed=false;show(feedback,false);render();});
  render();
})();
