import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../public');
const read=f=>fs.readFileSync(path.join(root,f),'utf8');
test('#8783 대표 확정: 0개 빈 기억 문구와 본문 읽기 단추',()=>{
 const ui=read('storymemory-library-ui-v1.js');
 assert.match(ui,/아직 기억이 없습니다\. 읽다가 표시하거나 메모를 남기면 여기에 모입니다\./);
 assert.match(ui,/recallBtn\.textContent='본문 읽기'/);
 assert.match(ui,/memoryTotal===0/);
});
test('#8783 NOTE는 메모, 필터는 이 책 기억만',()=>{
 const html=read('index.html');
 assert.match(html,/kind:m\.kind==='ai'\?'AI 질문':'메모'/);
 assert.match(html,/mem\.textContent='이 책 기억만'/);
});
test('#8783 저장 상태 중복의 기본값은 보이지 않고 오류는 보존',()=>{
 const css=read('styles/storymemory-product-v30-v319.css');
 assert.match(css,/#today \.today-data-status:not\(\.saving\):not\(\.error\)\s*\{\s*display:none/);
});
test('#8781 확정 메뉴 이름·기본 순서',()=>{
 const ui=read('storymemory-b61-library-firstscreen-v1.js');
 const html=read('index.html');
 assert.match(ui,/motionText\.textContent='책장 넘기는 속도'/);
 assert.match(html,/책장 순서 · <b>기본<\/b>/);
});
test('#8781 성경 책 표지만 작은 표 유지, 12px 이상',()=>{
 const css=read('styles/storymemory-v329-library-state.css');
 assert.match(css,/\.book-rig:not\(\[data-motif="bible"\]\) \.book-reading-state\{display:none\}/);
 assert.match(css,/#library \.book-rig\[data-motif="bible"\] \.book-reading-state small\{[^}]*font-size:12px/);
 assert.match(css,/#library \.book-rig\[data-motif="bible"\] \.book-reading-state b\{[^}]*font-size:12px/);
});
