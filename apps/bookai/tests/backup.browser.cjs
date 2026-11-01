const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844},acceptDownloads:true});
  await page.goto((process.env.B61_BASE_URL||'http://127.0.0.1:18778/')+'?view=today',{waitUntil:'load'});
  await page.waitForFunction(()=>window.StoryMemoryBackup && window.openStoryMemoryAuth);
  // Since #6547 the durable reader store is IndexedDB behind BookAIStorage, and the export
  // reads that same object. A raw localStorage write is invisible to it, so seed the value
  // through BookAIStorage (the way the app writes) and wait for the commit.
  await page.evaluate(async()=>{BookAIStorage.setItem('storymemory.pinnedEntities.v1','["backup-test"]');await BookAILocalDB.flush();window.openStoryMemoryAuth()});
  const downloadPromise=page.waitForEvent('download',{timeout:10000});
  await page.locator('#smBackupExport').click({timeout:10000});
  const download=await downloadPromise;
  const stream=await download.createReadStream(); let content=''; for await(const chunk of stream)content+=chunk;
  assert.deepEqual(JSON.parse(content).data['storymemory.pinnedEntities.v1'],'["backup-test"]');
  await page.evaluate(async()=>{BookAIStorage.setItem('storymemory.pinnedEntities.v1','["changed"]');await BookAILocalDB.flush()});
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#smBackupFile').setInputFiles({name:'backup.json',mimeType:'application/json',buffer:Buffer.from(content)});
  await page.waitForLoadState('load');
  await page.waitForFunction(()=>BookAIStorage.getItem('storymemory.pinnedEntities.v1')==='["backup-test"]');
  await page.evaluate(async()=>{BookAIStorage.setItem('storymemory.readerProgress.synthetic',JSON.stringify(['\uAC00'.repeat(1800000)]));await BookAILocalDB.flush();window.openStoryMemoryAuth()});
  const oversized=new Promise(resolve=>page.once('dialog',async dialog=>{const type=dialog.type();await dialog.accept();resolve(type)}));
  await page.locator('#smBackupExport').click({timeout:10000});
  assert.equal(await oversized,'alert');
  assert.equal(await page.evaluate(()=>JSON.parse(BookAIStorage.getItem('storymemory.readerProgress.synthetic'))[0].length),1800000);
  console.log('PASS: mobile UI download, restore and oversized backup warning');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
