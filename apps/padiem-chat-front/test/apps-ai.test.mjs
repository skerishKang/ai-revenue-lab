import test from 'node:test';
import assert from 'node:assert/strict';
import {createFront} from '../worker.mjs';
const env={FRONT_ORIGIN:'https://host.example',UPSTREAM_TIMEOUT_MS:'5',APPS_AI_TIMEOUT_MS:'100',FALLBACK_MODE:'static'};
const sign=async request=>new Headers(request.headers);
function delayed(request){
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>resolve(new Response('{"ok":true,"answer":"answer"}',{headers:{'content-type':'application/json'}})),30);
    request.signal.addEventListener('abort',()=>{clearTimeout(timer);reject(new Error('timeout'));},{once:true});
  });
}
test('app AI keeps signed request intact and uses model response deadline',async()=>{
  const handle=createFront({sign,fetchImpl:async request=>{
    assert.equal(new URL(request.url).pathname,'/api/apps/ai');
    assert.equal(request.headers.get('X-Bookai-Subject'),'sub_app_bookai');
    assert.equal(request.headers.get('X-Bookai-Timestamp'),'1700000000');
    assert.equal(request.headers.get('X-Bookai-Signature'),'test-signature');
    assert.equal(await request.clone().text(),'{"app_id":"b61"}');
    return delayed(request);
  }});
  const response=await handle(new Request('https://chat.padiem.net/api/apps/ai',{
    method:'POST',headers:{'X-Bookai-Subject':'sub_app_bookai','X-Bookai-Timestamp':'1700000000','X-Bookai-Signature':'test-signature'},
    body:'{"app_id":"b61"}'
  }),env);
  assert.equal(response.status,200);
  assert.equal((await response.json()).answer,'answer');
});
test('other API keeps ordinary response deadline',async()=>{
  const handle=createFront({sign,fetchImpl:delayed});
  const response=await handle(new Request('https://chat.padiem.net/api/other',{method:'POST',body:'{}'}),env);
  assert.equal(response.status,504);
});
test('app AI never dispatches to the Cloudflare Chat backup on COM2 outage',async()=>{
  let backup=0;
  const handle=createFront({sign,fetchImpl:async()=>{throw Error('offline');}});
  const response=await handle(new Request('https://chat.padiem.net/api/apps/ai',{method:'POST',body:'{}'}),
    {...env,COM2_CANONICAL:'off',FALLBACK_MODE:'service',CHAT_WORKER:{fetch:async()=>{backup++;return new Response('wrong');}}});
  assert.equal(response.status,502);assert.equal(backup,0);
});
