const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const STATIC = process.argv[2];
const feedbackSource = fs.readFileSync(path.join(STATIC, "chat-feedback-module.js"), "utf8");
const newsSource = fs.readFileSync(path.join(STATIC, "chat-news-module.js"), "utf8");
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
const ID = "fb_" + "a".repeat(32), NEWS_ID = "fb_" + "b".repeat(32);
const record = (values = {}) => ({ id: ID, body: "fixture feedback", status: "new", created_at: "2026-11-15T01:00:00Z",
  updated_at: "2026-11-15T01:00:00Z", screen: null, fixed_version: 0, unread_fixed: false,
  replies: [], unread_ops_replies: 0, is_ai_tester: false, sender_display: "", news: null, ...values });
const newsItem = (values = {}) => ({ number: 3, kind: "improved", title: "fixture news title", detail: "fixture news detail",
  source: "none", published_at: "2026-11-15T09:00:00Z", ...values });
const response = (status, data) => ({ status, json: async () => data });
const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise(setImmediate); };

class Element {
  constructor(tag = "div") { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.attrs = {}; this.value = ""; this.text = ""; this.hidden = false; this.checked = false; this.disabled = false; this.open = false; this.isConnected = true; this.dataset = {}; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ""; }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === "open") this.open = true; }
  removeAttribute(key) { delete this.attrs[key]; if (key === "open") this.open = false; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  emit(name) { for (const callback of this.listeners[name] || []) callback({ target: this, preventDefault() {} }); }
  click() { if (!this.disabled) this.emit("click"); }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit("close"); }
  all() { return [this, ...this.children.flatMap((child) => child.all())]; }
}

function setup(options = {}) {
  const ids = {};
  for (const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = ids[match[3]] = new Element(match[1]);
    node.hidden = /\bhidden\b/.test(match[2]);
    node.id = match[3];
  }
  ids.feedbackFilter.value = "all";
  let auth = options.guest ? null : { authenticated: true, ownerKey: "fixture-owner" };
  let lang = "ko";
  const calls = [], events = {}, errors = [];
  const server = { own: options.own || [], inbox: options.inbox || [], news: options.news || [],
    admin: options.admin === true, unread: options.unread ?? 0, newsStatus: options.newsStatus ?? 200,
    unreadStatus: options.unreadStatus ?? 200 };
  const document = { readyState: "complete", documentElement: { lang }, currentScript: { src: "https://fixture.invalid/chat-news-module.js?v=1234abcd" },
    activeElement: ids.newsButton, getElementById: (id) => ids[id], createElement: (tag) => new Element(tag) };
  const window = { document, innerWidth: 390, innerHeight: 844,
    location: { href: "https://fixture.invalid/" },
    PadiemAuthSession: { get: () => auth },
    __padiemLocale: { text: (key, values) => lang + ":" + key + (values ? JSON.stringify(values) : "") },
    addEventListener: (name, callback) => { (events[name] ||= []).push(callback); },
    fetch: (url, init = {}) => {
      const call = { url, method: init.method || "GET", ...init };
      calls.push(call);
      if (url === "/api/admin/session") return Promise.resolve(response(200, { authenticated: true, capabilities: { chat_admin: server.admin }, role: "admin" }));
      if (url === "/api/chat/news/unread") {
        if (server.unreadStatus !== 200) return Promise.resolve(response(server.unreadStatus, { ok: false }));
        return Promise.resolve(response(200, { ok: true, unread_count: server.unread }));
      }
      if (url === "/api/chat/news") {
        if (server.newsStatus !== 200) return Promise.resolve(response(server.newsStatus, { ok: false, error: { code: "news_unavailable" } }));
        return Promise.resolve(response(200, { ok: true, news: server.news, unread_count: server.unread, extra: "ignored" }));
      }
      if (url.startsWith("/api/admin/feedback") && call.method === "GET") return Promise.resolve(response(200, { ok: true, feedback: server.inbox, next_cursor: null }));
      if (call.method === "GET") return Promise.resolve(response(200, { ok: true, feedback: server.own, next_cursor: null, unread_fixed_count: 0, unread_ops_replies_count: 0,
        limits: { body_chars: 4000, daily_submissions: 10, reply_chars: 4000 } }));
      if (call.method === "POST" && url === "/api/chat/feedback") return Promise.resolve(response(201, { ok: true, feedback: record(JSON.parse(call.body)) }));
      throw new Error("unexpected fixture request");
    } };
  for (const name of ["localStorage", "sessionStorage"]) Object.defineProperty(window, name, { get() { throw new Error("browser storage is forbidden"); } });
  // Both modules load into one page: the feedback module bounds its requests with a
  // timer, exactly as a browser page provides one (#7835).
  const context = { window, document, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    console: { log: (...args) => errors.push(args), error: (...args) => errors.push(args) } };
  vm.runInNewContext(feedbackSource, context);
  vm.runInNewContext(newsSource, context);
  return { ids, calls, server, errors,
    event(name) { for (const callback of events[name] || []) callback(); },
    auth(value) { auth = value; this.event("padiem:auth-state"); },
    language(value) { lang = value; document.documentElement.lang = value; this.event("padiem:localechange"); },
    text() { return Object.values(ids).map((node) => node.textContent).join("\n"); },
    newsRow(number) { return ids.newsList.all().find((node) => node.dataset?.newsNumber === String(number)); },
    rowButton(list, suffix) { return ids[list].all().find((node) => node.tagName === "BUTTON" && node.textContent.endsWith(suffix)); },
  };
}

const scenarios = {
  async guest_has_no_entry_and_makes_no_calls() {
    const app = setup({ guest: true }); await settle();
    assert.equal(app.calls.length, 0);
    assert.equal(app.ids.newsButton.hidden, true);
    assert.equal(app.ids.newsDot.hidden, true);
  },

  async unread_dot_opens_list_and_marks_seen() {
    const app = setup({ unread: 2, news: [newsItem(), newsItem({ number: 1, kind: "fixed", source: "user" })] });
    await settle();
    assert.equal(app.calls.filter((call) => call.url === "/api/chat/news/unread").length, 1);
    assert.equal(app.ids.newsButton.hidden, false);
    assert.equal(app.ids.newsDot.hidden, false);
    assert.equal(app.ids.newsDotText.textContent, "ko:news-unread-notice");
    app.ids.newsButton.click(); await settle();
    assert.equal(app.ids.newsDialog.open, true);
    assert.equal(app.calls.filter((call) => call.url === "/api/chat/news").length, 1);
    assert.equal(app.ids.newsList.children.length, 2);
    const text = app.ids.newsList.textContent;
    assert.ok(text.includes("ko:news-kind-improved") && text.includes("ko:news-kind-fixed"));
    assert.ok(text.includes("ko:news-source-user"));
    assert.ok(!text.includes("fixture-owner"));
    assert.equal(app.ids.newsDot.hidden, true);
    app.ids.newsClose.click();
    assert.equal(app.ids.newsDialog.open, false);
  },

  async source_label_shows_once_per_run() {
    const app = setup({ news: [
      newsItem({ number: 5, source: "ai_tester" }),
      newsItem({ number: 4, kind: "fixed", source: "ai_tester" }),
      newsItem({ number: 3, kind: "fixed", source: "user" }),
      newsItem({ number: 2, source: "none" }),
      newsItem({ number: 1, kind: "fixed", source: "ai_tester" }),
    ] });
    await settle();
    app.ids.newsButton.click(); await settle();
    const text = app.ids.newsList.textContent;
    const count = (label) => text.split(label).length - 1;
    // A run of consecutive same-source items carries its label once, on the
    // last row of the run; "none" items never carry one and break the run.
    assert.equal(count("ko:news-source-ai-tester"), 2);
    assert.equal(count("ko:news-source-user"), 1);
    assert.ok(!app.newsRow(5).textContent.includes("ko:news-source-ai-tester"));
    assert.ok(app.newsRow(4).textContent.includes("ko:news-source-ai-tester"));
    assert.ok(app.newsRow(3).textContent.includes("ko:news-source-user"));
    assert.ok(!app.newsRow(2).textContent.includes("news-source"));
    assert.ok(app.newsRow(1).textContent.includes("ko:news-source-ai-tester"));
  },

  async empty_list_error_and_recovery() {
    const app = setup({ news: [] }); await settle();
    app.ids.newsButton.click(); await settle();
    assert.equal(app.ids.newsStatus.textContent, "ko:news-empty");
    assert.equal(app.ids.newsList.children.length, 0);
    const broken = setup({ newsStatus: 503 }); await settle();
    broken.ids.newsButton.click(); await settle();
    assert.equal(broken.ids.newsStatus.textContent, "ko:news-failed");
  },

  async fixed_feedback_links_to_news_item() {
    const app = setup({ unread: 0, news: [newsItem({ number: 7 })],
      own: [record({ status: "fixed", fixed_version: 1, news: { number: 7, kind: "fixed", title: "fixture news title" } }),
            record({ id: NEWS_ID, status: "fixed", fixed_version: 1, news: null })] });
    await settle();
    app.ids.feedbackOwnTab.click(); await settle();
    const link = app.rowButton("feedbackOwnList", "ko:feedback-news-open");
    assert.ok(link, "fixed feedback with a news link shows the jump button");
    link.click(); await settle();
    assert.equal(app.ids.feedbackDialog.open, false);
    assert.equal(app.ids.newsDialog.open, true);
    const row = app.newsRow(7);
    assert.ok(row && row.dataset.active === "true");
    // Only the linked row carries the jump button.
    const jumps = app.ids.feedbackOwnList.all().filter((node) => node.tagName === "BUTTON"
      && node.textContent.endsWith("ko:feedback-news-open"));
    assert.equal(jumps.length, 1);
    assert.equal(jumps[0], link);
  },

  async locale_switch_rerenders_and_guest_lockout() {
    const app = setup({ unread: 1, news: [newsItem()] }); await settle();
    app.ids.newsButton.click(); await settle();
    app.language("en"); await settle();
    assert.ok(app.ids.newsList.textContent.includes("en:news-kind-improved"));
    app.auth(null); await settle();
    assert.equal(app.ids.newsButton.hidden, true);
    assert.equal(app.ids.newsDot.hidden, true);
    assert.equal(app.ids.newsDialog.open, false);
  },
};

const name = process.argv[3];
if (!scenarios[name]) throw new Error("unknown scenario: " + name);
scenarios[name]().then(() => { console.log(JSON.stringify({ passed: name })); }, (error) => { console.error(error); process.exit(1); });
