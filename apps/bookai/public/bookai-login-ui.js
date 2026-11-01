(function(){
  'use strict';
  const primary=document.getElementById('authGatePrimary');
  const secondary=document.getElementById('authGateSecondary');
  const label=document.getElementById('todayCloudLabel');
  const state=document.getElementById('authGateState');
  const copy=document.getElementById('authGateCopy');
  if(!primary||!secondary||!state||!copy)return;
  let authenticated=false,accountId=null;
  function show(){
    if(label)label.textContent=authenticated?'로그인됨':'기기 저장';
    primary.textContent=authenticated?'로그아웃':'파디엠으로 로그인';
    secondary.textContent='닫기';
    const bold=state.querySelector('b'),detail=state.querySelector('span');
    if(bold)bold.textContent=authenticated?'PADIEM':'기기 저장';
    if(detail)detail.textContent=authenticated?'파디엠 계정으로 로그인됨':'로그인 없이 이 기기에서 읽을 수 있습니다.';
    copy.textContent=authenticated?'파디엠 계정으로 로그인했습니다.':'기록은 이 기기에 저장됩니다. 파디엠 계정으로 로그인할 수 있습니다.';
    primary.disabled=false;
  }
  async function refreshSession(){
    try {
      let response=await fetch('/auth/session',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw Error('session_unavailable');
      let data=await response.json();
      if(!data.authenticated){
        const refreshed=await fetch('/auth/refresh',{method:'POST',credentials:'same-origin'});
        if(refreshed.ok){response=await fetch('/auth/session',{credentials:'same-origin',cache:'no-store'});data=await response.json();}
      }
      authenticated=data.authenticated===true;
      accountId=authenticated&&/^sub_[A-Za-z0-9_-]+$/.test(data.account_id||'')?data.account_id:null;
    } catch(_){authenticated=false;accountId=null;}
    show();
    window.dispatchEvent(new CustomEvent('bookai-session',{detail:{authenticated,accountId}}));
    return authenticated;
  }
  primary.addEventListener('click',async event=>{
    event.stopImmediatePropagation();event.preventDefault();
    if(!authenticated){location.assign('/auth/login');return;}
    primary.disabled=true;
    try{
      const result=await fetch('/auth/logout',{method:'POST',credentials:'same-origin'});
      if(!result.ok)throw Error('logout_failed');
      authenticated=false;accountId=null;show();window.dispatchEvent(new CustomEvent('bookai-session',{detail:{authenticated:false,accountId:null}}));
    }catch(_){primary.disabled=false;copy.textContent='로그아웃하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.';}
  },true);
  secondary.addEventListener('click',event=>{
    event.stopImmediatePropagation();event.preventDefault();
    document.body.classList.remove('auth-gate-open');
    document.getElementById('authGateSheet')?.setAttribute('aria-hidden','true');
  },true);
  document.getElementById('todayCloudButton')?.addEventListener('click',()=>queueMicrotask(show));
  new MutationObserver(()=>{if(document.body.classList.contains('auth-gate-open'))show();}).observe(document.body,{attributes:true,attributeFilter:['class']});
  window.BookAISession=Object.freeze({refresh:refreshSession,isAuthenticated:()=>authenticated,getAccountId:()=>accountId});
  show();refreshSession();
})();
