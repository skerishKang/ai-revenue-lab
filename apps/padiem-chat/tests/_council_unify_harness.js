// Execute the shipped static/util-menu.js on a small fake DOM.
//
// The one behaviour this harness observes is the 2026-11-01 unification: the
// three 의원3종 entries leave for /apps/council/ with the tool in the fragment,
// and the PDF → Markdown utility still opens inside Chat.
//
// Usage: node _council_unify_harness.js <util-menu.js path>
const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];

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
  append(...children) { children.forEach((c) => this.appendChild(c)); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  async click() { for (const fn of (this._listeners.click || []).slice()) await fn(); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const key = String(sel);
    const direct = key.startsWith(".") ? key.slice(1) : null;
    return this.children.filter((child) => {
      if (direct) return child.classList.contains(direct);
      const attr = /^\[([\w-]+)\]$/.exec(key);
      return attr ? child.getAttribute(attr[1]) !== null : false;
    });
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
  const utilNav = mk("button", "utilNavButton", "side-item");
  utilNav.setAttribute("aria-current", "false");
  const utilView = mk("section", "utilView");
  const utilSubmenu = mk("div", "utilSubmenu");
  utilSubmenu.hidden = true;
  const submenu = { speech: null, sns: null, meeting: null, pdfmd: null };
  Object.keys(submenu).forEach((key) => {
    const b = mk("button", null, "util-submenu-item");
    b.dataset.util = key;
    utilSubmenu.appendChild(b);
    submenu[key] = b;
  });
  const tabs = {};
  ["speech", "sns", "meeting", "pdfmd"].forEach((key) => {
    const b = mk("button", null, key === "pdfmd" ? "util-tab active" : "util-tab");
    b.dataset.util = key;
    b.textContent = key === "pdfmd" ? "PDF → Markdown" : key;
    tabs[key] = b;
  });
  const toolCards = {};
  const toolGrid = mk("section", "utilToolGrid");
  ["speech", "sns", "meeting", "pdfmd", "claw-quote", "claw-excel"].forEach((key) => {
    const b = mk("button", null, "util-tool-open");
    b.setAttribute("data-util-tool", key);
    toolCards[key] = b;
    toolGrid.appendChild(b);
  });
  const pdfPanel = mk("div", "utilPdfmdPanel");
  const title = mk("h2", "utilTitle");
  const kicker = mk("p", "utilKicker");
  const tagline = mk("p", "utilTagline");
  mk("button", "clawNavButton");

  const document = {
    readyState: "complete",
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => {
      const match = /^\[data-util-tool="([^"]+)"\]$/.exec(sel);
      return match ? toolCards[match[1]] || null : null;
    },
    querySelectorAll: (sel) => {
      if (sel === ".util-tab") return Object.values(tabs);
      if (sel === ".util-submenu-item") return Object.values(submenu);
      if (sel === "[data-quick-util]") return [];
      if (sel === "[data-util-tool]") return Object.values(toolCards);
      return [];
    },
    addEventListener() {},
    createElement: (tag) => new N(tag),
  };
  const assigned = [];
  const window = {
    location: { assign: (href) => { assigned.push(href); } },
    history: { replaceState() {} },
  };
  const ctx = {
    document,
    window,
    URL: { createObjectURL: () => "", revokeObjectURL() {} },
    setTimeout: (fn) => { if (typeof fn === "function") fn(); return 0; },
    clearTimeout() {},
    MutationObserver: class { observe() {} },
    initPdfMdUtility: null,
    console,
  };
  vm.createContext(ctx);
  const initialized = [];
  window.initPdfMdUtility = (panel) => initialized.push(panel && panel.id);
  vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });
  return { ctx, assigned, initialized, tabs, submenu, toolCards, pdfPanel, title, kicker, tagline };
}

(async () => {
  try {
    const dom = makeDom();
    await dom.submenu.speech.click();
    await dom.submenu.sns.click();
    await dom.submenu.meeting.click();
    await dom.tabs.sns.click();
    await dom.toolCards.meeting.click();
    const afterCouncil = dom.assigned.slice();
    await dom.submenu.pdfmd.click();
    const pdfmd = {
      assigned: dom.assigned.slice(afterCouncil.length),
      initialized: dom.initialized.slice(),
      panelHidden: dom.pdfPanel.hidden,
      title: dom.title.textContent,
    };
    process.stdout.write(JSON.stringify({
      ok: true,
      observation: { assigned: afterCouncil, pdfmd },
    }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
  }
})();
