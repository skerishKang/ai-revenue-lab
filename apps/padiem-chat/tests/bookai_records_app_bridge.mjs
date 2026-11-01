// Test-only JSON bridge: the real BookAI authenticated proxy and sync client.
// Synthetic signing keys exist only in this process; stdout never includes JWTs.
import readline from 'node:readline';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {createBookAIAuth} from '../../bookai/public/bookai-auth.mjs';
const enc=new TextEncoder(), pending=new Map();
let serial=0;
const b64=value=>Buffer.from(value).toString('base64url');
const authority=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const jwk=await crypto.subtle.exportKey('jwk',authority.publicKey);
Object.assign(jwk,{kid:'integration-authority',alg:'ES256',use:'sig'});
const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
function upstream(url,init){
  const id=++serial;
  return new Promise((resolve,reject)=>{
    pending.set(id,{resolve,reject});
    emit({type:'fetch',id,url:String(url),method:init.method||'GET',
      headers:Object.fromEntries(new Headers(init.headers)),body:init.body||''});
  });
}
async function token(subject,now){
  const h=b64(JSON.stringify({alg:'ES256',typ:'JWT',kid:jwk.kid}));
  const p=b64(JSON.stringify({iss:'https://auth.padiem.net',aud:'b61',token_use:'access',
    iat:now,exp:now+900,sub:subject,account_id:subject,sid:'integration-session'}));
  return h+'.'+p+'.'+b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},authority.privateKey,enc.encode(h+'.'+p)));
}
async function run(input){
  const now=input.now+(input.clockOffset||0), subject=input.subject;
  const session=await token(subject,now);
  const handler=createBookAIAuth({
    clock:()=>now*1000,
    fetcher:async(url,init)=>{
      if(String(url)==='https://auth.padiem.net/.well-known/jwks.json')return Response.json({keys:[jwk]});
      if(!String(url).startsWith('https://chat.padiem.net/api/bookai/records'))throw Error('unexpected_upstream');
      return upstream(url,init);
    }
  });
  const env={BOOKAI_COM2_SYNC_SECRET:input.secret};
  async function request(path,options={}){
    const headers=new Headers(options.headers||{});
    headers.set('cookie','__Host_bookai_session='+session);
    headers.set('origin','https://bookai.padiem.net');
    const response=await handler(new Request('https://bookai.padiem.net'+path,{...options,headers}),env);
    if(!response)throw Error('unhandled_app_request');
    return response;
  }
  if(input.operation==='request'){
    const response=await request(input.path,{method:input.method||'GET',
      headers:input.method==='POST'?{'content-type':'application/json'}:{},
      ...(input.method==='POST'?{body:JSON.stringify(input.data)}:{})});
    return {status:response.status,headers:Object.fromEntries(response.headers),body:await response.json()};
  }
  if(input.operation!=='sync')throw Error('invalid_operation');
  // Only browser storage is substituted. The shipped loop, authenticated proxy,
  // JS HMAC, ASGI route, and SQL all execute unchanged.
  let cursor=input.cursor||0;
  const records=new Map(), outbox=new Map((input.pending||[]).map(row=>[row.record_id,row]));
  const timers=new Set();
  const context={
    TextEncoder,AbortController,URL,Promise,console,
    navigator:{onLine:true},
    fetch:request,
    setTimeout(fn,ms){const id=setTimeout(()=>{timers.delete(id);fn();},ms);timers.add(id);return id;},
    clearTimeout(id){timers.delete(id);clearTimeout(id);},
    setInterval(){return 1;},
    BookAIReady:Promise.resolve(true),
    BookAISession:{isAuthenticated:()=>true,getAccountId:()=>subject,refresh:async()=>true},
    BookAILocalDB:{
      flush:async()=>{},bindAccount:async id=>{if(id!==subject)throw Error('wrong_subject');},
      cursor:async()=>cursor,setCursor:async(_,value)=>{cursor=value;},
      pending:async()=>[...outbox.values()],
      acknowledge:async(_,rows)=>{for(const row of rows)if(outbox.get(row.record_id)?.updated_at===row.updated_at)outbox.delete(row.record_id);},
      merge:async(_,rows)=>{for(const row of rows){const old=records.get(row.record_id);if(!old||row.updated_at>old.updated_at)records.set(row.record_id,row);}}
    },
    addEventListener(){}
  };
  context.window=context;
  const source=await readFile(new URL('../../bookai/public/bookai-sync.js',import.meta.url),'utf8');
  vm.runInNewContext(source,context,{filename:'bookai-sync.js'});
  try{
    await Promise.resolve();await Promise.resolve();
    const status=await context.BookAISync.syncNow();
    return {status,records:[...records.values()],cursor,pending:outbox.size};
  }finally{for(const timer of timers)clearTimeout(timer);}
}
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
  let command;try{command=JSON.parse(line);}catch{emit({type:'error',error:'invalid_bridge_input'});return;}
  if(command.type==='upstream_result'){
    const call=pending.get(command.id);if(!call)return;
    pending.delete(command.id);
    call.resolve(new Response(command.body,{status:command.status,headers:command.headers}));
    return;
  }
  run(command).then(result=>emit({type:'result',result}),error=>emit({type:'result',error:String(error.message)}));
});
