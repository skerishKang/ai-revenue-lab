// Deterministic DOM boundary for the actual shipped header script (#5805).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(process.argv[2], "utf8");
const mode = process.argv[3];

function harness(documentTop = 0) {
  const surfaces = {
    ".conversation": { offsetParent: {}, scrollTop: 0 },
    ".claw-workspace": { offsetParent: {}, scrollTop: 0 },
    ".claw-inbox": { offsetParent: {}, scrollTop: 0 },
    ".code-block": { offsetParent: {}, scrollTop: 0 },
    ".chip-row": { offsetParent: {}, scrollTop: 0 },
  };
  let collapsed;
  let listener;
  let frames = [];
  let writes = 0;
  const shell = {
    querySelectorAll(selectors) {
      return selectors.split(",").map(s => surfaces[s.trim()]).filter(Boolean);
    },
    toggleAttribute(name, value) {
      assert.equal(name, "data-header-collapsed");
      assert.equal(typeof value, "boolean");
      collapsed = value;
      writes++;
    },
  };
  const document = {
    scrollingElement: { scrollTop: documentTop },
    querySelector(selector) { return selector === ".app-shell" ? shell : null; },
    addEventListener(name, fn, options) {
      assert.equal(name, "scroll");
      assert.equal(options.capture, true);
      assert.equal(options.passive, true);
      assert.equal(listener, undefined);
      listener = fn;
    },
  };
  const forbidden = () => { throw Error("comparison URL must not be consulted"); };
  const window = {
    requestAnimationFrame(fn) { frames.push(fn); },
    get location() { return forbidden(); },
    get URLSearchParams() { return forbidden(); },
  };
  const context = { document, window };
  Object.defineProperties(context, {
    location: { get: forbidden },
    URLSearchParams: { get: forbidden },
  });
  vm.runInNewContext(source, context);
  assert.equal(typeof listener, "function");
  function fire() { listener(); }
  function flush() {
    const queued = frames;
    frames = [];
    queued.forEach(fn => fn());
  }
  function sync(expected) {
    fire();
    flush();
    assert.equal(collapsed, expected);
  }
  return { surfaces, document, fire, flush, sync,
    get collapsed() { return collapsed; },
    get writes() { return writes; },
    get frames() { return frames.length; },
  };
}

if (mode === "comparison") {
  // No URL, query parser or floating-mode branch is required for either state.
  assert.equal(harness(0).collapsed, false);
  assert.equal(harness(25).collapsed, true);
} else if (mode === "scroll") {
  const h = harness();
  assert.equal(h.collapsed, false);
  for (const name of [".conversation", ".claw-workspace", ".claw-inbox"]) {
    const surface = h.surfaces[name];
    surface.scrollTop = 24;
    h.sync(false);
    surface.scrollTop = 25;
    h.sync(true);
    surface.offsetParent = null; // stale scroll position in a hidden view
    h.sync(false);
    surface.scrollTop = 0;
    surface.offsetParent = {};
    h.sync(false);
  }
  for (const name of [".code-block", ".chip-row"]) {
    h.surfaces[name].scrollTop = 100;
    h.sync(false);
  }
  h.document.scrollingElement.scrollTop = 25;
  const writes = h.writes;
  h.fire();
  h.fire();
  assert.equal(h.frames, 1, "scroll bursts must coalesce into one frame");
  assert.equal(h.writes, writes, "no synchronous DOM writes on scroll");
  h.flush();
  assert.equal(h.collapsed, true);
  assert.equal(h.writes, writes + 1);
  h.document.scrollingElement.scrollTop = 0;
  h.sync(false);
} else {
  throw Error("unknown case");
}
