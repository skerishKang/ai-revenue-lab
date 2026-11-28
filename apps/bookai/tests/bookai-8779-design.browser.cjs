// #8779 D1·D2·D3·D4·D7·D8·D9 실제 화면 측정: 창 1440/390.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
async function enterReader(page){
  for(let i=0;i<4;i++){
    if(await page.evaluate(()=>document.querySelector('.screen.active')?.id)==='index')break;
    await page.evaluate(()=>document.getElementById('openBook')?.click());await page.waitForTimeout(900);
  }
  await page.evaluate(()=>document.querySelector('[data-volume="사도행전"]')?.click());await page.waitForTimeout(800);
  await page.evaluate(()=>document.querySelector('.chapter-dot[aria-label="사도행전 3장"]')?.click());await page.waitForTimeout(400);
  for(let i=0;i<4;i++){
    if(await page.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;
    await page.evaluate(()=>document.getElementById('openChapter')?.click());await page.waitForTimeout(900);
  }
  await page.waitForTimeout(900);
  assert.equal(await page.evaluate(()=>document.querySelector('.screen.active')?.id),'reader');
}
async function measure(page){
  return page.evaluate(()=>{
    const box=s=>{const e=document.querySelector(s);return e?.getBoundingClientRect()||null;};
    const css=s=>getComputedStyle(document.querySelector(s));
    const lum=s=>(s.match(/[0-9.]+/g)||[]).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
    const ratio=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
    const nav=[box('#pageTurnPrev'),box('#pageTurnNext')];
    const sources=[...document.querySelectorAll('#readerPageBody *')].filter(e=>!e.children.length&&/개역|출처|1961/.test(e.textContent||'')).map(e=>e.getBoundingClientRect());
    const overlaps=sources.flatMap(s=>nav.filter(n=>s.left<n.right&&s.right>n.left&&s.top<n.bottom&&s.bottom>n.top));
    const rail=css('#aiRailTab'),hint=css('#bibleSearchPanel>summary span');
    const background=document.body.classList.contains('smr-theme-dark')?'rgb(38,33,26)':'rgb(255,253,248)';
    return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,
      headRight:box('#reader .paper-head').right,verseRight:box('#readerPageBody .verse').right,
      numberWidth:box('#readerPageBody .vn')?.width||0,word:document.querySelector('#aiRailTab span')?.textContent,
      ratio:ratio(rail.color,rail.backgroundColor),hintSize:parseFloat(hint.fontSize),hintRatio:ratio(hint.color,background),
      overlaps:overlaps.length,sourceCount:sources.length,
      noFloating:!document.querySelector('.bookai-feedback-open'),orangeLineGone:getComputedStyle(document.querySelector('#reader .paper-head'),'::after').content==='none'};
  });
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try{
    for(const [width,dark] of [[1440,false],[1440,true],[390,false]]){
      const page=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:'reduce'});
      await page.route('**/*',route=>{const u=new URL(route.request().url());if(['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname))route.continue();else route.abort();});
      await page.goto(BASE,{waitUntil:'domcontentloaded'});await page.waitForTimeout(1800);
      if(width===1440&&!dark){
        await page.locator('#libOverflow').click();
        assert.equal(await page.locator('#libOverflowMenu button:last-child').innerText(),'의견 보내기');
        await page.locator('#libOverflowMenu button:last-child').click();
        assert.ok(await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.open),'서재 메뉴의 기존 의견 창');
        await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.close());
        await page.locator('#todayEntry').click();await page.waitForTimeout(900);
        await page.locator('#bookaiTodayOverflow').click();
        assert.equal(await page.locator('#bookaiTodayOverflowMenu button:last-child').innerText(),'의견 보내기');
        await page.locator('#bookaiTodayOverflowMenu button:last-child').click();
        assert.ok(await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.open),'오늘 메뉴의 기존 의견 창');
        await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.close());
        await page.locator('#todayBack').click();await page.waitForTimeout(700);
      }
      await enterReader(page);
      if(width===1440&&!dark){
        await page.locator('#smalOverflowBtn').click();
        assert.ok((await page.locator('#smalOverflowMenu button:last-child').innerText()).includes('의견 보내기'));
        await page.locator('#smalOverflowMenu button:last-child').click();
        assert.ok(await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.open),'읽기 메뉴의 기존 의견 창');
        await page.locator('#bookaiFeedbackDialog').evaluate(e=>e.close());
      }
      if(dark){await page.evaluate(()=>document.querySelector('#smReaderSettingsPanel [data-field="theme"] [data-value="dark"]')?.click());await page.waitForTimeout(250);}
      const m=await measure(page);
      assert.ok(m.documentWidth<=width,'가로 넘침');
      assert.ok(m.noFloating,'떠 있는 의견 단추');
      assert.ok(m.orangeLineGone,'뜻 없는 주황 선');
      assert.equal(m.word,'AI 질문','탭 이름');
      assert.ok(m.ratio>=4.5,'측면 탭 대비 '+m.ratio);
      assert.ok(m.hintSize>=13,'검색 안내 글자 '+m.hintSize);
      assert.ok(m.hintRatio>=4.5,'검색 안내 대비 '+m.hintRatio);
      assert.ok(m.numberWidth>0,'절 번호 표시');
      assert.equal(m.overlaps,0,'출처/페이지 단추 겹침');
      assert.ok(m.sourceCount>0,'출처 확인이 되지 않아 검사 불가');
      if(width===1440)assert.ok(Math.abs(m.headRight-m.verseRight)<=1,'오른쪽 끝 '+(m.headRight-m.verseRight)+'px');
      console.log('통과',width,dark?'어둡게':'기본',JSON.stringify(m));
      await page.close();
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
