/* Prepare IndexedDB before any of the legacy reader's synchronous startup code. */
(function () {
  'use strict';
  const gate=document.createElement('div');
  gate.id='bookai-startup';
  gate.setAttribute('role','status');
  gate.style.cssText='position:fixed;inset:0;z-index:99999;display:grid;place-content:center;background:var(--bg,#faf8f4);color:var(--text,#282622);font:16px system-ui;text-align:center;padding:24px';
  gate.textContent='책과 기록을 열고 있습니다.';
  document.body.append(gate);
  document.body.setAttribute('aria-busy','true');
  function storageStatus(event) {
    const el=document.getElementById('todayDataStatus');
    if(el){el.classList.toggle('saving',!!event.detail.pending);el.textContent=event.detail.error?'기록을 저장하지 못했습니다. 이 화면을 닫지 마세요.':event.detail.pending?'기기에 저장 중':'기기에 저장됨';el.classList.toggle('error',!!event.detail.error);}
  }
  window.addEventListener('bookai-storage-status',storageStatus);
  async function runScript(old) {
    const script=document.createElement('script');
    for(const attr of old.attributes)if(!['type','data-bookai-script'].includes(attr.name))script.setAttribute(attr.name,attr.value);
    script.async=false;
    if(script.src)await new Promise((resolve,reject)=>{
      script.onload=resolve;script.onerror=()=>reject(new Error('reader_script_unavailable'));
      old.replaceWith(script);
    });
    else{script.textContent=old.textContent;old.replaceWith(script);}
  }
  window.BookAIReady=(async()=>{
    await BookAILocalDB.init();
    for(const script of [...document.querySelectorAll('script[data-bookai-script]')])await runScript(script);
    await BookAILocalDB.flush();
    gate.remove();document.body.removeAttribute('aria-busy');
    window.dispatchEvent(new Event('bookai-ready'));
    return true;
  })();
  window.BookAIReady.catch(()=>{
    gate.textContent='기록을 열지 못했습니다. 기존 기록은 보관되어 있습니다. 다른 북AI 창을 닫고 새로고침해 주세요.';
    document.body.removeAttribute('aria-busy');
  });
})();
