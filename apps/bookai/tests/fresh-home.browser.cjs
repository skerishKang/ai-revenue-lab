const {chromium}=require('playwright');const assert=require('node:assert/strict');
// #7574 항목 2 — 새 사용자에게 예시 기억이 숫자로 보이지 않는다.
// 오늘 화면의 복습 수(TODAY 버튼·"다시 떠올릴 기억")는 사용자가 직접 만든 기억만 센다.
// 본문에서 자동 수집한 개체 기억(entity: 바울·아볼로·하나님의 밭)은 집계에서 제외되며,
// 기억 패널의 흐름·관계 기능은 그대로 개체 원장을 쓴다. 새 사용자는 0이고, 사용자가
// 메모를 남기면 그 기억만 숫자로 올라온다. 첫 화면과 다시 불러온 화면이 같은 값을 보인다.
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});try{
for(const width of [390,1440]){const p=await b.newPage({viewport:{width,height:844}});
const settled=async()=>{await p.evaluate(()=>window.BookAIReady);await p.waitForFunction(()=>typeof todayRecallItems==='function',null,{timeout:20000});};
await p.goto('http://127.0.0.1:18779/?view=today',{waitUntil:'load'});
await settled();
// 첫 화면: 예시 기억이 숫자로 보이지 않는다(0), 개체 기억은 집계에 없다.
await p.evaluate(()=>renderTodayHome());
assert.equal(await p.locator('#todayRecallCount').innerText(),'0');
assert.equal(await p.locator('#todayEntryCount').innerText(),'0');
assert.deepEqual(await p.evaluate(()=>todayRecallItems().map(i=>i.kind)),[]);
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
assert.equal(await p.evaluate(()=>allReaderProgressEntries().length),0);
// 다시 불러온 화면: 같은 값.
await p.reload({waitUntil:'load'});
await settled();
await p.evaluate(()=>renderTodayHome());
assert.equal(await p.locator('#todayRecallCount').innerText(),'0');
assert.deepEqual(await p.evaluate(()=>todayRecallItems().map(i=>i.kind)),[]);
assert.equal(await p.locator('#todayContinueMeta').innerText(),'추천 본문');
// 사용자가 직접 만든 기억은 센다: 메모를 저장하면 1.
await p.evaluate(()=>{
  __smUserMemories.push({id:'test-user-memory-1',kind:'note',title:'내 메모',body:'직접 남긴 기억',context:'고린도전서 3장',createdAt:Date.now(),updatedAt:Date.now()});
  saveUserMemories?.();
  renderTodayHome();
});
assert.equal(await p.locator('#todayRecallCount').innerText(),'1');
assert.equal(await p.locator('#todayEntryCount').innerText(),'1');
assert.deepEqual(await p.evaluate(()=>todayRecallItems().map(i=>i.kind)),['note']);
await p.close();}console.log('PASS: fresh home counts only user-made memories (0 on fresh load, 1 after a user note) at 390/1440');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
