const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});
  try{
    const page=await browser.newPage();
    await page.route('**/auth/**',route=>route.fulfill({status:200,contentType:'application/json',body:'{"authenticated":false}'}));
    await page.goto(process.env.B61_BASE_URL||'http://127.0.0.1:18941/');
    await page.waitForFunction(()=>!!window.BookAIReady);
    await page.evaluate(()=>BookAIReady);
    const result=await page.evaluate(async()=>{
      const key='storymemory.userMemories.v1';
      const a={id:'race-a',kind:'note',context:'iliad',body:'a-original',updatedAt:1};
      const b={id:'race-b',kind:'note',context:'iliad',body:'b-original',updatedAt:1};
      BookAIStorage.setItem(key,JSON.stringify([a,b]));await BookAILocalDB.flush();
      await BookAILocalDB.bindAccount('race-account');
      let pending=await BookAILocalDB.pending('race-account');
      let remoteB=structuredClone(pending.find(r=>r.payload.value.id===b.id));
      remoteB.updated_at=Date.now()+1000;remoteB.payload.value.body='b-remote';
      // A real pull is in flight while the reader saves its previously loaded array.
      const merge=BookAILocalDB.merge('race-account',[remoteB]);
      BookAIStorage.setItem(key,JSON.stringify([{...a,body:'a-local'},b]));
      await merge;await BookAILocalDB.flush();
      const merged=JSON.parse(await BookAILocalDB.get(key));
      const deleted={...remoteB,deleted:true,updated_at:remoteB.updated_at+1};
      const remove=BookAILocalDB.merge('race-account',[deleted]);
      const current=JSON.parse(BookAIStorage.getItem(key));
      current.find(r=>r.id===a.id).body='a-local-again';
      BookAIStorage.setItem(key,JSON.stringify(current));
      await remove;await BookAILocalDB.flush();
      const afterDelete=JSON.parse(await BookAILocalDB.get(key));
      pending=await BookAILocalDB.pending('race-account');
      const sent=pending.find(r=>r.payload.value.id===a.id);
      const edit=JSON.parse(BookAIStorage.getItem(key));edit[0].body='a-not-yet-sent';
      BookAIStorage.setItem(key,JSON.stringify(edit));
      await BookAILocalDB.acknowledge('race-account',[sent]);await BookAILocalDB.flush();
      const queued=(await BookAILocalDB.pending('race-account')).find(r=>r.payload.value.id===a.id);
      let mismatch=false;
      try{await BookAILocalDB.bindAccount('other-account');}catch(error){mismatch=error.message==='account_mismatch';}
      BookAIStorage.setItem('storymemory.auditOffline.v1','still-writable');await BookAILocalDB.flush();
      return {merged,afterDelete,queued:queued.payload.value.body,mismatch,local:await BookAILocalDB.get('storymemory.auditOffline.v1')};
    });
    assert.deepEqual(result.merged.map(x=>[x.id,x.body]),[['race-a','a-local'],['race-b','b-remote']]);
    assert.deepEqual(result.afterDelete.map(x=>[x.id,x.body]),[['race-a','a-local-again']]);
    assert.equal(result.queued,'a-not-yet-sent');
    assert.equal(result.mismatch,true);assert.equal(result.local,'still-writable');
    console.log('PASS: concurrent reader save preserves remote updates/deletion; stale ACK keeps newer edit; different account cannot poison local storage');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
