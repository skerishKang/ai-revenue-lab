// #8779 2차, #8781 D 실측: 겹침=0px, 390 한 줄<=358px, 행간>=1.1,
// 안내와 제목 간격>=8px, 대비>=4.5:1, 터치 44px, 바깥 넘침 0.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
const r=el=>{const a=el?.getBoundingClientRect();return a?{x:a.x,y:a.y,right:a.right,bottom:a.bottom,width:a.width,height:a.height}:null};
const contrast=(a,b)=>{
 const f=s=>(s.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
 const x=f(a),y=f(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
};
async function browserPage(browser,width,height){
 const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
 await page.route('**/*',route=>{const u=new URL(route.request().url());return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?route.continue():route.abort();});
 await page.goto(BASE,{waitUntil:'domcontentloaded'});await page.waitForTimeout(1600);
 return page;
}
async function enterReader(page){
 for(let i=0;i<5;i++){
  if(await page.evaluate(()=>document.querySelector('.screen.active')?.id)==='index')break;
  await page.evaluate(()=>document.getElementById('openBook')?.click());await page.waitForTimeout(650);
 }
 await page.evaluate(()=>document.querySelector('[data-volume="고린도전서"]')?.click());await page.waitForTimeout(600);
 await page.evaluate(()=>document.querySelector('.chapter-dot[aria-label="고린도전서 3장"]')?.click());await page.waitForTimeout(400);
 for(let i=0;i<5;i++){
  if(await page.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;
  await page.evaluate(()=>document.getElementById('openChapter')?.click());await page.waitForTimeout(750);
 }
 await page.waitForTimeout(500);
 assert.equal(await page.evaluate(()=>document.querySelector('.screen.active')?.id),'reader');
}
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const startup=await b.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
  await startup.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname.endsWith('/storymemory-reader-view-runtime-v1.js'))await new Promise(resolve=>setTimeout(resolve,2000));
    if(['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname))await route.continue();
    else await route.abort();
  });
  await startup.goto(BASE,{waitUntil:'domcontentloaded'});await startup.waitForTimeout(350);
  const boot=await startup.evaluate(()=>{
    const gate=document.querySelector('#bookai-startup'),shelf=document.querySelector('#library');
    const spinner=gate?.querySelector('.bookai-startup-progress');
    return {gate:!!gate,bg:gate&&getComputedStyle(gate).backgroundImage,shelfBg:getComputedStyle(shelf).backgroundImage,
      spinnerSize:spinner?.getBoundingClientRect().width||0};
  });
  assert.ok(boot.gate&&boot.spinnerSize>=16,'불러오기 진행 표시');
  assert.equal(boot.bg,boot.shelfBg,'불러오기/서재 배경 색상 차이 0');
  await startup.close();
  for(const width of [390,1440]){
   const page=await browserPage(b,width,width===390?844:900);
   const m=await page.evaluate(()=>{
     const rect=el=>{let a=el.getBoundingClientRect();return {x:a.x,y:a.y,right:a.right,bottom:a.bottom,width:a.width,height:a.height}};
     const title=document.querySelector('#library .hero-title');
     const range=document.createRange();range.selectNodeContents(title.firstChild);
     const first=rect({getBoundingClientRect:()=>range.getBoundingClientRect()});
     const second=rect(title.querySelector('em')),kicker=rect(document.querySelector('#library .kicker'));
     const style=getComputedStyle(title),stats=rect(document.querySelector('#libraryReadingSummary')),markerArea=rect(document.querySelector('#markers'));
     const markers=[...document.querySelectorAll('#markers .marker')].map(e=>({r:rect(e),cursor:getComputedStyle(e).cursor}));
     const covers=[...document.querySelectorAll('#shelfTrack .cover-copy strong')].map(e=>({name:e.textContent,break:getComputedStyle(e).wordBreak,space:getComputedStyle(e).whiteSpace}));
     return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,first,second,kicker,
       lineRatio:parseFloat(style.lineHeight)/parseFloat(style.fontSize),stats,markers,markerArea,covers,decorTitle:getComputedStyle(document.querySelector('#library .lib-head'),'::after').content,
       deco:[...document.querySelectorAll('#library .scene-meta,#library .collection-stamp')].map(e=>getComputedStyle(e).display)};
   });
   console.log('서재 실측',width,JSON.stringify({lineRatio:m.lineRatio,overlap:m.first.bottom-m.second.y,gap:m.first.y-m.kicker.bottom,titleWidth:m.first.width,statRight:m.stats.right,markers:m.markers.length}));
   assert.ok(m.scrollWidth<=width,'서재 화면 밖 넘침');
   assert.ok(m.lineRatio>=1.1,'큰 제목 행간');
   assert.ok(m.first.bottom<=m.second.y+1,'큰 제목 두 줄 겹침');
   assert.ok(m.first.y-m.kicker.bottom>=8,'제목 위 여백');
   if(width===390)assert.ok(m.first.width<=358,'390 제목 한 줄 너비');
   assert.ok(m.covers.every(x=>x.break==='keep-all'),'책 이름 낱말 갈라짐');
   assert.ok(m.markers.every(x=>x.r.width>=44&&x.r.height>=44),'책장 점 터치 44×44');
   assert.ok(m.markers.every(x=>x.r.bottom<=(width===390?844:900)),'책장 점 터치 영역 화면 안');
   assert.ok(Math.abs((width-m.stats.right)-(width===390?16:48))<=1,'통계 오른쪽 여백');
   if(width===1440){assert.ok(m.deco.every(s=>s==='none'),'장식 글자 제거');assert.equal(m.decorTitle,'none','장식 제목 제거');}
   if(width===390){
    assert.ok(m.markerArea.right<=m.stats.x-8,'책장 점과 통계 줄 가림 없음');
    const previous=await page.locator('#libTitle').innerText();
    await page.locator('#markers .marker').first().click();await page.waitForTimeout(400);
    assert.notEqual(await page.locator('#libTitle').innerText(),previous,'책장 점에서 책 이동');
    await page.locator('#libOverflow').click();
    const menu=await page.locator('#libOverflowMenu').evaluate(el=>[...el.children].map(x=>({id:x.id,className:x.className,h:x.getBoundingClientRect().height,text:x.textContent.trim()})));
    assert.equal(menu.length,4,'서재 메뉴 항목 4개');
    assert.ok(menu[0].text.includes('계정')&&menu[1].text.includes('책 넘김 속도')&&menu[2].text.includes('책장 순서')&&menu[3].text.includes('의견 보내기'),'서재 메뉴 항목 순서');
    assert.ok(menu.every(x=>x.h>=44),'서재 메뉴 한 줄 44px');
   }
   await page.close();
  }
  const page=await browserPage(b,1440,900);
  const shortPosition=await page.evaluate(()=>{
    const content={kind:'bible',title:'성경'},record={bibleVolume:'고린도전서',bibleChapter:1,page:1,unitPageCount:3};
    const oldPosition=storyMemoryResumePositionLabel(content,record);
    if(oldPosition!=='페이지 2 / 3')throw Error('오늘·읽기 표기는 그대로여야 한다');
    return storyMemoryResumeUnitLabel(content,record)+' · '+storyMemoryShelfPositionLabel({record,position:oldPosition});
  });
  assert.equal(shortPosition,'고린도전서 1장 · 2/3쪽','읽기 기록 쪽수 표기');
  await enterReader(page);
  const theme=await page.locator('#srsg-label-theme').innerText();
  assert.equal(theme,'읽기 화면 테마','읽기 설정 테마 범위');
  const pos=await page.evaluate(()=>{
   const r=s=>document.querySelector(s).getBoundingClientRect();
   const body=r('#readerPageBody .verse'),source=r('#readerPageBody>.sm-verified-source-note');
   return {verseCenter:(body.left+body.right)/2,sourceCenter:(source.left+source.right)/2};
  });
  console.log('출처 정렬',pos);
  assert.ok(Math.abs(pos.verseCenter-pos.sourceCenter)<=1,'출처 줄 본문 열 가운데');
  await page.evaluate(()=>document.querySelector('#smReaderSettingsPanel [data-field="theme"] [data-value="dark"]')?.click());
  const chip=await page.evaluate(()=>{
   const e=document.querySelector('#reader .v2-chapter-chip'),s=getComputedStyle(e);
   return {bg:s.backgroundColor,fg:s.color,tokenBg:getComputedStyle(document.body).getPropertyValue('--sm-chapter-chip-bg')};
  });
  console.log('어두운 장 칩',chip);
  assert.ok(chip.tokenBg.trim(),'장 칩 테마 토큰');
  assert.ok(contrast(chip.fg,chip.bg)>=4.5,'어두운 장 칩 글자 대비 4.5:1');
  await page.close();
  console.log('북AI 디자인 2차 브라우저 실측 통과');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
