const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE_URL=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9507/';
const CHROME=process.env.BOOKAI_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';
let browser;
test.before(async()=>browser=await chromium.launch({headless:true,executablePath:CHROME}));
test.after(async()=>await browser?.close());
async function open(width,mode='reader',reduced=false){
 const p=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:reduced?'reduce':'no-preference'});
 await p.route('**/*',r=>{const u=new URL(r.request().url());return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?r.continue():r.abort()});
 await p.goto(BASE_URL,{waitUntil:'domcontentloaded'});await p.waitForTimeout(800);
 for(let i=0;i<5;i++){if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='index')break;
  await p.evaluate(()=>document.getElementById('openBook')?.click());await p.waitForTimeout(750);}
 if(mode==='index')return p;
 await p.evaluate(()=>document.querySelector('[data-volume="고린도전서"]')?.click());await p.waitForTimeout(600);
 await p.evaluate(()=>document.querySelector('.chapter-dot[aria-label="고린도전서 3장"]')?.click());await p.waitForTimeout(350);
 for(let i=0;i<5;i++){if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;
  await p.evaluate(()=>document.getElementById('openChapter')?.click());await p.waitForTimeout(750);}
 await p.waitForFunction(()=>document.querySelector('.screen.active')?.id==='reader',null,{timeout:10000});
 await p.waitForFunction(()=>getComputedStyle(document.querySelector('#paper')).opacity==='1',null,{timeout:10000});
 await p.waitForTimeout(950);
 return p;
}
const rectangle=r=>r&&({x:r.x,y:r.y,width:r.width,height:r.height});
const contrast=(a,b)=>{const l=x=>(x.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((z,v,i)=>z+v*[.2126,.7152,.0722][i],0);const x=l(a),y=l(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};

test('#8791-1 390·1440 읽기 화면 무한 애니메이션 0개, 1초간 칩·본문 위치 차이 0.1px 미만',async()=>{
 for(const width of [390,1440]){
  const p=await open(width);
  try{
   const before=await p.evaluate(()=>{
    const chip=document.querySelector('#reader .v2-chapter-chip').getBoundingClientRect(),text=document.querySelector('#readerPageBody .verse:not(.verse-en)').getBoundingClientRect();
    const infinite=document.querySelector('#reader').getAnimations({subtree:true}).filter(a=>a.effect?.getTiming()?.iterations===Infinity&&a.playState==='running').map(a=>({name:a.animationName,cls:a.effect.target?.className}));
    return {chip:{x:chip.x,y:chip.y},text:{x:text.x,y:text.y},infinite};
   });
   await p.waitForTimeout(1000);
   const after=await p.evaluate(()=>{
    const chip=document.querySelector('#reader .v2-chapter-chip').getBoundingClientRect(),text=document.querySelector('#readerPageBody .verse:not(.verse-en)').getBoundingClientRect();
    return {chip:{x:chip.x,y:chip.y},text:{x:text.x,y:text.y}};
   });
   const delta=Math.max(...['chip','text'].flatMap(k=>['x','y'].map(c=>Math.abs(after[k][c]-before[k][c]))));
   assert.equal(before.infinite.length,0,width+' 무한 애니메이션 '+JSON.stringify(before.infinite));
   assert.ok(delta<0.1,width+' 위치 변화 '+delta.toFixed(3));
  }finally{await p.close();}
 }
});
test('#8791-2 150장 창 양끝 흐림·내부 스크롤·현재 장 중심·바깥 스크롤 고정',async()=>{
 const p=await open(390);
 try{
  await p.evaluate(()=>window.BookAI7573NavigationV1.openBibleChapter('시편',90,'first'));
  await p.waitForFunction(()=>__smCurrentReaderLabel==='시편 90장',null,{timeout:15000});
  await p.locator('.v2-chapter-chip').click();
  await p.waitForTimeout(240); // opacity transition reaches its final state
  const x=await p.evaluate(()=>{
   const grid=document.querySelector('#sm7573ChapterGrid'),card=grid.querySelector('.sm7573-grid-card'),cells=grid.querySelector('.sm7573-grid-cells');
   const a=cells.querySelector('.sm7573-grid-cell.on'),r=cells.getBoundingClientRect(),ar=a.getBoundingClientRect();
   const top=grid.querySelector('.sm7573-grid-fade-top'),bottom=grid.querySelector('.sm7573-grid-fade');
   return {grid:!!grid,num:grid.querySelectorAll('.sm7573-grid-cell').length,scroll:cells.scrollTop,max:cells.scrollHeight-cells.clientHeight,
     activeShown:ar.top>=r.top-2&&ar.bottom<=r.bottom+2,top:top?{height:top.getBoundingClientRect().height,opacity:getComputedStyle(top).opacity}:null,
     bottom:bottom?{height:bottom.getBoundingClientRect().height,opacity:getComputedStyle(bottom).opacity}:null,
     outer:document.scrollingElement.scrollTop};
  });
  assert.equal(x.num,150,'시편 번호 수');
  assert.ok(x.scroll>0&&x.scroll<x.max&&x.activeShown,'현재 90장이 격자 안에 보여야 함 '+JSON.stringify(x));
  assert.ok(x.top&&x.top.height>=12&&Number(x.top.opacity)>0,'위 끝 흐림 '+JSON.stringify(x));
  assert.ok(x.bottom&&x.bottom.height>=12&&Number(x.bottom.opacity)>0,'아래 끝 흐림 '+JSON.stringify(x));
  await p.locator('.sm7573-grid-cells').hover({position:{x:12,y:20}});
  await p.mouse.wheel(0,380);await p.waitForTimeout(150);
  const m=await p.evaluate(()=>({scroll:document.querySelector('.sm7573-grid-cells').scrollTop,outer:document.scrollingElement.scrollTop}));
  assert.ok(m.scroll>x.scroll,'격자 내부 스크롤 '+JSON.stringify(m));
  assert.equal(m.outer,x.outer,'창 밖 스크롤 금지');
 }finally{await p.close();}
});
test('#8791-3 제목 옆 N장 크기 13px 이상, 대비 4.5:1 이상 (390·1440, 기본·어두운)',async()=>{
 for(const width of [390,1440])for(const theme of ['default','dark']){
  const p=await open(width);
  try{
   if(theme==='dark')await p.evaluate(()=>document.body.classList.add('smr-theme-dark'));
   await p.locator('.v2-chapter-chip').click();
   const x=await p.evaluate(()=>{
    const count=document.querySelector('#sm7573ChapterGrid .sm7573-grid-count'),parent=document.querySelector('#sm7573ChapterGrid .sm7573-grid-card');
    const cs=getComputedStyle(count);
    return {name:count?.textContent.trim(),size:parseFloat(cs.fontSize),color:cs.color,bg:getComputedStyle(parent).backgroundColor};
   });
   assert.equal(x.name,'16장'); // 3장 is from a 16-chapter volume
   assert.ok(x.size>=13,width+'/'+theme+' 제목 N장 '+JSON.stringify(x));
   assert.ok(contrast(x.color,x.bg)>=4.5,width+'/'+theme+' 대비 '+contrast(x.color,x.bg).toFixed(2));
  }finally{await p.close();}
 }
});
test('#8791-4 책·장 선택과 읽기 칩은 같은 격자 구조, 닫기·번호 클래스, 다른 책 버튼 범위',async()=>{
 const p=await open(390,'index');
 try{
  await p.evaluate(()=>{renderVolumes('old',{preserve:false});applyVolumeSelection('시편',document.querySelector('[data-volume="시편"]'));});
  await p.locator('#chapterNumberPick').click();
  const fromIndex=await p.evaluate(()=>{
   const el=document.querySelector('#sm7573ChapterGrid');return {classes:[el.className,el.querySelector('.sm7573-grid-card').className,el.querySelector('.sm7573-grid-head').className,el.querySelector('.sm7573-grid-cells').className,el.querySelector('.sm7573-grid-cell').className,el.querySelector('.sm7573-grid-x').className],count:el.querySelectorAll('.sm7573-grid-cell').length,other:!!el.querySelector('.sm7573-grid-otherbooks'),close:el.querySelector('.sm7573-grid-x')?.getBoundingClientRect().height};
  });
  assert.equal(fromIndex.count,150);assert.equal(fromIndex.other,false);assert.ok(fromIndex.close>=44);
  await p.evaluate(()=>document.querySelector('#sm7573ChapterGrid .sm7573-grid-x').click());
  await p.evaluate(()=>document.querySelector('[data-volume="고린도전서"]')?.click());await p.waitForTimeout(300);
  await p.evaluate(()=>document.querySelector('.chapter-dot[aria-label="고린도전서 3장"]')?.click());await p.waitForTimeout(300);
  for(let i=0;i<5;i++){if(await p.evaluate(()=>document.querySelector('.screen.active')?.id)==='reader')break;await p.evaluate(()=>document.getElementById('openChapter')?.click());await p.waitForTimeout(700);}
  await p.locator('.v2-chapter-chip').click();
  const fromReader=await p.evaluate(()=>{
   const el=document.querySelector('#sm7573ChapterGrid');return {classes:[el.className,el.querySelector('.sm7573-grid-card').className,el.querySelector('.sm7573-grid-head').className,el.querySelector('.sm7573-grid-cells').className,el.querySelector('.sm7573-grid-cell').className,el.querySelector('.sm7573-grid-x').className],count:el.querySelectorAll('.sm7573-grid-cell').length,other:!!el.querySelector('.sm7573-grid-otherbooks'),close:el.querySelector('.sm7573-grid-x')?.getBoundingClientRect().height};
  });
  assert.deepEqual(fromIndex.classes,fromReader.classes,'같은 컴포넌트 클래스');
  assert.equal(fromReader.other,true);assert.ok(fromReader.close>=44);
 }finally{await p.close();}
});

test('#8791-1 움직임 줄이기에서는 한 번짜리 쪽 전환도 애니메이션 없음',async()=>{
 const p=await open(390,'reader',true);
 try{
  const m=await p.evaluate(()=>{
    readerPageIndex=Math.min(1,READER_PAGES.length-1);
    renderReaderPage(1);
    const inner=document.querySelector('#paper.page-content-changing .paper-inner');
    const css=inner&&getComputedStyle(inner);
    const active=document.querySelector('#reader').getAnimations({subtree:true}).filter(a=>a.playState==='running'&&a.effect?.getTiming()?.duration>0);
    return {name:css?.animationName,active:active.map(a=>a.animationName)};
  });
  assert.equal(m.name,'none','움직임 줄이기의 한 번짜리 전환 '+JSON.stringify(m));
  assert.equal(m.active.length,0,'실행 중인 전환 애니메이션 '+JSON.stringify(m));
 }finally{await p.close();}
});
