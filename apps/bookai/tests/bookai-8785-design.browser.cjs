const test=require('node:test'),assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const base=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
const chrome=process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';
let browser;
test.before(async()=>{browser=await chromium.launch({headless:true,executablePath:chrome});});
test.after(async()=>{await browser?.close();});
async function pageAt(width=1440,screen='index',theme='default'){
 const p=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:'reduce'});
 await p.route('**/*',r=>{let u=new URL(r.request().url());return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?r.continue():r.abort();});
 await p.goto(base,{waitUntil:'domcontentloaded',timeout:30000});await p.waitForTimeout(1200);
 await p.evaluate(t=>{document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-glass','smr-theme-sepia');if(t!=='default')document.body.classList.add('smr-theme-'+t)},theme);
 if(screen==='index'){
  await p.evaluate(()=>document.getElementById('openBook')?.click());
  await p.waitForTimeout(1150);
  assert.equal(await p.evaluate(()=>document.querySelector('.screen.active')?.id),'index','책·장 선택 진입');
 }else if(screen==='today'){
  await p.evaluate(()=>document.getElementById('todayEntry')?.click());
  await p.waitForTimeout(300);
 }
 return p;
}
const contrast=(a,b)=>{const l=x=>(x.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
 return (Math.max(l(a),l(b))+.05)/(Math.min(l(a),l(b))+.05);};
test('#8785-1 150장 번호 선택은 기존 읽기 격자를 재사용하고 44px 단추로 38장에 이동',async()=>{
 const p=await pageAt(390);
 try{
  await p.evaluate(()=>{renderVolumes('old',{preserve:false});applyVolumeSelection('시편',document.querySelector('[data-volume="시편"]'));});
  const trigger=p.locator('#chapterNumberPick');
  assert.ok(await trigger.count(),'장 번호로 고르기 단추 누락');
  assert.ok((await trigger.boundingBox()).height>=44,'격자 열기 44px');
  await trigger.click();
  const grid=p.locator('#sm7573ChapterGrid');
  assert.ok(await grid.isVisible(),'기존 읽기 번호 격자 사용');
  assert.equal(await p.locator('.sm7573-grid-cell').count(),150,'시편 150개 번호');
  for(const n of [1,38,150]){let b=p.locator('.sm7573-grid-cell').filter({hasText:new RegExp('^'+n+'$')});const r=await b.boundingBox();assert.ok(r.height>=44&&r.width>=44,'번호 터치 44px '+n);}
  await p.locator('.sm7573-grid-cell').filter({hasText:/^38$/}).click();
  assert.equal(await p.evaluate(()=>selectedChapter),38);
  assert.equal(await p.locator('#chapterTrack .chapter-stack.on').getAttribute('data-chapter'),'38');
  assert.equal(await p.evaluate(()=>document.querySelector('.screen.active')?.id),'index','선택은 읽기 실행이 아니라 카드 이동');
 }finally{await p.close();}
});
test('#8785-1 150장은 점 대신 1 / 150 숫자로 표시',async()=>{
 const p=await pageAt(390);
 try{
  await p.evaluate(()=>{renderVolumes('old',{preserve:false});applyVolumeSelection('시편',document.querySelector('[data-volume="시편"]'));});
  assert.equal(await p.locator('#chapterDots .chapter-dot').count(),0,'150장에는 점 표시 없어야 함');
  assert.equal((await p.locator('#chapterDots').innerText()).trim(),'1 / 150');
  assert.equal(await p.locator('#chapterCarousel .chapter-specimen').evaluate(e=>getComputedStyle(e).display),'none','긴 장 숫자와 왼쪽 01 중복 제거');
 }finally{await p.close();}
});
test('#8785-2 책장 양끝 화살표 44px과 책 이름 글자 잘림 0',async()=>{
 const p=await pageAt(1440);
 try{
  for(const sel of ['#volumePrev','#volumeNext']){const e=p.locator(sel);assert.ok(await e.count(),sel+' 누락');const r=await e.boundingBox();assert.ok(r.width>=44&&r.height>=44,sel+' 44px');}
  const v=await p.evaluate(()=>{
   const el=document.querySelector('#volumes'),before=el.scrollLeft;
   document.getElementById('volumeNext').click();return {before,after:el.scrollLeft};
  });
  await p.waitForTimeout(400);
  assert.ok((await p.evaluate(()=>document.querySelector('#volumes').scrollLeft))>v.before,'오른쪽 책장 이동');
  const frame=await p.evaluate(()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {header:r('#index .index-top').bottom,tabs:r('#index .testament-tabs').top,rail:r('#index .sm-volume-rail').top,book:r('#volumes .volume.on').top};});
  assert.ok(frame.tabs>=frame.header+6&&frame.rail>=frame.header+6&&frame.book>=frame.header+6,'책장이 머리줄 뒤로 가려짐 '+JSON.stringify(frame));
  const books=await p.evaluate(()=>[...document.querySelectorAll('#volumes .volume')].map(e=>({name:e.querySelector('b')?.textContent,scroll:e.querySelector('b')?.scrollWidth,client:e.querySelector('b')?.clientWidth})));
  assert.ok(books.some(b=>b.name==='데살로니가전서'),'긴 책 이름 사례');
  assert.ok(books.every(b=>b.scroll<=b.client+1),'책 이름 잘림: '+JSON.stringify(books.filter(b=>b.scroll>b.client+1)));
  await p.setViewportSize({width:390,height:844});await p.waitForTimeout(250);
  const small=await p.evaluate(()=>[...document.querySelectorAll('#volumes .volume')].map(e=>({name:e.querySelector('b')?.textContent,scroll:e.querySelector('b')?.scrollWidth,client:e.querySelector('b')?.clientWidth})));
  assert.ok(small.every(b=>b.scroll<=b.client+1),'390 책 이름 잘림: '+JSON.stringify(small.filter(b=>b.scroll>b.client+1)));
 }finally{await p.close();}
});
test('#8785-3 책·장 선택 이름표 12px·설명 13px 및 대비 4.5',async()=>{
 const p=await pageAt(1440);
 try{
  const s=await p.evaluate(()=>{
   const selectors=[
    ['.index-top .crumb',12,'rgb(255,253,249)'],
    ['.volume-focus-titleblock small',12,'rgb(255,253,249)'],
    ['.volume-focus-fact small',12,'rgb(255,253,249)'],
    ['.resume-seal',12,'rgb(255,253,249)'],
    ['#volumes .volume.on small',13,'rgb(75,65,53)'],
    ['.chapter-stack.on .chapter-preview',13,'rgb(255,253,248)'],
    ['.chapter-stack.on .chapter-folio',13,'rgb(255,253,248)']
   ];
   return selectors.map(([sel,min,bg])=>{const e=document.querySelector(sel);if(!e)return {sel,missing:true};
     const c=getComputedStyle(e),r=e.getBoundingClientRect();return {sel,min,bg,text:e.textContent.trim().slice(0,70),font:parseFloat(c.fontSize),color:c.color,rect:{w:r.width,h:r.height}};});
  });
  for(const x of s){assert.ok(!x.missing,'요소 없음 '+x.sel);assert.ok(x.font>=x.min,x.sel+' '+x.font+'px');assert.ok(contrast(x.color,x.bg)>=4.5,x.sel+' 대비 '+contrast(x.color,x.bg).toFixed(2));}
 }finally{await p.close();}
});
test('#8785-4 SWIPE WHEEL 66 BOOKS 세로 글 없음',async()=>{
 const p=await pageAt(1440);
 try{const c=await p.evaluate(()=>getComputedStyle(document.querySelector('#volumes'),'::before').content);assert.ok(!/SWIPE|WHEEL|66 BOOKS/i.test(c),'세로 글 '+c);}
 finally{await p.close();}
});
test('#8785-6 어두운 책장 바탕은 테마 토큰에 연결',async()=>{
 const p=await pageAt(1440,'index','dark');
 try{
  const x=await p.evaluate(()=>{const e=document.querySelector('#volumes'),c=getComputedStyle(e);
    return {token:getComputedStyle(document.body).getPropertyValue('--sm-index-books-bg').trim(),image:c.backgroundImage,color:c.backgroundColor};});
  assert.ok(x.token,'책장 색 토큰 누락');assert.ok(x.image.includes('rgb(38,')||x.color==='rgb(38, 32, 25)','어두운 책장 색: '+JSON.stringify(x));
 }finally{await p.close();}
});
test('#8785-7 주황 장 표 안쪽에 있고 장 카드·읽기 단추 사이 12px',async()=>{
 const p=await pageAt(1440);
 try{
  const x=await p.evaluate(()=>{
    const e=document.querySelector('.chapter-stack.on .paper-layer.top'),tab=e.querySelector('.folio-tab'),nav=document.querySelector('#openChapter');
    const a=e.getBoundingClientRect(),b=tab.getBoundingClientRect(),c=nav.getBoundingClientRect(),pv=e.querySelector('.chapter-preview').getBoundingClientRect(),folio=e.querySelector('.chapter-folio').getBoundingClientRect();
    return {tab:{x:b.x,right:b.right,y:b.y,bottom:b.bottom},card:{x:a.x,right:a.right,y:a.y,bottom:a.bottom},button:{y:c.y},previewBottom:pv.bottom,folioTop:folio.y};
  });
  assert.ok(x.tab.x>=x.card.x&&x.tab.right<=x.card.right&&x.tab.y>=x.card.y&&x.tab.bottom<=x.card.bottom,'장 표 잘림 '+JSON.stringify(x));
  assert.ok(x.button.y-x.card.bottom>=12,'읽기 단추 간격 '+(x.button.y-x.card.bottom).toFixed(1));
  assert.ok(x.folioTop-x.previewBottom>=4,'장 카드 설명/하단 번호 겹침 '+JSON.stringify(x));
 }finally{await p.close();}
});
test('#8785-8 머리줄 바탕 완전 불투명',async()=>{
 const p=await pageAt(1440);
 try{
  const x=await p.evaluate(()=>{const c=getComputedStyle(document.querySelector('#index .index-top'));return {bg:c.backgroundColor,image:c.backgroundImage,blur:c.backdropFilter};});
  assert.ok(x.bg.startsWith('rgb(')&&!x.bg.startsWith('rgba('),'불투명 배경 '+JSON.stringify(x));
 }finally{await p.close();}
});
test('#8960 오늘 빈 상태 안내 keep-all, 서재 순서값 기본, 성경 상태표 새로 시작',async()=>{
 const p=await pageAt(1440);
 try{
  const a=await p.evaluate(()=>{
    const label=document.querySelector('#libraryOrderToggle .sm-menu-state');
    const badge=document.querySelector('.book-rig[data-motif="bible"] .book-reading-state .brs-top');
    return {order:label?.textContent.trim(),badge:badge?.textContent.replace(/\s+/g,' ').trim(),
      badgeJustify:badge&&getComputedStyle(badge).justifyContent};
  });
  assert.equal(a.order,'기본');
  assert.equal(a.badge,'새로 시작');
  assert.equal(a.badgeJustify,'center');
  await p.evaluate(()=>document.getElementById('todayEntry').click());await p.waitForTimeout(400);
  const b=await p.evaluate(()=>({wordBreak:getComputedStyle(document.querySelector('#today .today-recall-preview strong')).wordBreak,
    overflowWrap:getComputedStyle(document.querySelector('#today .today-recall-preview strong')).overflowWrap}));
  assert.equal(b.wordBreak,'keep-all','기억 안내 낱말 분리 금지');
 }finally{await p.close();}
});
