const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});await p.goto('http://127.0.0.1:18779/?view=today',{waitUntil:'load'});await p.waitForTimeout(600);
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
assert.equal(await p.locator('#todayRecallCount').innerText(),'0');
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
await p.locator('#todayContinueBtn').click();await p.waitForTimeout(1600);
assert.ok(await p.evaluate(()=>allReaderProgressEntries().length>0));
await p.reload({waitUntil:'load'});await p.waitForTimeout(600);
assert.ok(await p.evaluate(()=>allReaderProgressEntries().length>0));
assert.notEqual(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
await p.close();}console.log('PASS: fresh home, opening reader, and reload preserve real progress at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
