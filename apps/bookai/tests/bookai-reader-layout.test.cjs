const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','public','index.html'),'utf8');
const SCRIPT_ATTR='type="application/x-bookai" data-bookai-script';

test('Bible search panel stays inside paper-head and out of the reader grid',()=>{
  const stageStart=html.indexOf('<main class="reader-stage">');
  const paperStart=html.indexOf('<div class="paper-stack"',stageStart);
  assert.ok(stageStart>=0&&paperStart>stageStart,'reader-stage and paper-stack must exist');
  assert.ok(!html.slice(stageStart,paperStart).includes('id="bibleSearchPanel"'),'panel must not be a reader-stage child');
  const panel=html.indexOf('id="bibleSearchPanel"');
  const head=html.indexOf('<div class="paper-head">');
  const body=html.indexOf('<div id="readerPageBody">');
  assert.ok(head>=0&&panel>head&&panel<body,'panel must be inside paper-head before the body');
  assert.match(html,/#reader\.active \.paper-head>\.bible-search-panel\{flex:1 0 100%/);
});

test('ported scripts use the bookai loader and keep their relative order',()=>{
  const companion=html.indexOf('storymemory-companion-adapter-v1.js');
  const answer=html.indexOf('storymemory-answer-evidence-v1.js');
  const inline=html.indexOf('id="sm-companion-evidence-ux-v1"');
  assert.ok(companion>=0&&answer>companion,'answer-evidence must follow companion-adapter');
  assert.ok(inline>answer,'the #6808 inline block follows answer-evidence');
  assert.match(html.slice(answer-120,answer+120),new RegExp(SCRIPT_ATTR));
  const ref=html.indexOf('storymemory-bible-reference-v1.js');
  const search=html.indexOf('storymemory-bible-search-v1.js');
  assert.ok(ref>=0&&search>ref,'bible-reference precedes bible-search');
  assert.match(html.slice(ref-120,ref+120),new RegExp(SCRIPT_ATTR));
  assert.match(html.slice(search-120,search+120),new RegExp(SCRIPT_ATTR));
  assert.match(html.slice(inline-160,inline+40),new RegExp(SCRIPT_ATTR));
});

test('#6476 모바일 章 칩은 44px 이상 높이로 제공한다',()=>{
  const css=fs.readFileSync(path.join(__dirname,'..','public','styles','storymemory-reader-simplification-v2.css'),'utf8').replace(/\s+/g,' ');
  assert.match(css,/\.v2-chapter-chip\{[^}]*min-height:44px/,'v2ChapterChip must keep a 44px touch target');
});

test('#6476 모바일 읽기 화면에서 의견 보내기는 AI 하단 탭을 덮지 않는다',()=>{
  const css=fs.readFileSync(path.join(__dirname,'..','public','styles','bookai-7839-feedback.css'),'utf8').replace(/\s+/g,' ');
  assert.match(css,/body\.reader-mode \.bookai-feedback-open \{ bottom: 128px; \}/,'feedback button must move above the reader dock');
});

test('#6476 홈 첫 화면 안내문은 떠 있는 TODAY 칩 아래에서 시작한다',()=>{
  const css=fs.readFileSync(path.join(__dirname,'..','public','styles','storymemory-b61-mobile-polish-v1.css'),'utf8').replace(/\s+/g,' ');
  assert.match(css,/@media \(max-width: 720px\) \{ #library \.lib-head \{ margin-top: 58px; \}/,
    'TODAY 칩(높이 44, y 28~72) 아래에서 시작하도록 위 여백이 있어야 한다');
  assert.match(css,/#library \.lib-head \.kicker \{ white-space: normal; line-height: 1\.45; \}/,
    '폭이 좁아도 안내문이 잘리지 않도록 줄바꿈을 허용한다');
  const html=fs.readFileSync(path.join(__dirname,'..','public','index.html'),'utf8');
  assert.match(html,/<div class="kicker">북AI · 읽고, 묻고, 기억하는 책<\/div>/,
    '안내문은 없애지 않고 그대로 둔다');
});

test('#6476 클라우드 설정 닫기 버튼은 40px 터치 영역을 제공한다',()=>{
  const css=fs.readFileSync(path.join(__dirname,'..','public','styles','storymemory-product-v30-v319.css'),'utf8').replace(/\s+/g,' ');
  assert.match(css,/\.auth-gate-close\{[^}]*width:40px;height:40px/,'auth gate close button must meet the 40px touch target');
});
