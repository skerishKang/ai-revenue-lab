import {com2SignedHeaders} from './com2-hmac.mjs';

export const COM2_AI_URL = 'https://chat.padiem.net/api/apps/ai';
export const INGRESS_EXECUTE_URL = 'https://padiem-ai-engine-ingress.charliekant.workers.dev/internal/v1/execute';
const MAX_STREAM_PROBE_BYTES=64*1024;
const APP_CREDENTIALS = Object.freeze({
  storymemory: {subject:'sub_app_storymemory', key:'STORYMEMORY_COM2_AI_SECRET'},
  bookai: {subject:'sub_app_bookai', key:'BOOKAI_COM2_AI_SECRET'}
});
export function com2CredentialConfigured(env, app) {
  const name=APP_CREDENTIALS[app]?.key;
  return !!name && typeof env?.[name] === 'string' && env[name].length > 0;
}
export function ingressCredential(env) {
  const credential=String(env?.PADIEM_INGRESS_CLIENT_SECRET ?? '');
  return credential.length >= 32 && credential.length <= 512 ? credential : null;
}
function failed(code, status, transport) {
  return {status, transport, payload:{ok:false,error:{code,retryable:status>=500}}};
}
async function post(url, headers, body, transport, timeoutMs) {
  const controller=new AbortController();
  let timeout;
  const timeoutPromise=new Promise((_, reject)=>{
    timeout=setTimeout(()=>{controller.abort();reject(new Error('app_ai_timeout'));},timeoutMs);
  });
  try {
    return await Promise.race([(async()=>{
      const response=await fetch(new Request(url,{
        method:'POST',headers,body,redirect:'manual',signal:controller.signal
      }));
      const timing=response.headers.get('server-timing')||'';
      let payload;
      try {payload=await response.json();}
      catch {return failed(transport==='com2_p01'?'com2_ai_invalid_response':'ingress_invalid_response',response.status>=400?response.status:502,transport);}
      if(response.status>=300&&response.status<400)return failed('upstream_redirect_rejected',502,transport);
      return {status:response.status,transport,payload,timing};
    })(),timeoutPromise]);
  } catch(error) {
    if(error?.message==='app_ai_timeout'||controller.signal.aborted)
      return failed(transport==='com2_p01'?'com2_ai_timeout':'ingress_timeout',504,transport);
    return failed(transport==='com2_p01'?'com2_ai_request_failed':'ingress_request_failed',502,transport);
  } finally {clearTimeout(timeout);}
}
function fallbackEligible(result) {
  // During cutover P01 may not yet have the existing b61 caller registration.
  // Only these two service-auth codes may use 1.0's separately authenticated ingress.
  const serviceAuthFailure=result.status===403 &&
    ['service_app_not_authorized','service_authentication_failed'].includes(upstreamErrorCode(result.payload,''));
  return serviceAuthFailure || result.status===401 || result.status===404 || result.status>=500;
}
// The caller selects only its compile-time app identity. Browser input cannot
// choose a URL, app secret, signed subject, transport or fallback policy.
export async function executeAppAI({env, app, payload, allowIngressFallback=false, timeoutMs=60000, ingressTimeoutMs=60000}) {
  const identity=APP_CREDENTIALS[app];
  if(!identity)throw new Error('invalid_app');
  const body=JSON.stringify(payload);
  let result;
  if(!com2CredentialConfigured(env,app))result=failed('com2_ai_credential_unavailable',503,'com2_p01');
  else {
    const headers=await com2SignedHeaders({method:'POST',path:'/api/apps/ai',
      timestamp:Math.floor(Date.now()/1000),subject:identity.subject,body,secret:env[identity.key]});
    headers['content-type']='application/json';
    result=await post(COM2_AI_URL,headers,body,'com2_p01',timeoutMs);
    if(result.status>=200&&result.status<300&&
       (result.payload?.ok!==true||typeof result.payload.answer!=='string'))
      result=failed('com2_ai_invalid_response',502,'com2_p01');
  }
  if(app==='storymemory'&&allowIngressFallback&&fallbackEligible(result)){
    const credential=ingressCredential(env);
    if(credential)return post(INGRESS_EXECUTE_URL,{
      'content-type':'application/json','X-Padiem-Ingress-Credential':credential
    },body,'authenticated_ingress',ingressTimeoutMs);
  }
  return result;
}
export function upstreamErrorCode(payload, fallback='com2_ai_execution_failed') {
  const value=typeof payload?.error==='string'?payload.error:payload?.error?.code;
  return typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,96}$/.test(value)?value:fallback;
}
function streamFailed(code,status,transport){
  return {stream:false,status,transport,payload:{ok:false,error:{code,retryable:status>=500}},transportFailure:true};
}
// Streaming is a capability probe, not a second pipeline: a JSON answer or any
// refusal is handed back so the caller keeps its existing one-shot handling.
export async function executeAppAIStream({env, app, payload, timeoutMs=60000}) {
  const identity=APP_CREDENTIALS[app];
  if(!identity)throw new Error('invalid_app');
  if(!com2CredentialConfigured(env,app))
    return streamFailed('com2_ai_credential_unavailable',503,'com2_p01');
  const body=JSON.stringify(payload);
  const headers=await com2SignedHeaders({method:'POST',path:'/api/apps/ai',
    timestamp:Math.floor(Date.now()/1000),subject:identity.subject,body,secret:env[identity.key]});
  headers['content-type']='application/json';
  headers['accept']='application/x-ndjson';
  const controller=new AbortController();
  const timer=setTimeout(()=>{controller.abort();},timeoutMs);
  let response;
  try {
    response=await fetch(new Request(COM2_AI_URL,{
      method:'POST',headers,body,redirect:'manual',signal:controller.signal
    }));
  } catch {
    clearTimeout(timer);
    const aborted=controller.signal.aborted;
    return streamFailed(aborted?'com2_ai_timeout':'com2_ai_request_failed',aborted?504:502,'com2_p01');
  }
  if(response.status>=300&&response.status<400){
    clearTimeout(timer);
    return streamFailed('upstream_redirect_rejected',502,'com2_p01');
  }
  const timing=response.headers.get('server-timing')||'';
  const contentType=String(response.headers.get('content-type')||'').split(';',1)[0].trim().toLowerCase();
  if(response.status===200&&contentType==='application/x-ndjson'){
    return {
      stream:true,status:response.status,transport:'com2_p01',response,timing,
      cleanup(){clearTimeout(timer);}
    };
  }
  // The upstream answered with its ordinary JSON envelope (or refused). Read it
  // bounded and let the caller decide between using it and the one-shot path.
  let parsed=null;
  try{
    const text=await response.text();
    if(text.length<=MAX_STREAM_PROBE_BYTES){try{parsed=JSON.parse(text);}catch{parsed=null;}}
  }catch{parsed=null;}
  clearTimeout(timer);
  return {
    stream:false,status:response.status,transport:'com2_p01',timing,
    payload:parsed||{ok:false,error:{code:response.ok?'com2_ai_invalid_response':'com2_ai_execution_failed',retryable:false}},
    transportFailure:false
  };
}
