const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const publicDir = path.join(__dirname, '../public');
function setup({catalog, packet} = {}) {
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
    storyMemoryStatic: {getCatalog: catalog || (() => Promise.resolve({works: []}))},
    storyMemoryBuildBoundedCompanionPacketV1: packet || (() => ({
      co_reader_decision: {decision: 'ALLOW'}, diagnostics: {boundary_available: true},
    })),
  };
  const context = vm.createContext({
    window, document, AbortController,
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
  for (const file of ['storymemory-retrieval-adapter-v1.js', 'storymemory-companion-adapter-v1.js']) {
    vm.runInContext(fs.readFileSync(path.join(publicDir, file), 'utf8'), context, {filename: file});
  }
  function fire(ms) {
    const found = [...timers.entries()].find(([, timer]) => timer.ms === ms);
    assert.ok(found, `expected ${ms}ms timer`);
    timers.delete(found[0]);
    found[1].fn();
  }
  return {window, button, results, requests, userMessages, timers, fire};
}

test('guest submit shows a retry bubble after an unresolved grounding fetch within ten seconds', async () => {
  let finishCatalog;
  const catalog = new Promise(resolve => { finishCatalog = resolve; });
  const env = setup({catalog: () => catalog});
  assert.equal(env.window.BookAISession.isAuthenticated(), false);
  const submitted = env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  assert.equal(env.button.disabled, true);
  assert.equal(env.requests.length, 0);
  assert.ok([...env.timers.values()].some(timer => timer.ms === 8000 && timer.ms < 10000));
  env.fire(8000);
  const result = await submitted;
  assert.equal(result.error, 'packet_timeout');
  assert.equal(result.retryable, true);
  assert.equal(env.button.disabled, false);
  env.fire(0);
  assert.equal(env.results.length, 1);
  assert.match(env.results[0][1], /다시 시도/);
  finishCatalog({works: []});
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