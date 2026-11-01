import assert from 'node:assert/strict';
import test from 'node:test';
import {createFront} from '../worker.mjs';

const env={FRONT_ORIGIN:'https://host.invalid',FALLBACK_MODE:'service',COM2_CANONICAL:'off'};
const headers={'X-Bookai-Subject':'sub_fixture','X-Bookai-Timestamp':'1793534400',
  'X-Bookai-Signature':'a'.repeat(64),'content-type':'application/json'};
const sign=async request=>new Headers(request.headers);

for(const method of ['GET','POST']) {
  test(method+' preserves the signed path, subject and exact body',async()=>{
    const path='/api/bookai/records'+(method==='GET'?'?limit=1000&since=%31':'');
    const body=method==='POST'?'{"records":[]}':undefined;
    const handle=createFront({sign,fetchImpl:async request=>{
      assert.equal(request.url,'https://host.invalid'+path);
      assert.equal(request.method,method);
      for(const [name,value] of Object.entries(headers))assert.equal(request.headers.get(name),value);
      assert.equal(await request.text(),body||'');
      return Response.json(method==='GET'?{records:[],next_since:1,more:false}:{accepted:0,kept_newer:[]},
        {headers:{'cache-control':'private, no-store'}});
    }});
    const response=await handle(new Request('https://chat.padiem.net'+path,{method,headers,body}),env);
    assert.equal(response.status,200);
    assert.equal(response.headers.get('cache-control'),'private, no-store');
  });

  test(method+' on COM2 failure never reaches the old Cloudflare database',async()=>{
    let fallbackCalls=0;
    const handle=createFront({sign,fetchImpl:async()=>{throw Error('offline');}});
    const response=await handle(new Request('https://chat.padiem.net/api/bookai/records',
      {method,headers,body:method==='POST'?'{"records":[]}':undefined}),
      {...env,CHAT_WORKER:{fetch:async()=>{fallbackCalls++;return Response.json({records:[]});}}});
    assert.equal(response.status,502);
    assert.equal(fallbackCalls,0);
  });
}
