const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const STATIC = process.argv[2];
const feedbackSource = fs.readFileSync(path.join(STATIC, "chat-feedback-module.js"), "utf8");
const newsSource = fs.readFileSync(path.join(STATIC, "chat-news-module.js"), "utf8");
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
const ID = "fb_" + "a".repeat(32), NEWS_ID = "fb_" + "b".repeat(32);
const HISTORY_FIXTURE = { number: 987654321, published_at: "2099-01-01T00:00:00Z",
  title: "fixture history title", detail: "fixture history detail" };
const record = (values = {}) => ({ id: ID, body: "fixture feedback", status: "new", created_at: "2026-11-15T01:00:00Z",
  updated_at: "2026-11-15T01:00:00Z", screen: null, fixed_version: 0, unread_fixed: false,
  replies: [], unread_ops_replies: 0, is_ai_tester: false, sender_display: "", news: null, ...values });
const newsItem = (values = {}) => ({ number: 3, kind: "improved", title: "fixture news title", detail: "fixture news detail",
  source: "none", published_at: "2026-11-15T09:00:00Z", version: "", ...values });
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
  const newsProgram = options.emptyHistory
    ? newsSource.replace(/const HISTORY_EVENTS = Object\.freeze\(\[[\s\S]*?\]\);/, "const HISTORY_EVENTS = Object.freeze([]);")
    : newsSource;
  if (options.emptyHistory) assert.notEqual(newsProgram, newsSource, "empty-history fixture replaces production milestones only in the test harness");
  vm.runInNewContext(newsProgram, context);
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
    // 배포 표시가 없는 두 항목은 하나의 '그 밖의 소식' 머리글 아래에 모인다(#7847).
    assert.equal(app.ids.newsList.children.length, 3);
    assert.equal(app.ids.newsList.children[0].className, "news-group");
    assert.equal(app.ids.newsList.children[0].textContent, "ko:news-other");
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

  async version_groups_newest_first_with_other_last() {
    const app = setup({ news: [
      newsItem({ number: 6, version: "2026.11.16" }),
      newsItem({ number: 5, kind: "fixed", source: "user", version: "2026.11.16" }),
      newsItem({ number: 4, version: "2026.11.02" }),
      newsItem({ number: 3, kind: "fixed" }),
      newsItem({ number: 2, version: "not-a-date" }),
      newsItem({ number: 1, kind: "fixed", source: "user", version: "2025.12.01" }),
    ] });
    await settle();
    app.ids.newsButton.click(); await settle();
    const list = app.ids.newsList;
    const headings = list.children.filter((node) => node.className === "news-group").map((node) => node.textContent);
    // 배포는 최신이 먼저, 배포 표시가 없는(또는 모양이 틀린) 소식은 마지막 한 묶음.
    assert.deepEqual(headings, [
      'ko:news-version{"version":"2026.11.16"}',
      'ko:news-version{"version":"2026.11.02"}',
      'ko:news-version{"version":"2025.12.01"}',
      "ko:news-other",
    ]);
    const order = list.children.filter((node) => node.dataset?.newsNumber).map((node) => node.dataset.newsNumber);
    assert.deepEqual(order, ["6", "5", "4", "1", "3", "2"]);
    // 항목 자신의 improved/fixed 표시는 그대로 남는다.
    assert.ok(app.newsRow(5).textContent.includes("ko:news-kind-fixed"));
    assert.ok(!app.newsRow(6).textContent.includes("news-version"));
    app.language("en"); await settle();
    assert.equal(app.ids.newsList.children[0].textContent, 'en:news-version{"version":"2026.11.16"}');
    assert.equal(app.ids.newsList.children[7].textContent, "en:news-other");
  },

  async history_is_chronological_and_separate_from_news_fixtures() {
    const app = setup({ news: [newsItem({ number: HISTORY_FIXTURE.number, title: HISTORY_FIXTURE.title,
      detail: HISTORY_FIXTURE.detail, published_at: HISTORY_FIXTURE.published_at })] });
    await settle();
    app.ids.newsButton.click(); await settle();
    const rows = app.ids.newsHistoryList.children;
    const dates = rows.map((node) => node.dataset.historyDate);
    assert.equal(rows.length, 17);
    assert.deepEqual(dates, [...dates].sort());
    assert.equal(dates[0], "2026-08-26");
    assert.equal(dates.at(-1), "2026-11-16");
    assert.ok(app.newsRow(HISTORY_FIXTURE.number), "server news fixtures remain in the news list");
    assert.ok(!app.ids.newsHistoryList.textContent.includes(HISTORY_FIXTURE.title));
    assert.ok(!app.ids.newsHistoryList.textContent.includes(HISTORY_FIXTURE.detail));
    assert.ok(!app.ids.newsHistoryList.textContent.includes("2099"));
    assert.ok(app.ids.newsHistoryList.textContent.includes("Padiem Chat을 웹에서 공개했어요."));
    app.language("en"); await settle();
    assert.ok(app.ids.newsHistoryList.textContent.includes("Padiem Chat went live on the web."));
  },

  async history_empty_state_when_no_entries() {
    const app = setup({ emptyHistory: true, news: [] }); await settle();
    app.ids.newsButton.click(); await settle();
    assert.equal(app.ids.newsStatus.textContent, "ko:news-empty");
    assert.equal(app.ids.newsHistoryStatus.textContent, "ko:news-history-empty");
    assert.equal(app.ids.newsHistoryList.children.length, 0);
  },
};

const name = process.argv[3];
if (!scenarios[name]) throw new Error("unknown scenario: " + name);
scenarios[name]().then(() => { console.log(JSON.stringify({ passed: name })); }, (error) => { console.error(error); process.exit(1); });
