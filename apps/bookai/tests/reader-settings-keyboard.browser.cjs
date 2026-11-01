const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});
await p.goto('http://127.0.0.1:18782/?view=reader',{waitUntil:'load'});await p.waitForSelector('#smalOverflowBtn');
await p.locator('#smalOverflowBtn').focus();await p.keyboard.press('Enter');
await p.locator('.srsg-btn').focus();await p.keyboard.press('Enter');
await p.locator('.srsg-panel').waitFor({state:'visible'});
assert.equal(await p.evaluate(()=>document.activeElement.className),'srsg-x');
await p.keyboard.press('Escape');assert.equal(await p.locator('.srsg-panel').isVisible(),false);
assert.equal(await p.evaluate(()=>document.activeElement.id),'smalOverflowBtn');await p.close()}
console.log('PASS: keyboard open, close and focus return at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
