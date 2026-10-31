/* #3186 — 새 견적서 양식 시작 dialog: 지금 되는 두 경로만 연다.

   The file path has no source extraction behind it (#3293 not done), so the
   card must be disabled with an explanation and must NOT open the wizard. The
   other two paths must still hand off. The promise-shaped "곧 지원" wording is
   refused here so it cannot come back silently.

   Pure Node: a tiny DOM stub, no browser, no network. */
"use strict";

const assert = require("assert");
const path = require("path");

function makeNode(tag) {
  const node = {
    tagName: String(tag || "").toUpperCase(),
    nodeType: 1,
    id: "",
    className: "",
    textContent: "",
    hidden: false,
    disabled: false,
    type: "",
    open: false,
    parentNode: null,
    children: [],
    attrs: {},
    handlers: {},
    onclick: null,
    append(...kids) {
      for (const kid of kids) node.appendChild(kid);
    },
    appendChild(kid) {
      node.children.push(kid);
      if (kid && typeof kid === "object") kid.parentNode = node;
      return kid;
    },
    insertBefore(kid, before) {
      const at = node.children.indexOf(before);
      node.children.splice(at < 0 ? node.children.length : at, 0, kid);
      if (kid && typeof kid === "object") kid.parentNode = node;
      return kid;
    },
    setAttribute(name, value) {
      node.attrs[name] = String(value);
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(node.attrs, name)
        ? node.attrs[name] : null;
    },
    addEventListener(type, fn) {
      (node.handlers[type] = node.handlers[type] || []).push(fn);
    },
    showModal() {
      node.open = true;
    },
    close() {
      node.open = false;
      for (const fn of node.handlers.close || []) fn();
    },
    focus() {
      globalThis.__focused = node;
    },
    querySelector(selector) {
      const wanted = selector.replace(/^\./, "");
      const stack = [...node.children];
      while (stack.length) {
        const current = stack.shift();
        if (!current || typeof current !== "object") continue;
        if (wanted && String(current.className || "").split(/\s+/).includes(wanted)) {
          return current;
        }
        stack.push(...(current.children || []));
      }
      return null;
    },
    find(predicate) {
      const stack = [...node.children];
      while (stack.length) {
        const current = stack.shift();
        if (!current || typeof current !== "object") continue;
        if (predicate(current)) return current;
        stack.push(...(current.children || []));
      }
      return null;
    },
  };
  return node;
}

function install() {
  const body = makeNode("body");
  const document = {
    body,
    createElement: (tag) => makeNode(tag),
    createComment: () => ({ nodeType: 8, text: "comment" }),
    getElementById(id) {
      return body.find((node) => node.id === id) || null;
    },
  };
  globalThis.document = document;
  globalThis.window = globalThis;
  globalThis.MutationObserver = class {
    observe() {}
    disconnect() {}
  };
  return document;
}

function load() {
  const file = path.join(__dirname, "..", "quote-skill-start-dialog.js");
  delete require.cache[require.resolve(file)];
  require(file);
  return require(path.join("..", "quote-skill-start-dialog.js")).B66SkillStartDialog
    || globalThis.B66SkillStartDialog;
}

function click(card) {
  assert.ok(typeof card.onclick === "function", "expected a click handler");
  card.onclick();
}

// ── file path is disabled with a truthful explanation and does not open
{
  install();
  const dialogApi = load();
  let fileOpened = false;
  dialogApi.open({
    fileOpen: () => { fileOpened = true; },
    blankOpen: () => {},
    blankCancel: () => {},
    assistOpen: () => {},
  }, makeNode("button"));

  const fileCard = document.getElementById("b66SkillStartFromFile");
  assert.ok(fileCard, "file card must stay visible");
  assert.strictEqual(fileCard.disabled, true);
  assert.strictEqual(fileCard.getAttribute("aria-disabled"), "true");
  assert.strictEqual(fileCard.onclick, null);

  const text = fileCard.children.map((child) => child.textContent).join(" ");
  assert.ok(text.includes("사용할 수 없음"), "the card must say it cannot be used yet");
  assert.ok(!text.includes("곧"), "no promise-shaped wording");
  assert.ok(text.includes("직접 만들기") && text.includes("운영자에게 맡기기"),
    "the explanation must point at the paths that do work");

  // Clicking the disabled card cannot reach the file workflow.
  assert.strictEqual(fileCard.onclick, null);
  assert.strictEqual(fileOpened, false);
  const dialog = document.getElementById("b66SkillStartDialog");
  assert.strictEqual(dialog.open, true, "the dialog must stay where the user is");
}

// ── the two working paths still hand off
{
  install();
  const dialogApi = load();
  const seen = [];
  dialogApi.open({
    fileOpen: () => seen.push("file"),
    blankOpen: () => seen.push("blank"),
    blankCancel: () => {},
    assistOpen: () => seen.push("assist"),
  }, makeNode("button"));

  click(document.getElementById("b66SkillStartAssist"));
  assert.deepStrictEqual(seen, ["assist"]);
  assert.strictEqual(document.getElementById("b66SkillStartDialog").open, false);

  // Blank path needs its panel; the enabled card is wired to it.
  const blankCard = document.getElementById("b66SkillStartFromBlank");
  assert.ok(typeof blankCard.onclick === "function");
  assert.strictEqual(blankCard.disabled, false);
  assert.ok(!seen.includes("file"));
}

// ── focus lands on a card the user can actually use
{
  install();
  const dialogApi = load();
  dialogApi.open({
    fileOpen: () => {},
    blankOpen: () => {},
    blankCancel: () => {},
    assistOpen: () => {},
  }, makeNode("button"));
  assert.strictEqual(globalThis.__focused.id, "b66SkillStartFromBlank");
}

console.log("B66_3186_SKILL_START_PATHS=PASS");
