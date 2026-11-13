const {chromium}=require('playwright');const assert=require('node:assert/strict');
// #7574 — 화면 문구·표시 다듬기 검증 (항목 1·2·3·4·7)
// 1. 이슈가 지적한 영어·내부 용어가 화면 글자에서 사라졌고, 바꾼 한국어 문구가 보인다.
// 2. 새 사용자 상태에서 기억 숫자가 0이다(예시 기억 미집계).
// 3. '찾아보며 읽기'(전체 참고)에서 첫 안내가 "아직 읽지 않은 내용은 보여주지 않습니다"와
//    모순되지 않고, '처음 읽어요'로 바꾸면 그 문구로 바뀐다.
// 4. AI 오류 말풍선에는 오류 문구와 "다시 시도"만 있다(저장 버튼·출처 줄·확인 배지 없음).
// 7. 서재의 '자료/＋' 스위치가 보이지 않는다.
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});
await p.goto('http://127.0.0.1:18779/?view=today',{waitUntil:'load'});
await p.evaluate(()=>window.BookAIReady);
await p.evaluate(()=>{renderTodayHome();transitionTo('today');});
await p.waitForTimeout(500);

// 1 · 오늘 화면 문구
let body=await p.locator('body').innerText();
for(const bad of ['PERSONAL READING HOME','Recall 시작','← Library','LOCAL · SAVED','TODAY\'S MEMORIES','CONTINUE READING','RECENT READING THREAD'])
  assert.ok(!body.includes(bad),'today 화면에 옛 문구가 남아 있음: '+bad);
assert.ok(body.includes('← 서재'),'새 문구 없음: ← 서재');
assert.ok(body.includes('복습 시작'),'새 문구 없음: 복습 시작');
assert.ok(body.includes('내 읽기 홈'),'새 문구 없음: 내 읽기 홈');

// 2 · 새 사용자 기억 숫자
assert.equal(await p.locator('#todayRecallCount').innerText(),'0');
assert.equal(await p.locator('#todayEntryCount').innerText(),'0');

// 1 · 서재 화면 문구 + 7 · 자료 스위치 숨김
await p.evaluate(()=>transitionTo('library'));
await p.waitForTimeout(700);
body=await p.locator('body').innerText();
assert.ok(!body.includes('STORYMEMORY · READ / REMEMBER'),'책 표지 옛 이름이 남아 있음');
assert.ok(!body.includes('ORDER ·'),'옛 정렬 문구가 남아 있음');
const switchVisible=await p.evaluate(()=>{
  const el=document.querySelector('.source-mode-switch');
  if(!el)return false;
  const r=el.getBoundingClientRect();
  return !!(el.offsetParent!==null&&r.width>0&&r.height>0);
});
assert.equal(switchVisible,false,'자료/＋ 스위치가 보이면 안 됩니다');

// 1·3 · 읽기 화면 + AI 안내
await p.evaluate(()=>transitionTo('reader'));
await p.waitForTimeout(2500);
body=await p.locator('body').innerText();
for(const bad of ['MEMORY TIMELINE','MARGINALIA / INDEX','AI Companion'])
  assert.ok(!body.includes(bad),'읽기 화면에 옛 문구가 남아 있음: '+bad);
assert.ok(body.includes('기억 흐름'),'새 문구 없음: 기억 흐름');
// 성경 기본 '찾아보며 읽기' — 모순 문구가 없어야 한다
let guide=await p.evaluate(()=>document.querySelector('#companionEmptyState p')?.textContent||'');
assert.ok(!guide.includes('아직 읽지 않은 내용은 보여주지 않습니다'),'찾아보며 읽기에서 모순 안내가 보임');
assert.ok(guide.includes('지금 읽는 책의 내용과 저장한 기억을 함께 사용해 답합니다'),'찾아보며 읽기 안내 문구 없음');
// '처음 읽어요'로 바꾸면 제한 문구로 바뀐다
// (읽기 방식은 읽기 진행 레코드가 있는 책에 저장된다 — 레코드를 먼저 만든다)
await p.evaluate(()=>storyMemoryAdvanceReadingProgressV1('bible-web','bible:고린도전서:3:1'));
await p.evaluate(()=>storyMemoryAdvanceReadingProgressV1('bible-web','bible:고린도전서:3:1'));
await p.evaluate(()=>storyMemorySetReadingModeV1('bible-web','first_read'));
guide=await p.evaluate(()=>document.querySelector('#companionEmptyState p')?.textContent||'');
assert.ok(guide.includes('아직 읽지 않은 내용은 보여주지 않습니다'),'처음 읽어요 안내 문구 없음');
await p.evaluate(()=>storyMemorySetReadingModeV1('bible-web','browse'));

// 3 · AI 시트 맨 위 빈 흰 상자가 없다
await p.evaluate(()=>{document.body.classList.add('ai-open');document.body.classList.remove('memory-open');});
await p.waitForTimeout(400);
const boxVisible=await p.evaluate(()=>{
  const el=document.querySelector('#reader .ai-panel .chat-thread>.ai-context-runtime');
  if(!el)return false;
  const r=el.getBoundingClientRect();
  return !!(el.offsetParent!==null&&r.height>0);
});
assert.equal(boxVisible,false,'AI 시트 맨 위 빈 흰 상자가 보이면 안 됩니다');

// 4 · AI 오류 말풍선
const err=await p.evaluate(()=>{const n=appendAIMessage('일시적인 기술 문제입니다.','다시 시도해 주세요.','현재 본문 · DB 우선',{liveCompanion:true,error:'network_failed',retryable:true,question:'오류 시험'});
  return {verified:!!n.querySelector('.verified'),source:!!n.querySelector('.source'),save:!!n.querySelector('.save-ai-memory'),chip:!!n.querySelector('.ai-persona-chip'),retry:!!n.querySelector('.sm-ev-retry button')};});
assert.equal(err.verified,false,'오류 말풍선에 확인 배지가 붙음');
assert.equal(err.source,false,'오류 말풍선에 출처 줄이 붙음');
assert.equal(err.save,false,'오류 말풍선에 저장 버튼이 붙음');
assert.equal(err.chip,false,'오류 말풍선에 AI 읽기 동행 칩이 붙음');
assert.equal(err.retry,true,'오류 말풍선에 다시 시도가 없음');
// 정상 답변에는 저장 버튼과 확인 배지가 그대로 있다
const ok=await p.evaluate(()=>{const n=appendAIMessage('확인된 기억','정상 답변 본문입니다.','현재 본문 · DB 우선',{liveCompanion:true,question:'정상 시험'});
  return {verified:!!n.querySelector('.verified'),save:!!n.querySelector('.save-ai-memory')};});
assert.equal(ok.verified,true,'정상 답변 확인 배지 사라짐');
assert.equal(ok.save,true,'정상 답변 저장 버튼 사라짐');

await p.close();}
console.log('PASS: #7574 copy/visibility checks at 390 and 1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
