/* The browser adapter's streamed answer: the pending bubble becomes the answer
   bubble on the first fragment, and a cut still leaves retry guidance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const publicDir = path.join(__dirname, '../public');
const encoder = new TextEncoder();

function streamResponse(chunks) {
  let index = 0;
  return {
    ok: true,
    headers: {get: () => 'application/x-ndjson'},
    body: {
      getReader() {
        return {
          async read() {
            if (index >= chunks.length) return {done: true};
            return {done: false, value: encoder.encode(chunks[index++])};
          },
          releaseLock() {},
        };
      },
    },
  };
}

function jsonResponse(payload) {
  return {ok: true, headers: {get: () => 'application/json'}, json: async () => payload};
}

function setup(fetchImpl) {
  const results = [];
  const userMessages = [];
  const texts = [];
  const classes = [];
  const button = {disabled: false, setAttribute() {}, removeAttribute() {}};
  const thread = {append(el) { el.parentNode = this; }, removeChild(el) { el.parentNode = null; }, scrollHeight: 0, scrollTop: 0};
  const document = {
    getElementById(id) { return id === 'sendBtn' ? button : id === 'chatThread' ? thread : null; },
    createElement() {
      const el = {parentNode: null, setAttribute() {}, removeAttribute() {}};
      Object.defineProperty(el, 'className', {set(value) { classes.push(String(value)); }, get() { return classes[classes.length - 1] || ''; }});
      Object.defineProperty(el, 'textContent', {set(value) { texts.push(String(value)); }, get() { return texts[texts.length - 1] || ''; }});
      return el;
    },
    querySelector() { return null; },
  };
  const window = {
    storyMemoryBuildBoundedCompanionPacketV1: () => ({
      co_reader_decision: {decision: 'ALLOW', reason: 'WITHIN_CEILING'},
      diagnostics: {boundary_available: true},
      reader_context: {authoritative_reader: true, current_work_key: 'bible-web'},
    }),
  };
  const context = vm.createContext({
    window, document, AbortController, TextDecoder, setTimeout, clearTimeout,
    performance: {now: () => 0},
    appendUserMessage(...args) { userMessages.push(args); },
    appendAIMessage(...args) { results.push(args); },
    fetch: fetchImpl,
  });
  vm.runInContext(fs.readFileSync(path.join(publicDir, 'storymemory-companion-adapter-v1.js'), 'utf8'), context, {
    filename: 'storymemory-companion-adapter-v1.js',
  });
  return {window, results, userMessages, texts, classes, button};
}

test('the pending bubble becomes the answer bubble and grows in fragment order', async () => {
  const chunks = [
    '{"ok":true,"type":"delta","text":"반"}\n{"ok":true,"type":"del',
    'ta","text":"가"}\n{"ok":true,"type":"done","answer":"반가","context_permission":{"boundary_disposition":"permitted"},"runtime":"padiem-p01"}\n',
  ];
  const env = setup(async () => streamResponse(chunks));
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  await new Promise(resolve => setTimeout(resolve, 10));

  assert.equal(result.ok, true);
  assert.equal(result.answer, '반가');
  assert.equal(result.runtime, 'padiem-p01');
  assert.deepEqual(env.texts, ['답을 준비하고 있어요', '반', '반가']);
  assert.equal(env.classes[env.classes.length - 1], 'msg ai');
  assert.equal(env.results.length, 1);
  assert.equal(env.results[0][1], '반가');
  assert.equal(env.button.disabled, false);
});

test('a stream cut keeps only retry guidance, not the fragment', async () => {
  const chunks = [
    '{"ok":true,"type":"delta","text":"잘린"}\n',
    '{"ok":false,"type":"error","error":{"code":"answer_incomplete","retryable":true}}\n',
  ];
  const env = setup(async () => streamResponse(chunks));
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  await new Promise(resolve => setTimeout(resolve, 10));

  assert.equal(result.ok, false);
  assert.equal(result.error, 'answer_incomplete');
  assert.equal(result.retryable, true);
  assert.match(env.results[0][1], /다시 시도/);
  assert.notEqual(env.results[0][1], '잘린');
});

test('a JSON upstream response keeps the existing single-bubble path', async () => {
  const env = setup(async () => jsonResponse({ok: true, answer: '한 번에 온 답', context_permission: null}));
  const result = await env.window.storyMemorySubmitCompanionQuestionV1('question', {delay: 0});
  await new Promise(resolve => setTimeout(resolve, 10));

  assert.equal(result.ok, true);
  assert.equal(env.results.length, 1);
  assert.equal(env.results[0][1], '한 번에 온 답');
  assert.deepEqual(env.texts, ['답을 준비하고 있어요']);
});
