/* 261106 · 동행 독자 결정·근거·접힘 시험 (오프라인 node --test).
   운영에서 확인된 세 가지 거절 문제를 실제 코퍼스(public/content/bible-web)로 재현한다:
   (1) "바울은 누구인가요?" — 현재 페이지 토큰 완전일치 게이트가 조사 어미 변형
       (바울에게라/바울이나 vs 바울은) 때문에 배경 질문을 거절했다.
   (2) "오늘 기분이 안 좋아요" — 창세기 1~24장 어휘의 일상어(오늘)가 질문을
       작품 질문으로 승격시켜 같은 게이트가 일반 대화를 거절했다.
   (3) "고린도는 어디인가요?" — 배경 질문이 배경 질문으로 분류되지 않았다.
   (4) 처음 읽어요 모드의 전개 질문 — 접힘 응답으로 바뀐다.
   (5) 질문 전 정적 장 요청은 3개 이하(현재 장+직전 장)여야 한다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const publicDir = path.join(__dirname, '../public');
const contentDir = path.join(publicDir, 'content/bible-web');

function freshContext(store) {
  const backing = store || new Map();
  const window = {};
  const ctx = {
    window,
    BookAIStorage: {
      getItem: key => (backing.has(key) ? backing.get(key) : null),
      setItem: (key, value) => backing.set(key, String(value)),
      removeItem: key => backing.delete(key)
    }
  };
  return {ctx, window, backing};
}
function loadModule(ctx, file) {
  vm.runInNewContext(fs.readFileSync(path.join(publicDir, file), 'utf8'), ctx);
}
function loadCompanionStack(store) {
  const {ctx, window, backing} = freshContext(store);
  loadModule(ctx, 'storymemory-locator-progress-v1.js');
  loadModule(ctx, 'storymemory-keyword-search-v1.js');
  loadModule(ctx, 'storymemory-retrieval-adapter-v1.js');
  loadModule(ctx, 'storymemory-knowledge-ceiling-policy-v1.js');
  return {ctx, window, backing};
}
function readChapter(code, chapter) {
  return JSON.parse(fs.readFileSync(
    path.join(contentDir, `book-${code}-chapter-${String(chapter).padStart(3, '0')}.json`), 'utf8'));
}
function evidenceVerses(code, chapter, verses) {
  return (readChapter(code, chapter).passages || [])
    .filter(row => verses.includes(Number(String(row.canonical_locator).split(':')[4])))
    .map(row => ({text: String(row.ko || row.en || '')}));
}
function genesisBlocks(chapters) {
  const blocks = [];
  for (const chapter of chapters) {
    const unit = readChapter('GEN', chapter);
    for (const row of unit.passages || []) {
      blocks.push({
        canonical_locator: row.canonical_locator,
        work_key: 'bible-web',
        unit_key: unit.unit_key,
        unit_ordinal: unit.unit_ordinal,
        sequence: Number(row.sequence) || blocks.length + 1,
        ko: String(row.ko || ''),
        en: String(row.en || ''),
        text: String(row.ko || row.en || '')
      });
    }
  }
  return blocks;
}
function seedProgress(backing, workKey, entry) {
  const key = 'storymemory.readingProgress.v1';
  let raw = backing.get(key) || null;
  let parsed = raw ? JSON.parse(raw) : null;
  if (!parsed || typeof parsed !== 'object') parsed = {version: 1, works: {}};
  parsed.works[workKey] = entry;
  backing.set(key, JSON.stringify(parsed));
}
function seedGenesisCeiling(window, workKey) {
  // 운영과 같은 조건: 창세기 1~24장 어휘로 만든 천장 용어 색인 (일상어 오늘 포함).
  window.storyMemorySeedGroundingBlocksV1(genesisBlocks([1, 4, 14, 19, 21, 24]), workKey);
}

const FIRST_CO3 = {furthest_read_locator: 'bible:web:1CO:3:5', knowledge_ceiling_locator: 'bible:web:1CO:3:5'};
const GEN37 = {furthest_read_locator: 'bible:web:GEN:37:31', knowledge_ceiling_locator: 'bible:web:GEN:37:31'};

test('(1) 고전 3장에서 "바울은 누구인가요?" 는 배경 질문으로 허용된다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', FIRST_CO3);
  // 현재 페이지 근거: 3:4(바울에게라)·3:22(바울이나) — 조사가 다른 완전일치 불가 케이스.
  const evidence = evidenceVerses('1CO', 3, [4, 22]);
  const decision = window.storyMemoryCoReaderDecisionV1('바울은 누구인가요?', null, 'bible-web', evidence);
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.reason, 'BACKGROUND_QUESTION');
});

test('(2) "오늘 기분이 안 좋아요" 는 일반 대화로 허용된다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', FIRST_CO3);
  seedGenesisCeiling(window, 'bible-web');
  const evidence = evidenceVerses('1CO', 3, [4, 5]);
  const decision = window.storyMemoryCoReaderDecisionV1('오늘 기분이 안 좋아요', null, 'bible-web', evidence);
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.reason, 'GENERAL_CHAT');
  assert.equal(decision.question_class, 'general');
});

test('(3) "고린도는 어디인가요?" 는 배경 질문으로 분류되어 허용된다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', FIRST_CO3);
  seedGenesisCeiling(window, 'bible-web');
  const evidence = evidenceVerses('1CO', 3, [4, 5]);
  const decision = window.storyMemoryCoReaderDecisionV1('고린도는 어디인가요?', null, 'bible-web', evidence);
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.reason, 'BACKGROUND_QUESTION');
  assert.equal(decision.question_class, 'background');
});

test('(4) 처음 읽어요 모드에서 창 37장 중 전개 질문은 접힘 응답으로 허용된다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', {...GEN37, reading_mode: 'first_read', opened_units: ['bible:web:GEN:37']});
  const evidence = evidenceVerses('GEN', 37, [2, 28]);
  const decision = window.storyMemoryCoReaderDecisionV1('요셉은 형들을 다시 만나나요?', null, 'bible-web', evidence, {
    readingMode: 'first_read', openedUnits: ['bible:web:GEN:37'], currentBookId: 'GEN'
  });
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.question_class, 'plot');
  assert.equal(decision.spoiler_fold, true);
});

test('(4-2) 찾아보며 읽기 모드의 전개 질문은 전체 참고로 허용된다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', {...GEN37, reading_mode: 'browse', opened_units: ['bible:web:GEN:37']});
  const decision = window.storyMemoryCoReaderDecisionV1('요셉은 형들을 다시 만나나요?', null, 'bible-web', [], {
    readingMode: 'browse', openedUnits: ['bible:web:GEN:37'], currentBookId: 'GEN'
  });
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.question_class, 'plot');
});

test('(4-3) 비이야기책(서신)은 처음 읽어요 모드에서도 전개 질문이 전체 참고다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', FIRST_CO3);
  const evidence = evidenceVerses('1CO', 3, [4, 5]);
  const decision = window.storyMemoryCoReaderDecisionV1('바울은 다음에 어디로 떠났어요?', null, 'bible-web', evidence, {
    readingMode: 'first_read', openedUnits: ['bible:web:1CO:3'], currentBookId: '1CO'
  });
  assert.equal(decision.decision, 'ALLOW');
  assert.equal(decision.spoiler_fold, undefined);
});

test('(5) 질문 전 정적 장 요청은 3개 이하이다 (현재 장+직전 장)', async () => {
  const store = new Map();
  const {ctx, window} = loadCompanionStack(store);
  seedProgress(store, 'bible-web', {...GEN37, reading_mode: 'first_read', opened_units: ['bible:web:GEN:37']});
  const loadedOrdinals = [];
  const unitByOrdinal = new Map();
  for (const ordinal of [36, 37]) {
    const unit = readChapter('GEN', ordinal);
    unitByOrdinal.set(ordinal, unit);
  }
  window.storyMemoryStatic = {
    getCatalog: async () => ({works: [{work_key: 'bible-web'}]}),
    getManifest: async () => {
      const manifest = JSON.parse(fs.readFileSync(path.join(contentDir, 'manifest.json'), 'utf8'));
      return {entry: {work_key: 'bible-web'}, manifest};
    },
    loadUnit: async ({unitOrdinal}) => {
      loadedOrdinals.push(unitOrdinal);
      return {unit: unitByOrdinal.get(unitOrdinal) || readChapter('GEN', Math.min(50, unitOrdinal))};
    }
  };
  window.storyMemoryGetReaderContextV1 = () => ({
    authoritative_reader: true, current_work_key: 'bible-web',
    current_unit_key: 'bible:web:GEN:37', current_unit_ordinal: 37,
    visible_locator_start: 'bible:web:GEN:37:1', visible_locator_end: 'bible:web:GEN:37:31'
  });
  const blocks = await window.storyMemoryEnsureGroundingBlocksV1('bible-web');
  assert.ok(blocks && blocks.length, 'grounding blocks are loaded');
  assert.ok(loadedOrdinals.length <= 3, `static unit loads must stay <=3, got ${loadedOrdinals.length}`);
  const units = new Set(loadedOrdinals);
  assert.ok(units.has(37), 'current chapter is loaded');
  assert.ok(units.has(36), 'previous chapter is loaded');
});

test('(6) 읽은 장 집합이 진행 위치와 함께 저장되고 모드 기본값이 책 종류를 따른다', () => {
  const store = new Map();
  const {window} = loadCompanionStack(store);
  window.storyMemoryAdvanceReadingProgressV1('bible-web', 'bible:web:GEN:37:31');
  window.storyMemoryAdvanceReadingProgressV1('bible-web', 'bible:web:GEN:36:1');
  const progress = window.storyMemoryGetReadingProgressV1('bible-web');
  assert.deepEqual(Array.from(progress.opened_units).sort(), ['bible:web:GEN:36', 'bible:web:GEN:37']);
  assert.equal(progress.furthest_read_locator, 'bible:web:GEN:37:31');
  assert.equal(window.storyMemoryGetReadingModeV1('bible-web'), 'browse');
  assert.equal(window.storyMemoryGetReadingModeV1('divine-comedy'), 'first_read');
  window.storyMemorySetReadingModeV1('bible-web', 'first_read');
  assert.equal(window.storyMemoryGetReadingModeV1('bible-web'), 'first_read');
  const reloaded = loadCompanionStack(store);
  assert.deepEqual(Array.from(reloaded.window.storyMemoryGetReadingProgressV1('bible-web').opened_units).sort(),
    ['bible:web:GEN:36', 'bible:web:GEN:37']);
  assert.equal(reloaded.window.storyMemoryGetReadingModeV1('bible-web'), 'first_read');
});

test('(7) 답변의 접힘 버튼은 누르기 전까지 본문을 DOM 에 넣지 않는다', () => {
  const {window} = loadCompanionStack();
  const makeElement = tagName => ({
    tagName, children: [], dataset: {}, attributes: {},
    className: '',
    append(child) { this.children.push(child); },
    insertBefore(child) { this.children.push(child); },
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    classList: {add() {}, remove() {}, toggle() {}},
    remove() {}
  });
  const document = {createElement: makeElement, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null};
  const evidenceApi = require('../public/storymemory-answer-evidence-v1.js');
  const ctx = {window: {storyMemoryAnswerEvidenceV1: evidenceApi}, document};
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  const script = html.match(/<script[^>]*id="sm-companion-evidence-ux-v1"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(script, 'B61 evidence presentation script is present');
  vm.runInNewContext(script[1], ctx);
  const node = makeElement('article');
  ctx.window.__smV1823EvidenceUXV1.decorateLive(node, {
    liveCompanion: true,
    question: '요셉은 형들을 다시 만나나요?',
    spoilerFolds: [{books: ['창세기 45장'], text: '형들을 다시 만납니다. 요셉이 자신을 드러냅니다.'}]
  }, '읽은 범위 안에서는 이 질문에 답할 내용이 아직 없어요.');
  const html1 = JSON.stringify(node);
  assert.ok(!html1.includes('자신을 드러냅니다'), 'folded text must stay out of the DOM before the click');
  const foldWrap = node.children.find(child => child.className === 'sm-spoiler-folds');
  assert.ok(foldWrap, 'fold container is rendered');
  const foldItem = foldWrap.children.find(child => child.className === 'sm-spoiler-fold');
  assert.ok(foldItem, 'fold item is rendered');
  const btn = foldItem.children.find(child => String(child.className || '').indexOf('sm-spoiler-fold-btn') >= 0);
  assert.ok(btn, 'fold button is rendered');
  assert.match(btn.textContent, /더 보기 · 아직 안 읽은 창세기 45장 포함/);
  btn.onclick();
  assert.ok(JSON.stringify(foldWrap).includes('자신을 드러냅니다'), 'click inserts the folded paragraph');
});
