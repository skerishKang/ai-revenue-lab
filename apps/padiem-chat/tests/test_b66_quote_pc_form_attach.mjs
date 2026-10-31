import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

// The quote launcher promises "내 PC 엑셀 양식으로 견적서", so the opened dialog
// must actually contain the PC form section and its "내 PC 엑셀 양식 가져오기"
// button. This is behaviour on the shipped bytes: the runtime is evaluated in a
// vm against a small DOM stub that implements exactly the startup surface it
// touches (create/append/insertBefore/after/get-by-id/simple selectors) —
// including the DOM rule that Element.after() on a parentless node is a no-op,
// the rule the original defect relied on when it called messageLabel.after(pcForm)
// before either node was attached.
//
// The PC pairing probe is stubbed to an active link, the #5895 entry path where
// the PC form is the whole point, so the pick button must stay visible.

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SOURCE = readFileSync(join(HERE, "..", "static", "b66-quote-runtime.js"), "utf8");

function dashedAttribute(key) {
  return "data-" + String(key).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}

function makeDataset(node) {
  return new Proxy({}, {
    set(_, key, value) {
      node.attributes[dashedAttribute(key)] = String(value);
      return true;
    },
    get(_, key) {
      return node.attributes[dashedAttribute(key)];
    },
    has(_, key) {
      return dashedAttribute(key) in node.attributes;
    },
  });
}

function adopt(parent, child, at) {
  if (child.parentNode) {
    const siblings = child.parentNode.childNodes;
    const index = siblings.indexOf(child);
    if (index !== -1) siblings.splice(index, 1);
  }
  child.parentNode = parent;
  parent.childNodes.splice(Math.min(at, parent.childNodes.length), 0, child);
}

function walk(node, visit) {
  visit(node);
  for (const child of node.childNodes) walk(child, visit);
}

function descendantText(node) {
  return node.childNodes.reduce((acc, child) => acc + child.textContent, "");
}

function matchSimple(node, selector) {
  let rest = selector.trim();
  const tag = /^([a-zA-Z][a-zA-Z0-9-]*)/.exec(rest);
  if (tag) {
    if (node.tagName !== tag[1].toLowerCase()) return false;
    rest = rest.slice(tag[1].length);
  }
  const parts = rest.match(/#[^.[\]]+|\.[^.[\]]+|\[[^\]]+\]/g) || [];
  for (const part of parts) {
    if (part.startsWith("#")) {
      if (node.id !== part.slice(1)) return false;
    } else if (part.startsWith(".")) {
      if (!String(node.className).split(/\s+/).includes(part.slice(1))) return false;
    } else {
      const attr = /^\[(.+)\]$/.exec(part)[1];
      const eq = /^(.+?)="(.*)"$/.exec(attr) || /^(.+?)='(.*)'$/.exec(attr);
      if (eq) {
        if (node.attributes[eq[1]] !== eq[2]) return false;
      } else if (!(attr in node.attributes)) {
        return false;
      }
    }
  }
  return true;
}

function makeDocument() {
  const doc = {};
  const makeElement = (tag) => {
    const node = {
      tagName: String(tag).toLowerCase(),
      parentNode: null,
      childNodes: [],
      attributes: {},
      listeners: {},
      className: "",
      id: "",
      text: "",
      hidden: false,
      open: false,
      disabled: false,
      type: "",
      value: "",
      lang: "",
    };
    node.dataset = makeDataset(node);
    node.append = (...nodes) => {
      let at = node.childNodes.length;
      for (const child of nodes) {
        adopt(node, child, at);
        at += 1;
      }
    };
    node.appendChild = (child) => {
      adopt(node, child, node.childNodes.length);
      return child;
    };
    node.insertBefore = (child, ref) => {
      const at = ref ? node.childNodes.indexOf(ref) : -1;
      adopt(node, child, at === -1 ? node.childNodes.length : at);
      return child;
    };
    // DOM rule under test: Element.after() on a parentless node does nothing.
    node.after = (...nodes) => {
      const parent = node.parentNode;
      if (!parent) return;
      let at = parent.childNodes.indexOf(node) + 1;
      for (const child of nodes) {
        adopt(parent, child, at);
        at += 1;
      }
    };
    node.remove = () => {
      if (!node.parentNode) return;
      const at = node.parentNode.childNodes.indexOf(node);
      if (at !== -1) node.parentNode.childNodes.splice(at, 1);
      node.parentNode = null;
    };
    node.replaceChildren = (...nodes) => {
      for (const child of [...node.childNodes]) child.remove();
      for (const child of nodes) adopt(node, child, node.childNodes.length);
    };
    node.setAttribute = (name, value) => { node.attributes[name] = String(value); };
    node.getAttribute = (name) => (name in node.attributes ? node.attributes[name] : null);
    node.hasAttribute = (name) => name in node.attributes;
    node.removeAttribute = (name) => { delete node.attributes[name]; };
    node.addEventListener = (type, fn) => { (node.listeners[type] ||= []).push(fn); };
    node.removeEventListener = (type, fn) => {
      const fns = node.listeners[type] || [];
      const at = fns.indexOf(fn);
      if (at !== -1) fns.splice(at, 1);
    };
    node.click = () => {
      for (const fn of [...(node.listeners.click || [])]) {
        fn({ preventDefault() {}, target: node });
      }
    };
    node.focus = () => {};
    node.scrollIntoView = () => {};
    node.querySelector = (selector) => {
      let found = null;
      walk(node, (n) => {
        if (!found && n !== node && matchSimple(n, selector)) found = n;
      });
      return found;
    };
    Object.defineProperties(node, {
      textContent: {
        get() { return node.text + descendantText(node); },
        set(value) {
          node.text = String(value);
          for (const child of [...node.childNodes]) child.remove();
        },
      },
      isConnected: {
        get() {
          let n = node;
          while (n) {
            if (n === doc.body) return true;
            n = n.parentNode;
          }
          return false;
        },
      },
      classList: { value: { toggle() {} } },
    });
    if (node.tagName === "dialog") {
      node.showModal = () => { node.open = true; node.setAttribute("open", ""); };
      node.close = () => { node.open = false; node.removeAttribute("open"); };
    }
    return node;
  };
  doc.makeElement = makeElement;
  doc.documentElement = makeElement("html");
  doc.documentElement.lang = "ko";
  doc.readyState = "complete";
  doc.head = makeElement("head");
  doc.body = makeElement("body");
  doc.body.parentNode = doc;
  doc.createElement = makeElement;
  doc.getElementById = (id) => {
    let found = null;
    walk(doc.body, (n) => {
      if (!found && n.id === id) found = n;
    });
    return found;
  };
  doc.querySelector = (selector) => {
    let found = null;
    walk(doc.body, (n) => {
      if (!found && n !== doc.body && matchSimple(n, selector)) found = n;
    });
    return found;
  };
  doc.querySelectorAll = (selector) => {
    const found = [];
    walk(doc.body, (n) => {
      if (n !== doc.body && matchSimple(n, selector)) found.push(n);
    });
    return found;
  };
  doc.addEventListener = () => {};
  return doc;
}

function ancestorsOf(node) {
  const chain = [];
  let n = node.parentNode;
  while (n) {
    chain.push(n);
    n = n.parentNode;
  }
  return chain;
}

const doc = makeDocument();
// The startup path builds the launcher only inside an existing side navigation.
const firstNav = doc.makeElement("nav");
firstNav.className = "side-nav";
doc.body.append(firstNav);
// An actively linked PC keeps the pick button visible (#5895's own scenario).
// The picker is answered here instead of loading the real component script, so
// the fill half (#3180's review list) runs on the shipped bytes too.
const FILL_ANSWER = {
  ok: true,
  filled_file_id: "file_" + "b".repeat(32),
  filled_name: "견적서_대한건설_2026-10-29.xlsx",
  template_name: "견적서 양식.xlsx",
  client: "대한건설",
  mapping: { Sheet1: { B5: "대한건설", B6: "2026-10-29", D9: 30000 } },
  extend: [{ sheet: "Sheet1", template_row: 12, at_row: 13, count: 2 }],
};
const windowStub = {
  fetch: async (url) => {
    const target = String(url || "");
    if (target.includes("/api/b66/pc-quote/fill")) {
      return { ok: true, status: 200, json: async () => FILL_ANSWER };
    }
    return { ok: true, status: 200, json: async () => ({ links: [{ state: "active" }] }) };
  },
  PadiemPcFileExchange: {
    open: ({ onSelect }) => onSelect({ fileId: "file_" + "a".repeat(32), name: "견적서 양식.xlsx", path: "C:/견적/견적서 양식.xlsx" }),
  },
  addEventListener: () => {},
  setTimeout,
  clearTimeout,
};
const context = vm.createContext({ window: windowStub, document: doc, URL, setTimeout, clearTimeout });
vm.runInContext(SOURCE, context, { filename: "b66-quote-runtime.js" });

test("the opened quote dialog contains the PC Excel form section and its pick button", async () => {
  await new Promise((resolve) => setImmediate(resolve)); // let the pairing probe settle

  const launcher = doc.getElementById("b66QuoteNavButton");
  assert.ok(launcher, "the quote launcher exists after startup");

  launcher.click();
  const dialog = doc.getElementById("b66QuoteDialog");
  assert.ok(dialog, "the quote dialog exists");
  assert.equal(dialog.open, true, "clicking the launcher opens the dialog");

  const form = doc.getElementById("b66QuoteForm");
  assert.ok(form, "the quote form exists");

  const pick = doc.getElementById("b66QuotePcPick");
  assert.ok(pick, "the '내 PC 엑셀 양식 가져오기' button exists in the DOM");
  assert.equal(pick.textContent, "내 PC 엑셀 양식 가져오기");
  assert.equal(pick.hidden, false, "the pick button is not hidden");
  assert.ok(pick.isConnected, "the pick button is attached to the document");

  const section = ancestorsOf(pick).find((n) =>
    n.tagName === "section" && String(n.className).split(/\s+/).includes("b66-quote-pcform"));
  assert.ok(section, "the pick button is wrapped by the b66-quote-pcform section");
  assert.ok(ancestorsOf(pick).includes(form), "the PC form section sits inside the quote form");
  assert.ok(ancestorsOf(pick).includes(dialog), "the PC form section sits inside the open dialog");
  assert.ok(ancestorsOf(pick).every((n) => !n.hidden), "no ancestor hides the pick button");
  assert.equal(dialog.open, true, "the dialog is open while the pick button is shown");

  const note = doc.getElementById("b66QuotePcNote");
  assert.ok(note && note.hidden, "a linked PC does not swap the form for the connect note");

  // Placement: the PC form rides directly under the request field, before the
  // submit button — the position the broken after() call intended.
  const requestLabel = doc.querySelector('[data-b66-quote-request-label="true"]').parentNode;
  const submit = doc.getElementById("b66QuoteGenerate");
  const children = form.childNodes;
  const atRequest = children.indexOf(requestLabel);
  const atSection = children.indexOf(section);
  const atSubmit = children.indexOf(submit);
  assert.ok(atRequest !== -1 && atSection !== -1 && atSubmit !== -1,
    "the request field, PC form and submit button are direct children of the form");
  assert.ok(atRequest < atSection && atSection < atSubmit,
    "the PC form sits between the request field and the submit button");
});

test("the PC form section exists exactly once in the opened dialog", () => {
  const seen = doc.querySelectorAll("section.b66-quote-pcform");
  assert.equal(seen.length, 1, "ensureUi builds the PC form section exactly once");
});

// #3180: between "the model filled the form" and "save to my PC" the owner
// must see which cell received which value. The fill answer already carries the
// mapping, so this test drives the shipped buttons and reads what the dialog
// rendered — no new endpoint, no new store.
test("filling my PC form shows what went into which cell before saving", async () => {
  const request = doc.getElementById("b66QuoteRequest");
  assert.ok(request, "the quote request field exists");
  request.value = "대한건설에 배관 20개 개당 3만원으로 견적서 만들어줘";

  const review = doc.getElementById("b66QuotePcReview");
  assert.ok(review, "the review section exists in the PC form");
  assert.equal(review.hidden, true, "nothing is reviewed before a fill");

  doc.getElementById("b66QuotePcPick").click();
  await new Promise((resolve) => setImmediate(resolve));
  const make = doc.getElementById("b66QuotePcMake");
  assert.equal(make.hidden, false, "picking a form enables the make button");

  make.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(review.hidden, false, "a fill opens the review");
  const lines = [];
  walk(review, (node) => { if (node.tagName === "li") lines.push(node.textContent); });
  assert.deepEqual(lines, ["Sheet1!B5 ← 대한건설", "Sheet1!B6 ← 2026-10-29", "Sheet1!D9 ← 30000"],
    "each filled cell is listed as sheet!cell ← value");

  const text = descendantText(review);
  assert.ok(text.includes("거래처: 대한건설"), "the customer the fill used is shown");
  assert.ok(text.includes("늘린 행: 2"), "added item rows are reported");
  assert.ok(text.includes("합계·세금은 양식의 수식이 계산합니다"),
    "the review says where the totals come from");

  const save = doc.getElementById("b66QuotePcSave");
  assert.equal(save.hidden, false, "saving is offered next to the review");
  // The review is plain text, never markup built from the fill answer.
  assert.equal(review.innerHTML, undefined, "no markup is written from the model's values");
});
