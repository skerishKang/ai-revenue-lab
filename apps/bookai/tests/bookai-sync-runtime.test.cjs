const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../public/bookai-sync.js'),'utf8');
function record(id, text='', updated=100) {
  return {record_id:id,book_id:'bible-web',locator:'ACT.9.1',kind:'note',
    payload:{body:text},updated_at:updated,deleted:false};
}
function harness({remote=[],queued=[],cap=Infinity}={}) {
  const server = new Map(remote.map(row=>[row.record_id,structuredClone(row)]));
  const local = new Map(), queue = new Map(queued.map(row=>[row.record_id,structuredClone(row)]));
  let cursor=0, release, periodic, requests=[], postBytes=[];
  const ready = new Promise(resolve=>{release=resolve;});
  const events = new EventTarget();
  const root = {
    BookAIReady:ready,
    BookAISession:{isAuthenticated:()=>true,getAccountId:()=>'sub_test'},
    addEventListener:events.addEventListener.bind(events),
    BookAILocalDB:{
      flush:async()=>{},bindAccount:async()=>{},
      cursor:async()=>cursor,setCursor:async(_id,value)=>{cursor=value;},
      pending:async()=>Array.from(queue.values()).map(row=>structuredClone(row)),
      merge:async(_id,rows)=>{for(const row of rows){
        const old=local.get(row.record_id);
        if(!old||row.updated_at>old.updated_at)local.set(row.record_id,structuredClone(row));
      }},
      acknowledge:async(_id,rows)=>{for(const row of rows){
        if(queue.get(row.record_id)?.updated_at===row.updated_at)queue.delete(row.record_id);
      }}
    }
  };
  const fetcher=async(raw,init)=>{
    const url=new URL(raw,'https://bookai.padiem.net');requests.push({url,method:init.method});
    if(init.method==='POST'){
      postBytes.push(Buffer.byteLength(init.body));const data=JSON.parse(init.body),kept=[];
      for(const row of data.records){
        if((server.get(row.record_id)?.updated_at||0)>row.updated_at)kept.push(row.record_id);
        else server.set(row.record_id,structuredClone(row));
      }
      return {ok:true,json:async()=>({accepted:data.records.length-kept.length,kept_newer:kept})};
    }
    const since=Number(url.searchParams.get('since')),limit=Math.min(cap,Number(url.searchParams.get('limit')));
    const candidates=Array.from(server.values()).filter(row=>row.updated_at>since).sort((a,b)=>a.updated_at-b.updated_at);
    const rows=candidates.slice(0,limit);
    return {ok:true,json:async()=>({records:rows,next_since:rows.at(-1)?.updated_at??since,more:candidates.length>rows.length})};
  };
  let timer=0;
  vm.runInNewContext(source,{window:root,navigator:{onLine:true},TextEncoder,AbortController,fetch:fetcher,
    setTimeout:()=>++timer,clearTimeout:()=>{},setInterval:callback=>{periodic=callback;return ++timer;},console});
  return {root,release,server,local,queue,requests,postBytes,cursor:()=>cursor,poll:()=>periodic()};
}
(async()=>{
  const paged=harness({remote:Array.from({length:620},(_,i)=>record('same-'+i))});
  const waiting=paged.root.BookAISync.syncNow();
  await Promise.resolve();assert.equal(paged.requests.length,0,'must wait for actual UI readiness');
  paged.release();assert.equal((await waiting).state,'synced');
  assert.equal(paged.local.size,620);assert.equal(paged.cursor(),100);
  assert.ok(paged.requests.some(r=>Number(r.url.searchParams.get('limit'))>500));
  const delayed=harness({remote:[record('newer-online','online',200)]});
  delayed.release();await delayed.root.BookAISync.syncNow();
  assert.equal(delayed.cursor(),200);
  delayed.server.set('older-offline',record('older-offline','delayed upload',100));
  await delayed.root.BookAISync.syncNow();
  assert.equal(delayed.local.has('older-offline'),false,'incremental cursor cannot see an older offline upload');
  await delayed.poll();await delayed.root.BookAISync.syncNow();
  assert.equal(delayed.local.get('older-offline').payload.body,'delayed upload');
  assert.equal(delayed.local.size,2,'periodic full reconciliation must recover delayed offline records');
  const cap=harness({remote:Array.from({length:620},(_,i)=>record('cap-'+i)),cap:500});
  cap.release();const limited=await cap.root.BookAISync.syncNow();
  assert.equal(limited.state,'queued');assert.equal(limited.reason,'sync_cursor_page_limit');
  assert.equal(cap.cursor(),99,'must not skip records at an incomplete timestamp');
  const upload=harness({queued:[record('oversized','x'.repeat(6*1024*1024)),
    ...Array.from({length:6},(_,i)=>record('normal-'+i,'n'.repeat(1024*1024)))]});
  upload.release();const sent=await upload.root.BookAISync.syncNow();
  assert.equal(sent.state,'queued');assert.equal(sent.reason,'record_exceeds_sync_limit');
  assert.equal(upload.queue.size,1);assert.ok(upload.queue.has('oversized'));
  assert.equal(upload.server.size,6);assert.ok(upload.postBytes.length>=2);
  assert.ok(upload.postBytes.every(size=>size<=5*1024*1024));
  console.log('PASS: UI-ready gate, 620 equal-time records, late offline upload reconciliation, safe capped cursor, >5MiB batched queue and isolated oversized record');
})().catch(error=>{console.error(error);process.exitCode=1;});