(function(root){
  'use strict';
  const doc=root.document, byId=id=>doc.getElementById(id);
  const entry=byId('bookaiDeleteEntry'), dialog=byId('bookaiDeleteDialog');
  if(!entry||!dialog)return;
  const locale=byId('bookaiDeleteLanguage'), confirm=byId('bookaiDeleteConfirm');
  const submit=byId('bookaiDeleteSubmit'), cancel=byId('bookaiDeleteCancel'), status=byId('bookaiDeleteStatus');
  const accountMenu=doc.createElement('button');
  accountMenu.id='bookaiAccountMenu';accountMenu.type='button';
  accountMenu.setAttribute('aria-haspopup','dialog');
  accountMenu.setAttribute('aria-controls','authGateSheet');
  byId('libOverflowMenu')?.prepend(accountMenu);
  let returnFocus=byId('todayCloudButton');
  accountMenu.addEventListener('click',()=>{
    byId('libOverflowMenu')?.classList.remove('open');
    byId('libOverflow')?.setAttribute('aria-expanded','false');
    returnFocus=byId('libOverflow');root.openStoryMemoryAuth();
  });
  byId('todayCloudButton')?.addEventListener('click',()=>{returnFocus=byId('todayCloudButton');});
  const copy={
    ko:{account:'계정',entry:'탈퇴',title:'모든 서비스에서 탈퇴',language:'언어',
      scope:'이 파디엠 계정과 연결된 모든 서비스의 계정과 데이터가 삭제됩니다. 북AI 읽기 기록·메모·하이라이트·대화와 이 계정에 연결된 현재 기기의 기록도 삭제됩니다.',
      warning:'삭제한 데이터는 복구할 수 없습니다. 필요한 기록은 먼저 계정 메뉴에서 백업해 주세요.',
      confirm:'삭제 대상을 확인했으며 모든 서비스에서 탈퇴합니다.',submit:'모두 삭제하고 탈퇴',cancel:'취소',
      busy:'계정과 데이터를 삭제하고 있습니다. 잠시 기다려 주세요.',
      unavailable:'지금은 탈퇴를 완료할 수 없습니다. 이 화면에서는 기기 기록을 삭제하지 않았습니다. 잠시 후 다시 시도해 주세요.',
      auth:'로그인 상태를 확인할 수 없습니다. 계정 메뉴에서 로그인 상태를 확인한 뒤 다시 시도해 주세요.',
      admin:'관리자 권한이 있는 계정은 이 화면에서 탈퇴할 수 없습니다. 계정과 기록은 유지됩니다.',
      done:'탈퇴가 완료되었습니다. 계정에 연결된 이 기기의 기록도 정리했습니다.',
      pending:'서비스 데이터 삭제를 완료했습니다. 남은 계정 정리는 자동으로 다시 시도합니다.',
      local:'서버 데이터 삭제를 완료했습니다. 이 기기 기록 정리를 다시 시도해 주세요.',retry:'기기 기록 정리 다시 시도',continue:'처음 화면으로'},
    en:{account:'Account',entry:'Delete account',title:'Delete account from all services',language:'Language',
      scope:'Your account and data across all services linked to this PADIEM account will be deleted. This includes BookAI reading history, notes, highlights, conversations, and records on this device linked to the account.',
      warning:'Deleted data cannot be recovered. Back up any records you need from the account menu first.',
      confirm:'I understand what will be deleted and want to leave all services.',submit:'Delete all and leave',cancel:'Cancel',
      busy:'Deleting your account and data. Please wait.',
      unavailable:'Account deletion could not be completed now. This screen has not deleted device records. Please try again later.',
      auth:'Your login could not be verified. Check your login in the account menu and try again.',
      admin:'Accounts with administrator access cannot be deleted from this screen. Your account and records are unchanged.',
      done:'Your account has been deleted. Linked records on this device have also been cleared.',
      pending:'Service data has been deleted. Remaining account cleanup will retry automatically.',
      local:'Server data has been deleted. Please retry clearing records on this device.',retry:'Retry device cleanup',continue:'Return to start'}
  };
  let language=new URLSearchParams(root.location.search).get('lang')||doc.documentElement.lang;
  language=language==='en'?'en':'ko';
  let busy=false, deleted=false, finished=false, notice='', account=null, cleanupComplete=true;
  function render(){
    const t=copy[language];dialog.lang=language;locale.value=language;
    accountMenu.textContent=t.account;
    entry.textContent=t.entry;entry.hidden=!root.BookAISession?.isAuthenticated();
    for(const [id,key] of [['Title','title'],['Scope','scope'],['Warning','warning'],['ConfirmText','confirm'],['LanguageLabel','language']])
      byId('bookaiDelete'+id).textContent=t[key];
    status.textContent=t[notice]||'';
    submit.textContent=t[deleted?'retry':'submit'];
    submit.disabled=busy||(!deleted&&!confirm.checked);submit.hidden=finished;
    cancel.textContent=t[finished?'continue':'cancel'];cancel.disabled=busy||deleted&&!finished;
    confirm.disabled=busy||deleted;locale.disabled=busy;
    byId('bookaiDeleteConfirmation').hidden=deleted;
    dialog.setAttribute('aria-busy',String(busy));
  }
  function open(){
    if(!root.BookAISession?.isAuthenticated())return;
    account=root.BookAISession.getAccountId();confirm.checked=false;notice='';deleted=false;finished=false;
    doc.body.classList.remove('auth-gate-open');byId('authGateSheet')?.setAttribute('aria-hidden','true');
    render();dialog.showModal();cancel.focus();
  }
  async function finish(){
    try{
      await root.BookAILocalDB.clearDeletedAccount(account);
      if(root.BookAISession.getAccountId()===account)root.BookAISession.deleted();
      finished=true;notice=cleanupComplete?'done':'pending';
    }catch{notice='local';}
  }
  async function remove(){
    if(busy||(!deleted&&!confirm.checked))return;
    busy=true;notice='busy';render();
    try{
      await root.BookAIReady;
      await root.BookAISync.pause();
      if(!deleted){
        if(account!==root.BookAISession.getAccountId())throw Error('not_authenticated');
        const response=await fetch('/api/bookai/account/shared-delete',{method:'POST',credentials:'same-origin',
          cache:'no-store',headers:{'content-type':'application/json'},body:JSON.stringify({confirm:true,account_id:account})});
        if(!response.ok){
          if(response.status===403){
            const error=await response.json().catch(()=>null);
            if(error?.error==='account_delete_admin_blocked')throw Error('admin');
          }
          throw Error([401,403].includes(response.status)?'not_authenticated':'unavailable');
        }
        const data=await response.json();
        if(data.ok!==true||data.common_account_deleted!==true||typeof data.cleanup?.complete!=='boolean')throw Error('unavailable');
        deleted=true;cleanupComplete=data.cleanup.complete;
      }
      await finish();
    }catch(error){
      notice=error.message==='admin'?'admin':error.message==='not_authenticated'?'auth':'unavailable';
      if(!deleted)root.BookAISync?.resume();
    }finally{busy=false;render();if(finished)cancel.focus();}
  }
  entry.addEventListener('click',open);
  submit.addEventListener('click',remove);
  confirm.addEventListener('change',render);
  locale.addEventListener('change',()=>{language=locale.value==='en'?'en':'ko';render();});
  cancel.addEventListener('click',()=>{if(finished)root.location.reload();else if(!busy&&!deleted)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy||deleted)event.preventDefault();});
  dialog.addEventListener('close',()=>{if(!deleted)returnFocus?.focus();});
  root.addEventListener('bookai-session',render);
  render();
})(window);
