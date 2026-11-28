const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9437/';
let browser;
test.before(async()=>{browser=await chromium.launch({headless:true,executablePath:process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});});
test.after(async()=>await browser?.close());
async function reader(width=1440,theme='default'){
 const p=await browser.newPage({viewport:{width,height:width===390?844:width===2560?1440:900},reducedMotion:'reduce'});
 await p.route('**/*',r=>{const u=new URL(r.request().url());return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?r.continue():r.abort()});
 await p.goto(BASE,{waitUntil:'domcontentloaded'});await p.waitForTimeout(800);
 for(let i=0;i<4;i++){
  if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='index')break;
  await p.evaluate(()=>document.getElementById('openBook')?.click());await p.waitForTimeout(850);
 }
 await p.evaluate(()=>document.querySelector('[data-volume="고린도전서"]')?.click());await p.waitForTimeout(600);
 await p.evaluate(()=>document.querySelector('.chapter-dot[aria-label="고린도전서 3장"]')?.click());await p.waitForTimeout(250);
 for(let i=0;i<4;i++){
  if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;
  await p.evaluate(()=>document.getElementById('openChapter')?.click());await p.waitForTimeout(850);
 }
 await p.waitForTimeout(900);
 await p.evaluate(t=>{document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-sepia','smr-theme-glass');if(t!=='default')document.body.classList.add('smr-theme-'+t)},theme);
 assert.equal(await p.evaluate(()=>document.querySelector('.screen.active')?.id),'reader');
 return p;
}
function contrast(a,b){
 const l=v=>(v.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0);
 const x=l(a),y=l(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
test('#8787-1 last-page next chapter button 44px and click',async()=>{
 const p=await reader();
 try{
  await p.evaluate(()=>{readerPageIndex=READER_PAGES.length-1;renderReaderPage(0)});
  const b=p.locator('#readerPageBody .sm7573-next-chapter');
  assert.ok(await b.count(),'마지막 쪽 다음 장 단추 없음');
  assert.equal((await b.innerText()).trim(),'다음 장: 고린도전서 4장 →');
  const r=await b.boundingBox();assert.ok(r&&r.height>=44);
  await b.click();
  await p.waitForFunction(()=>typeof __smCurrentReaderLabel==='string'&&__smCurrentReaderLabel==='고린도전서 4장',null,{timeout:12000});
  await p.waitForFunction(()=>readerPageIndex===0,null,{timeout:12000});
  assert.equal(await p.evaluate(()=>__smCurrentReaderLabel),'고린도전서 4장');
 }finally{await p.close()}
});
test('#8787-1 last chapter offers next book first chapter',async()=>{
 const p=await reader();
 try{
  await p.evaluate(()=>window.BookAI7573NavigationV1.openBibleChapter('고린도전서',16,'first'));
  await p.waitForFunction(()=>__smCurrentReaderLabel==='고린도전서 16장',null,{timeout:15000});
  await p.waitForFunction(()=>__smDynamicReaderState?.mode==='static'&&READER_PAGES.length>0,null,{timeout:15000});
  await p.evaluate(()=>{readerPageIndex=READER_PAGES.length-1;renderReaderPage(0)});
  const b=p.locator('#readerPageBody .sm7573-next-chapter');
  assert.equal((await b.innerText()).trim(),'다음 책: 고린도후서 1장 →');
  await b.click();
  await p.waitForFunction(()=>__smCurrentReaderLabel==='고린도후서 1장'&&readerPageIndex===0,null,{timeout:15000});
 }finally{await p.close()}
});
test('#8787-1 first page previous control labels previous chapter',async()=>{
 const p=await reader(390);
 try{const x=await p.locator('#pageTurnPrev').evaluate(e=>({aria:e.getAttribute('aria-label'),title:e.title}));assert.match(x.aria||'',/이전 장/);assert.match(x.title||'',/이전 장/);}
 finally{await p.close()}
});
test('#8787-2 source right displays current / total pages with font and contrast',async()=>{
 for(const width of [390,1440]){
  const p=await reader(width);
  try{
   const s=await p.evaluate(()=>{
    const r=document.querySelector('#readerPageBody>.sm-verified-source-note'),e=r?.querySelector('.sm-reader-source-page-index');
    const cs=e&&getComputedStyle(e),rr=e?.getBoundingClientRect(),parent=r?.getBoundingClientRect();
    return {text:e?.textContent,fontsize:cs&&parseFloat(cs.fontSize),color:cs?.color,right:rr?.right,parentRight:parent?.right,background:getComputedStyle(document.querySelector('#paper')).backgroundColor,index:readerPageIndex+1,count:READER_PAGES.length};
   });
   assert.equal(s.text,String(s.index)+' / '+s.count+'쪽');
   assert.ok(s.fontsize>=13&&s.right<=s.parentRight+1,'쪽수 크기/정렬 '+JSON.stringify(s));
   assert.ok(contrast(s.color,s.background)>=4.5,'쪽수 대비 '+JSON.stringify(s));
  }finally{await p.close()}
 }
});
test('#8787-3 phone source to arrow gap <=32px on first, middle, last',async()=>{
 const p=await reader(390);
 try{
  const len=await p.evaluate(()=>READER_PAGES.length);
  for(const index of [0,Math.floor((len-1)/2),len-1]){
   const m=await p.evaluate(i=>{readerPageIndex=i;renderReaderPage(0);const a=document.querySelector('#readerPageBody>.sm-verified-source-note')?.getBoundingClientRect(),b=document.getElementById('pageTurnPrev').getBoundingClientRect();return {gap:a&&b?b.top-a.bottom:null,n:READER_PAGES.length,index:readerPageIndex}},index);
   assert.ok(m.gap!==null&&m.gap>=0&&m.gap<=32,'390 출처/넘김 단추 틈 '+JSON.stringify(m));
  }
 }finally{await p.close()}
});
test('#8787-4 wide paper grows and 2560 body 18px+ with 35-45 chars and rails 13px+',async()=>{
 const p=await reader(2560);
 try{
  const m=await p.evaluate(()=>{
   const page=document.querySelector('#paperStack'),verse=document.querySelector('#readerPageBody .verse:not(.verse-en)'),cs=getComputedStyle(verse),r=verse.getBoundingClientRect(),v=document.createElement('canvas').getContext('2d');v.font=cs.font;
   const width=v.measureText('가'.repeat(40)).width/40;
   const lr=document.querySelector('.rail-tab-memory span,#memoryRailTab span,.rail-tab-memory');
   const rr=document.querySelector('#aiRailTab span');
   return {paper:page?.getBoundingClientRect().width,font:parseFloat(cs.fontSize),chars:r.width/width,left:lr&&parseFloat(getComputedStyle(lr).fontSize),right:rr&&parseFloat(getComputedStyle(rr).fontSize)};
  });
  assert.ok(m.paper>=1030,'종이 확대 '+JSON.stringify(m));
  assert.ok(m.font>=18&&m.chars>=35&&m.chars<=45,'본문 크기·행 글자 수 '+JSON.stringify(m));
  assert.ok(m.left>=13&&m.right>=13,'양옆 탭 '+JSON.stringify(m));
 }finally{await p.close()}
});
test('#8787-5 English-together contrast >=4.5 in five themes',async()=>{
 for(const theme of ['default','light','sepia','dark','glass']){
  const p=await reader(1440,theme);
  try{
   const m=await p.evaluate(()=>{
    document.body.classList.remove('smr-en-hide','smr-en-compact');document.body.classList.add('smr-en-together');
    const e=document.querySelector('#readerPageBody .verse-en'),cs=getComputedStyle(e),bg=getComputedStyle(document.querySelector('#paper')).backgroundColor;
    return {color:cs.color,opacity:parseFloat(cs.opacity),bg};
   });
   assert.ok(m.opacity>=.999&&contrast(m.color,m.bg)>=4.5,theme+' 영어 대비 '+contrast(m.color,m.bg).toFixed(2)+' opacity '+m.opacity);
  }finally{await p.close()}
 }
});
test('#8787-6 chapter chip label 13px+',async()=>{
 const p=await reader();
 try{const f=await p.locator('.v2-chapter-chip').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));assert.ok(f>=13,'장 칩 '+f+'px');}
 finally{await p.close()}
});
