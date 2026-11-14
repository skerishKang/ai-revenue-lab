import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../public/bookai-account-delete-ui.js',import.meta.url),'utf8');
const html=fs.readFileSync(new URL('../public/index.html',import.meta.url),'utf8');
class Element{
  constructor(){this.listeners=new Map();this.checked=false;this.textContent='';this.hidden=false;this.children=[];this.classList={remove(){}};}
  addEventListener(name,callback){this.listeners.set(name,callback);}
  async trigger(name){return this.listeners.get(name)?.({preventDefault:()=>{this.prevented=true;}});}
  setAttribute(){} focus(){this.focused=true;} showModal(){this.open=true;} close(){this.open=false;}
  prepend(child){this.children.unshift(child);}
}
function harness({authenticated=true,status=200,errorCode='',pending=false,cleanupFailure=false,lang='ko'}={}){
  const elements=new Map(),calls=[];let id=authenticated?'sub_fixture':null,clears=0,paused=false,reloaded=false,accountOpened=0;
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const root={document:{getElementById:get,createElement:()=>new Element(),documentElement:{lang},body:{classList:{remove(){}}}},
    location:{search:'',reload:()=>{reloaded=true;}},addEventListener(){},
    openStoryMemoryAuth:()=>{accountOpened++;},
    BookAISession:{isAuthenticated:()=>!!id,getAccountId:()=>id,deleted:()=>{id=null;}},
    BookAISync:{pause:async()=>{paused=true;},resume:()=>{paused=false;}},
    BookAILocalDB:{clearDeletedAccount:async account=>{assert.equal(account,'sub_fixture');clears++;if(cleanupFailure)throw Error('fixture-private-details');}}
  };
  vm.runInNewContext(source,{window:root,URLSearchParams,fetch:async(url,init)=>{
    assert.equal(paused,true);calls.push({url,init});
    return {ok:status===200,status,json:async()=>({ok:true,error:errorCode,common_account_deleted:true,cleanup:{complete:!pending,pending:pending?1:0}})};
  }});
  return {get,root,calls,clears:()=>clears,paused:()=>paused,reloaded:()=>reloaded,accountOpened:()=>accountOpened,
    setCleanupFailure:value=>{cleanupFailure=value;},setAccount:value=>{id=value;},
    open:()=>get('bookaiDeleteEntry').trigger('click'),
    confirm:async()=>{get('bookaiDeleteConfirm').checked=true;await get('bookaiDeleteConfirm').trigger('change');},
    submit:()=>get('bookaiDeleteSubmit').trigger('click')};
}
test('first-screen overflow opens the existing account sheet in both languages',async()=>{
  for(const [lang,label] of [['ko','계정'],['en','Account']]){
    const h=harness({lang});
    const menuEntry=h.get('libOverflowMenu').children[0];
    assert.equal(menuEntry.id,'bookaiAccountMenu');assert.equal(menuEntry.textContent,label);
    await menuEntry.trigger('click');assert.equal(h.accountOpened(),1);
    await h.open();assert.equal(h.get('bookaiDeleteDialog').open,true);
    await h.get('bookaiDeleteDialog').trigger('close');assert.equal(h.get('libOverflow').focused,true);
  }
});
test('account entrance, scope and explicit confirmation use the shared deletion route',async()=>{
  const h=harness();await h.open();
  assert.equal(h.get('bookaiDeleteDialog').open,true);assert.equal(h.get('bookaiDeleteSubmit').disabled,true);
  assert.match(h.get('bookaiDeleteScope').textContent,/모든 서비스/);assert.match(h.get('bookaiDeleteScope').textContent,/현재 기기/);
  await h.submit();assert.equal(h.calls.length,0);
  await h.confirm();await h.submit();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'/api/bookai/account/shared-delete');
  assert.equal(h.calls[0].init.body,'{"confirm":true,"account_id":"sub_fixture"}');assert.equal(h.clears(),1);
  assert.equal(h.root.BookAISession.isAuthenticated(),false);assert.equal(h.paused(),true);
  assert.match(h.get('bookaiDeleteStatus').textContent,/탈퇴가 완료/);
  await h.get('bookaiDeleteCancel').trigger('click');assert.equal(h.reloaded(),true);
});
for(const status of [401,403,503])test('failure '+status+' preserves device data and resumes synchronization',async()=>{
  const h=harness({status});await h.open();await h.confirm();await h.submit();
  assert.equal(h.clears(),0);assert.equal(h.paused(),false);assert.equal(h.root.BookAISession.isAuthenticated(),true);
  assert.equal(h.get('bookaiDeleteSubmit').disabled,false);assert.doesNotMatch(h.get('bookaiDeleteStatus').textContent,/fixture/);
});
test('account-only login requires no Chat session; guests have no destructive entrance',async()=>{
  const h=harness({authenticated:false});assert.equal(h.get('bookaiDeleteEntry').hidden,true);
  await h.open();assert.equal(h.get('bookaiDeleteDialog').open,undefined);assert.equal(h.calls.length,0);
});
test('existing admin refusal is explained without suggesting another login',async()=>{
  const h=harness({status:403,errorCode:'account_delete_admin_blocked',lang:'en'});
  await h.open();await h.confirm();await h.submit();
  assert.match(h.get('bookaiDeleteStatus').textContent,/administrator access/);
  assert.equal(h.clears(),0);assert.equal(h.paused(),false);
});
test('changed account cannot submit a previously confirmed deletion',async()=>{
  const h=harness();await h.open();await h.confirm();h.setAccount('sub_other');await h.submit();
  assert.equal(h.calls.length,0);assert.equal(h.clears(),0);assert.equal(h.paused(),false);
});
test('English pending cleanup message is truthful and language can be changed',async()=>{
  const h=harness({lang:'en',pending:true});assert.equal(h.get('bookaiDeleteEntry').textContent,'Delete account');
  await h.open();await h.confirm();await h.submit();
  assert.match(h.get('bookaiDeleteStatus').textContent,/retry automatically/);
  h.get('bookaiDeleteLanguage').value='ko';await h.get('bookaiDeleteLanguage').trigger('change');
  assert.match(h.get('bookaiDeleteStatus').textContent,/자동/);
});
test('local cleanup retry never resubmits the committed account deletion',async()=>{
  const h=harness({cleanupFailure:true});await h.open();await h.confirm();await h.submit();
  assert.equal(h.calls.length,1);assert.equal(h.paused(),true);assert.equal(h.get('bookaiDeleteCancel').disabled,true);
  assert.doesNotMatch(h.get('bookaiDeleteStatus').textContent,/fixture/);
  h.setCleanupFailure(false);await h.submit();assert.equal(h.calls.length,1);assert.equal(h.clears(),2);
});
test('native dialog markup provides labels and all copy is rendered as text',()=>{
  assert.match(html,/<dialog id="bookaiDeleteDialog"[^>]+aria-labelledby="bookaiDeleteTitle"/);
  assert.match(html,/id="bookaiDeleteStatus" role="status" aria-live="polite"/);
  assert.match(html,/src="\.\/bookai-account-delete-ui\.js"/);
  assert.ok(html.indexOf('src="storymemory-b61-library-firstscreen-v1.js"')<html.indexOf('src="./bookai-account-delete-ui.js"'));
  const today=html.slice(html.indexOf('<section class="screen today-screen"'));
  assert.ok(today.indexOf('</main>\n</section>')<today.indexOf('id="authGateSheet"'),
    'the shared account sheet must not inherit the hidden Today screen');
  assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|console\./);
});
