const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await browser.newPage({viewport:{width,height:844}});
await p.goto('http://127.0.0.1:18782/',{waitUntil:'load'});await p.waitForTimeout(1500);
await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
await p.waitForFunction(()=>__smCurrentReaderLabel==='사도행전 9장'&&document.querySelector('#readerPageBody .verse-en')&&document.querySelector('#readerPageBody .verse')?.textContent.includes('사울'),null,{timeout:15000});
const first=p.locator('#readerPageBody .verse:not(.verse-en)').first();
await p.locator('#smalOverflowBtn').click();await p.locator('.srsg-btn').click();
await p.locator('.srsg-panel').getByRole('button',{name:'좁게',exact:true}).click();
const tight=await first.evaluate(e=>parseFloat(getComputedStyle(e).lineHeight));
await p.locator('.srsg-panel').getByRole('button',{name:'넓게',exact:true}).click();
const loose=await first.evaluate(e=>parseFloat(getComputedStyle(e).lineHeight));assert.ok(loose>tight,'loose line height should exceed tight');
const source=await p.locator('#readerPageBody .sm-verified-source-note').first().innerText();
assert.ok(source.includes('KRV-1961')&&source.includes('World English Bible'));
await p.reload({waitUntil:'load'});assert.ok(await p.evaluate(()=>document.body.classList.contains('smr-lh-loose')));await p.close()}
console.log('PASS: real Acts 9 spacing and edition labels at 390/1440');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
