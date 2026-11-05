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
