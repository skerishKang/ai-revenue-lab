import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

// #6100: the logged-out quote dialog must not show three empty selects. The
// capability event is the product's own auth signal (product-capabilities
// dispatches it at startup and after every login), so this is behaviour on
// the shipped bytes: a guest pass hides the select fields behind one sign-in
// line that opens the account area's own login dialog (#loginButton), and the
// authenticated pass restores the selects through the same refresh() flow
// that already filled them — the post-login behaviour is unchanged.

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

function makeElement(tag) {
  const node = {
    tagName: String(tag).toUpperCase(),
    childNodes: [],
    attributes: {},
    listeners: {},
    id: "",
    className: "",
    parentNode: null,
    hidden: false,
    disabled: false,
    type: "",
    value: "",
    lang: "",
    open: false,
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
}

function descendantText(node) {
  return node.childNodes.reduce((acc, child) => acc + child.textContent, "");
}

function matchSimple(node, selector) {
  const classMatch = selector.match(/\.([A-Za-z0-9_-]+)/g) || [];
  const idMatch = selector.match(/#([A-Za-z0-9_-]+)/);
  if (idMatch && node.id !== idMatch[1]) return false;
  for (const cls of classMatch) {
    if (!node.className || !node.className.split(/\s+/).includes(cls.slice(1))) return false;
  }
  return true;
}

function makeDocument() {
  const doc = makeElement("document");
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

const doc = makeDocument();
const firstNav = doc.makeElement("nav");
firstNav.className = "side-nav";
doc.body.append(firstNav);

const fetchCalls = [];
const windowStub = {
  fetch: async (url) => {
    fetchCalls.push(String(url));
    // The quote screen never gets a runtime in this test: whatever the event
    // says, the fetch answer is a refusal, and the flow must still land.
    return { ok: false, status: 401, json: async () => ({}) };
  },
  listeners: {},
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  setTimeout,
  clearTimeout,
};
const context = vm.createContext({ window: windowStub, document: doc, URL, setTimeout, clearTimeout });
vm.runInContext(SOURCE, context, { filename: "b66-quote-runtime.js" });

const settle = async (rounds = 20) => {
  for (let index = 0; index < rounds; index += 1) await new Promise((resolve) => setImmediate(resolve));
};

function dispatchCapability(auth) {
  for (const fn of windowStub.listeners["padiem:capabilitychange"] || []) {
    fn({ detail: { auth } });
  }
}

const FIELD_IDS = ["b66QuoteSkillField", "b66QuoteModelField", "b66QuoteReasoningField"];

test("a guest sees the sign-in line instead of empty selects", async () => {
  await settle();
  dispatchCapability({ authenticated: false });
  await settle();

  const hint = doc.getElementById("b66QuoteSigninHint");
  assert.ok(hint, "the sign-in hint exists");
  assert.equal(hint.hidden, false, "the hint is shown to a guest");
  assert.equal(hint.textContent.includes("로그인하면 내 양식과 등급을 고를 수 있어요"), true, hint.textContent);

  for (const id of FIELD_IDS) {
    const field = doc.getElementById(id);
    assert.ok(field, `${id} exists`);
    assert.equal(field.hidden, true, `${id} is hidden for a guest`);
  }

  const button = doc.getElementById("b66QuoteSigninButton");
  assert.ok(button, "the hint carries a login button");
  assert.equal(button.textContent, "로그인");
});

test("the hint's login button opens the account area's own login entry", () => {
  // #loginButton is not in this stub's document: the shipped handler must
  // look it up by id and survive its absence (optional chaining), and the
  // click it would forward is the account area's own dialog opener.
  const source = SOURCE;
  assert.ok(source.includes('document.getElementById("loginButton")?.click()'));
});

test("the authenticated event restores the selects through refresh()", async () => {
  dispatchCapability({ authenticated: true });
  await settle();

  const hint = doc.getElementById("b66QuoteSigninHint");
  assert.equal(hint.hidden, true, "the hint is gone once signed in");
  for (const id of FIELD_IDS) {
    const field = doc.getElementById(id);
    assert.equal(field.hidden, false, `${id} is visible again`);
  }
  assert.ok(fetchCalls.some((url) => url.includes("/api/b66/runtime-config")), "refresh() asked the server");
});
