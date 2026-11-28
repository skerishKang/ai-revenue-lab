import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../public');
const source=(name)=>fs.readFileSync(path.join(root,name),'utf8');

test('#8779-1 의견 보내기는 떠 있지 않고 서재·읽기 메뉴 마지막에 있다',()=>{
  const html=source('index.html');
  const css=source('styles/bookai-7839-feedback.css');
  const library=source('storymemory-b61-library-firstscreen-v1.js');
  const reader=source('storymemory-reader-settings-v1.js');
  assert.doesNotMatch(html,/<button class="bookai-feedback-open"/);
  assert.doesNotMatch(css,/position:\s*fixed/);
  assert.match(library,/menu\.append\(.*feedback/);
  assert.match(reader,/ovMenu\.append\(.*feedback/);
});

test('#8779-2 휴대폰 본문 끝 56px 보호 여백',()=>{
  const css=source('styles/storymemory-review-261031.css');
  assert.match(css,/#reader #readerPageBody\s*\{[^}]*padding-bottom:56px/);
});

test('#8779-6 큰 화면 절 번호를 왼쪽 바깥으로 밀지 않음',()=>{
  const css=source('styles/storymemory-reader-simplification-v2.css');
  assert.match(css,/#reader #readerPageBody \.vn\s*\{[^}]*margin-left:0/);
});

test('#8779-7 제목과 검색 줄은 본문 열 최대 폭에 맞춤',()=>{
  const css=source('styles/storymemory-reader-simplification-v2.css');
  assert.match(css,/#reader \.paper-head\s*\{[^}]*width:696px/);
});

test('#8779-3 측면 AI 질문 통일',()=>{
  const html=source('index.html');
  assert.match(html,/id="aiRailTab"[^>]*><span>AI 질문<\/span>/);
  assert.doesNotMatch(html,/id="aiRailTab"[^>]*AI 도우미/);
});

test('#8779-4 어둡게 탭은 테마 토큰을 사용',()=>{
  const css=source('styles/storymemory-b61-typography-authority-v1.css');
  assert.match(css,/\.panel-rail-tab\{[^}]*background:var\(--sm-rail-bg\)/);
  assert.match(css,/\.panel-rail-tab\{[^}]*color:var\(--sm-rail-ink\)/);
  assert.match(css,/body\.smr-theme-dark\s*\{[^}]*--sm-rail-bg:/);
});

test('#8779-8 검색 안내 문구 최소 13px와 대비 4.5:1',()=>{
  const css=source('styles/bookai-7574-polish-v1.css');
  assert.match(css,/\.bible-search-panel>summary span[^}]*font-size:13px/);
  assert.match(css,/--sm-search-hint-ink/);
});

test('#8779-9 의미 없는 장식선 제거',()=>{
  const css=source('styles/storymemory-reader-simplification-v2.css');
  assert.match(css,/\.v2-chapter-chip::after\s*\{[^}]*content:none/);
  assert.match(css,/\.paper-head::after\s*\{[^}]*content:none/);
  const search=source('styles/bookai-7574-polish-v1.css');
  assert.match(search,/\.bible-search-panel>summary::after\s*\{[^}]*content:none/);
});
