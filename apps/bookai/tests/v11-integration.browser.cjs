const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{let b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{for(const width of [390,1440]){let p=await b.newPage({viewport:{width,height:900}});let errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto('http://127.0.0.1:18783/',{waitUntil:'load'});await p.waitForTimeout(1200);
// #6511 split this app out as 북AI (apps/bookai); the tab title carries the product name,
// not the 1.0 StoryMemory name this test used to pin.
assert.equal(await p.title(),'북AI · 읽고, 묻고, 기억하는 책');
assert.equal(await p.locator('[data-mobile=memory]').textContent(),'기억');
await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
await p.waitForFunction(()=>document.querySelector('#readerPageBody')?.innerText.includes('사울'),null,{timeout:15000});
await p.waitForTimeout(600);
assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
const unknown=await p.locator('.system-memory').evaluateAll(els=>els.filter(x=>x.dataset.memoryVisibility==='unknown').every(x=>getComputedStyle(x).display==='none'));assert.equal(unknown,true);
let x=p.locator('#readerPageBody .verse:not(.verse-en)').first();let before=await x.evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
await p.locator('#smalOverflowBtn').click();await p.locator('.srsg-btn').click();await p.locator('.srsg-panel').getByRole('button',{name:'매우 크게'}).click();let after=await x.evaluate(e=>parseFloat(getComputedStyle(e).fontSize));assert.ok(after>before,'font size increases');
assert.deepEqual(errors,[]);console.log('PASS integration',width);await p.close()}}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});