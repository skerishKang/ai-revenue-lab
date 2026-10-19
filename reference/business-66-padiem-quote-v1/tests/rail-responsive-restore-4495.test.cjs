"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Exercise the real production resize function without booting the full quote
// page or reading customer records. This is not a substitute for Tabbit E2E.
const source = fs.readFileSync(path.join(__dirname, "..", "shell-layout.js"), "utf8");
const start = source.indexOf("  function syncMobileDefault() {");
const end = source.indexOf("\n  function wireOverlayKeyboard()", start);
assert.ok(start >= 0 && end > start, "canonical B66 responsive handler present");
const resizeFunction = source.slice(start, end);

function harness(initialWidth = 1920) {
  let width = initialWidth;
  const classes = new Set();
  const classList = {
    contains: (name) => classes.has(name),
    add: (name) => classes.add(name),
    remove: (name) => classes.delete(name),
  };
  const context = vm.createContext({
    document: { body: { classList } },
    window: {
      matchMedia: (query) => {
        const match = /max-width:\s*(\d+)px/.exec(query);
        assert.ok(match, "expected maximum-width query");
        return { matches: width <= Number(match[1]) };
      },
    },
  });
  vm.runInContext(
    "var MOBILE_BREAKPOINT=900, COMPACT_PREVIEW_BREAKPOINT=1480;" +
      "var previewAutoCollapsed=false, railAutoCollapsed=false;" +
      "var wasCompact=null, wasMobile=null;\n" + resizeFunction,
    context,
  );
  function resize(next) {
    width = next;
    vm.runInContext("syncMobileDefault()", context);
  }
  return {
    resize,
    hidden: () => classes.has("rail-collapsed"),
    previewHidden: () => classes.has("preview-collapsed"),
    manuallyClose: () => {
      vm.runInContext("railAutoCollapsed=false", context);
      classes.add("rail-collapsed");
    },
    manuallyOpen: () => {
      vm.runInContext("railAutoCollapsed=false", context);
      classes.delete("rail-collapsed");
    },
  };
}

test("4495: desktop -> DevTools narrow -> desktop restores only auto-hidden rail", () => {
  const ui = harness();
  ui.resize(1920);
  assert.equal(ui.hidden(), false);
  ui.resize(900);
  assert.equal(ui.hidden(), true);
  ui.resize(901);
  assert.equal(ui.hidden(), false);
  for (let n = 0; n < 3; n++) {
    ui.resize(900);
    assert.equal(ui.hidden(), true);
    ui.resize(901);
    assert.equal(ui.hidden(), false);
  }
  ui.resize(390);
  assert.equal(ui.hidden(), true);
  ui.resize(1024);
  assert.equal(ui.hidden(), false);
  ui.resize(1920);
  assert.equal(ui.hidden(), false);
});

test("4495: explicit desktop collapse survives responsive transitions", () => {
  const ui = harness();
  ui.resize(1920);
  ui.manuallyClose();
  ui.resize(900);
  ui.resize(390);
  ui.resize(901);
  ui.resize(1920);
  assert.equal(ui.hidden(), true);
});

test("4495: explicit mobile drawer control is never mistaken for auto-close", () => {
  const ui = harness(390);
  ui.resize(390);
  assert.equal(ui.hidden(), true);
  ui.manuallyOpen();
  assert.equal(ui.hidden(), false);
  ui.manuallyClose();
  ui.resize(1024);
  assert.equal(ui.hidden(), true);
});

test("4495: right preview retains its separate automatic/manual compact rule", () => {
  const ui = harness();
  ui.resize(1920);
  assert.equal(ui.previewHidden(), false);
  ui.resize(1024);
  assert.equal(ui.previewHidden(), true);
  assert.equal(ui.hidden(), false); // Rail is only automatic at <=900px.
  ui.resize(390);
  assert.equal(ui.hidden(), true);
  ui.resize(1920);
  assert.equal(ui.hidden(), false);
  assert.equal(ui.previewHidden(), false);
});

test("4495: real rail collapse/toggle event handlers cancel auto state", () => {
  assert.match(source, /railCollapse\.addEventListener\("click", function \(\) \{\s*railAutoCollapsed = false;/);
  assert.match(source, /toggle\.addEventListener\("click", function \(\) \{\s*railAutoCollapsed = false;/);
  assert.match(source, /new MutationObserver\(syncSemantics\)/);
  assert.match(source, /event\.key === "Escape"/);
});
