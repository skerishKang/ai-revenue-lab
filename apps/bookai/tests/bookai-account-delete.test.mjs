import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,createHmac} from 'node:crypto';
import {createBookAIAuth} from '../public/bookai-auth.mjs';
import {ACCOUNT_DELETE_PATH,accountDeleteSignedHeaders} from '../public/bookai-account-delete.mjs';
import {bookaiSignedHeaders} from '../public/bookai-com2-signature.mjs';

const origin='https://bookai.padiem.net', now=1761960000000, enc=new TextEncoder();
const keys=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const pub=await crypto.subtle.exportKey('jwk',keys.publicKey);pub.kid='fixture';pub.alg='ES256';pub.use='sig';
const client=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const env={BOOKAI_AUTH_CLIENT_PRIVATE_JWK:JSON.stringify(await crypto.subtle.exportKey('jwk',client.privateKey)),
  BOOKAI_COM2_SYNC_SECRET:'synthetic-delete-signature'};
async function token({account='sub_fixture',sid='fixture-session',aud='b61',expiry=900}={}){
  const b64=value=>Buffer.from(value).toString('base64url');
  const head=b64(JSON.stringify({alg:'ES256',typ:'JWT',kid:'fixture'}));
  const body=b64(JSON.stringify({iss:'https://auth.padiem.net',aud,token_use:'access',iat:now/1000,
    exp:now/1000+expiry,sub:'fixture-user',account_id:account,sid}));
  return head+'.'+body+'.'+b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},keys.privateKey,enc.encode(head+'.'+body)));
}
async function harness(options={}){
  const access=await token(options.current), fresh=await token(options.fresh), calls=[];
  const handler=createBookAIAuth({clock:()=>now,fetcher:async(url,init)=>{
    if(url.endsWith('/.well-known/jwks.json'))return Response.json({keys:[pub]});
    calls.push({url,init});
    if(url.endsWith('/token')){
      // This fixture accepts only the registered BookAI refresh client.
      assert.equal(init.body.get('client_id'),'b61');assert.equal(init.body.get('grant_type'),'refresh_token');
      assert.equal(init.body.get('refresh_token'),'fixture-refresh');
      if(options.refreshStatus)return Response.json({error:'private-error-fixture'}, {status:options.refreshStatus});
      return Response.json({access_token:fresh,refresh_token:'fixture-rotated-refresh'});
    }
    assert.equal(url,'https://chat.padiem.net'+ACCOUNT_DELETE_PATH);
    if(options.throwUpstream)throw Error('private-error-fixture');
    return Response.json(options.result||{ok:true,common_account_deleted:true,cleanup:{complete:true,pending:0}},
      {status:options.upstreamStatus||200});
  }});
  const request=(changes={})=>new Request(origin+ACCOUNT_DELETE_PATH+(changes.query||''),{
    method:changes.method||'POST',headers:{origin,'content-type':'application/json',
      cookie:'__Host_bookai_session='+access+'; __Host_bookai_refresh=fixture-refresh',...changes.headers},
    ...(changes.method==='GET'?{}:{body:changes.body??'{"confirm":true,"account_id":"sub_fixture"}'})});
  return {handler,calls,request};
}

test('BookAI-only session refreshes before signing the existing all-service deletion',async()=>{
  const h=await harness(), response=await h.handler(h.request(),env), body=await response.json();
  assert.equal(response.status,200);assert.equal(body.common_account_deleted,true);
  assert.equal(h.calls.length,2);assert.ok(h.calls[0].url.endsWith('/token'));
  const sent=h.calls[1].init, data=JSON.parse(sent.body);
  assert.deepEqual(Object.keys(data).sort(),['confirm','expires_at','request_id','session_id']);
  assert.equal(data.session_id,'fixture-session');assert.equal(data.expires_at,now/1000+900);
  assert.match(data.request_id,/^[0-9a-f-]{36}$/);assert.equal(sent.headers['X-Bookai-Subject'],'sub_fixture');
  const expected=createHmac('sha256',env.BOOKAI_COM2_SYNC_SECRET).update(['POST',ACCOUNT_DELETE_PATH,now/1000,
    'sub_fixture',createHash('sha256').update(sent.body).digest('hex')].join('\n')).digest('hex');
  assert.equal(sent.headers['X-Bookai-Signature'],expected);assert.equal(sent.redirect,'manual');
  assert.equal(response.headers.getSetCookie().length,3);
  assert.ok(response.headers.getSetCookie().every(value=>value.includes('Max-Age=0')));
  assert.equal(response.headers.get('cache-control'),'no-store');
});

for(const status of [403,503])test('closed authority preserves rotated cookies and sanitizes upstream '+status,async()=>{
  const h=await harness({upstreamStatus:status,result:{error:'private-error-fixture',account:'private-account-fixture'}});
  const response=await h.handler(h.request(),env), text=await response.text();
  assert.equal(response.status,status);assert.doesNotMatch(text,/private-|fixture/);
  assert.equal(response.headers.getSetCookie().length,2);
  assert.ok(response.headers.getSetCookie().some(value=>value.includes('fixture-rotated-refresh')));
  assert.ok(response.headers.getSetCookie().every(value=>!value.includes('Max-Age=0')));
});

test('pending existing cleanup is still a committed deletion and expires cookies',async()=>{
  const h=await harness({result:{ok:true,common_account_deleted:true,cleanup:{complete:false,pending:1},message:'private-error-fixture'}});
  const response=await h.handler(h.request(),env);
  assert.deepEqual(await response.json(),{ok:true,common_account_deleted:true,cleanup:{complete:false,pending:1}});
  assert.ok(response.headers.getSetCookie().every(value=>value.includes('Max-Age=0')));
});

test('existing admin refusal keeps only its fixed code',async()=>{
  const h=await harness({upstreamStatus:403,result:{error:'account_delete_admin_blocked',message:'private-error-fixture'}});
  const response=await h.handler(h.request(),env);
  assert.equal(response.status,403);assert.deepEqual(await response.json(),{error:'account_delete_admin_blocked'});
  assert.equal(response.headers.getSetCookie().length,2);
});

for(const [name,changes,status] of [
  ['CSRF',{headers:{origin:'https://untrusted.invalid'}},403],
  ['missing login',{headers:{cookie:''}},401],['wrong content type',{headers:{'content-type':'text/plain'}},400],
  ['unconfirmed',{body:'{"confirm":false,"account_id":"sub_fixture"}'},400],
  ['missing confirmed account',{body:'{"confirm":true}'},400],
  ['stale account confirmation',{body:'{"confirm":true,"account_id":"sub_other"}'},401],
  ['injected session',{body:'{"confirm":true,"account_id":"sub_fixture","session_id":"other"}'},400],
  ['oversized body',{body:' '.repeat(1025)+'{"confirm":true}'},400],['invalid JSON',{body:'{'},400],
  ['query parameters',{query:'?confirm=true'},400],['wrong method',{method:'GET'},405]
])test(name+' never reaches the deletion backend',async()=>{
  const h=await harness(), response=await h.handler(h.request(changes),env);
  assert.equal(response.status,status);assert.equal(h.calls.length,0);
});

for(const [name,options,status] of [
  ['revoked refresh',{refreshStatus:400},401],['refresh outage',{refreshStatus:503},503],
  ['wrong refreshed account',{fresh:{account:'sub_other'}},401],['wrong refreshed session',{fresh:{sid:'other-session'}},401],
  ['wrong refresh audience',{fresh:{aud:'chat'}},503]
])test(name+' cannot sign deletion',async()=>{
  const h=await harness(options), response=await h.handler(h.request(),env);
  assert.equal(response.status,status);assert.ok(h.calls.every(call=>!call.url.includes('/api/bookai/')));
});

test('expired access can finish with a live refresh session for the confirmed account',async()=>{
  const h=await harness({current:{expiry:0}}),response=await h.handler(h.request(),env);
  assert.equal(response.status,200);assert.equal(h.calls.length,2);
});

test('network and malformed-success responses keep fresh cookies without leaking details',async()=>{
  for(const options of [{throwUpstream:true},{result:{ok:true,common_account_deleted:false}},
    {result:{ok:true,common_account_deleted:true,cleanup:{complete:true,pending:1}}}]){
    const h=await harness(options),response=await h.handler(h.request(),env);
    assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'account_delete_unavailable'});
    assert.equal(response.headers.getSetCookie().length,2);
  }
});

test('signature wrappers retain separate exact public path contracts',async()=>{
  const args={method:'POST',path:ACCOUNT_DELETE_PATH,timestamp:now/1000,subject:'sub_fixture',body:'{}',secret:'fixture'};
  await assert.rejects(bookaiSignedHeaders(args),/invalid_request/);
  await assert.rejects(accountDeleteSignedHeaders({...args,path:'/api/bookai/records'}),/invalid_request/);
  await assert.rejects(accountDeleteSignedHeaders({...args,method:'GET'}),/invalid_request/);
});
