"use strict";
/* #7476 2번 범위 12: the alerts control is one switch whose aria-checked
 * follows the existing clawPushToggle state machine (no server needed). */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../static/claw-push.js"), "utf8");

function makeElement(id) {
  const attributes = new Map();
  const listeners = new Map();
  return {
    id,
    hidden: false,
    disabled: false,
    textContent: "",
    dataset: {},
    setAttribute(name, value) {
      attributes.set(name, String(value));
    },
    getAttribute(name) {
      return attributes.has(name) ? attributes.get(name) : null;
    },
    removeAttribute(name) {
      attributes.delete(name);
    },
    addEventListener(type, handler) {
      listeners.set(type, handler);
    },
    click() {
      const handler = listeners.get("click");
      return handler ? handler() : undefined;
    },
  };
}

function load() {
  const elements = {
    clawPushSetting: makeElement("clawPushSetting"),
    clawPushToggle: makeElement("clawPushToggle"),
    clawPushStatus: makeElement("clawPushStatus"),
  };
  const context = {
    console,
    window: {},
    document: {
      readyState: "loading",
      getElementById: (id) => elements[id] || null,
      addEventListener() {},
    },
    navigator: {},
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(SOURCE, context, { filename: "claw-push.js" });
  return { context, elements };
}

test("aria-checked follows on/off and aria-pressed is gone", () => {
  const { context, elements } = load();
  context.renderPushToggle("on");
  assert.equal(elements.clawPushToggle.getAttribute("aria-checked"), "true");
  assert.equal(elements.clawPushToggle.getAttribute("aria-pressed"), null);
  assert.equal(elements.clawPushToggle.disabled, false);

  context.renderPushToggle("off");
  assert.equal(elements.clawPushToggle.getAttribute("aria-checked"), "false");
});

test("the normal state is the switch alone; only exceptional states keep a line", () => {
  const { context, elements } = load();
  context.renderPushToggle("on");
  assert.equal(elements.clawPushStatus.textContent, "");
  assert.equal(elements.clawPushStatus.hidden, true);
  context.renderPushToggle("off");
  assert.equal(elements.clawPushStatus.textContent, "");
  assert.equal(elements.clawPushStatus.hidden, true);

  context.renderPushToggle("denied");
  assert.match(elements.clawPushStatus.textContent, /차단/);
  assert.equal(elements.clawPushStatus.hidden, false);
});

test("clicking the switch moves aria-checked in both directions", async () => {
  const { context, elements } = load();
  context.currentPushState = async () => "off";
  context.enablePush = async () => "on";
  vm.runInContext("wirePushToggle()", context);
  await elements.clawPushToggle.click();
  assert.equal(elements.clawPushToggle.getAttribute("aria-checked"), "true");

  context.currentPushState = async () => "on";
  context.disablePush = async () => "off";
  await elements.clawPushToggle.click();
  assert.equal(elements.clawPushToggle.getAttribute("aria-checked"), "false");
});
