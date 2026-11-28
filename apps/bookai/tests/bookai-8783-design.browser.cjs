const test=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
let browser;
test.before(async()=>{browser=await chromium.launch({headless:true,executablePath:process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});});
test.after(async()=>{await browser?.close();});
async function openPage(width,today=true){
 const page=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:'reduce'});
 await page.route('**/*',r=>{const u=new URL(r.request().url());return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?r.continue():r.abort();});
 await page.goto(BASE,{waitUntil:'domcontentloaded'});await page.waitForTimeout(1400);
 if(today){await page.locator('#todayEntry').click();await page.waitForTimeout(500);}
 return page;
}
const lum=s=>(s.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((x,y,i)=>x+y*[.2126,.7152,.0722][i],0);
const contrast=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
const labels=['#today .today-kicker','#today .today-section-label','#today .today-date-block span','#today .today-panel-head span','#todayContinueMeta','#todayContinueProgressText'];
const buttons=['#todayBack','#todayCloudButton','#todayOpenGlobal','#todayContinueBtn','#todayRecallBtn','#todayAllMemoryBtn','#today .sm-journal-chip','#today .sm-journal-clear'];
const secondary=['#todayContinueNote','#todayRecallCopy','#today .today-empty','#today .sm-journal-summary','#today .sm-journal-empty','#today .sm-journal-search','#today .sm-journal-book'];
for(const width of [390,1440]){
 test('#8783 이름표·단추·보조 글자 하한 및 대비 '+width,async()=>{
  const page=await openPage(width);
  try{
   const a=await page.evaluate(({labels,buttons,secondary})=>{
    const out=[];
    for(const [type,els] of Object.entries({labels,buttons,secondary}))for(const selector of els){
     const el=document.querySelector(selector);if(!el)continue;
     const cs=getComputedStyle(el);if(cs.display==='none')continue;
     out.push({type,selector,text:el.textContent.trim().slice(0,35),size:parseFloat(cs.fontSize),color:cs.color,bg:cs.backgroundColor});
    }
    return out;
   },{labels,buttons,secondary});
   for(const x of a){
    const min=x.type==='labels'?12:x.type==='buttons'?14:13;
    assert.ok(x.size>=min,width+' '+x.selector+'='+x.size+'px / 최소 '+min);
    const dark=/todayContinueMeta|todayContinueProgressText|todayContinueNote/.test(x.selector);
    const bg=dark?'rgb(48,44,50)':x.selector==='#todayContinueBtn'?'rgb(244,233,220)':x.bg==='rgb(61, 53, 47)'?x.bg:'rgb(244,238,231)';
    assert.ok(contrast(x.color,bg)>=4.5,width+' '+x.selector+' 대비 '+contrast(x.color,bg).toFixed(2));
   }
  }finally{await page.close();}
 });
 test('#8783 제목 낱말 분리·이탤릭 없음 '+width,async()=>{
  const page=await openPage(width);
  try{
   const s=await page.evaluate(()=>{
    const h=document.querySelector('#today .today-intro h1'),em=h.querySelector('em'),rg=document.createRange();rg.selectNodeContents(em);
    return {break:getComputedStyle(h).wordBreak,style:getComputedStyle(em).fontStyle,
      rects:[...rg.getClientRects()].filter(r=>r.width>1).map(r=>r.width),scroll:document.documentElement.scrollWidth};
   });
   assert.equal(s.break,'keep-all');assert.equal(s.style,'normal');
   assert.equal(s.rects.length,1,'문장 나뉨 '+JSON.stringify(s));
   if(width===390)assert.ok(s.rects[0]<=358,'390 문장 폭 '+s.rects[0]);
   assert.ok(s.scroll<=width);
  }finally{await page.close();}
 });
}
test('#8783 기억 0개 문구·본문 읽기만·중복 저장 글 없음',async()=>{
 const page=await openPage(1440);
 try{
  const x=await page.evaluate(()=>({
   total:__smUserMemories.length+__smAnnotations.length,
   copy:document.getElementById('todayRecallCopy').textContent,
   preview:document.getElementById('todayRecallPreview').textContent,
   button:document.getElementById('todayRecallBtn').textContent.trim(),
   more:document.getElementById('todayAllMemoryBtn').getBoundingClientRect().height,
   status:getComputedStyle(document.getElementById('todayDataStatus')).display,
   cloud:document.getElementById('todayCloudLabel').textContent.trim()
  }));
  assert.equal(x.total,0);
  assert.ok((x.copy+x.preview).includes('아직 기억이 없습니다. 읽다가 표시하거나 메모를 남기면 여기에 모입니다.'),JSON.stringify(x));
  assert.ok(!x.preview.includes('오늘의 복습을 마쳤습니다.'),JSON.stringify(x));
  assert.equal(x.button,'본문 읽기');assert.equal(x.more,0);
  assert.equal(x.status,'none');assert.equal(x.cloud,'기기 저장');
 }finally{await page.close();}
});
test('#8783 기억 1개는 NOTE 대신 메모, 복습 시작 유지',async()=>{
 const page=await openPage(390);
 try{
  const x=await page.evaluate(()=>{
   __smUserMemories.push({id:'qa-8783-1',kind:'note',title:'시험 메모',body:'본문',context:'고린도전서 3장',createdAt:Date.now(),updatedAt:Date.now()});
   renderTodayHome();
   return {n:document.getElementById('todayMemoryCount').textContent,
    kind:document.querySelector('#todayMemoryList .today-memory-row small')?.textContent,
    button:document.getElementById('todayRecallBtn').textContent,
    preview:document.getElementById('todayRecallPreview').textContent};
  });
  assert.equal(x.n,'1');assert.equal(x.kind,'메모');assert.equal(x.button,'복습 시작');
  assert.ok(!x.preview.includes('아직 기억이 없습니다.'));
 }finally{await page.close();}
});
test('#8783 이 책 기억만·필터 초기화 칩 모양 44px',async()=>{
 const page=await openPage(390);
 try{
  const x=await page.evaluate(()=>{
   const f=document.querySelector('#today .sm-memory-focus'),b=document.querySelector('#today .sm-journal-clear');
   const cs=getComputedStyle(b),r=b.getBoundingClientRect();
   return {filter:f.textContent.trim(),clear:b.textContent.trim(),size:parseFloat(cs.fontSize),height:r.height,width:r.width,
    border:cs.borderTopStyle,bg:cs.backgroundColor};
  });
  assert.equal(x.filter,'이 책 기억만');assert.equal(x.clear,'필터 초기화');
  assert.ok(x.height>=44&&x.width>=44&&x.size>=14,JSON.stringify(x));
  assert.ok(x.border!=='none'&&x.bg!=='rgba(0, 0, 0, 0)',JSON.stringify(x));
 }finally{await page.close();}
});
test('#8781 1440 작은 책 표 성경 하나만·12px 이상',async()=>{
 const page=await openPage(1440,false);
 try{
  const rows=await page.evaluate(()=>[...document.querySelectorAll('#library .book-rig:not(.motion-echo)')].map(e=>{
   const v=e.querySelector('.book-reading-state'),s=getComputedStyle(v);
   const r=v.getBoundingClientRect(),front=e.querySelector('.book-front').getBoundingClientRect();
   return {book:e.dataset.motif,display:s.display,opacity:parseFloat(s.opacity),
    b:parseFloat(getComputedStyle(v.querySelector('b')).fontSize),
    small:parseFloat(getComputedStyle(v.querySelector('small')).fontSize),
    z:new DOMMatrixReadOnly(s.transform).m43,
    width:r.width,height:r.height,badgeTop:r.top,frontTop:front.top};
  }));
  assert.ok(rows.length>=5);
  for(const x of rows)if(x.book==='bible'){
   assert.notEqual(x.display,'none');assert.ok(x.opacity>=.9);assert.ok(x.b>=12&&x.small>=12,JSON.stringify(x));
   assert.ok(x.z>=45&&x.width>=90&&x.height>=32&&x.badgeTop<x.frontTop,'실제로 보이는 성경 상태표: '+JSON.stringify(x));
  }else assert.equal(x.display,'none',JSON.stringify(x));
 }finally{await page.close();}
});
test('#8781 확정된 서재 메뉴 문구 표시',async()=>{
 const page=await openPage(390,false);
 try{
  await page.locator('#libOverflow').click();
  const o=await page.evaluate(()=>({
   speed:document.querySelector('#motionToggle span')?.textContent.trim(),
   order:document.querySelector('#libraryOrderToggle')?.textContent.replace(/\s+/g,' ').trim()
  }));
  assert.equal(o.speed,'책장 넘기는 속도');assert.equal(o.order,'책장 순서 · 기본');
 }finally{await page.close();}
});
