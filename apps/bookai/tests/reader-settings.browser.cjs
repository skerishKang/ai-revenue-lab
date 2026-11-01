const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await browser.newPage({viewport:{width,height:844}});
await p.goto('http://127.0.0.1:18782/?view=reader',{waitUntil:'load'});await p.waitForSelector('#smalOverflowBtn');
await p.locator('#smalOverflowBtn').click();await p.locator('.srsg-btn').click();
const panel=p.locator('.srsg-panel');await panel.waitFor({state:'visible'});
await panel.getByRole('button',{name:'한글만'}).click();assert.ok(await p.evaluate(()=>document.body.classList.contains('smr-en-hide')));
await panel.getByRole('button',{name:'크게',exact:true}).click();assert.ok(await p.evaluate(()=>document.body.classList.contains('smr-fs-lg')));
await panel.getByRole('button',{name:'넓게',exact:true}).click();assert.ok(await p.evaluate(()=>document.body.classList.contains('smr-lh-loose')));
await p.reload({waitUntil:'load'});assert.ok(await p.evaluate(()=>document.body.classList.contains('smr-en-hide')&&document.body.classList.contains('smr-fs-lg')&&document.body.classList.contains('smr-lh-loose')));
await p.close()}
console.log('PASS: settings controls and persisted language, size, spacing at 390/1440');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
