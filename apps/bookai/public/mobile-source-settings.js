(function(){
'use strict';
function init(){
 const reader=document.querySelector('#reader'),host=document.getElementById('sourceTrustControl');
 if(!reader||!host||!window.HTMLDialogElement)return;
 const ids=['packMarketplaceLaunch','packMarketplacePanel','autoPackLaunch','autoPackPanel','packEntitlementLaunch','packEntitlementPanel','packVerificationLaunch','packVerificationPanel'];
 const items=ids.map(id=>document.getElementById(id));
 if(items.some(x=>!x))return;
 const trigger=document.createElement('button');trigger.type='button';trigger.className='mobile-source-settings-trigger';trigger.textContent='지식 팩 및 추가 설정';trigger.setAttribute('aria-haspopup','dialog');
 const dialog=document.createElement('dialog');dialog.className='mobile-source-settings';dialog.setAttribute('aria-labelledby','mobileSourceSettingsTitle');
 const header=document.createElement('header');header.className='mobile-source-settings-header';
 const title=document.createElement('h2');title.id='mobileSourceSettingsTitle';title.textContent='지식 팩 및 추가 설정';
 const close=document.createElement('button');close.type='button';close.textContent='닫기';close.setAttribute('aria-label','추가 설정 닫기');
 header.append(title,close);const body=document.createElement('div');body.className='mobile-source-settings-body';dialog.append(header,body);reader.append(dialog);host.append(trigger);
 function restore(){items.forEach(item=>{if(item.tagName==='SECTION')item.hidden=true;host.insertBefore(item,trigger)});trigger.focus()}
 trigger.addEventListener('click',()=>{items.forEach(item=>body.append(item));dialog.showModal();close.focus()});
 close.addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',restore);
 window.matchMedia('(max-width: 767px)').addEventListener('change',e=>{if(!e.matches&&dialog.open)dialog.close()});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
