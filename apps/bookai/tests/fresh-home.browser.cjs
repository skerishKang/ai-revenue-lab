const {chromium}=require('playwright');const assert=require('node:assert/strict');
// A fresh install has no reading progress. Two things made the old fixed-600ms version flaky:
// the home is rendered after the IndexedDB store is ready (window.BookAIReady), and the very
// first load only seeds that store -- the bundled entity Memory of the recommended passage
// (고린도전서 3장: 바울·아볼로·하나님의 밭) reaches the home once the store is restored, from
// the second load on. So the scenario now waits for readiness, reloads to that steady state,
// and pins the count together with its source; reading progress is pinned at 0 on both loads.
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});
const settled=async()=>{await p.evaluate(()=>window.BookAIReady);await p.waitForFunction(()=>typeof todayRecallItems==='function'&&todayRecallItems().length>0&&document.getElementById('todayRecallCount').textContent===String(todayRecallItems().length),null,{timeout:20000});};
await p.goto('http://127.0.0.1:18779/?view=today',{waitUntil:'load'});
await p.evaluate(()=>window.BookAIReady);
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
await p.reload({waitUntil:'load'});
await settled();
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
assert.equal(await p.locator('#todayRecallCount').innerText(),'3');
assert.deepEqual(await p.evaluate(()=>todayRecallItems().map(i=>i.id)),['entity:고린도전서 3장:바울','entity:고린도전서 3장:아볼로','entity:고린도전서 3장:하나님의 밭']);
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
await p.locator('#todayContinueBtn').click();
await p.waitForFunction(()=>allReaderProgressEntries().length>0,null,{timeout:20000});
await p.reload({waitUntil:'load'});
await p.evaluate(()=>window.BookAIReady);
await p.waitForFunction(()=>allReaderProgressEntries().length>0,null,{timeout:20000});
assert.notEqual(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
await p.close();}console.log('PASS: fresh home, opening reader, and reload preserve real progress at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
