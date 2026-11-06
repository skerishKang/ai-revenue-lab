const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const publicDir = path.join(__dirname, '../public');
function setup({catalog, packet, staticAdapter, actualPacket, createAdapter, fetchStatic, withoutAbort} = {}) {
  const timers = new Map();
  let nextTimer = 1;
  const results = [], requests = [], userMessages = [];
  const button = {disabled: false, setAttribute() {}, removeAttribute() {}};
  const thread = {
    append(el) { el.parentNode = this; },
    removeChild(el) { el.parentNode = null; },
    scrollHeight: 0, scrollTop: 0,
  };
  const document = {
    getElementById(id) { return id === 'sendBtn' ? button : id === 'chatThread' ? thread : null; },
    createElement() { return {setAttribute() {}, parentNode: null}; },
    querySelector() { return null; },
  };
  const window = {
    BookAISession: {isAuthenticated: () => false},
    storyMemoryGetReaderContextV1: () => ({current_work_key: 'bible-web'}),
    storyMemoryStatic: staticAdapter || {getCatalog: catalog || (() => Promise.resolve({works: []}))},
    storyMemoryBuildBoundedCompanionPacketV1: packet || (() => ({
      co_reader_decision: {decision: 'ALLOW'}, diagnostics: {boundary_available: true},
    })),
  };
  if (createAdapter) window.createStoryMemoryStaticAdapter = createAdapter;
  if (fetchStatic) window.fetch = fetchStatic;
  if (actualPacket) {
    window.storyMemoryGetReadingProgressV1 = () => ({knowledge_ceiling_locator: 'bible:web:GEN:1:1'});
    window.storyMemoryBuildAIContextPacketV1 = () => ({source_passages: []});
    window.storyMemoryCoReaderDecisionV1 = () => ({decision: 'ALLOW'});
  }
  const context = vm.createContext({
    window, document, AbortController: withoutAbort ? undefined : AbortController,
    sendChat: null, askPreset: null,
    setTimeout(fn, ms) { const id = nextTimer++; timers.set(id, {fn, ms}); return id; },
    clearTimeout(id) { timers.delete(id); },
    appendUserMessage(...args) { userMessages.push(args); },
    appendAIMessage(...args) { results.push(args); },
    async fetch(...args) {
      requests.push(args);
      return {ok: true, json: async () => ({ok: true, answer: 'answer'})};
    },
  });
  const files = ['storymemory-retrieval-adapter-v1.js'];
  if (actualPacket) files.push('storymemory-bounded-companion-packet-v1.js');
  files.push('storymemory-companion-adapter-v1.js');
  for (const file of files) {
    vm.runInContext(fs.readFileSync(path.join(publicDir, file), 'utf8'), context, {filename: file});
  }
  function fire(ms) {
    const found = [...timers.entries()].find(([, timer]) => timer.ms === ms);
    assert.ok(found, `expected ${ms}ms timer`);
    timers.delete(found[0]);
    found[1].fn();
  }
  return {window, context, button, results, requests, userMessages, timers, fire};
}

test('guest submit shows a retry bubble after an unresolved packet build within ten seconds', async () => {
  let finishPacket;
  const packet = new Promise(resolve => { finishPacket = resolve; });
  const env = setup({packet: () => packet});
  assert.equal(env.window.BookAISession.isAuthenticated(), false);
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  assert.equal(env.button.disabled, true);
  assert.equal(env.requests.length, 0);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok([...env.timers.values()].some(timer => timer.ms === 8000 && timer.ms < 10000));
  env.fire(8000);
  const result = await submitted;
  assert.equal(result.error, 'packet_timeout');
  assert.equal(result.retryable, true);
  assert.equal(env.button.disabled, false);
  env.fire(0);
  assert.equal(env.results.length, 1);
  assert.match(env.results[0][1], /다시 시도/);
  finishPacket({co_reader_decision: {decision: 'ALLOW'}, diagnostics: {boundary_available: true}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(env.requests.length, 0);
  assert.equal(env.results.length, 1);
});

test('guest submit still reaches the API when grounding finishes and the boundary allows it', async () => {
  const env = setup();
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(0);
  assert.equal(result.ok, true);
  assert.equal(env.requests.length, 1);
  assert.equal(env.requests[0][0], '/api/storymemory-ai');
  assert.equal(env.results[0][1], 'answer');
  assert.equal(env.button.disabled, false);
});

test('a guest packet without an allowed boundary remains locally blocked', async () => {
  const env = setup({packet: () => ({
    co_reader_decision: {decision: 'BLOCK', copy: 'blocked'},
    diagnostics: {boundary_available: false},
  })});
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(0);
  assert.equal(result.blocked, true);
  assert.equal(env.results[0][1], 'blocked');
  assert.equal(env.requests.length, 0);
});
test('guest grounding deadline sends an empty prior-evidence packet and releases a stuck load for retry', async () => {
  let finishFirst;
  let calls = 0;
  const stalled = new Promise(resolve => { finishFirst = resolve; });
  const env = setup({actualPacket: true, staticAdapter: {
    getCatalog: () => {
      calls += 1;
      return calls === 1 ? stalled : Promise.resolve({works: []});
    },
    getManifest: async () => ({units: [{unit_ordinal: 1}]}),
    loadUnit: async () => ({unit: {unit_ordinal: 1, passages: [{canonical_locator: 'bible:web:GEN:1:1', ko: 'late'}]}}),
  }});
  assert.equal(env.window.BookAISession.isAuthenticated(), false);
  const first = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  assert.ok([...env.timers.values()].some(timer => timer.ms === 6000));
  env.fire(6000);
  assert.equal((await first).ok, true);
  env.fire(0);
  const packet = JSON.parse(env.requests[0][1].body).packet;
  assert.deepEqual(packet.source_passages, []);
  assert.equal(packet.diagnostics.boundary_available, true);
  assert.equal(env.window.storyMemoryGroundingBlocksV1('bible-web'), null);
  const second = await env.window.storyMemorySubmitCompanionQuestionV1('question again', {delay: 0});
  env.fire(0);
  assert.equal(second.ok, true);
  assert.equal(calls, 2);
  assert.equal(env.requests.length, 2);
  finishFirst({works: [{work_key: 'bible-web'}]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(env.window.storyMemoryGroundingBlocksV1('bible-web'), null);
});

test('guest offline grounding failure continues with no fabricated prior evidence', async () => {
  const env = setup({actualPacket: true, catalog: () => Promise.reject(new Error('offline'))});
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(0);
  assert.equal(result.ok, true);
  assert.deepEqual(JSON.parse(env.requests[0][1].body).packet.source_passages, []);
  assert.equal(env.window.storyMemoryGroundingBlocksV1('bible-web'), null);
});

test('a stalled chapter load is bounded by the same grounding deadline', async () => {
  let unitCalled = false;
  const env = setup({actualPacket: true, staticAdapter: {
    getCatalog: async () => ({works: [{work_key: 'bible-web'}]}),
    getManifest: async () => ({units: [{unit_ordinal: 1}]}),
    loadUnit: () => { unitCalled = true; return new Promise(() => {}); },
  }});
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(unitCalled, true);
  env.fire(6000);
  assert.equal((await submitted).ok, true);
  env.fire(0);
  assert.deepEqual(JSON.parse(env.requests[0][1].body).packet.source_passages, []);
});

test('timeout aborts isolated static requests and does not use the reader-wide adapter', async () => {
  let signal;
  let sharedCalls = 0;
  const env = setup({
    actualPacket: true,
    staticAdapter: {getCatalog: () => { sharedCalls += 1; return new Promise(() => {}); }},
    createAdapter: ({fetchImpl}) => ({getCatalog: () => fetchImpl('/content/catalog.json', {})}),
    fetchStatic: (_url, options) => { signal = options.signal; return new Promise(() => {}); },
  });
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  assert.equal(sharedCalls, 0);
  assert.equal(signal.aborted, false);
  env.fire(6000);
  assert.equal((await submitted).ok, true);
  env.fire(0);
  assert.equal(signal.aborted, true);
  assert.equal(sharedCalls, 0);
});

test('grounding failure cannot bypass a missing reading boundary', async () => {
  const env = setup({actualPacket: true, catalog: () => Promise.reject(new Error('offline'))});
  env.window.storyMemoryGetReadingProgressV1 = () => null;
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(0);
  assert.equal(result.blocked, true);
  assert.equal(env.requests.length, 0);
});
test('a failed chapter discards partial grounding from the same load', async () => {
  const loaded = [];
  const env = setup({actualPacket: true, staticAdapter: {
    getCatalog: async () => ({works: [{work_key: 'bible-web'}]}),
    getManifest: async () => ({units: [{unit_ordinal: 1}, {unit_ordinal: 2}]}),
    loadUnit: async ({unitOrdinal}) => {
      loaded.push(unitOrdinal);
      if (unitOrdinal === 1) throw new Error('offline');
      return {unit: {unit_ordinal: 2, passages: [{canonical_locator: 'bible:web:GEN:2:1', ko: 'partial'}]}};
    },
  }});
  env.window.storyMemoryGetReaderContextV1 = () => ({current_work_key: 'bible-web', current_unit_ordinal: 2});
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(0);
  assert.equal(result.ok, true);
  assert.deepEqual(loaded, [2, 1]);
  assert.deepEqual(JSON.parse(env.requests[0][1].body).packet.source_passages, []);
  assert.equal(env.window.storyMemoryGroundingBlocksV1('bible-web'), null);
});

test('the grounding deadline also applies to an authenticated session', async () => {
  const env = setup({actualPacket: true, catalog: () => new Promise(() => {})});
  env.window.BookAISession.isAuthenticated = () => true;
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(6000);
  assert.equal((await submitted).ok, true);
  env.fire(0);
  assert.deepEqual(JSON.parse(env.requests[0][1].body).packet.source_passages, []);
});
test('an unavailable abort API still isolates a timed-out load from later attempts', async () => {
  let fetches = 0;
  let sharedCalls = 0;
  const env = setup({
    actualPacket: true, withoutAbort: true,
    staticAdapter: {getCatalog: () => { sharedCalls += 1; return new Promise(() => {}); }},
    createAdapter: ({fetchImpl}) => ({getCatalog: () => fetchImpl('/content/catalog.json', {})}),
    fetchStatic: () => {
      fetches += 1;
      return fetches === 1 ? new Promise(() => {}) : Promise.resolve({works: []});
    },
  });
  const first = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(6000);
  assert.equal((await first).ok, true);
  env.fire(0);
  assert.equal((await env.window.storyMemorySubmitCompanionQuestionV1('retry', {delay: 0})).ok, true);
  env.fire(0);
  assert.equal(fetches, 2);
  assert.equal(sharedCalls, 0);
});
test('a stalled manifest is bounded before the outer packet deadline', async () => {
  const env = setup({actualPacket: true, staticAdapter: {
    getCatalog: async () => ({works: [{work_key: 'bible-web'}]}),
    getManifest: () => new Promise(() => {}),
  }});
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  await new Promise(resolve => setImmediate(resolve));
  env.fire(6000);
  assert.equal((await submitted).ok, true);
  env.fire(0);
  assert.deepEqual(JSON.parse(env.requests[0][1].body).packet.source_passages, []);
});

test('a slow grounding load that finishes before the deadline retains its evidence', async () => {
  let finishCatalog;
  const catalog = new Promise(resolve => { finishCatalog = resolve; });
  const env = setup({actualPacket: true, staticAdapter: {
    getCatalog: () => catalog,
    getManifest: async () => ({units: [{unit_ordinal: 1}]}),
    loadUnit: async () => ({unit: {unit_ordinal: 1, passages: [{canonical_locator: 'bible:web:GEN:1:1', ko: 'available'}]}}),
  }});
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  finishCatalog({works: [{work_key: 'bible-web'}]});
  assert.equal((await submitted).ok, true);
  env.fire(0);
  assert.equal(env.window.storyMemoryGroundingBlocksV1('bible-web')[0].text, 'available');
  assert.equal([...env.timers.values()].some(timer => timer.ms === 6000), false);
});
test('the shipped static adapter isolates a stalled fetch and can retry after the deadline', async () => {
  let fetches = 0;
  let firstSignal;
  let sharedCalls = 0;
  const env = setup({
    actualPacket: true,
    staticAdapter: {getCatalog: () => { sharedCalls += 1; return new Promise(() => {}); }},
    fetchStatic: (_url, options) => {
      fetches += 1;
      if (fetches === 1) {
        firstSignal = options.signal;
        return new Promise(() => {});
      }
      return Promise.resolve({ok: true, json: async () => ({
        schema_version: 'storymemory-static-content-1.0', works: [],
      })});
    },
  });
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  const start = html.indexOf('function createStoryMemoryStaticAdapter(');
  const end = html.indexOf('\nconst storyMemoryStatic=createStoryMemoryStaticAdapter();', start);
  assert.ok(start >= 0 && end > start);
  env.context.STORYMEMORY_STATIC_CONTENT_CONFIG = {
    basePath: 'content', catalogPath: 'content/catalog.json', schemaVersion: 'storymemory-static-content-1.0',
  };
  vm.runInContext(html.slice(start, end) + '\nwindow.createStoryMemoryStaticAdapter=createStoryMemoryStaticAdapter;', env.context);
  const first = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  env.fire(6000);
  assert.equal((await first).ok, true);
  env.fire(0);
  assert.equal(firstSignal.aborted, true);
  assert.equal((await env.window.storyMemorySubmitCompanionQuestionV1('retry', {delay: 0})).ok, true);
  env.fire(0);
  assert.equal(fetches, 2);
  assert.equal(sharedCalls, 0);
});