// Actual reader acceptance tests. No isolated storage or fake sync implementation.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const BASE = process.env.B61_BASE_URL || 'http://127.0.0.1:18941/';
const NOTE_KEY = 'storymemory.userMemories.v1';
const ACCOUNT = 'sub_bookai_acceptance';
const pageErrors=[];
async function checkedContext(browser,options){
  const context=await browser.newContext(options);
  context.on('page',page=>page.on('pageerror',error=>pageErrors.push(error.message)));
  return context;
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await sleep(100); }
  throw new Error('Timed out: ' + label);
}
function mockServer() {
  const rows = new Map(), requests = [];
  return {
    rows, requests,
    async install(context, signedIn = true) {
      await context.route('**/auth/session', route => route.fulfill({
        status:200, contentType:'application/json',
        body:JSON.stringify({authenticated:signedIn,account_id:signedIn?ACCOUNT:null})
      }));
      await context.route('**/auth/refresh', route => route.fulfill({
        status:signedIn?200:401,contentType:'application/json',body:'{}'
      }));
      await context.route('**/api/bookai/records**', async route => {
        const request = route.request(), url = new URL(request.url());
        requests.push({method:request.method(),since:url.searchParams.get('since'),limit:url.searchParams.get('limit')});
        if (request.method() === 'POST') {
          const body = request.postDataJSON();
          assert.ok(Array.isArray(body.records), 'POST must contain records');
          assert.ok(Buffer.byteLength(request.postData()) <= 5 * 1024 * 1024, 'POST respects COM2 5 MiB');
          let accepted = 0;
          const kept_newer = [];
          for (const record of body.records) {
            assert.ok(record.record_id && record.book_id && record.locator);
            assert.ok(['progress','note','highlight','ai_chat'].includes(record.kind));
            assert.equal(typeof record.deleted, 'boolean');
            const old = rows.get(record.record_id);
            if (!old || record.updated_at >= old.updated_at) {
              rows.set(record.record_id, structuredClone(record));
              accepted++;
            } else kept_newer.push(record.record_id);
          }
          await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({accepted,kept_newer})});
        } else {
          const since = Number(url.searchParams.get('since') || 0);
          const limit = Math.max(1, Number(url.searchParams.get('limit') || 500));
          const pending = [...rows.values()].filter(row => row.updated_at > since)
            .sort((a,b) => a.updated_at-b.updated_at || a.record_id.localeCompare(b.record_id));
          const records = pending.slice(0,limit);
          const next_since = records.length ? records.at(-1).updated_at : since;
          await route.fulfill({status:200,contentType:'application/json',
            body:JSON.stringify({records,next_since,more:pending.length>records.length})});
        }
      });
    }
  };
}
async function ready(page) {
  try {
    await page.waitForFunction(() => !!window.BookAIReady, null, {timeout:30000});
    await page.evaluate(() => window.BookAIReady);
    await page.waitForFunction(() => typeof openStoredMemoryContext === 'function');
  } catch(error) {
    console.error('STARTUP_DIAGNOSTIC',JSON.stringify({pageErrors,...await page.evaluate(()=>({gate:document.getElementById('bookai-startup')?.textContent,readyType:typeof BookAIReady,readerType:typeof openStoredMemoryContext,scripts:[...document.scripts].map(s=>({src:s.getAttribute('src'),type:s.type,pending:s.hasAttribute('data-bookai-script'),chars:s.textContent.length}))}))}));
    throw error;
  }
}
async function reader(page) {
  await page.evaluate(() => openStoredMemoryContext('사도행전 9장'));
  await page.waitForFunction(() => document.querySelector('#reader')?.classList.contains('active')
    && document.querySelector('#readerPageBody [data-source-locator]')
    && document.querySelector('#readerPageBody').innerText.includes('사울'), null, {timeout:30000});
  if (!await page.locator('#newFreeNote').isVisible()) {
    const opener = page.locator('#memoryRailTab');
    if (await opener.isVisible()) await opener.click();
    else await page.locator('[data-mobile="memory"]').click();
  }
}
async function saved(page) {
  await page.waitForFunction(() => {
    const status=document.getElementById('todayDataStatus');
    return status && !status.classList.contains('saving') && !status.classList.contains('error');
  }, null, {timeout:30000});
  await page.evaluate(() => BookAILocalDB.flush());
}
async function note(page, body) {
  await page.locator('#newFreeNote').click();
  await page.locator('#memoryNoteInput').fill(body);
  await page.locator('#saveMemoryNote').click();
  await saved(page);
}
async function notes(page) {
  return page.evaluate(async key => JSON.parse(await BookAILocalDB.get(key)||'[]'), NOTE_KEY);
}
async function edit(page, previous, replacement) {
  const row = page.locator('#userMemoryList .user-memory-entry').filter({hasText:previous});
  await row.getByTitle('편집',{exact:true}).click();
  await page.locator('#memoryNoteInput').fill(replacement);
  await page.locator('#saveMemoryNote').click();
  await saved(page);
}
async function deleteNote(page, body) {
  await page.locator('#userMemoryList .user-memory-entry').filter({hasText:body})
    .getByTitle('삭제',{exact:true}).click();
  await saved(page);
}
async function receive(page) {
  // Deterministic invocation of the actual periodic GET/POST loop (no mocked client).
  await page.evaluate(() => BookAISync.syncNow());
}
async function migration(browser) {
  const context = await checkedContext(browser,{viewport:{width:1440,height:1000}});
  const server = mockServer(); await server.install(context,false);
  const stamp = 1700000000000;
  const oldNotes = Array.from({length:125},(_,i)=>({
    id:'legacy-note-'+i,seq:i+1,kind:i%2?'note':'ai',context:'이전 책',page:i,
    source:'이전 책',body:'옛 기록 '+i+' — 온전히 보관',question:i%2?'':'옛 질문 '+i,
    title:'기억 '+i,quote:'인용 '+i,createdAt:stamp+i,updatedAt:stamp+i
  }));
  const oldV2 = Array.from({length:85},(_,i)=>({
    id:'legacy-ann-'+i,seq:i+1,context:'이전 책',page:i,text:'밑줄 '+i,type:'annot-line',
    verse:'1',source:'이전 책',clientUpdatedAt:stamp+i
  }));
  const oldV1 = Array.from({length:505},(_,i)=>({
    id:'an-legacy-'+i,kind:i%2?'underline':'memo',locator:'iliad:book:1:line:9',
    unit:'iliad:book:1',start:0,end:4,text:'line',...(i%2?{}:{note:'보관할 메모 '+i}),createdAt:stamp+i
  }));
  const legacy = {
    [NOTE_KEY]:JSON.stringify(oldNotes),
    'storymemory.annotations.v2':JSON.stringify(oldV2),
    'storymemory.annotations.v1':JSON.stringify({version:1,items:oldV1}),
    ['storymemory.readerProgress.'+encodeURIComponent('이전 책')]:JSON.stringify({page:19,context:'이전 책',updatedAt:stamp}),
    'storymemory.readingProgress.v1':JSON.stringify({version:1,works:{iliad:{furthest_read_locator:'iliad:book:1:line:9',knowledge_ceiling_locator:'iliad:book:1:line:9',updatedAt:stamp}}}),
    'storymemory.auditMigration.v1':JSON.stringify({text:'알 수 없는 이전 기록도 보존',array:[1,2,3]})
  };
  // An init script runs before any application script, on the same origin.
  await context.addInitScript(data => {
    if (!localStorage.getItem('__bookai_acceptance_seed')) {
      for (const [key,value] of Object.entries(data)) localStorage.setItem(key,value);
      localStorage.setItem('__bookai_acceptance_seed','1');
    }
  },legacy);
  const page = await context.newPage();
  await page.goto(BASE,{waitUntil:'load'}); await ready(page);
  const after = await page.evaluate(async keys => {
    const db={},original={}; for(const key of keys){db[key]=await BookAILocalDB.get(key);original[key]=localStorage.getItem(key);}
    return {db,original};
  },Object.keys(legacy));
  assert.deepEqual(after.original,legacy,'native legacy keys remain byte-for-byte intact');
  function retained(before,afterRows,label) {
    assert.equal(afterRows.length,before.length,label+' record count');
    for(const row of before) {
      const actual=afterRows.find(item=>item.id===row.id);
      assert.ok(actual,label+' ID '+row.id);
      for(const [key,value] of Object.entries(row)) assert.deepEqual(actual[key],value,label+' '+row.id+'.'+key);
    }
  }
  retained(oldNotes,JSON.parse(after.db[NOTE_KEY]),'note/AI migration');
  retained(oldV2,JSON.parse(after.db['storymemory.annotations.v2']),'legacy underline migration');
  retained(oldV1,JSON.parse(after.db['storymemory.annotations.v1']).items,'locator annotation migration');
  for(const key of Object.keys(legacy).filter(key=>!key.includes('annotations')&&key!==NOTE_KEY))
    assert.equal(after.db[key],legacy[key],'other key preserved: '+key);
  assert.equal(server.requests.length,0,'guest does not synchronize');
  await page.reload({waitUntil:'load'}); await ready(page);
  assert.equal((await notes(page)).length,oldNotes.length,'reload does not re-import or truncate');
  await context.close();
  console.log('PASS 1/4: same-origin migration preserves 715 records plus progress/other keys; byte-identical legacy retained');
}
async function largeScreen(browser) {
  const context = await checkedContext(browser,{viewport:{width:1440,height:1000}});
  const server=mockServer();await server.install(context,false);
  const page=await context.newPage();await page.goto(BASE);await ready(page);await reader(page);
  const bodies=Array.from({length:6},(_,i)=>'BOOKAI_LARGE_'+i+'\n'+'x'.repeat(1024*1024));
  for(const body of bodies)await note(page,body);
  const stored=await notes(page);
  assert.ok(Buffer.byteLength(JSON.stringify(stored))>5*1024*1024,'actual reader stored more than 5MiB');
  assert.deepEqual(stored.map(x=>x.body),bodies);
  assert.equal(await page.evaluate(key=>localStorage.getItem(key),NOTE_KEY),null,'native localStorage did not receive notes');
  await page.reload();await ready(page);await reader(page);
  assert.deepEqual((await notes(page)).map(x=>x.body),bodies);
  for(let i=0;i<bodies.length;i++){
    await page.locator('#userMemoryList .user-memory-entry').filter({hasText:'BOOKAI_LARGE_'+i}).getByTitle('편집',{exact:true}).click();
    assert.equal(await page.locator('#memoryNoteInput').inputValue(),bodies[i],'actual editor restores full note '+i);
    await page.locator('#cancelMemoryNote').click();
  }
  assert.equal(server.requests.length,0);
  await context.close();
  console.log('PASS 2/4: actual reader saves >6 MiB, reloads, and restores all six complete notes into editor');
}
async function synchronization(browser) {
  const server=mockServer();
  const a=await checkedContext(browser,{viewport:{width:1440,height:1000}});
  const b=await checkedContext(browser,{viewport:{width:1440,height:1000}});
  await server.install(a);await server.install(b);
  const pa=await a.newPage(),pb=await b.newPage();
  await pa.goto(BASE);await ready(pa);await reader(pa);
  await until(()=>pa.evaluate(()=>BookAISession.getAccountId()==='sub_bookai_acceptance'),'authenticated account');
  await until(()=>server.requests.some(x=>x.method==='GET'),'automatic startup GET');
  await a.setOffline(true);
  await note(pa,'OFFLINE_NOTE retained on this device');
  await until(()=>pa.evaluate(()=>BookAISync.status().state==='offline'),'automatic offline retry leaves queue intact');
  assert.ok(await pa.evaluate(async()=> (await BookAILocalDB.pending(BookAISession.getAccountId())).length>0),'offline outbox is durable');
  assert.equal([...server.rows.values()].some(row=>JSON.stringify(row.payload).includes('OFFLINE_NOTE')),false);
  await a.setOffline(false);
  await until(()=>[...server.rows.values()].some(row=>!row.deleted&&JSON.stringify(row.payload).includes('OFFLINE_NOTE')),'automatic online POST');
  console.log('PASS 3/4: offline reader save survives, reconnect automatically sends queued record');
  await pb.goto(BASE);await ready(pb);await reader(pb);
  await until(async()=> (await notes(pb)).some(row=>row.body==='OFFLINE_NOTE retained on this device'),'device B startup GET applies note');
  await a.setOffline(true);await b.setOffline(true);
  await note(pa,'DEVICE_A independent note');
  await note(pb,'DEVICE_B independent note');
  await edit(pa,'OFFLINE_NOTE retained on this device','SHARED first edit on A');
  await edit(pb,'OFFLINE_NOTE retained on this device','SHARED latest edit on B');
  await a.setOffline(false);await b.setOffline(false);
  await until(()=>[...server.rows.values()].some(row=>JSON.stringify(row.payload).includes('DEVICE_A'))&&
    [...server.rows.values()].some(row=>JSON.stringify(row.payload).includes('DEVICE_B')),'both device POST queues');
  await receive(pa);await receive(pb);
  await until(async()=> {
    const na=await notes(pa),nb=await notes(pb);
    return ['DEVICE_A independent note','DEVICE_B independent note','SHARED latest edit on B'].every(body=>
      na.some(x=>x.body===body)&&nb.some(x=>x.body===body));
  },'two devices merge independent records and latest edit');
  await deleteNote(pa,'DEVICE_A independent note');
  await until(()=>[...server.rows.values()].some(row=>row.deleted),'server stores deletion tombstone');
  await receive(pb);
  await until(async()=>!(await notes(pb)).some(row=>row.body==='DEVICE_A independent note'),'device B applies deletion');
  await pb.reload();await ready(pb);
  assert.equal((await notes(pb)).some(row=>row.body==='DEVICE_A independent note'),false,'deleted record stays deleted after reload');
  assert.ok(server.requests.some(x=>x.method==='GET'&&Number(x.since)>0),'incremental GET uses nonzero since cursor');
  const sample=[...server.rows.values()].find(row=>row.kind==='note'&&!row.deleted);
  const timestamp=Date.now()+1000;
  for(let i=0;i<620;i++){
    const slot='same-time-'+String(i).padStart(4,'0');
    const value={...sample.payload.value,id:slot,body:'SAME_TIMESTAMP '+i,createdAt:timestamp,updatedAt:timestamp};
    const record_id='bookai-'+require('node:crypto').createHash('sha256').update(NOTE_KEY+'\n'+slot).digest('hex');
    server.rows.set(record_id,{...sample,record_id,updated_at:timestamp,
      payload:{_bookai:{key:NOTE_KEY,mode:'array',slot},value}});
  }
  await receive(pa);await receive(pb);
  await until(async()=> (await notes(pa)).filter(x=>x.id.startsWith('same-time-')).length===620&&
    (await notes(pb)).filter(x=>x.id.startsWith('same-time-')).length===620,'all 620 equal-time records cross pagination boundary');
  assert.ok(server.requests.some(x=>x.method==='GET'&&Number(x.limit)>500),'timestamp boundary expands GET page');
  await a.close();await b.close();
  console.log('PASS 4/4: two real reader contexts merge independent notes, latest edit, tombstone deletion and reload');
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {await migration(browser);await largeScreen(browser);await synchronization(browser);assert.deepEqual(pageErrors,[],'no browser page errors');}
  finally {await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
