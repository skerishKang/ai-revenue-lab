import assert from 'node:assert/strict';
import {createHash,createHmac} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import bookai from '../public/_worker.js';
import storymemory from '../../storymemory/public/_worker.js';
import {executeAppAI,COM2_AI_URL,INGRESS_EXECUTE_URL} from '../public/app-ai-transport.mjs';
const subjects={bookai:'sub_app_bookai',storymemory:'sub_app_storymemory'};
const env={
  BOOKAI_COM2_AI_SECRET:'synthetic-bookai-ai-test-credential',
  STORYMEMORY_COM2_AI_SECRET:'synthetic-storymemory-ai-test-credential',
  PADIEM_INGRESS_CLIENT_SECRET:'synthetic-ingress-fallback-test-credential'
};
const packet={version:'1',mode:'storymemory_bounded_companion',source_scope:'ceiling_filtered',
  diagnostics:{boundary_available:true,spoiler_policy:'hard_no_future'},
  co_reader_decision:{decision:'ALLOW',reason:'WITHIN_CEILING'},
  reader_context:{authoritative_reader:true,current_work_key:'bible-web'},
  reading_progress:{furthest_read_locator:'bible:web:ACT:9:5',knowledge_ceiling_locator:'bible:web:ACT:9:5'},
  source_passages:[{canonical_locator:'bible:web:ACT:9:3',text:'A light shone around Saul.'}]};
const cp={boundary_disposition:'permitted',context_filtered_count:0,context_allowed_count:2,
  context_candidate_count:2,filter_reason_codes:[],policy_version:'storymemory-b61-ceiling:v1'};
const success=()=>Response.json({ok:true,answer:'<thought>hidden chain</thought>Saul saw a light.',context_permission:cp});
const req=(extra={})=>new Request('https://reader.invalid/api/storymemory-ai',{
  method:'POST',headers:{'content-type':'application/json','origin':'https://reader.invalid','cookie':'ignored-browser-cookie'},
  body:JSON.stringify({question:'What happened to Saul?',packet,...extra})});
const originalFetch=globalThis.fetch;
let executePayload;
try {
  for(const [app,worker] of [['bookai',bookai],['storymemory',storymemory]]) {
    let calls=0;
    globalThis.fetch=async request=>{
      calls++;
      assert.equal(request.url,COM2_AI_URL);
      assert.equal(request.method,'POST');
      assert.equal(request.redirect,'manual');
      assert.equal(request.headers.get('origin'),null);
      assert.equal(request.headers.get('cookie'),null);
      assert.equal(request.headers.get('x-padiem-ingress-credential'),null);
      const text=await request.text(),subject=request.headers.get('x-bookai-subject');
      const timestamp=request.headers.get('x-bookai-timestamp');
      assert.equal(subject,subjects[app]);
      assert.ok(Math.abs(Number(timestamp)-Date.now()/1000)<2);
      const digest=createHash('sha256').update(text).digest('hex');
      const expected=createHmac('sha256',env[app==='bookai'?'BOOKAI_COM2_AI_SECRET':'STORYMEMORY_COM2_AI_SECRET'])
        .update(['POST','/api/apps/ai',timestamp,subject,digest].join('\n')).digest('hex');
      assert.equal(request.headers.get('x-bookai-signature'),expected);
      executePayload=JSON.parse(text);
      assert.deepEqual(executePayload.agent.model_policy,{model:'google/gemini-3.1-flash-lite',max_retries:0});
      assert.equal(executePayload.context_permission_required,true);
      assert.equal(executePayload.messages.length,1);
      assert.ok(executePayload.messages[0].content.includes('A light shone around Saul.'));
      return success();
    };
    const response=await worker.fetch(req(),env),data=await response.json();
    assert.equal(response.status,200);
    assert.equal(data.answer,'Saul saw a light.');
    assert.equal(data.runtime,'padiem-p01');
    assert.equal(data.transport,'com2_p01');
    assert.deepEqual(data.context_permission,cp);
    assert.equal(calls,1);
  }
  // 1.0 stays usable during COM2 cutover and transient failures.
  for(const status of [401,404,500,503]) {
    const calls=[];
    globalThis.fetch=async request=>{
      calls.push(request.url);
      if(request.url===COM2_AI_URL)return Response.json({ok:false,error:{code:'temporary_upstream_error'}},{status});
      assert.equal(request.headers.get('x-padiem-ingress-credential'),env.PADIEM_INGRESS_CLIENT_SECRET);
      assert.equal(request.headers.get('x-bookai-signature'),null);
      return success();
    };
    const response=await storymemory.fetch(req(),env),data=await response.json();
    assert.equal(response.status,200);assert.equal(data.transport,'authenticated_ingress');
    assert.equal(data.answer,'Saul saw a light.');assert.deepEqual(calls,[COM2_AI_URL,INGRESS_EXECUTE_URL]);
  }
  for(const code of ['service_app_not_authorized','service_authentication_failed']) {
    let calls=[];
    globalThis.fetch=async request=>{
      calls.push(request.url);
      return request.url===COM2_AI_URL?Response.json({ok:false,error:{code}},{status:403}):success();
    };
    const response=await storymemory.fetch(req(),env),data=await response.json();
    assert.equal(response.status,200);assert.equal(data.transport,'authenticated_ingress');
    assert.deepEqual(calls,[COM2_AI_URL,INGRESS_EXECUTE_URL]);
    calls=[];
    const bookaiResponse=await bookai.fetch(req(),env);
    assert.equal(bookaiResponse.status,403);assert.equal((await bookaiResponse.json()).error,code);
    assert.deepEqual(calls,[COM2_AI_URL]);
  }
  for(const scenario of ['missing-secret','network']) {
    const calls=[];
    globalThis.fetch=async request=>{
      calls.push(request.url);
      if(request.url===COM2_AI_URL)throw new TypeError('synthetic network failure');
      return success();
    };
    const cfg=scenario==='missing-secret'?{PADIEM_INGRESS_CLIENT_SECRET:env.PADIEM_INGRESS_CLIENT_SECRET}:env;
    const response=await storymemory.fetch(req(),cfg);
    assert.equal(response.status,200);
    assert.deepEqual(calls,scenario==='missing-secret'?[INGRESS_EXECUTE_URL]:[COM2_AI_URL,INGRESS_EXECUTE_URL]);
  }
  let timeoutCalls=[];
  globalThis.fetch=request=>{
    timeoutCalls.push(request.url);
    return request.url===COM2_AI_URL?new Promise(()=>{}):Promise.resolve(success());
  };
  const timed=await executeAppAI({app:'storymemory',env,payload:executePayload,allowIngressFallback:true,timeoutMs:5});
  assert.equal(timed.status,200);assert.equal(timed.transport,'authenticated_ingress');
  assert.deepEqual(timeoutCalls,[COM2_AI_URL,INGRESS_EXECUTE_URL]);
  // Policy, validation, and quota denial must not be bypassed through fallback.
  for(const [status,code] of [[403,'app_ai_model_not_allowed'],[403,'app_not_authorized'],[403,'context_permission_denied'],[422,'invalid_model_policy'],[429,'app_ai_limit_exceeded']]) {
    let calls=0;
    globalThis.fetch=async()=>{calls++;return Response.json({ok:false,error:{code}},{status});};
    const response=await storymemory.fetch(req(),env);
    assert.equal(response.status,status);assert.equal((await response.json()).error,code);assert.equal(calls,1);
  }
  globalThis.fetch=async()=>new Response('Denied',{status:403});
  assert.equal((await storymemory.fetch(req(),env)).status,403);
  // BookAI has no CF fallback even if an ingress credential remains configured.
  for(const status of [401,404,503]) {
    let calls=0;
    globalThis.fetch=async request=>{calls++;assert.equal(request.url,COM2_AI_URL);return Response.json({ok:false,error:'com2_unavailable'},{status});};
    const response=await bookai.fetch(req(),env);
    assert.equal(response.status,status);assert.equal((await response.json()).error,'com2_unavailable');assert.equal(calls,1);
  }
  globalThis.fetch=async()=>{throw new Error('must not fetch');};
  const noKey=await bookai.fetch(req(),{PADIEM_INGRESS_CLIENT_SECRET:env.PADIEM_INGRESS_CLIENT_SECRET});
  assert.equal(noKey.status,503);assert.equal((await noKey.json()).error,'com2_ai_credential_unavailable');
  for(const worker of [bookai,storymemory]){
    const wrongModel=await worker.fetch(req(),{...env,STORYMEMORY_MODEL:'b14/auto'});
    assert.equal(wrongModel.status,503);
    assert.equal((await worker.fetch(req({target_url:'https://other.invalid'}),env)).status,400);
    globalThis.fetch=async()=>Response.json({ok:true,answer:'Answer',context_permission:{...cp,context_filtered_count:1}});
    const invalid=await worker.fetch(req(),env);assert.equal(invalid.status,502);
    assert.equal((await invalid.json()).error,'engine_permission_projection_invalid');
  }
  for(const name of ['com2-hmac.mjs','app-ai-transport.mjs'])
    assert.equal(await readFile(new URL('../public/'+name,import.meta.url),'utf8'),
      await readFile(new URL('../../storymemory/public/'+name,import.meta.url),'utf8'),'deployable helpers stay identical');
  console.log('PASS: both workers signed COM2 success + bounded answer; 1.0 missing/network/timeout/401/404/5xx fallback; no policy/quota bypass; BookAI COM2-only; thought and CP filters preserved');
}finally{globalThis.fetch=originalFetch;}
