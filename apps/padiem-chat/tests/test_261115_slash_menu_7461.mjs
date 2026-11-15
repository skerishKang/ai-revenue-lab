import test from "node:test";
import assert from "node:assert/strict";

// #7461 · 261115: the composer slash-command interception keeps three
// promises, pinned here against the real modules (manifest + util-slash.js):
// 1. A Korean/CJK IME composition in flight (isComposing, or keyCode 229
//    engines) is never intercepted — Enter and both arrows pass through, and
//    the settled post-composition keydown is what gets judged.
// 2. Claw never sees the feature: no menu, no interception, no navigation.
// 3. Any unmatched "/..." text and a plain Enter stay untouched, so the
//    existing app.js submit flow keeps its exact behavior.

function makeEl(tag) {
  const classes = new Set();
  const el = {
    tagName: tag,
    children: [],
    attributes: {},
    listeners: {},
    dataset: {},
    hidden: false,
    isConnected: false,
    title: "",
    tabIndex: 0,
    get className() { return [...classes].join(" "); },
    set className(v) {
      classes.clear();
      String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
    classList: {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : Boolean(force);
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
    },
    setAttribute(n, v) { el.attributes[n] = String(v); },
    getAttribute(n) { return n in el.attributes ? el.attributes[n] : null; },
    removeAttribute(n) { delete el.attributes[n]; },
    addEventListener(type, fn) { (el.listeners[type] ||= []).push(fn); },
    appendChild(c) { el.children.push(c); c.isConnected = true; c.parentElement = el; return c; },
    insertBefore(c, ref) {
      const i = ref ? el.children.indexOf(ref) : -1;
      if (i < 0) el.children.push(c); else el.children.splice(i, 0, c);
      c.isConnected = true;
      c.parentElement = el;
      return c;
    },
    replaceChildren(...next) {
      el.children.length = 0;
      next.forEach((c) => el.appendChild(c));
    },
    closest() { return null; },
    scrollIntoView() {},
  };
  return el;
}

const shell = makeEl("div");
shell.dataset.state = "home";
shell.isConnected = true;
const form = makeEl("form");
form.isConnected = true;
const input = makeEl("textarea");
input.isConnected = true;
const docListeners = {};
const observers = [];

globalThis.document = {
  readyState: "complete",
  documentElement: { lang: "ko" },
  querySelector(sel) { return sel === ".app-shell" ? shell : null; },
  getElementById(id) {
    if (id === "composerForm") return form;
    if (id === "messageInput") return input;
    return null;
  },
  createElement: (tag) => makeEl(tag),
  addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
};
globalThis.Element = class Element {};
globalThis.MutationObserver = class {
  constructor(callback) { this.callback = callback; }
  observe(target, options) { observers.push({ callback: this.callback, target, options }); }
};
globalThis.location = { hash: "" };
globalThis.addEventListener = () => {}; // window-level listeners (locale change) are not under test
globalThis.window = globalThis;

await import(new URL("../static/util-manifest.js", import.meta.url));
await import(new URL("../static/util-slash.js", import.meta.url));

const manifest = globalThis.PadiemUtilManifest;
const slash = globalThis.PadiemUtilSlash;

function keydown(overrides = {}) {
  const event = {
    key: "Enter",
    keyCode: 0,
    isComposing: false,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    target: input,
    defaultPrevented: false,
    stopped: false,
    preventDefault() { event.defaultPrevented = true; },
    stopPropagation() { event.stopped = true; },
    ...overrides,
  };
  for (const fn of docListeners.keydown ?? []) fn(event);
  return event;
}

function type(value) {
  input.value = value;
  for (const fn of input.listeners.input ?? []) fn({ target: input });
}

function menu() { return form.children[0]; }

function activeRow() {
  return menu().children.findIndex((row) => row.attributes["aria-selected"] === "true");
}

function reset(state = "home") {
  slash.close();
  shell.dataset.state = state;
  input.value = "";
  globalThis.location.hash = "";
}

test("a Korean IME composition in flight is never intercepted", () => {
  reset();
  const composing = [
    { isComposing: true, keyCode: 0 },
    { isComposing: true, keyCode: 229 },
    { isComposing: false, keyCode: 229 }, // engines that only emit 229
  ];
  for (const value of ["/견", "/견적서"]) {
    type(value);
    assert.equal(menu().hidden, false, value);
    const before = activeRow();
    for (const key of ["Enter", "ArrowDown", "ArrowUp"]) {
      for (const state of composing) {
        const event = keydown({ key, ...state });
        assert.equal(event.defaultPrevented, false, `${key} ${JSON.stringify(state)}`);
        assert.equal(event.stopped, false, `${key} ${JSON.stringify(state)}`);
        assert.equal(globalThis.location.hash, "", `${key} while composing must not navigate`);
      }
    }
    assert.equal(activeRow(), before, `arrows did not move the selection while composing (${value})`);
  }
});

test("the settled post-composition Enter opens the exact command", () => {
  reset();
  type("/견적서");
  const event = keydown({ key: "Enter", isComposing: false, keyCode: 0 });
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, true);
  assert.equal(
    globalThis.location.hash,
    manifest.toolHref("quote") + "?mode=chat",
    "the tool's chat-mode deep link",
  );
  assert.equal(input.value, "", "the composer is cleared for the handoff");
});

test("Claw never sees the menu or the interception", () => {
  reset("claw");
  assert.equal(observers.length, 1, "the shell state switch is watched");
  assert.equal(observers[0].target, shell);
  assert.deepEqual(observers[0].options.attributeFilter, ["data-state"]);

  type("/견");
  assert.equal(menu().hidden, true, "no suggestion menu on Claw");
  let event = keydown({ key: "Enter" });
  assert.equal(event.defaultPrevented, false, "Claw Enter is not intercepted");
  assert.equal(event.stopped, false);
  assert.equal(globalThis.location.hash, "", "Claw Enter does not navigate");

  // Back on Chat the menu works again, and the Claw switch closes it for good.
  shell.dataset.state = "home";
  type("/견");
  assert.equal(menu().hidden, false);
  shell.dataset.state = "claw";
  observers[0].callback();
  assert.equal(menu().hidden, true, "the menu does not survive the Chat → Claw switch");
  event = keydown({ key: "ArrowDown" });
  assert.equal(event.defaultPrevented, false, "Claw arrows are not intercepted");
});

test("an unmatched \"/...\" and a plain Enter keep the app.js flow untouched", () => {
  reset();
  for (const value of ["/없는명령", "앞/뒤", "/두 단어", ""]) {
    type(value);
    if (value.startsWith("/") && !value.includes(" ")) {
      assert.equal(menu().hidden, true, `no suggestions for ${JSON.stringify(value)}`);
    }
    const event = keydown({ key: "Enter" });
    assert.equal(event.defaultPrevented, false, JSON.stringify(value));
    assert.equal(event.stopped, false, JSON.stringify(value));
    assert.equal(globalThis.location.hash, "", JSON.stringify(value));
    assert.equal(input.value, value, "the composer text is left for app.js");
  }
});

test("the open list proposes the manifest commands and is keyboard-driven", () => {
  reset();
  const withSlash = manifest.TOOLS.filter(
    (tool) => typeof tool.slashCommand === "string" && tool.slashCommand.startsWith("/"),
  );
  assert.ok(withSlash.length >= 6, "the manifest carries the slash commands");

  type("/");
  assert.equal(menu().hidden, false);
  assert.equal(menu().children.length, withSlash.length, "one row per manifest command");
  assert.equal(menu().attributes.role, "listbox");
  assert.equal(input.attributes["aria-controls"], menu().id);
  assert.equal(input.attributes["aria-expanded"], "true");
  assert.equal(activeRow(), 0, "the first row is highlighted");

  const down = keydown({ key: "ArrowDown" });
  assert.equal(down.defaultPrevented, true, "arrows steer the open list");
  assert.equal(activeRow(), 1);

  const escape = keydown({ key: "Escape" });
  assert.equal(escape.defaultPrevented, false);
  assert.equal(menu().hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");

  type("/회");
  assert.equal(menu().children.length, 1, "the list filters as the query grows");
  const meeting = manifest.TOOLS.find((tool) => tool.slashCommand === "/회의정리");
  const pick = keydown({ key: "Enter" });
  assert.equal(pick.defaultPrevented, true, "Enter picks the highlighted row");
  assert.equal(globalThis.location.hash, manifest.toolHref(meeting.id) + "?mode=chat");
});
