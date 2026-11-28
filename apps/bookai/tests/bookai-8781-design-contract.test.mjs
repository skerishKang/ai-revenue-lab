// #8779 2차 + #8781: 화면 측정 수치와 함께 바뀌면 안 되는 설계 계약.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
const pub=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../public');
const read=f=>fs.readFileSync(path.join(pub,f),'utf8');
const shelf=()=>read('styles/storymemory-b61-library-firstscreen-v1.css');

test('#8779-A 읽기 설정 이름만 읽기 화면 테마로 확정',()=>{
 const js=read('storymemory-reader-settings-v1.js');
 assert.match(js,/lb\.textContent='읽기 화면 테마'/);
 assert.doesNotMatch(js,/lb\.textContent='테마 · 배경'/);
});

test('#8779-C 어둡게 장 칩의 바탕·글자는 같은 테마 토큰으로 지정',()=>{
 const css=read('styles/storymemory-reader-simplification-v2.css');
 assert.match(css,/--sm-chapter-chip-bg:/);
 assert.match(css,/body\.smr-theme-dark\s*\{[^}]*--sm-chapter-chip-bg:/);
 assert.match(css,/\.v2-chapter-chip\{[^}]*background:var\(--sm-chapter-chip-bg\)/);
 assert.match(css,/\.v2-chapter-chip\{[^}]*color:var\(--sm-chapter-chip-ink\)/);
});

test('#8781-1 큰 제목 행간·작은 화면 글자 크기는 승인된 수치',()=>{
 assert.match(shelf(),/#library \.hero-title\s*\{[^}]*line-height:1\.48/);
 const mobile=read('styles/storymemory-interaction-v28-v282.css');
 assert.match(mobile,/font-size:clamp\(30px,8\.5vw,39px\)!important/);
 assert.match(mobile,/line-height:1\.48!important/);
});

test('#8781-2 한글 책 이름과 자료 서재 안내에 낱말 단위 줄바꿈',()=>{
 const css=shelf();
 assert.match(css,/\.cover-copy strong[^}]*word-break:keep-all/);
 assert.match(css,/\.spine-copy[^}]*word-break:keep-all/);
 const source=read('storymemory-source-ui.css');
 assert.match(source,/\.source-object-copy (?:strong|span)[^}]*word-break:keep-all/);
});

test('#8781-3 SEMANTIC POSITION 제거 및 확정된 서재 문구 유지',()=>{
 const html=read('index.html');
 assert.match(html,/\.filter\(part=>part && part!=='SEMANTIC POSITION'\)/);
 assert.match(html,/책장 순서 · <b>기본<\/b>/);
 const lib=read('storymemory-b61-library-firstscreen-v1.js');
 assert.match(lib,/책장 넘기는 속도/);
});

test('#8781-4 데스크톱의 의미 없는 서재 장식 글자 제거',()=>{
 assert.match(shelf(),/@media\(min-width:901px\)[\s\S]*?#library \.scene-meta[^}]*display:none/);
 assert.match(shelf(),/#library \.collection-stamp[^}]*display:none/);
});

test('#8781-5 서재 통계 줄 여백과 쪽수 표기',()=>{
 const css=shelf();
 assert.match(css,/#library \.library-order-control\s*\{[^}]*right:48px/);
 assert.match(css,/#library \.library-reading-summary\s*\{[^}]*font:[^}]*12px/);
 const html=read('index.html');
 assert.match(html,/\$\{page\}\/\$\{pageCount\}쪽/);
});

test('#8781-6 서재 메뉴는 기존 네 항목을 한 줄 목록으로 제공',()=>{
 const js=read('storymemory-b61-library-firstscreen-v1.js');
 assert.match(js,/menu\.append\(account,motion,order,feedback\)/);
 assert.match(js,/sm-library-menu-item/);
 assert.match(shelf(),/\.sm-library-menu-item\s*\{[^}]*min-height:44px/);
});

test('#8781-7 불러오기 덮개와 서재 바탕은 같은 색 토큰, 진행 표시 있음',()=>{
 const boot=read('bookai-bootstrap.js');
 const css=read('styles/storymemory-shell-foundation-v1.css');
 assert.match(boot,/var\(--sm-library-bg\)/);
 assert.match(boot,/bookai-startup-progress/);
 assert.match(css,/--sm-library-bg:/);
});

test('#8781-8 눌리는 책장 점은 44×44 이상',()=>{
 assert.match(shelf(),/#library #markers \.marker\s*\{[^}]*min-width:44px;[^}]*min-height:44px/);
});
