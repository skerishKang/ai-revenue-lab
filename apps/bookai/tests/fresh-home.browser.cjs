const {chromium}=require('playwright');const assert=require('node:assert/strict');
// A fresh install has no reading progress, and the home used to count 0 on its first load while
// every later load counted 3: the bundled entity Memory of the recommended passage
// (고린도전서 3장: 바울·아볼로·하나님의 밭) was only recorded when a stored session was restored.
// The seed is now recorded during boot (index.html, right after the initial reader setup), so
// first load and later loads show the same number and the same Memory ids. This test pins both
// loads; reading progress stays pinned at 0, because a fresh install has never read anything.
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});
const settled=async()=>{await p.evaluate(()=>window.BookAIReady);await p.waitForFunction(()=>typeof todayRecallItems==='function'&&todayRecallItems().length>0&&document.getElementById('todayRecallCount').textContent===String(todayRecallItems().length),null,{timeout:20000});};
const recallIds=()=>todayRecallItems().map(i=>i.id);
const bundled=['entity:고린도전서 3장:바울','entity:고린도전서 3장:아볼로','entity:고린도전서 3장:하나님의 밭'];
await p.goto('http://127.0.0.1:18779/?view=today',{waitUntil:'load'});
await settled();
// First load: the seed must already be there, before any reload.
assert.equal(await p.locator('#todayRecallCount').innerText(),'3');
assert.deepEqual(await p.evaluate(recallIds),bundled);
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
// Later load: same number, same Memory ids.
await p.reload({waitUntil:'load'});
await settled();
assert.equal(await p.locator('#todayRecallCount').innerText(),'3');
assert.deepEqual(await p.evaluate(recallIds),bundled);
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
await p.locator('#todayContinueBtn').click();
await p.waitForFunction(()=>allReaderProgressEntries().length>0,null,{timeout:20000});
await p.reload({waitUntil:'load'});
await p.evaluate(()=>window.BookAIReady);
await p.waitForFunction(()=>allReaderProgressEntries().length>0,null,{timeout:20000});
assert.notEqual(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
await p.close();}console.log('PASS: fresh home shows the same 3 recall Memory on the first load and after reload at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});