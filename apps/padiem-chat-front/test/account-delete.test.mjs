import test from 'node:test';
import assert from 'node:assert/strict';
import {createFront} from '../worker.mjs';

const paths=['/api/account/delete','/api/account/shared-delete','/api/bookai/account/shared-delete'];
const request=path=>new Request('https://chat.example.test'+path,{
  method:'POST',headers:{'content-type':'application/json','x-bookai-signature':'synthetic-signature'},body:'{"confirm":true}',
});
const env={FRONT_ORIGIN:'https://upstream.example.test',UPSTREAM_TIMEOUT_MS:'5',COM2_CANONICAL:'off',FALLBACK_MODE:'service'};
for(const path of paths){
  test(path+' waits for withdrawal cleanup and forwards proof unchanged',async()=>{
    const seen=[];
    const front=createFront({sign:async req=>new Headers(req.headers),fetchImpl:async req=>{
      seen.push(req);await new Promise(resolve=>setTimeout(resolve,30));
      return Response.json({ok:true,common_account_deleted:true,cleanup:{complete:true,pending:0}});
    }});
    const response=await front(request(path),env);
    assert.equal(response.status,200);
    assert.equal(seen.length,1);
    assert.equal(seen[0].headers.get('x-bookai-signature'),'synthetic-signature');
    assert.equal(await seen[0].text(),'{"confirm":true}');
  });
  test(path+' never retries deletion against a fallback backend',async()=>{
    let calls=0,fallbacks=0;
    const front=createFront({sign:async req=>new Headers(req.headers),fetchImpl:async()=>{
      calls++;throw Error('connect failed');
    }});
    const response=await front(request(path),{...env,CHAT_WORKER:{fetch:async()=>{
      fallbacks++;return Response.json({ok:true});
    }}});
    assert.equal(response.status,503);assert.equal(calls,1);assert.equal(fallbacks,0);
  });
}
