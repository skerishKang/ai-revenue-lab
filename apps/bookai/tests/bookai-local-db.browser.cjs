const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});
 try {
  const page=await browser.newPage();
  await page.goto(process.env.B61_BASE_URL||'http://127.0.0.1:18821/',{waitUntil:'load'});
  assert.equal(await page.title(),'\uBD81AI \u00b7 \uC77D\uACE0, \uBB3B\uACE0, \uAE30\uC5B5\uD558\uB294 \uCC45');
  assert.match(await page.locator('.lib-head .kicker').innerText(),/\uBD81AI/);
  await page.addScriptTag({url:'/bookai-local-db.js'});
  const results=await page.evaluate(async()=>{
    const a='storymemory.annotations.v2', b='storymemory.readerProgress.book1';
    const beforeA=JSON.stringify([{note:'기록',location:'1:2'}]),beforeB=JSON.stringify({page:14});
    localStorage.setItem(a,beforeA); localStorage.setItem(b,beforeB);
    localStorage.setItem('storymemory.authBridgeState.v1','private');
    await BookAILocalDB.migrate(localStorage);
    const imported=[await BookAILocalDB.get(a),await BookAILocalDB.get(b),await BookAILocalDB.get('storymemory.authBridgeState.v1')];
    await BookAILocalDB.set(a,'updated');
    await BookAILocalDB.migrate(localStorage);
    const repeat=await BookAILocalDB.get(a);
    const huge='한'.repeat(1800000); await BookAILocalDB.set('storymemory.userMemories.v1',huge);
    return {imported,repeat,large:(await BookAILocalDB.get('storymemory.userMemories.v1')).length,original:[localStorage.getItem(a),localStorage.getItem(b)],beforeA,beforeB};
  });
  assert.deepEqual(results.imported,[results.beforeA,results.beforeB,null]);
  assert.deepEqual(results.original,[results.beforeA,results.beforeB]);
  assert.equal(results.repeat,'updated'); assert.equal(results.large,1800000);
  console.log('PASS: IndexedDB foundation preserves legacy values, excludes auth state, is idempotent, and stores >5 MB UTF-8');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
