const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});await p.goto('http://127.0.0.1:18780/?view=reader',{waitUntil:'load'});await p.waitForTimeout(1500);
const out=await p.evaluate(()=>{
 __smCurrentReaderLabel='사도행전 9장';READER_PAGES=['<p>첫 페이지</p>','<p>바울</p>'];readerPageIndex=0;localStorage.removeItem('storymemory.pinnedEntities.v1');__smV319RefreshMemoryRail();
 const el=[...document.querySelectorAll('.system-memory')].find(x=>(x.dataset.memoryKey||x.querySelector('b')?.textContent?.trim())==='바울');if(!el)throw Error('missing memory item');
 const future={state:el.dataset.memoryVisibility,display:getComputedStyle(el).display};
 localStorage.setItem('storymemory.pinnedEntities.v1',JSON.stringify(['바울']));__smV319RefreshMemoryRail();const pinned=el.style.display;
 localStorage.removeItem('storymemory.pinnedEntities.v1');readerPageIndex=1;__smV319RefreshMemoryRail();const seen={state:el.dataset.memoryVisibility,display:el.style.display};
 __smCurrentReaderLabel='창세기 1장';READER_PAGES=['<p>태초</p>'];readerPageIndex=0;__smV319RefreshMemoryRail();const other={state:el.dataset.memoryVisibility,display:getComputedStyle(el).display};
 return {future,pinned,seen,other};});
assert.deepEqual(out.future,{state:'future',display:'none'});assert.equal(out.pinned,'');assert.deepEqual(out.seen,{state:'seen',display:''});assert.deepEqual(out.other,{state:'unknown',display:'none'});await p.close()}
console.log('PASS: unread, pinned, read and unrelated states at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
