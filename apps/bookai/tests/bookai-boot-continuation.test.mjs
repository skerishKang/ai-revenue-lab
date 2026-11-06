import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const publicRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
const bootstrapSource = fs.readFileSync(path.join(publicRoot, 'bookai-bootstrap.js'), 'utf8');
const html = fs.readFileSync(path.join(publicRoot, 'index.html'), 'utf8');

const flushMicrotasks = async (times = 5) => {
  for (let index = 0; index < times; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};

function createClock() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  return {
    setTimeout(fn, ms = 0) {
      const id = nextId++;
      timers.set(id, { at: now + Number(ms), fn });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    async advance(ms) {
      now += ms;
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.at <= now)
          .sort((left, right) => left[1].at - right[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        due[1].fn();
        await flushMicrotasks();
      }
    },
  };
}

function createBootHarness() {
  const clock = createClock();
  const started = [];
  const pendingExternal = [];
  const executedInline = [];
  const readyEvents = [];
  const consoleErrors = [];
  let initCalls = 0;
  let flushCalls = 0;

  class FakeElement {
    constructor(tagName) {
      this.tagName = tagName.toUpperCase();
      this.attributes = [];
      this.children = [];
      this.parent = null;
      this.style = {};
      this.id = '';
      this.src = '';
      this.textContent = '';
      this.async = true;
      this.onload = null;
      this.onerror = null;
      this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
    }
    setAttribute(name, value) {
      const existing = this.attributes.find((attribute) => attribute.name === name);
      if (existing) existing.value = String(value);
      else this.attributes.push({ name, value: String(value) });
      if (name === 'id') this.id = String(value);
      if (name === 'src') this.src = String(value);
    }
    getAttribute(name) {
      return this.attributes.find((attribute) => attribute.name === name)?.value ?? null;
    }
    hasAttribute(name) {
      return this.attributes.some((attribute) => attribute.name === name);
    }
    removeAttribute(name) {
      this.attributes = this.attributes.filter((attribute) => attribute.name !== name);
      if (name === 'src') this.src = '';
    }
    append(child) {
      this.children.push(child);
      child.parent = this;
    }
    remove() {
      if (!this.parent) return;
      this.parent.children = this.parent.children.filter((child) => child !== this);
      this.parent = null;
    }
    replaceWith(next) {
      if (this.parent) {
        this.parent.children[this.parent.children.indexOf(this)] = next;
        next.parent = this.parent;
        this.parent = null;
      }
      if (next.src) {
        started.push(next.getAttribute('src'));
        pendingExternal.push(next);
      } else {
        executedInline.push(next.textContent);
      }
    }
  }

  const body = new FakeElement('body');
  const scripts = [];
  const addScript = ({ src, text }) => {
    const script = new FakeElement('script');
    script.setAttribute('type', 'application/x-bookai');
    script.setAttribute('data-bookai-script', '');
    if (src) script.setAttribute('src', src);
    if (text) script.textContent = text;
    body.append(script);
    scripts.push(script);
    return script;
  };

  const connected = [];
  const collect = (element) => {
    connected.push(element);
    for (const child of element.children) collect(child);
  };
  const document = {
    body,
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    getElementById(id) {
      connected.length = 0;
      collect(body);
      return connected.find((element) => element.id === id) ?? null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, 'script[data-bookai-script]');
      return scripts;
    },
  };

  const context = {
    console: {
      error(...args) {
        consoleErrors.push(args.map(String).join(' '));
      },
      log() {},
    },
    document,
    Event: class FakeEvent {
      constructor(type) {
        this.type = type;
      }
    },
    BookAILocalDB: {
      async init() {
        initCalls += 1;
      },
      async flush() {
        flushCalls += 1;
      },
    },
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    addEventListener() {},
    dispatchEvent(event) {
      readyEvents.push(event.type);
      return true;
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(bootstrapSource, context, { filename: 'bookai-bootstrap.js' });

  return {
    addScript,
    clock,
    document,
    context,
    started,
    pendingExternal,
    executedInline,
    readyEvents,
    consoleErrors,
    flushCalls: () => flushCalls,
    initCalls: () => initCalls,
    async resolveExternal(src) {
      const index = pendingExternal.findIndex((script) => script.getAttribute('src') === src);
      assert.ok(index >= 0, `${src} should be waiting to load`);
      const [script] = pendingExternal.splice(index, 1);
      script.onload();
      await flushMicrotasks();
    },
  };
}

test('#6476 remaining boot scripts keep loading after the 15s deadline', async () => {
  const harness = createBootHarness();
  harness.addScript({ src: 'slow-first.js' });
  harness.addScript({ src: 'second.js' });
  harness.addScript({ text: 'window.__inlineBootScript=true;' });

  await flushMicrotasks();
  assert.equal(harness.initCalls(), 1);
  assert.deepEqual(harness.started, ['slow-first.js']);
  assert.ok(harness.document.getElementById('bookai-startup'), 'gate must stay until the deadline');

  await harness.clock.advance(15000);
  assert.equal(harness.document.getElementById('bookai-startup'), null, 'timeout must remove only the gate');
  assert.equal(harness.document.body.getAttribute('aria-busy'), null);
  assert.equal(harness.document.getElementById('bookai-boot-toast')?.textContent, '일부 기능을 불러오지 못했어요');
  assert.deepEqual(harness.started, ['slow-first.js'], 'a slow script must not stop the queue by itself');
  assert.equal(harness.flushCalls(), 0);

  await harness.resolveExternal('slow-first.js');
  assert.deepEqual(harness.started, ['slow-first.js', 'second.js'], 'the next script must load after the timeout');
  await harness.resolveExternal('second.js');
  assert.deepEqual(harness.executedInline, ['window.__inlineBootScript=true;']);

  const result = await harness.context.window.BookAIReady;
  assert.equal(result, true);
  assert.equal(harness.flushCalls(), 1, 'the storage flush must still run after a timeout');
  assert.deepEqual(harness.readyEvents, ['bookai-ready']);
  assert.deepEqual(harness.consoleErrors, []);
});

test('#6476 login UI loads right after the auth bridge definition and before later scripts', () => {
  const bridgeDefinition = html.indexOf('function installStoryMemoryAuthBridge(');
  assert.ok(bridgeDefinition > 0, 'the auth bridge definition must exist');
  const blockStart = html.lastIndexOf('<script', bridgeDefinition);
  const blockEnd = html.indexOf('</script>', bridgeDefinition);
  assert.ok(blockStart >= 0 && blockEnd > bridgeDefinition, 'the bridge definition must sit in a script block');

  const loginCopy = html.match(/bookai-login-ui\.js/g) ?? [];
  assert.equal(loginCopy.length, 1, 'the login UI script tag must appear exactly once');
  const loginIndex = html.indexOf('bookai-login-ui.js');
  assert.ok(loginIndex > blockEnd, 'the login UI tag must follow the bridge definition block');

  const tagStart = html.lastIndexOf('<script', loginIndex);
  assert.ok(tagStart > blockEnd, 'the login UI script tag must start after the bridge block');
  const between = html.slice(blockEnd, tagStart);
  assert.doesNotMatch(between, /<script\b[^>]*data-bookai-script[^>]*\bsrc=/, 'no external boot script may run before the login UI');

  const tagEnd = html.indexOf('>', loginIndex);
  const tag = html.slice(tagStart, tagEnd + 1);
  assert.match(tag, /application\/x-bookai/);
  assert.match(tag, /\bdata-bookai-script\b/);
  assert.match(tag, /src="\.\/bookai-login-ui\.js"/);

  const laterExternal = html.indexOf('data-bookai-script src=', loginIndex);
  const laterInline = html.indexOf('data-bookai-script>', loginIndex);
  assert.ok(laterExternal > loginIndex || laterInline > loginIndex, 'later boot scripts must still exist');
});
