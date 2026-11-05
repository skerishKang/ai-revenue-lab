const {chromium}=require('playwright');const assert=require('node:assert/strict');
// Owner decision 2026-11-05: the Bible search panel must not create a reader
// grid row. At 375x812 the paper stack must keep top <= 120 and height >= 600.
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
  const p=await browser.newPage({viewport:{width:375,height:812}});
  await p.goto(process.env.B61_BASE_URL||'http://127.0.0.1:18782/',{waitUntil:'load'});
  await p.waitForTimeout(1500);
  await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
  await p.waitForFunction(()=>__smCurrentReaderLabel==='사도행전 9장'&&document.querySelector('#readerPageBody .verse-en'),null,{timeout:15000});
  const parent=await p.locator('#bibleSearchPanel').evaluate(el=>el.parentElement?.className||'');
  assert.ok(parent.includes('paper-head'),'search panel must live inside .paper-head');
  const box=await p.locator('#paperStack').boundingBox();
  assert.ok(box,'paper-stack must have a box');
  assert.ok(box.y<=120,`paper-stack top ${box.y} must be <= 120`);
  assert.ok(box.height>=600,`paper-stack height ${box.height} must be >= 600`);
  console.log(`PASS: 375x812 paper-stack top=${Math.round(box.y)} height=${Math.round(box.height)} parent=${parent}`);
  await p.close();
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
