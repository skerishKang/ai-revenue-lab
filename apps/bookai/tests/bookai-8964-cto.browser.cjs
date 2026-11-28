const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const url=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
const chrome=process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';
async function setup(width,theme='default'){
 const browser=await chromium.launch({headless:true,executablePath:chrome});
 const page=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:'reduce'});
 await page.route('**/*',r=>{const host=new URL(r.request().url()).hostname;return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(host)?r.continue():r.abort()});
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});
 await page.waitForTimeout(800);
 await page.evaluate(theme=>{document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-sepia','smr-theme-glass');if(theme!=='default')document.body.classList.add('smr-theme-'+theme);document.querySelector('#openBook')?.click()},theme);
 await page.waitForTimeout(1250);
 assert.equal(await page.evaluate(()=>document.querySelector('.screen.active')?.id),'index');
 return {browser,page,close:async()=>browser.close()};
}
test('#8964 CTO 1: 양옆 장 카드의 번호 중앙과 쪽수 사이 간격 12px 이상',async()=>{
 const ctx=await setup(1440);
 try{
  const cards=await ctx.page.evaluate(()=>[...document.querySelectorAll('.chapter-stack:not(.on)')].filter(e=>['1','2','4','5'].includes(e.dataset.chapter)).map(e=>{
   const r=n=>n.getBoundingClientRect(),card=r(e.querySelector('.paper-layer.top')),num=r(e.querySelector('.chapter-no')),folio=r(e.querySelector('.chapter-folio'));
   return {chapter:e.dataset.chapter,offset:(num.top+num.height/2)-(card.top+card.height/2),gap:folio.top-num.bottom};
  }));
  assert.equal(cards.length,4,'1·2·4·5 카드 모두 검사');
  for(const c of cards){assert.ok(Math.abs(c.offset)<=16,'가운데 번호 '+JSON.stringify(c));assert.ok(c.gap>=12,'번호/쪽수 최소 12px '+JSON.stringify(c));}
 }finally{await ctx.close()}
});
test('#8964 CTO 2: 어둡게 머리줄의 불투명 배경과 hit-test 차폐',async()=>{
 const ctx=await setup(1440,'dark');
 try{
  const x=await ctx.page.evaluate(()=>{
   const head=document.querySelector('#index .index-top'),cs=getComputedStyle(head),bg=cs.backgroundColor;
   const top=head.getBoundingClientRect();const points=[180,700,880,970,1250].flatMap(x=>[15,35,55].map(y=>({x,y,target:document.elementFromPoint(x,y),within:head.contains(document.elementFromPoint(x,y))})));
   return {bg,token:getComputedStyle(document.body).getPropertyValue('--sm-index-header-bg').trim(),headTop:top.top,headBottom:top.bottom,hit:points.map(({x,y,within})=>({x,y,within}))};
  });
  assert.match(x.bg,/^rgb\(\d+, \d+, \d+\)$/,'불투명 어두운 배경 '+x.bg);
  assert.ok(x.token.length>0,'어둡게 토큰');
  assert.ok(x.hit.every(p=>p.within),'머리줄 뒤 글자·단추 비침 '+JSON.stringify(x.hit.filter(p=>!p.within)));
 }finally{await ctx.close()}
});
test('#8964 CTO 3: 390 장 카드 설명 낱말 분리 0·2줄 말줄임',async()=>{
 const ctx=await setup(390,'glass');
 try{
  await ctx.page.evaluate(()=>{renderVolumes('old',{preserve:false});applyVolumeSelection('시편',document.querySelector('[data-volume="시편"]'))});
  const x=await ctx.page.evaluate(()=>{
   const e=document.querySelector('.chapter-stack.on .chapter-preview'),css=getComputedStyle(e),txt=e.firstChild,range=document.createRange();
   const word='사건의',index=txt.textContent.indexOf(word);
   if(index>=0){range.setStart(txt,index);range.setEnd(txt,index+word.length)}
   const pieces=index>=0?[...range.getClientRects()].map(r=>({top:r.top,width:r.width})):null;
   return {text:e.textContent,wordBreak:css.wordBreak,overflowWrap:css.overflowWrap,clamp:css.webkitLineClamp,overflow:css.overflow,pieces,clientHeight:e.clientHeight,lineHeight:parseFloat(css.lineHeight)};
  });
  assert.equal(x.wordBreak,'keep-all','한글 낱말 분리 방지 '+JSON.stringify(x));
  assert.equal(x.clamp,'2','2줄 말줄임 '+JSON.stringify(x));
  assert.equal(x.overflow,'hidden','설명 넘침 차단');
  assert.ok(x.clientHeight<=x.lineHeight*2+2,'실제 2줄 초과 '+JSON.stringify(x));
  if(x.pieces){
    const distinct=new Set(x.pieces.map(p=>p.top.toFixed(1)+':'+p.width.toFixed(1)));
    assert.ok(distinct.size<=1,'사건의 다른 줄로 분리 '+JSON.stringify(x));
  }
 }finally{await ctx.close()}
});
test('#8964 CTO 4: 번호 창 내부 스크롤·하단 흐림·현재 장 위치, 호버 잔상 없음',async()=>{
 const ctx=await setup(390,'glass');
 try{
  await ctx.page.evaluate(()=>{renderVolumes('old',{preserve:false});applyVolumeSelection('시편',document.querySelector('[data-volume="시편"]'));selectChapter(90)});
  await ctx.page.locator('#chapterNumberPick').click();
  const m=await ctx.page.evaluate(()=>{
   const dialog=document.querySelector('#sm7573ChapterGrid'),box=dialog.querySelector('.sm7573-grid-card'),cells=dialog.querySelector('.sm7573-grid-cells'),current=dialog.querySelector('.sm7573-grid-cell.on'),shade=dialog.querySelector('.sm7573-grid-fade');
   const br=box.getBoundingClientRect(),cr=cells.getBoundingClientRect(),on=current?.getBoundingClientRect();
   return {screen:document.querySelector('.screen.active')?.id,gridScroll:cells.scrollTop,scrollHeight:cells.scrollHeight,clientHeight:cells.clientHeight,
     selectedVisible:on?.top>=cr.top&&on?.bottom<=cr.bottom,cardBottom:br.bottom,windowHeight:innerHeight,
     shade:shade?{display:getComputedStyle(shade).display,opacity:getComputedStyle(shade).opacity,height:shade.getBoundingClientRect().height}:null,
     documentScroll:document.scrollingElement.scrollTop};
  });
  assert.ok(m.scrollHeight>m.clientHeight+100,'격자 내부 세로 스크롤 필요 '+JSON.stringify(m));
  assert.ok(m.gridScroll>0&&m.selectedVisible,'현재 90장으로 스크롤 '+JSON.stringify(m));
  assert.ok(m.shade&&m.shade.display!=='none'&&Number(m.shade.opacity)>0&&m.shade.height>=12,'하단 흐림 표시 '+JSON.stringify(m));
  assert.ok(m.cardBottom<=m.windowHeight+1,'격자 창 화면 밖 넘침 '+JSON.stringify(m));
  const first=m.documentScroll;
  await ctx.page.locator('.sm7573-grid-cells').hover({position:{x:10,y:20}});
  await ctx.page.mouse.wheel(0,440);
  await ctx.page.waitForTimeout(160);
  const scroll=await ctx.page.evaluate(()=>({grid:document.querySelector('.sm7573-grid-cells').scrollTop,document:document.scrollingElement.scrollTop}));
  assert.ok(scroll.grid>m.gridScroll,'창 안에서만 스크롤 '+JSON.stringify(scroll));
  assert.equal(scroll.document,first,'배경 문서 스크롤 방지');
  await ctx.page.locator('.sm7573-grid-cell').filter({hasText:/^34$/}).hover();
  const normal=await ctx.page.locator('.sm7573-grid-cell').first().evaluate(e=>getComputedStyle(e).backgroundColor);
  const hovered=await ctx.page.locator('.sm7573-grid-cell').filter({hasText:/^34$/}).evaluate(e=>{const r=e.getBoundingClientRect();return {bg:getComputedStyle(e).backgroundColor,rect:{x:r.x,y:r.y}}});
  assert.equal(hovered.bg,normal,'34번 이유 없는 강조 금지');
 }finally{await ctx.close()}
});
test('#8964 CTO 5: 장 번호로 고르기 단추는 카드 판 안쪽 여백 12px',async()=>{
 for(const width of [390,1440]){
  const ctx=await setup(width);
  try{
   const x=await ctx.page.evaluate(()=>{
    const b=document.querySelector('#chapterNumberPick').getBoundingClientRect(),p=document.querySelector('#chapterCarousel').getBoundingClientRect();
    const t=document.querySelector('.chapter-stack.on .folio-tab').getBoundingClientRect();
    return {button:{x:b.x,y:b.y,right:b.right,bottom:b.bottom,width:b.width,height:b.height},panel:{x:p.x,y:p.y,right:p.right,bottom:p.bottom},tab:{x:t.x,y:t.y,right:t.right,bottom:t.bottom}};
   });
   assert.ok(x.button.x>=x.panel.x+12&&x.button.right<=x.panel.right-12,'양옆 여백 '+width+' '+JSON.stringify(x));
   assert.ok(x.button.y>=x.panel.y+12&&x.button.bottom<=x.panel.bottom-12,'상하 여백 '+width+' '+JSON.stringify(x));
   assert.ok(x.button.width>=44&&x.button.height>=44,'터치 44px');
   assert.ok(!(x.button.x<x.tab.right&&x.button.right>x.tab.x&&x.button.y<x.tab.bottom&&x.button.bottom>x.tab.y),'장 번호 단추와 주황 장 탭 겹침 '+width+' '+JSON.stringify(x));
  }finally{await ctx.close()}
 }
});
