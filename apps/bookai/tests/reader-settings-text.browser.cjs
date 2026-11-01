const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
const p=await b.newPage({viewport:{width:390,height:844}});
await p.goto('http://127.0.0.1:18782/',{waitUntil:'load'});await p.waitForTimeout(1500);
await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
await p.waitForFunction(()=>__smCurrentReaderLabel==='사도행전 9장'&&document.querySelectorAll('#readerPageBody .verse-en').length>0,null,{timeout:15000});
let initial=await p.locator('#readerPageBody .verse:not(.verse-en)').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
await p.locator('#smalOverflowBtn').click();await p.locator('.srsg-btn').click();
await p.locator('.srsg-panel').getByRole('button',{name:'매우 크게'}).click();
let larger=await p.locator('#readerPageBody .verse:not(.verse-en)').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
assert.ok(larger>initial,'font size should grow');
await p.locator('.srsg-panel').getByRole('button',{name:'한글만'}).click();
assert.equal(await p.locator('#readerPageBody .verse-en').first().isVisible(),false);
console.log('PASS: real Acts 9 Korean font grows and English hides');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
