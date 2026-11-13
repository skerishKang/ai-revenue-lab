const {chromium}=require('playwright');const assert=require('node:assert/strict');
/* #7573 · 페이지 버튼 가림 / #7574 · 새 사용자 기억 숫자 — 실제 화면 시험.
   정적 서버(기본 http://127.0.0.1:18779)와 B61_CHROME_PATH 가 필요하다.
   브라우저 QA 레인 전용이며 `node --test tests/*.test.mjs` 대상이 아니다. */
const BASE=process.env.B61_BASE_URL||'http://127.0.0.1:18779';
const WIDTHS=[[1440,900],[820,1180],[390,844]];
const ENTER=async(p)=>{
  for(let i=0;i<8;i++){
    if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='index')break;
    await p.evaluate(()=>document.getElementById('openBook')?.click());await p.waitForTimeout(1000);
  }
  await p.waitForTimeout(1000);
  await p.evaluate(()=>document.querySelector('[data-volume="사도행전"]')?.click());await p.waitForTimeout(1200);
  await p.evaluate(()=>document.querySelector('.chapter-dot[aria-label="사도행전 3장"]')?.click());await p.waitForTimeout(1000);
  for(let i=0;i<4;i++){
    if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;
    await p.evaluate(()=>document.getElementById('openChapter')?.click());await p.waitForTimeout(1400);
  }
  await p.waitForTimeout(1600);
  await p.evaluate(()=>{if(typeof applyReaderViewMode==='function')applyReaderViewMode('page');});
  await p.waitForTimeout(1000);
};
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
  /* 1. 장식 층은 클릭을 받지 않는다 + 버튼이 장식 위에 있다 */
  for(const [width,height] of WIDTHS){
    const p=await b.newPage({viewport:{width,height}});
    await p.goto(BASE,{waitUntil:'load'});await p.evaluate(()=>window.BookAIReady);await p.waitForTimeout(600);
    await ENTER(p);
    const pe=await p.evaluate(()=>({
      stack:getComputedStyle(document.getElementById('paperStack')).pointerEvents,
      under:getComputedStyle(document.querySelector('.under2')).pointerEvents,
      paper:getComputedStyle(document.getElementById('paper')).pointerEvents,
      zone:getComputedStyle(document.getElementById('turnRight')).pointerEvents,
      button:getComputedStyle(document.getElementById('pageTurnNext')).pointerEvents,
    }));
    assert.equal(pe.stack,'none','종이 묶음 상자가 클릭을 받고 있다 · '+width);
    assert.equal(pe.under,'none','밑장 장식이 클릭을 받고 있다 · '+width);
    assert.equal(pe.paper,'auto','본문은 클릭을 받아야 한다 · '+width);
    assert.equal(pe.zone,'auto','넘김 영역이 죽으면 안 된다 · '+width);
    assert.equal(pe.button,'auto','페이지 버튼이 죽으면 안 된다 · '+width);
    for(let i=0;i<6;i++){
      const top=await p.evaluate(()=>{const e=document.getElementById('pageTurnNext');const r=e.getBoundingClientRect();
        const t=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return t?(t.id||String(t.className)):'null';});
      assert.equal(top,'pageTurnNext','버튼 중심이 장식/넘김 영역에 덮였다 · '+width);
      await p.waitForTimeout(220);
    }
    /* 버튼을 실제로 눌러 페이지가 넘어가는지(크기별 3회) */
    let moved=0;
    for(let i=0;i<3;i++){
      const c=await p.evaluate(()=>{const e=document.getElementById('pageTurnNext');const r=e.getBoundingClientRect();
        return [r.left+r.width/2,r.top+r.height/2];});
      const before=await p.evaluate(()=>readerPageIndex);
      await p.mouse.click(c[0],c[1]);await p.waitForTimeout(1200);
      if(await p.evaluate(()=>readerPageIndex)!==before)moved++;
    }
    assert.equal(moved,3,'페이지 버튼 클릭이 넘어가지 않았다 · '+width);
    await p.close();
  }
  /* 2. 새 사용자 숫자 0 — 화면 폭 390 에서 여러 번 새로 열어도 0 */
  for(let i=0;i<6;i++){
    const p=await b.newPage({viewport:{width:390,height:844}});
    await p.goto(BASE,{waitUntil:'load'});await p.evaluate(()=>window.BookAIReady);await p.waitForTimeout(3000);
    assert.equal(await p.locator('#todayRecallCount').innerText(),'0','새 사용자 홈 숫자 · '+(i+1));
    await p.evaluate(()=>document.getElementById('todayEntry').click());await p.waitForTimeout(1500);
    assert.equal(await p.locator('#todayRecallCount').innerText(),'0','새 사용자 오늘 화면 숫자 · '+(i+1));
    await p.close();
  }
  console.log('bookai-7573-layout hit testing: ok');
}finally{await b.close();}})();
