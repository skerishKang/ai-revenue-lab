const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {projectAnswerEvidence, parseCitations, krvLabelOf} = require('../public/storymemory-answer-evidence-v1.js');

const publicDir = path.join(__dirname, '../public');
const codes = {사도행전: 'ACT', 창세기: 'GEN'};
const compareContext = {window: {}, localStorage: {getItem: () => null, setItem: () => {}, removeItem: () => {}}};
vm.runInNewContext(fs.readFileSync(path.join(publicDir, 'storymemory-locator-progress-v1.js'), 'utf8'), compareContext);
const compareLocators = compareContext.window.storyMemoryCompareLocatorV1;

function packet(locators, ceiling = 'bible:web:ACT:9:5') {
  return {
    reader_context: {authoritative_reader: true, current_work_key: 'bible-web', current_unit_key: 'bible:web:ACT:9'},
    reading_progress: {furthest_read_locator: ceiling, knowledge_ceiling_locator: ceiling},
    source_passages: locators.map(canonical_locator => ({canonical_locator}))
  };
}

test('only explicitly cited verses already in the bounded packet are displayed', () => {
  const answer = '사울에게 일어난 일은 사도행전 9장 1~5절에 나옵니다.';
  const allowed = ['bible:web:ACT:9:1', 'bible:web:ACT:9:2', 'bible:web:ACT:9:5'];
  const mixedPacket = packet([...allowed, 'bible:web:GEN:2:1', 'bible:web:GEN:2:2', 'bible:web:GEN:2:3']);
  // This reproduces the reported display leak: prior Genesis candidates are
  // model-visible, and an absent unit key bypasses the old UI's chapter guard.
  mixedPacket.reader_context.current_unit_key = null;
  assert.deepEqual(projectAnswerEvidence(answer, mixedPacket, codes, compareLocators), allowed);
});

test('a relevant-only packet keeps its cited verse locator', () => {
  const onlyActs = packet(['bible:web:ACT:9:1', 'bible:web:ACT:9:2']);
  assert.deepEqual(
    projectAnswerEvidence('사도행전 9:1-2에서 사울이 길을 나섭니다.', onlyActs, codes, compareLocators),
    ['bible:web:ACT:9:1', 'bible:web:ACT:9:2']
  );
});

test('no explicit answer citation produces no verse evidence chips', () => {
  const candidatePacket = packet(['bible:web:ACT:9:1', 'bible:web:GEN:2:1']);
  assert.deepEqual(projectAnswerEvidence('사울은 다메섹으로 가던 중 예수를 만났습니다.', candidatePacket, codes, compareLocators), []);
  assert.deepEqual(projectAnswerEvidence('사도행전 9장을 읽어 보세요.', candidatePacket, codes, compareLocators), []);
});

test('a named verse outside the read ceiling is never displayed', () => {
  const answer = '사도행전 10:1을 보면 됩니다.';
  const beyondCeilingPacket = packet(['bible:web:ACT:10:1'], 'bible:web:ACT:9:5');
  assert.deepEqual(projectAnswerEvidence(answer, beyondCeilingPacket, codes, compareLocators), []);
});

test('evidence is hidden when the authoritative read ceiling is unavailable', () => {
  const withoutBoundary = packet(['bible:web:ACT:9:1'], null);
  assert.deepEqual(projectAnswerEvidence('사도행전 9:1을 보면 됩니다.', withoutBoundary, codes, compareLocators), []);
});

test('a locator is not invented when the answer names a verse absent from the packet', () => {
  const answer = '창세기 2:1-3을 참고하세요.';
  const actsOnly = packet(['bible:web:ACT:9:1', 'bible:web:ACT:9:2']);
  assert.deepEqual(projectAnswerEvidence(answer, actsOnly, codes, compareLocators), []);
});

test('shared abbreviations, overlap resolution and explicit locator form', () => {
  const citations = parseCitations('1 John 1:9와 창 1:1, bible:web:JHN:3:16', codes);
  assert.deepEqual(citations.map(c => [c.code, c.chapter, c.start]),
    [['1JN', 1, 9], ['GEN', 1, 1], ['JHN', 3, 16]]);
  const onlyLong = parseCitations('요일 1:9', codes);
  assert.equal(onlyLong.length, 1);
  assert.equal(onlyLong[0].code, '1JN');
  assert.deepEqual(parseCitations('고후 13:13', codes).map(c => c.code), ['2CO']);
  assert.equal(krvLabelOf('bible:web:2CO:13:14').verse, 13);
  assert.equal(krvLabelOf('bible:web:ROM:14:24').verse, 25);
});

test('KRV-numbered citations keep their evidence chip', () => {
  const packet2 = packet(['bible:web:2CO:13:14'], 'bible:web:2CO:13:14');
  assert.deepEqual(projectAnswerEvidence('고후 13:13의 축도', packet2, codes, compareLocators), ['bible:web:2CO:13:14']);
});

test('clicking the displayed verse routes to its book, chapter, and exact locator', () => {
  const controls = {};
  function makeElement(tagName) {
    return {
      tagName, children: [], dataset: {}, attributes: {},
      append(child) { this.children.push(child); },
      setAttribute(name, value) { this.attributes[name] = value; },
      querySelector(selector) { return controls[selector] || null; },
      insertBefore(child) { this.children.push(child); }
    };
  }
  const selectors = [];
  const document = {
    createElement: makeElement,
    querySelector(selector) { selectors.push(selector); return null; },
    querySelectorAll() { return []; },
    getElementById() { return null; }
  };
  const readerContext = {current_work_key: 'bible-web'};
  const navigation = {reader: null, screen: null, scope: null};
  const window = {
    storyMemoryAnswerEvidenceV1: require('../public/storymemory-answer-evidence-v1.js'),
    storyMemoryGetReaderContextV1: () => readerContext,
    storyMemoryGetKnowledgeCeilingV1: () => 'bible:web:ACT:9:5',
    storyMemoryCompareLocatorV1: compareLocators,
    __smDynamicReaderState: null
  };
  const context = {
    window, document, STORYMEMORY_BIBLE_USFM_CODES: codes,
    setReaderContext: value => { navigation.reader = value; },
    showScreen: value => { navigation.screen = value; },
    applyMemoryScope: value => { navigation.scope = value; },
    setTimeout: () => 0
  };
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  const script = html.match(/<script[^>]*id="sm-companion-evidence-ux-v1"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(script, 'B61 evidence presentation script is present');
  vm.runInNewContext(script[1], context);

  controls['.answer-contract'] = makeElement('div');
  controls['.source'] = makeElement('div');
  controls['.md-body'] = makeElement('div');
  controls['.save-ai-memory'] = makeElement('button');
  const node = makeElement('article');
  const mixedPacket = packet([
    'bible:web:ACT:9:1', 'bible:web:ACT:9:2', 'bible:web:ACT:9:3', 'bible:web:ACT:9:4', 'bible:web:ACT:9:5',
    'bible:web:GEN:2:1', 'bible:web:GEN:2:2', 'bible:web:GEN:2:3'
  ]);
  window.__smV1823EvidenceUXV1.decorateLive(
    node,
    {liveCompanion: true, question: '사울에게 일어난 일', answerEvidencePacket: mixedPacket},
    '사울에게 일어난 일은 사도행전 9장 1~5절에 나옵니다.'
  );
  const uncitedNode = makeElement('article');
  window.__smV1823EvidenceUXV1.decorateLive(
    uncitedNode,
    {liveCompanion: true, question: '사울에게 일어난 일', answerEvidencePacket: mixedPacket},
    '사울은 다메섹으로 가던 중 예수를 만났습니다.'
  );
  assert.equal(uncitedNode.children.some(child => child.className === 'sm-ev-strip'), false);
  const strip = node.children.find(child => child.className === 'sm-ev-strip');
  assert.ok(strip);
  const chips = strip.children.filter(child => child.className && child.className.indexOf('sm-ev-chip') >= 0);
  assert.equal(chips.length, 1);
  chips[0].onclick();
  assert.equal(navigation.reader.volume, '사도행전');
  assert.equal(navigation.reader.chapter, 9);
  assert.equal(navigation.screen, 'reader');
  assert.match(selectors[0], /ACT\\:9\\:1/);
});
