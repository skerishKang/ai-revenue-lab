import { createVerifier } from './bookai-auth-verify.mjs';
import { bookaiSignedHeaders } from './bookai-com2-signature.mjs';
const ORIGIN='https://bookai.padiem.net', AUTH='https://auth.padiem.net', CALLBACK=ORIGIN+'/auth/callback';
const CLIENT='b61', KID='b61-bookai-6affe050', enc=new TextEncoder(), dec=new TextDecoder();
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
const un64=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(s.length/4)*4,'=')),c=>c.charCodeAt(0));
const random=()=>b64(crypto.getRandomValues(new Uint8Array(32)));
const cookie=(name,value,age,path='/')=>`${name}=${value}; Path=${path}; Max-Age=${age}; HttpOnly; Secure; SameSite=Lax`;
function cookies(request){const out={};for(const part of (request.headers.get('cookie')||'').split(';')){const i=part.indexOf('=');if(i>0){const k=part.slice(0,i).trim();if(Object.hasOwn(out,k))throw Error('duplicate_cookie');out[k]=part.slice(i+1).trim();}}return out;}
function keyMaterial(env){const v=env?.BOOKAI_AUTH_CLIENT_PRIVATE_JWK;if(typeof v!=='string'||!v)throw Error('auth_not_configured');return v;}
async function stateKey(env){const material=await crypto.subtle.digest('SHA-256',enc.encode('bookai-oauth-state-v1\0'+keyMaterial(env)));return crypto.subtle.importKey('raw',material,'AES-GCM',false,['encrypt','decrypt']);}
async function seal(env,data){const iv=crypto.getRandomValues(new Uint8Array(12));const cipher=await crypto.subtle.encrypt({name:'AES-GCM',iv},await stateKey(env),enc.encode(JSON.stringify(data)));return b64(iv)+'.'+b64(cipher);}
async function unseal(env,value){const p=(value||'').split('.');if(p.length!==2)throw Error('bad_state');return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:un64(p[0])},await stateKey(env),un64(p[1]))));}
async function assertion(env,now){const jwk=JSON.parse(keyMaterial(env));const key=await crypto.subtle.importKey('jwk',jwk,{name:'ECDSA',namedCurve:'P-256'},false,['sign']);const h=b64(enc.encode(JSON.stringify({alg:'ES256',typ:'JWT',kid:KID})));const b=b64(enc.encode(JSON.stringify({iss:CLIENT,sub:CLIENT,aud:AUTH+'/token',iat:now,exp:now+120,jti:random()})));return h+'.'+b+'.'+b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},key,enc.encode(h+'.'+b)));}
const noStore={'cache-control':'no-store','referrer-policy':'no-referrer'};
function reply(body,status=200,headers={}){return Response.json(body,{status,headers:{...noStore,...headers}});}
function sameOrigin(req){return req.headers.get('origin')===ORIGIN;}
function withCookies(response,values){for(const v of values)response.headers.append('set-cookie',v);return response;}
export function createBookAIAuth({fetcher=fetch,clock=()=>Date.now()}={}){
 const verify=createVerifier({audience:CLIENT,fetcher,clock});
 async function exchange(env,fields){const now=Math.floor(clock()/1000);const params=new URLSearchParams({client_id:CLIENT,client_assertion_type:'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',client_assertion:await assertion(env,now),...fields});const response=await fetcher(AUTH+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:params,redirect:'manual'});if(!response.ok)throw Error('exchange_failed');const data=await response.json();if(typeof data.access_token!=='string'||typeof data.refresh_token!=='string')throw Error('invalid_tokens');await verify(data.access_token);return data;}
 async function identity(req){const token=cookies(req).__Host_bookai_session;if(!token)return null;try{return await verify(token);}catch{return null;}}
 function sessionCookies(tokens){return [cookie('__Host_bookai_session',tokens.access_token,900),cookie('__Host_bookai_refresh',tokens.refresh_token,2592000)];}
 return async function handle(request,env){
  const url=new URL(request.url),path=url.pathname;
  if(!['/auth/login','/auth/callback','/auth/session','/auth/refresh','/auth/logout','/api/bookai/records'].includes(path))return null;
  try{
   if(url.origin!==ORIGIN)return reply({error:'invalid_origin'},403);
   if(path==='/auth/login'&&request.method==='GET'){
    const state=random(),verifier=random(),challenge=b64(await crypto.subtle.digest('SHA-256',enc.encode(verifier)));
    const sealed=await seal(env,{state,verifier,exp:Math.floor(clock()/1000)+600});
    const dest=new URL(AUTH+'/login');for(const [k,v] of Object.entries({client_id:CLIENT,redirect_uri:CALLBACK,state,code_challenge:challenge,code_challenge_method:'S256'}))dest.searchParams.set(k,v);
    return withCookies(new Response(null,{status:302,headers:{...noStore,location:dest.href}}),[cookie('__Host_bookai_state',sealed,600)]);
   }
   if(path==='/auth/callback'&&request.method==='GET'){
    const stateValues=url.searchParams.getAll('state'),codes=url.searchParams.getAll('code');
    if(stateValues.length!==1||codes.length!==1||!codes[0])throw Error('bad_callback');
    const state=await unseal(env,cookies(request).__Host_bookai_state);
    if(state.state!==stateValues[0]||state.exp<=Math.floor(clock()/1000)||typeof state.verifier!=='string')throw Error('bad_state');
    const tokens=await exchange(env,{grant_type:'authorization_code',code:codes[0],redirect_uri:CALLBACK,code_verifier:state.verifier});
    return withCookies(new Response(null,{status:303,headers:{...noStore,location:'/'}}),[...sessionCookies(tokens),cookie('__Host_bookai_state','',0)]);
   }
   if(path==='/auth/session'&&request.method==='GET'){const who=await identity(request);return reply({authenticated:!!who,account_id:who?.accountId||null});}
   if(path==='/auth/refresh'&&request.method==='POST'){
    if(!sameOrigin(request))return reply({error:'invalid_origin'},403);
    const refresh=cookies(request).__Host_bookai_refresh;if(!refresh)return reply({error:'not_authenticated'},401);
    const tokens=await exchange(env,{grant_type:'refresh_token',refresh_token:refresh});return withCookies(reply({ok:true}),sessionCookies(tokens));
   }
   if(path==='/auth/logout'&&request.method==='POST'){
    if(!sameOrigin(request))return reply({error:'invalid_origin'},403);
    const refresh=cookies(request).__Host_bookai_refresh;
    if(refresh){const params=new URLSearchParams({client_id:CLIENT,client_assertion_type:'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',client_assertion:await assertion(env,Math.floor(clock()/1000)),refresh_token:refresh});const r=await fetcher(AUTH+'/logout',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:params,redirect:'manual'});if(!r.ok)throw Error('logout_failed');}
    return withCookies(reply({ok:true}),[cookie('__Host_bookai_session','',0),cookie('__Host_bookai_refresh','',0)]);
   }
   if(path==='/api/bookai/records'&&['GET','POST'].includes(request.method)){
    if(request.method==='POST'&&!sameOrigin(request))return reply({error:'invalid_origin'},403);
    const who=await identity(request);if(!who)return reply({error:'not_authenticated'},401);
    if(typeof env.BOOKAI_COM2_SYNC_SECRET!=='string'||!env.BOOKAI_COM2_SYNC_SECRET)return reply({error:'sync_unavailable'},503);
    const body=request.method==='POST'?await request.text():'';if(enc.encode(body).length>5*1024*1024)return reply({error:'request_too_large'},413);
    const target=path+url.search, headers=await bookaiSignedHeaders({method:request.method,path:target,timestamp:Math.floor(clock()/1000),subject:who.accountId,body,secret:env.BOOKAI_COM2_SYNC_SECRET});
    if(request.method==='POST')headers['content-type']='application/json';
    const upstream=await fetcher('https://chat.padiem.net'+target,{method:request.method,headers,body:request.method==='POST'?body:undefined,redirect:'manual'});
    return new Response(upstream.body,{status:upstream.status,headers:{...noStore,'content-type':upstream.headers.get('content-type')||'application/json'}});
   }
   return reply({error:'method_not_allowed'},405);
  }catch{return reply({error:'service_unavailable'},503);}
 };
}
