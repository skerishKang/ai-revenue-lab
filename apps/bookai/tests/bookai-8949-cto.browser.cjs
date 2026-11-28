// #8949 CTO 검토: 390·1440 × 글래스·밝게, 메뉴 겹침·이름·상단 칩 실측
const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:9407/';
const CAPDIR=process.env.BOOKAI_REVIEW_CAPTURE_DIR||'';
const CHROME=process.env.BOOKAI_CHROME_PATH||undefined;
const modes=[{width:390,theme:'glass'},{width:390,theme:'light'},{width:1440,theme:'glass'},{width:1440,theme:'light'},{width:1440,theme:'default'}];
let browser;
const results=[];
const overlap=(a,b)=>a&&b&&a.x<b.right&&a.right>b.x&&a.y<b.bottom&&a.bottom>b.y;
const diagnostic=(state,item)=>{
 const label=item.label||{},value=item.value||{};
 return [state.width,state.theme,item.key,'이름='+label.text,'이름 상자='+JSON.stringify(label.rect),
   '값='+value.text,'값 상자='+JSON.stringify(value.rect),'메뉴='+JSON.stringify(item.row)].join(' ');
};
function measure(){
 const box=r=>r?{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}:null;
 const text=el=>{
   if(!el)return null;
   const cs=getComputedStyle(el),n=[...el.childNodes].find(x=>x.nodeType===3&&x.textContent.trim());
   if(!n)return {text:el.textContent.trim(),rect:box(el.getBoundingClientRect()),color:cs.color,display:cs.display,visibility:cs.visibility};
   const range=document.createRange();range.selectNodeContents(n);
   return {text:n.textContent.trim(),rect:box(range.getBoundingClientRect()),color:cs.color,display:cs.display,visibility:cs.visibility};
 };
 const ids=[
   ['account','#bookaiAccountMenu',null,null],
   ['motion','#motionToggle','#motionToggle span','#motionValue'],
   ['order','#libraryOrderToggle','#libraryOrderToggle .sm-menu-label','#libraryOrderToggle .sm-menu-state'],
   ['feedback','#libOverflowMenu .bookai-feedback-menu-item',null,null]
 ];
 const rows=ids.map(([key,sel,labSel,valSel])=>{
  const e=document.querySelector(sel),css=e&&getComputedStyle(e);
  const label=labSel?document.querySelector(labSel):e,value=valSel?document.querySelector(valSel):null;
  return {key,row:box(e?.getBoundingClientRect()),label:text(label),value:text(value),
    icon:css&&getComputedStyle(e,'::before').content,html:e?.outerHTML.slice(0,400)};
 });
 const chip=document.querySelector('#library #todayEntry'),cb=chip.getBoundingClientRect(),cc=getComputedStyle(chip);
 const menuButton=document.querySelector('#libOverflow').getBoundingClientRect();
 return {rows,menuRect:box(document.querySelector('#libOverflowMenu').getBoundingClientRect()),chip:{text:chip.textContent.trim(),rect:box(cb),display:cc.display,
   visibility:cc.visibility,opacity:parseFloat(cc.opacity),pointerEvents:cc.pointerEvents},
  menuButton:box(menuButton),scrollWidth:document.documentElement.scrollWidth};
}
const ratio=(fg,bg)=>{
 const parse=x=>(x.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
 const lum=rgb=>parse(rgb).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((p,n,i)=>p+n*[.2126,.7152,.0722][i],0);
 const a=lum(fg),b=lum(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
};
test.before(async()=>{
 browser=await chromium.launch({headless:true,...(CHROME?{executablePath:CHROME}:{})});
 if(CAPDIR)fs.mkdirSync(CAPDIR,{recursive:true});
 for(const m of modes){
  const page=await browser.newPage({viewport:{width:m.width,height:m.width===390?844:900},reducedMotion:'reduce'});
  await page.route('**/*',r=>{
    const u=new URL(r.request().url());
    return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(u.hostname)?r.continue():r.abort();
  });
  await page.goto(BASE,{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(1000);
  await page.evaluate(theme=>{
    document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-sepia','smr-theme-glass');
    if(theme!=='default')document.body.classList.add('smr-theme-'+theme);
  },m.theme);
  await page.waitForTimeout(140);
  await page.locator('#libOverflow').click();
  await page.waitForTimeout(150);
  if(CAPDIR&&m.theme!=='default')await page.screenshot({path:path.join(CAPDIR,'menu-'+m.width+'-'+m.theme+'.png'),animations:'disabled'});
  const metrics=await page.evaluate(measure);
  results.push({...m,...metrics});
  await page.close();
 }
 if(CAPDIR)fs.writeFileSync(path.join(CAPDIR,'measurements.json'),JSON.stringify(results,null,2));
});
test.after(async()=>{await browser?.close();});
test('1. 메뉴 각 줄 이름·값 글자 상자 겹침 0, 높이 44px 이상',()=>{
 for(const state of results){
  const menu=state.menuRect;
  for(const [i,item] of state.rows.entries()){
   assert.ok(item.row&&item.row.height>=44,diagnostic(state,item));
   assert.ok(item.row.x>=menu.x+5&&item.row.right<=menu.right-5,'메뉴 밖으로 밀린 줄: '+diagnostic(state,item));
   assert.ok(item.row.y>=menu.y+5&&item.row.bottom<=menu.bottom-5,'메뉴 세로 경계 밖: '+diagnostic(state,item));
   if(i)assert.ok(state.rows[i-1].row.bottom+1<=item.row.y,'메뉴 줄끼리 겹침: '+diagnostic(state,item));
   assert.ok(!overlap(item.label?.rect,item.value?.rect),'이름·값 겹침: '+diagnostic(state,item));
   if(item.value&&item.label?.rect?.width>0)assert.ok(item.label.rect.right+4<=item.value.rect.x,'이름·값 간격 4px: '+diagnostic(state,item));
  }
 }
});
test('2. 모든 메뉴 줄에서 계정·책 넘김 속도·책장 순서·의견 보내기 이름이 보여야 함',()=>{
 const names=['계정','책 넘김 속도','책장 순서','의견 보내기'];
 for(const state of results){
  assert.equal(state.rows.length,4);
  for(const [i,item] of state.rows.entries()){
   assert.ok(item.label?.text.includes(names[i]),'항목 이름 누락: '+diagnostic(state,item));
   assert.ok(item.label.rect?.width>=5&&item.label.rect?.height>=10,'이름 글자상자 없음: '+diagnostic(state,item));
   assert.ok(item.label.display!=='none'&&item.label.visibility!=='hidden','이름 숨김: '+diagnostic(state,item));
   assert.ok(item.label.rect.x>=item.row.x+25&&item.label.rect.right<=item.row.right-7,'아이콘/바깥 겹침: '+diagnostic(state,item));
   assert.ok(ratio(item.label.color,'rgb(25,28,36)')>=4.5,'메뉴 이름 대비: '+diagnostic(state,item));
  }
 }
});
test('3. 1440 오늘 떠올릴 기억 칩은 ⋯ 왼쪽에 보이고 390도 유지',()=>{
 for(const state of results){
  const ch=state.chip,m=state.menuButton;
  assert.ok(ch.text.includes('오늘 떠올릴 기억'),'칩 이름: '+state.width+'/'+state.theme);
  assert.ok(ch.display!=='none'&&ch.visibility!=='hidden'&&ch.opacity>=0.95&&ch.pointerEvents!=='none','칩 표시: '+state.width+'/'+state.theme+' '+JSON.stringify(ch));
  assert.ok(ch.rect.width>=65&&ch.rect.height>=25,'칩 크기: '+state.width+'/'+state.theme);
  assert.ok(ch.rect.right+6<=m.x,'칩은 ⋯ 왼쪽: '+state.width+'/'+state.theme);
  assert.ok(ch.rect.x>=0&&ch.rect.right<=state.width,'칩 화면 안: '+state.width+'/'+state.theme);
 }
});
