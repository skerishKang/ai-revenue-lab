const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.BOOKAI_PLAYWRIGHT||'playwright');
const BASE=process.env.BOOKAI_BASE_URL||'http://127.0.0.1:14507/';
const CHROME=process.env.BOOKAI_CHROME_PATH;
const CAPTURES=process.env.BOOKAI_8794_CAPTURE_DIR||'';
let browser;
test.before(async()=>{browser=await chromium.launch({headless:true,...(CHROME?{executablePath:CHROME}:{})});});
test.after(async()=>{await browser?.close();});
const manifest={schema_version:'storymemory-bible-search-index-1',shards:[{path:'shard-01.json'}]};
const shard={schema_version:1,units:[['JHN',3,1,'JHN 3',1,[[16,'','예수께서 세상을 사랑하시므로 모두가 생명을 얻습니다.','Jesus came to the world.',null]]]]};
async function open(width,theme='default',mock=false,delay=0){
 const p=await browser.newPage({viewport:{width,height:width===390?844:900},reducedMotion:'reduce'});
 await p.addInitScript(()=>{window.__smBibleSearchNoPrefetch=true;});
 await p.route('**/*',route=>{
  const h=new URL(route.request().url()).hostname;
  return ['127.0.0.1','localhost','fonts.googleapis.com','fonts.gstatic.com'].includes(h)?route.continue():route.abort();
 });
 if(mock){
  await p.route('**/content/bible-web/search-index/manifest.json',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(manifest)}));
  await p.route('**/content/bible-web/search-index/shard-01.json',async r=>{
   if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
   await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(shard)});
  });
 }
 await p.goto(BASE,{waitUntil:'domcontentloaded'});
 await p.locator('#library.active').waitFor({timeout:20000});
 await p.locator('#openBook').click();
 await p.locator('#index.active').waitFor({timeout:20000});
 await p.locator('#resume').click();
 await p.locator('#reader.active').waitFor({timeout:20000});
 await p.locator('#readerPageBody .sm-source-passage').first().waitFor({timeout:30000});
 if(theme!=='default')await p.evaluate(t=>{document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-glass','smr-theme-sepia');document.body.classList.add('smr-theme-'+t);},theme);
 await p.locator('#bibleSearchPanel summary').click();
 await p.waitForTimeout(280);
 return p;
}
async function screenshot(p,name){
 if(!CAPTURES)return;
 fs.mkdirSync(CAPTURES,{recursive:true});
 await p.screenshot({path:path.join(CAPTURES,name+'.png'),animations:'disabled'});
}
async function fakeSearch(p,count=65,q='예수께서'){
 await p.evaluate(n=>{
  window.__smStaticKeywordSearchV1.staticKeywordSearch=(term,opts)=>{
   const start=Math.max(0,Number(opts.offset)||0);
   const rows=Array.from({length:Math.max(0,Math.min(n-start,opts.limit||20))},(_,i)=>({
     canonical_locator:'bible:web:JHN:3:16',raw_locator:[{book:'JHN',chapter:3,verse:16}],
     snippet:'사람들이 들으니 예수께서 사랑으로 말씀하셨습니다. '+(start+i+1),
     ko:'예수께서 사랑으로 말씀하셨습니다.',title:'성경 말씀 '+(start+i+1)
   }));
   return {total:n,results:rows,truncated:n>rows.length};
  };
 },count);
 await p.locator('#bibleSearchInput').fill(q);
 await p.locator('#bibleSearchInput').press('Enter');
 await p.waitForFunction(()=>!document.querySelector('#bibleSearchSubmit').disabled,{timeout:15000});
}
function rgb(s){
 const nums=(s.match(/[\d.]+/g)||[]).map(Number);
 return nums.length>=3?nums:[0,0,0,0];
}
function contrast(a,b){
 const luminance=s=>rgb(s).slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((x,v,i)=>x+v*[.2126,.7152,.0722][i],0);
 const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
test('#8794-1 펼친 창 불투명, 뒤 본문 비침 0 (기본·글래스·어둡게)',async()=>{
 for(const theme of ['default','glass','dark']){
  const p=await open(1440,theme);
  try{
   await screenshot(p,'open-1440-'+theme);
   const color=await p.locator('.bible-search-content').evaluate(el=>getComputedStyle(el).backgroundColor);
   assert.equal(rgb(color)[3]??1,1,theme+' 창 배경 '+color);
  }finally{await p.close();}
 }
});
test('#8794-2 1440 결과 창 좌우 끝은 검색 상자와 ±2px',async()=>{
 const p=await open(1440);
 try{
  const r=await p.evaluate(()=>{
   const a=document.querySelector('#bibleSearchPanel>summary').getBoundingClientRect(),b=document.querySelector('.bible-search-content').getBoundingClientRect();
   return {left:Math.abs(a.left-b.left),right:Math.abs(a.right-b.right),w:a.width,content:b.width};
  });
  assert.ok(r.left<=2&&r.right<=2,JSON.stringify(r));
 }finally{await p.close();}
});
test('#8794-3 불러오기 취소: 로딩 때만 보이고 결과 없음·구절 확인 뒤 숨김',async()=>{
 const p=await open(390,'default',true,700);
 try{
  await p.evaluate(()=>{window.__smStaticKeywordSearchV1.staticKeywordSearch=()=>({total:0,results:[]});});
  await p.locator('#bibleSearchInput').fill('해당없음');
  await p.locator('#bibleSearchInput').press('Enter');
  assert.equal(await p.locator('#bibleSearchCancel').isVisible(),true,'로딩 중 취소 표시');
  await p.waitForFunction(()=>document.querySelector('#bibleSearchStatus').textContent.includes('검색 결과가 없어요.'),{timeout:16000});
  await screenshot(p,'none-390-default');
  assert.equal(await p.locator('#bibleSearchCancel').isVisible(),false,'결과 없음 상태 취소 숨김');
  await p.locator('#bibleSearchInput').fill('요한복음 3장 16절');
  await p.locator('#bibleSearchInput').press('Enter');
  await p.waitForFunction(()=>document.querySelector('#bibleSearchStatus').textContent.includes('구절을 찾았어요.'),{timeout:15000});
  assert.equal(await p.locator('#bibleSearchCancel').isVisible(),false,'구절 찾음 상태 취소 숨김');
 }finally{await p.close();}
});
test('#8794-4 대표 확정 안내 글 정확히 표시',async()=>{
 const p=await open(390);
 try{assert.equal(await p.locator('.bible-search-hint').innerText(),'성경 전체에서 찾습니다. 결과를 눌러도 읽던 곳은 그대로입니다.');}
 finally{await p.close();}
});
test('#8794-5 이름표 12px, 상태·미리보기 13px 이상 및 대비 4.5:1 (390·1440, 기본·어둡게)',async()=>{
 for(const width of [390,1440])for(const theme of ['default','dark']){
  const p=await open(width,theme,true);
  try{
   await fakeSearch(p,65);
   const vals=await p.evaluate(()=>{
    const label=document.querySelector('.bible-search-content form label'),status=document.getElementById('bibleSearchStatus'),preview=document.querySelector('.bible-search-result span');
    const a=document.querySelector('.bible-search-content'),b=document.querySelector('.bible-search-result');
    return [ [label,a],[status,a],[preview,b] ].map(([el,parent])=>({size:parseFloat(getComputedStyle(el).fontSize),fg:getComputedStyle(el).color,bg:getComputedStyle(parent).backgroundColor}));
   });
   assert.ok(vals[0].size>=12,width+'/'+theme+' label '+JSON.stringify(vals));
   for(const i of [1,2])assert.ok(vals[i].size>=13,width+'/'+theme+' 글자 '+i+' '+JSON.stringify(vals));
   for(const i of [0,1,2])assert.ok(contrast(vals[i].fg,vals[i].bg)>=4.5,width+'/'+theme+' 대비 '+i+' '+contrast(vals[i].fg,vals[i].bg).toFixed(2));
   await screenshot(p,'results-'+width+'-'+theme);
  }finally{await p.close();}
 }
});
test('#8794-6 아래 끝 흐림, 결과 더 보기 44px, 누를 때마다 20개 (50개 상한 없음)',async()=>{
 const p=await open(1440,'glass',true);
 try{
  await fakeSearch(p,65);
  await screenshot(p,'many-1440-glass');
  const c=()=>p.locator('#bibleSearchResults li').count();
  assert.equal(await c(),20);
  const fade=await p.evaluate(()=>{
   const el=document.querySelector('.bible-search-list-wrap');if(!el||!el.classList.contains('has-scroll-more'))return null;
   const pseudo=getComputedStyle(el,'::after');return {content:pseudo.content,height:parseFloat(pseudo.height),background:pseudo.backgroundImage};
  });
  assert.ok(fade&&fade.content!=='none'&&fade.height>=12&&fade.background.includes('gradient'),JSON.stringify(fade));
  const button=p.locator('.bible-search-more');
  assert.equal(await button.innerText(),'결과 더 보기');
  assert.ok((await button.boundingBox()).height>=44,'더 보기 44px 미만');
  const visible=await p.evaluate(()=>{
   const outer=document.querySelector('.bible-search-content').getBoundingClientRect();
   const more=document.querySelector('.bible-search-more').getBoundingClientRect();
   return {outerBottom:outer.bottom,buttonBottom:more.bottom,buttonTop:more.top};
  });
  assert.ok(visible.buttonBottom<=visible.outerBottom-6,'더 보기 단추가 결과 창 아래에 가려짐 '+JSON.stringify(visible));
  await button.click();assert.equal(await c(),40);
  await button.click();assert.equal(await c(),60);
  await screenshot(p,'more-1440-glass');
  await button.click();assert.equal(await c(),65);
  assert.equal(await button.count(),0,'마지막 결과 뒤 단추 숨김');
 }finally{await p.close();}
 const mobile=await open(390,'glass',true);
 try{
  await fakeSearch(mobile,65);
  await screenshot(mobile,'many-390-glass');
  const rect=await mobile.evaluate(()=>{
   const outer=document.querySelector('.bible-search-content').getBoundingClientRect();
   const more=document.querySelector('.bible-search-more').getBoundingClientRect();
   return {outerBottom:outer.bottom,buttonBottom:more.bottom,buttonTop:more.top};
  });
  assert.ok(rect.buttonBottom<=rect.outerBottom-6,'390 더 보기 단추가 가려짐 '+JSON.stringify(rect));
 }finally{await mobile.close();}
});
test('#8794-7 결과 미리보기에서 검색어 굵게 강조',async()=>{
 const p=await open(390,'default',true);
 try{
  await fakeSearch(p,65,'예수께서');
  const b=p.locator('#bibleSearchResults .bible-search-result span strong').first();
  assert.equal(await b.innerText(),'예수께서');
  const weight=await b.evaluate(el=>Number(getComputedStyle(el).fontWeight));
  assert.ok(weight>=700,'강조 굵기 '+weight);
 }finally{await p.close();}
});
