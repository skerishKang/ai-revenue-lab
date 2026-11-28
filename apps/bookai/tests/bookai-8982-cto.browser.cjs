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

function geo(s){const el=document.querySelector(s);if(!el)return null;const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,top:r.top,bottom:r.bottom};}
test('#8982 CTO 1: 1920·2560 제목·검색·본문·출처 열은 종이 좌우 여백 차이 8px 이하',async()=>{
 for(const width of [1920,2560]){
  const p=await reader(width,'glass');
  try{
   await p.waitForFunction(()=>typeof __smDynamicReaderState==='object'&&['static','remote'].includes(__smDynamicReaderState.mode)&&__smDynamicReaderState.passages?.length>0,null,{timeout:15000});
   const x=await p.evaluate(()=>{
    const box=sel=>{const n=document.querySelector(sel),r=n?.getBoundingClientRect();return r&&{left:r.left,right:r.right,width:r.width,top:r.top,bottom:r.bottom};};
    return {paper:box('#paperStack'),head:box('#reader .paper-head'),search:box('#bibleSearchPanel'),verse:box('#readerPageBody .verse:not(.verse-en)'),source:box('#readerPageBody>.sm-verified-source-note'),
      page:readerPageIndex,total:READER_PAGES.length};
   });
   assert.ok(x.paper&&x.head&&x.search&&x.verse&&x.source,'필수 본문 열 존재 '+JSON.stringify(x));
   for(const [name,key] of [['제목','head'],['본문','verse'],['출처','source']]){
    const r=x[key],left=r.left-x.paper.left,right=x.paper.right-r.right;
    assert.ok(Math.abs(left-right)<=8,width+' '+name+' 종이 좌우 여백 차이 '+(left-right).toFixed(1)+'px '+JSON.stringify(x));
   }
   assert.ok(x.search.left>=x.head.left-2&&x.search.right<=x.head.right+2,width+' 검색 상자는 본문 열 안 '+JSON.stringify(x));
  }finally{await p.close();}
 }
});
test('#8982 CTO 2: 1440 다음 장 단추 오른쪽 끝이 본문 열·출처 오른쪽과 ±2px',async()=>{
 const p=await reader(1440,'glass');
 try{
  await p.waitForFunction(()=>typeof __smDynamicReaderState==='object'&&['static','remote'].includes(__smDynamicReaderState.mode)&&__smDynamicReaderState.passages?.length>0,null,{timeout:15000});
  await p.evaluate(()=>{readerPageIndex=READER_PAGES.length-1;renderReaderPage(0)});
  const g=await p.evaluate(()=>{
   const box=s=>{const n=document.querySelector(s),r=n?.getBoundingClientRect();return r&&{left:r.left,right:r.right,width:r.width,top:r.top,bottom:r.bottom};};
   return {button:box('#readerPageBody>.sm7573-next-chapter'),verse:box('#readerPageBody .verse:not(.verse-en)'),source:box('#readerPageBody>.sm-verified-source-note')};
  });
  assert.ok(g.button&&g.verse&&g.source,'다음 장 단추 또는 본문 열 누락 '+JSON.stringify(g));
  assert.ok(Math.abs(g.button.right-g.verse.right)<=2,'다음 장 단추/본문 오른쪽 끝 차이 '+(g.button.right-g.verse.right).toFixed(1)+'px');
  assert.ok(Math.abs(g.button.right-g.source.right)<=2,'다음 장 단추/출처 오른쪽 끝 차이 '+(g.button.right-g.source.right).toFixed(1)+'px');
 }finally{await p.close();}
});
