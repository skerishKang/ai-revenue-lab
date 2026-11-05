/* Prepare IndexedDB before any of the legacy reader's synchronous startup code.
   One bad script must never hold the first screen hostage: every script is
   isolated, the gate is always removed, and the whole boot is capped at 15s. */
(function () {
  'use strict';
  const BOOT_TIMEOUT_MS = 15000;
  const gate=document.createElement('div');
  gate.id='bookai-startup';
  gate.setAttribute('role','status');
  gate.style.cssText='position:fixed;inset:0;z-index:99999;display:grid;place-content:center;background:var(--bg,#faf8f4);color:var(--text,#282622);font:16px system-ui;text-align:center;padding:24px';
  gate.textContent='책과 기록을 열고 있습니다.';
  document.body.append(gate);
  document.body.setAttribute('aria-busy','true');
  let finished=false;
  let deadlineTimer=null;
  function storageStatus(event) {
    const el=document.getElementById('todayDataStatus');
    if(el){el.classList.toggle('saving',!!event.detail.pending);el.textContent=event.detail.error?'기록을 저장하지 못했습니다. 이 화면을 닫지 마세요.':event.detail.pending?'기기에 저장 중':'기기에 저장됨';el.classList.toggle('error',!!event.detail.error);}
  }
  window.addEventListener('bookai-storage-status',storageStatus);
  function toast(message){
    const el=document.createElement('div');
    el.id='bookai-boot-toast';
    el.setAttribute('role','status');
    el.textContent=message;
    el.style.cssText='position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:100000;background:#282622;color:#fff;padding:10px 16px;border-radius:10px;font:14px system-ui;box-shadow:0 4px 16px rgba(0,0,0,.25);max-width:calc(100vw - 32px);text-align:center';
    document.body.append(el);
    setTimeout(()=>el.remove(),8000);
  }
  function finish(reason){
    if(finished)return;
    finished=true;
    clearTimeout(deadlineTimer);
    const current=document.getElementById('bookai-startup');
    if(current)current.remove();
    document.body.removeAttribute('aria-busy');
    if(reason==='timeout')toast('일부 기능을 불러오지 못했어요');
    window.dispatchEvent(new Event('bookai-ready'));
  }
  function scriptName(script){
    return script.getAttribute('src')||'inline';
  }
  async function runScript(old) {
    const script=document.createElement('script');
    for(const attr of old.attributes)if(!['type','data-bookai-script'].includes(attr.name))script.setAttribute(attr.name,attr.value);
    script.async=false;
    if(script.src)await new Promise((resolve,reject)=>{
      script.onload=resolve;
      script.onerror=()=>reject(new Error('reader_script_unavailable'));
      old.replaceWith(script);
    });
    else{script.textContent=old.textContent;old.replaceWith(script);}
  }
  window.BookAIReady=(async()=>{
    deadlineTimer=setTimeout(()=>finish('timeout'),BOOT_TIMEOUT_MS);
    try{
      try{await BookAILocalDB.init();}
      catch(error){console.error('bookai_storage_failed',error&&error.message||error);}
      for(const script of [...document.querySelectorAll('script[data-bookai-script]')]){
        if(finished)break;
        try{await runScript(script);}
        catch(error){console.error('bookai_script_failed',scriptName(script),error&&error.message||error);}
      }
      if(!finished){
        try{await BookAILocalDB.flush();}
        catch(error){console.error('bookai_storage_flush_failed',error&&error.message||error);}
      }
      finish('ready');
    }catch(error){
      console.error('bookai_boot_failed',error&&error.message||error);
      finish('error');
    }
    return true;
  })();
})();
