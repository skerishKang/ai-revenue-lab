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

async function switchFlow(p){
 await p.waitForFunction(()=>typeof __smDynamicReaderState==='object'&&['static','remote'].includes(__smDynamicReaderState.mode)&&__smDynamicReaderState.passages?.length>0,null,{timeout:15000});
 await p.evaluate(()=>{readerPageIndex=0;applyReaderViewMode('flow',{restore:false})});
 await p.waitForTimeout(350);
}
function rect(e){const r=e?.getBoundingClientRect();return r&&{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};}
test('#8789-1 흐름 390·1440 맨 위 머리(장 칩·제목·검색) 표시',async()=>{
 for(const width of [390,1440]){
  const p=await reader(width);
  try{
   await switchFlow(p);
   const x=await p.evaluate(()=>{
    const scroll=document.querySelector('#reader .paper-inner').scrollTop;
    const els=['#reader .v2-chapter-chip','#reader .paper-head h1','#bibleSearchPanel'].map(s=>{const n=document.querySelector(s),r=n?.getBoundingClientRect();return {text:n?.textContent.trim().slice(0,60),top:r?.top,bottom:r?.bottom,width:r?.width,shown:!!r&&r.width>0&&r.height>0&&getComputedStyle(n).display!=='none'};});
    const label=document.querySelector('#bibleSearchPanel>summary strong');
    return {scroll,els,searchLabelWidth:label?.getBoundingClientRect().width};
   });
   assert.ok(x.scroll<=2,width+' 흐름 첫 화면 상단 스크롤 '+JSON.stringify(x));
   assert.ok(x.els.every(o=>o.shown&&o.top>=0&&o.bottom<=p.viewportSize().height),width+' 흐름 머리 '+JSON.stringify(x));
   assert.ok(/고린도전서/.test(x.els[0].text)&&/고린도전서/.test(x.els[1].text),width+' 책 장 이름');
   assert.ok(x.els[2].width>=200&&x.searchLabelWidth>=50,width+' 흐름 검색 상자 및 이름 '+JSON.stringify(x));
  }finally{await p.close();}
 }
});
test('#8789-2 흐름 쪽 이름표·쪽 구분선 0, 출처는 장 끝 1회',async()=>{
 for(const width of [390,1440]){
  const p=await reader(width);
  try{
   await switchFlow(p);
   const x=await p.evaluate(()=>{
    const body=document.querySelector('#readerPageBody'),sections=[...body.querySelectorAll('.reader-flow-section')];
    const note=body.querySelectorAll('.sm-verified-source-note');
    return {pages:READER_PAGES.length,sections:sections.length,folio:body.querySelectorAll('.reader-flow-folio').length,
      notes:note.length,atEnd:note.length===1&&note[0].parentElement===body,sectionNotes:sections.map(x=>x.querySelectorAll('.sm-verified-source-note').length),
      border:sections.map(x=>getComputedStyle(x).borderBottomWidth),labels:[...body.querySelectorAll('*')].filter(x=>x.children.length===0&&/^페이지\s*0\d$/.test(x.textContent.trim())).length};
   });
   assert.ok(x.pages>1,x.pages+'쪽 상태를 검사');
   assert.equal(x.folio,0,'페이지 0N 표시 '+JSON.stringify(x));
   assert.equal(x.labels,0,'쪽 이름표');
   assert.ok(x.border.every(v=>v==='0px'),'쪽 구분선 '+JSON.stringify(x.border));
   assert.equal(x.notes,1,'출처 중복 '+JSON.stringify(x));
   assert.ok(x.atEnd&&x.sectionNotes.every(n=>n===0),'출처는 장 끝에 한 번');
  }finally{await p.close();}
 }
});
test('#8789-3 흐름·페이지 넘김 다음 장 문구 일치 및 공통 함수',async()=>{
 const p=await reader(1440);
 try{
  await p.waitForFunction(()=>typeof __smDynamicReaderState==='object'&&__smDynamicReaderState.passages?.length>0,null,{timeout:15000});
  const pageText=await p.evaluate(()=>{readerPageIndex=READER_PAGES.length-1;renderReaderPage(0);return document.querySelector('#readerPageBody>.sm7573-next-chapter')?.textContent.trim()});
  await switchFlow(p);
  const flowText=await p.locator('#readerPageBody>.sm7573-next-chapter').innerText();
  assert.equal(flowText.trim(),pageText,'두 보기의 다음 장 문구');
  assert.equal(flowText.trim(),'다음 장: 고린도전서 4장 →');
 }finally{await p.close();}
});
test('#8789-4 390 흐름 끝 다음 장 단추와 ⋯ 겹침 0',async()=>{
 const p=await reader(390);
 try{
  await switchFlow(p);
  await p.evaluate(()=>{const x=document.querySelector('#reader .paper-inner');x.style.scrollBehavior='auto';x.scrollTop=x.scrollHeight;});
  await p.waitForTimeout(160);
  const x=await p.evaluate(()=>{
   const a=document.querySelector('#readerPageBody>.sm7573-next-chapter')?.getBoundingClientRect(),b=document.querySelector('#smalOverflowBtn')?.getBoundingClientRect(),
     inner=document.querySelector('#reader .paper-inner').getBoundingClientRect();
   return {button:a&&{left:a.left,right:a.right,top:a.top,bottom:a.bottom},more:b&&{left:b.left,right:b.right,top:b.top,bottom:b.bottom},
    inner:inner&&{bottom:inner.bottom}};
  });
  assert.ok(x.button&&x.more,JSON.stringify(x));
  const overlaps=x.button.left<x.more.right&&x.button.right>x.more.left&&x.button.top<x.more.bottom&&x.button.bottom>x.more.top;
  assert.ok(!overlaps,'⋯ 와 다음 장 겹침 '+JSON.stringify(x));
  assert.ok(x.button.bottom+12<=x.more.top || x.button.right+12<=x.more.left,'다음 장 단추와 ⋯ 사이 12px '+JSON.stringify(x));
 }finally{await p.close();}
});
test('#8789-5 1440 흐름 다음 장 오른쪽 끝 본문 열과 ±2px',async()=>{
 const p=await reader(1440);
 try{
  await switchFlow(p);
  const x=await p.evaluate(()=>{
   const a=document.querySelector('#readerPageBody>.sm7573-next-chapter')?.getBoundingClientRect(),
     b=document.querySelector('#readerPageBody .verse:not(.verse-en)')?.getBoundingClientRect(),
     c=document.querySelector('#readerPageBody>.sm-verified-source-note')?.getBoundingClientRect();
   return {buttonRight:a?.right,verseRight:b?.right,sourceRight:c?.right};
  });
  assert.ok(x.buttonRight&&x.verseRight&&x.sourceRight,JSON.stringify(x));
  assert.ok(Math.abs(x.buttonRight-x.verseRight)<=2,'다음 장·본문 정렬 '+JSON.stringify(x));
  assert.ok(Math.abs(x.buttonRight-x.sourceRight)<=2,'다음 장·출처 정렬 '+JSON.stringify(x));
 }finally{await p.close();}
});
test('#8789-6 1440 이상 페이지 넘김·흐름 제목·본문·출처 좌우 여백 차이 8px 이하',async()=>{
 for(const width of [1440,2560]){
  const p=await reader(width);
  try{
   await p.waitForFunction(()=>typeof __smDynamicReaderState==='object'&&__smDynamicReaderState.passages?.length>0,null,{timeout:15000});
   for(const mode of ['page','flow']){
    await p.evaluate(mode=>{readerPageIndex=0;applyReaderViewMode(mode,{restore:false})},mode);
    await p.waitForTimeout(180);
    const x=await p.evaluate(()=>{
      const box=s=>{const n=document.querySelector(s),r=n?.getBoundingClientRect();return r&&{left:r.left,right:r.right}};
      return {paper:box('#paperStack'),head:box('#reader .paper-head'),search:box('#bibleSearchPanel'),
        verse:box('#readerPageBody .verse:not(.verse-en)'),source:box('#readerPageBody .sm-verified-source-note')};
    });
    assert.ok(x.paper&&x.head&&x.search&&x.verse&&x.source,width+'/'+mode+' elements '+JSON.stringify(x));
    for(const name of ['head','verse','source']){
      const m=x[name],left=m.left-x.paper.left,right=x.paper.right-m.right;
      assert.ok(Math.abs(left-right)<=8,width+'/'+mode+' '+name+' 좌우 여백 '+left.toFixed(1)+'/'+right.toFixed(1));
    }
    assert.ok(x.search.left>=x.head.left-2&&x.search.right<=x.head.right+2,'검색 열 '+JSON.stringify(x));
   }
  }finally{await p.close();}
 }
});

test('#8789-3 마지막 장에서는 다음 책 1장으로 흐름 이어 읽기',async()=>{
 const p=await reader(1440);
 try{
  await p.evaluate(()=>window.BookAI7573NavigationV1.openBibleChapter('고린도전서',16,'first'));
  await p.waitForFunction(()=>__smCurrentReaderLabel==='고린도전서 16장',null,{timeout:15000});
  await p.waitForFunction(()=>__smDynamicReaderState?.mode==='static'&&READER_PAGES.length>0,null,{timeout:15000});
  await switchFlow(p);
  const name=await p.locator('#readerPageBody>.sm7573-next-chapter').innerText();
  assert.equal(name.trim(),'다음 책: 고린도후서 1장 →');
  await p.evaluate(()=>document.querySelector('#readerPageBody>.sm7573-next-chapter').click());
  await p.waitForFunction(()=>__smCurrentReaderLabel==='고린도후서 1장'&&readerPageIndex===0,null,{timeout:15000});
 }finally{await p.close();}
});
test('#8789-6 390 페이지 넘김 쪽수는 흐름 전환 전후 동일',async()=>{
 const p=await reader(390);
 try{
  await p.waitForFunction(()=>__smDynamicReaderState?.mode==='static'&&READER_PAGES.length>0,null,{timeout:15000});
  const before=await p.evaluate(()=>READER_PAGES.length);
  await switchFlow(p);
  const flow=await p.evaluate(()=>READER_PAGES.length);
  await p.evaluate(()=>applyReaderViewMode('page',{restore:false}));
  const after=await p.evaluate(()=>READER_PAGES.length);
  assert.equal(before,flow);assert.equal(after,before);
  assert.ok(before>=2,'쪽 분할 실제 자료');
 }finally{await p.close();}
});
