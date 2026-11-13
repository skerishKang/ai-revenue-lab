/* #7665 글래스 선택 테마 시험
   - 테마 목록에 글래스가 있다
   - 기본 테마는 글래스를 고르지 않으면 그대로다(고른 뒤 되돌려도 같다)
   - 글래스를 고르면 body.smr-theme-glass 가 붙고 유리 면 값이 적용된다
   - 새로고침 뒤에도 선택이 유지된다
   - 저장값이 목록에 없는 값이면 기본 테마로 떨어진다
   - 새 CSS 파일의 모든 규칙은 body.smr-theme-glass 아래에만 있다 */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const BASE=process.env.B61_BASE_URL||'http://127.0.0.1:18782';

function checkGlassCssScoped(){
  const css=fs.readFileSync(path.join(__dirname,'..','public','styles','bookai-glass-theme-v1.css'),'utf8');
  const noComments=css.replace(/\/\*[\s\S]*?\*\//g,'');
  const ruleLines=noComments.split('\n').filter(l=>/\{\s*$/.test(l.trim())&&!l.trim().startsWith('@'));
  assert.ok(ruleLines.length>0,'glass css should have rules');
  ruleLines.forEach(l=>assert.ok(l.includes('smr-theme-glass'),'rule outside glass theme selector: '+l.trim()));
}

async function openSettingsPanel(p){
  await p.locator('#smalOverflowBtn').click();
  await p.locator('.srsg-btn').click();
  await p.locator('.srsg-panel').waitFor({state:'visible'});
}

(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
  checkGlassCssScoped();
  for(const width of [1440,390]){
    const p=await b.newPage({viewport:{width,height:900}});
    await p.goto(BASE+'/',{waitUntil:'load'});await p.waitForTimeout(1500);
    await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
    await p.waitForFunction(()=>__smCurrentReaderLabel==='사도행전 9장',null,{timeout:15000});
    // 기본 테마는 그대로
    assert.equal(await p.evaluate(()=>document.body.classList.contains('smr-theme-glass')),false);
    const defaultPaper=await p.evaluate(()=>getComputedStyle(document.querySelector('.paper')).backgroundColor);
    assert.equal(defaultPaper,'rgb(255, 253, 248)','default paper unchanged');
    // 테마 목록에 글래스
    await openSettingsPanel(p);
    const glassBtn=p.locator('.srsg-panel .srsg-sw button[data-value="glass"]');
    assert.equal(await glassBtn.count(),1,'glass swatch exists');
    assert.equal(await glassBtn.getAttribute('aria-label'),'글래스');
    // 글래스 선택
    await glassBtn.click();
    assert.equal(await p.evaluate(()=>document.body.classList.contains('smr-theme-glass')),true);
    const glassPaper=await p.evaluate(()=>getComputedStyle(document.querySelector('.paper')).backgroundColor);
    assert.equal(glassPaper,'rgba(250, 247, 242, 0.93)','glass surface value reused');
    // 새로고침 뒤에도 유지
    await p.reload({waitUntil:'load'});await p.waitForTimeout(1500);
    await p.waitForFunction(()=>__smCurrentReaderLabel==='사도행전 9장',null,{timeout:15000}).catch(()=>{});
    assert.equal(await p.evaluate(()=>document.body.classList.contains('smr-theme-glass')),true,'glass persists after reload');
    // 목록에 없는 저장값은 기본 테마로 떨어진다
    await p.evaluate(()=>{BookAIStorage.setItem('storymemory.readerSettings.v1',JSON.stringify({version:1,font:'noto-sans-kr',fontSize:'base',lineHeight:'relaxed',theme:'nope',englishMode:'compact',verseNumbers:true}));});
    await p.waitForTimeout(300);
    await p.reload({waitUntil:'load'});await p.waitForTimeout(1500);
    await p.evaluate(()=>openStoredMemoryContext('사도행전 9장'));
    await p.waitForFunction(()=>document.getElementById('reader').classList.contains('active'),null,{timeout:15000});
    assert.equal(await p.evaluate(()=>document.body.classList.contains('smr-theme-glass')),false,'unknown saved theme falls back');
    const backPaper=await p.evaluate(()=>getComputedStyle(document.querySelector('.paper')).backgroundColor);
    assert.equal(backPaper,'rgb(255, 253, 248)','fallback returns default paper');
    // 기본 테마로 되돌리면 글래스 클래스가 남지 않는다
    await openSettingsPanel(p);
    await p.locator('.srsg-panel .srsg-sw button[data-value="glass"]').click();
    await p.locator('.srsg-panel .srsg-sw button[data-value="default"]').click();
    assert.equal(await p.evaluate(()=>document.body.classList.contains('smr-theme-glass')),false,'switching back removes glass class');
    await p.close();
  }
  console.log('PASS: glass theme (list, default unchanged, apply, persist, unknown fallback, scoped css) at 1440 and 390');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
