// Execute static/util-manifest.js + static/util-menu.js on a fake DOM (#7460).
//
// Proves the sidebar Util submenu renders all 6 tools from the single manifest
// and routes every entry in-app (#util/<id>) with zero external redirects.
//
// Usage: node _council_unify_harness.js <util-manifest.js> <util-menu.js>
const fs = require("node:fs");
const vm = require("node:vm");

const manifestPath = process.argv[2];
const utilMenuPath = process.argv[3];

class N {
  constructor(tag, id) {
    this.tagName = String(tag || "div").toUpperCase();
    this.id = id || "";
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.hidden = false;
    this.textContent = "";
    this._cls = "";
    this._listeners = {};
    this.parentNode = null;
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls; }
  get classList() {
    const self = this;
    return {
      add: (...c) => { self._cls = [...new Set([...self._cls.split(/\s+/).filter(Boolean), ...c])].join(" "); },
      remove: (...c) => { const d = new Set(c); self._cls = self._cls.split(/\s+/).filter((x) => x && !d.has(x)).join(" "); },
      toggle: (c, on) => { if (on) self.classList.add(c); else self.classList.remove(c); },
      contains: (c) => self._cls.split(/\s+/).includes(c),
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  replaceChildren(...children) {
    this.children = [];
    children.forEach((c) => this.appendChild(c));
  }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  async click() { for (const fn of (this._listeners.click || []).slice()) await fn(); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const key = String(sel);
    const direct = key.startsWith(".") ? key.slice(1) : null;
    return this.children.filter((child) => (direct ? child.classList.contains(direct) : false));
  }
}

function makeDom() {
  const byId = {};
  const mk = (tag, id, cls) => {
    const node = new N(tag, id);
    if (id) byId[id] = node;
    if (cls) node.className = cls;
    return node;
  };
  const shell = mk("div", null, "app-shell");
  shell.dataset.state = "home";
  const utilNav = mk("button", "utilNavButton", "side-item");
  utilNav.setAttribute("aria-current", "false");
  const chevron = mk("span", null, "side-chevron");
  chevron.textContent = "›";
  utilNav.appendChild(chevron);
  const utilView = mk("section", "utilView");
  utilView.hidden = true;
  const utilSubmenu = mk("div", "utilSubmenu");
  utilSubmenu.hidden = true;

  const document = {
    readyState: "complete",
    documentElement: { lang: "ko" },
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => (sel === ".app-shell" ? shell : null),
    querySelectorAll: () => [],
    addEventListener() {},
    createElement: (tag) => new N(tag),
  };
  const assigned = [];
  const navigated = [];
  const loc = { hash: "", assign: (href) => { assigned.push(href); } };
  const window = {
    location: loc,
    history: { replaceState() {} },
    addEventListener() {},
    PadiemUtilApp: {
      navigate: (hash) => { loc.hash = hash; navigated.push(hash); },
      parseHash: (hash) => {
        if (!hash || !hash.startsWith("#util")) return null;
        if (hash === "#util") return { screen: "list" };
        return { screen: "tool", id: hash.slice("#util/".length) };
      },
    },
  };
  const ctx = {
    document,
    window,
    MutationObserver: class { observe() {} },
    console,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(manifestPath, "utf8"), ctx, { filename: "util-manifest.js" });
  vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });
  return { assigned, navigated, utilNav, utilView, utilSubmenu, shell };
}

(async () => {
  try {
    const dom = makeDom();
    const items = dom.utilSubmenu.children.slice();
    for (const item of items) {
      await item.click();
    }
    process.stdout.write(JSON.stringify({
      ok: true,
      observation: {
        assigned: dom.assigned,
        navigated: dom.navigated,
        renderedIds: items.map((i) => i.dataset.util),
        renderedLabels: items.map((i) => i.textContent),
      },
    }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
  }
})();
