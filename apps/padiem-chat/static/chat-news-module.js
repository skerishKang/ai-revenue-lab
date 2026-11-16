(() => {
  "use strict";
  // #7718 2단계 — Chat 안 '새 소식'(버전 노트). 로그인 사용자만 입구가 보이고,
  // 목록을 열면 서버가 '마지막으로 본 시각'을 기록한다. 사용자 이름은 어디에도 없다.
  const API = "/api/chat/news";
  const KINDS = { improved: "kind-improved", fixed: "kind-fixed" };
  const SOURCES = { ai_tester: "source-ai-tester", user: "source-user" };
  // #7847 — 서버가 보내는 배포 표시는 'YYYY.MM.DD' 하나뿐이다. 모양이 다른 값은
  // 목록을 버리지 않고 '그 밖의 소식'으로 묶는다.
  const VERSION = /^\d{4}\.\d{2}\.\d{2}$/;
  const state = { owner: "", epoch: 0, items: [], unread: 0, loading: false, error: "", open: false, focus: 0 };
  const requests = new Set();
  let nodes, returnFocus;
  const copy = (key, values) => window.__padiemLocale?.text("news-" + key, values) || "news-" + key;
  const owner = () => {
    const auth = window.PadiemAuthSession?.get?.();
    return auth?.authenticated === true && typeof auth.ownerKey === "string" ? auth.ownerKey : "";
  };
  const current = (epoch) => epoch === state.epoch && state.owner && owner() === state.owner;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function reset() {
    state.epoch += 1;
    for (const controller of requests) controller.abort();
    requests.clear();
    Object.assign(state, { items: [], unread: 0, loading: false, error: "", open: false, focus: 0 });
  }
  async function request(path) {
    if (!state.owner || owner() !== state.owner) return null;
    const epoch = state.epoch, controller = new AbortController();
    requests.add(controller);
    const init = { method: "GET", credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json" } };
    try {
      const response = await window.fetch(path, init);
      const data = await response.json().catch(() => null);
      if (!current(epoch)) return null;
      if (response.status === 401) { state.owner = ""; reset(); paint(); return null; }
      return { status: response.status, data };
    } catch (_) {
      return current(epoch) ? { status: 0, data: null } : null;
    } finally { requests.delete(controller); }
  }
  function item(value) {
    if (!value || !Number.isInteger(value.number) || value.number < 1
        || typeof value.kind !== "string" || !KINDS[value.kind]
        || typeof value.title !== "string" || typeof value.detail !== "string"
        || typeof value.source !== "string" || !(value.source in SOURCES || value.source === "none")
        || typeof value.published_at !== "string") return null;
    return { number: value.number, kind: value.kind, title: value.title, detail: value.detail,
      source: value.source, published_at: value.published_at,
      version: typeof value.version === "string" && VERSION.test(value.version) ? value.version : "" };
  }
  const date = (value) => {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleDateString(document.documentElement.lang === "en" ? "en" : "ko") : "";
  };
  // The source label is bundled: consecutive items that share one source
  // carry it only on the last row of the run, so a batch does not repeat the
  // label on every line.
  const lastOfRun = (items) => items.map((entry, index) => {
    const next = items[index + 1];
    return Boolean(SOURCES[entry.source]) && (!next || next.source !== entry.source);
  });
  function row(entry, active, showSource) {
    const li = element("li", "news-item");
    li.dataset.newsNumber = String(entry.number);
    if (active) li.dataset.active = "true";
    const heading = element("div", "news-item-heading");
    heading.append(element("span", "news-kind " + (entry.kind === "fixed" ? "news-kind-fixed" : "news-kind-improved"), copy(KINDS[entry.kind])));
    const when = date(entry.published_at);
    if (when) heading.append(element("span", "news-date", when));
    li.append(heading, element("h3", "news-title", entry.title), element("p", "news-detail", entry.detail));
    if (showSource) li.append(element("small", "news-source", copy(SOURCES[entry.source])));
    return li;
  }
  // #7847 — 같은 배포에서 낸 소식은 그 배포 제목 아래에 모으고, 배포 표시가 없는
  // 소식은 마지막 '그 밖의 소식'에 모은다. 배포는 최신이 먼저다.
  function groups(items) {
    const order = [];
    const buckets = new Map();
    for (const entry of items) {
      if (!buckets.has(entry.version)) { buckets.set(entry.version, []); order.push(entry.version); }
      buckets.get(entry.version).push(entry);
    }
    order.sort((left, right) => (!left ? 1 : !right ? -1 : right.localeCompare(left)));
    return order.map((version) => ({ version, items: buckets.get(version) }));
  }
  function listRows() {
    const lines = [];
    for (const group of groups(state.items)) {
      const heading = element("li", "news-group");
      heading.append(element("h3", "news-group-title", group.version
        ? copy("version", { version: group.version }) : copy("other")));
      lines.push(heading);
      const runs = lastOfRun(group.items);
      lines.push(...group.items.map((entry, index) => row(entry, state.focus === entry.number, runs[index])));
    }
    return lines;
  }
  function paint() {
    if (!nodes) return;
    const signedIn = Boolean(state.owner);
    nodes.button.hidden = !signedIn;
    const unseen = signedIn && state.unread > 0;
    nodes.dot.hidden = !unseen;
    nodes.dotText.hidden = !unseen;
    if (unseen) nodes.dotText.textContent = copy("unread-notice");
    nodes.button.setAttribute("aria-expanded", String(state.open && nodes.dialog.open));
    if (state.open) {
      nodes.list.replaceChildren(...listRows());
      nodes.status.textContent = state.error ? copy(state.error)
        : state.loading ? copy("loading")
        : state.items.length ? "" : copy("empty");
      nodes.list.setAttribute("aria-busy", String(state.loading));
    }
  }
  async function refreshUnread() {
    if (!state.owner || state.open) return;
    const epoch = state.epoch;
    const reply = await request(API + "/unread");
    if (!reply || !current(epoch) || state.open) return;
    state.unread = reply.status === 200 && reply.data?.ok === true
      && Number.isInteger(reply.data.unread_count) ? Math.max(0, reply.data.unread_count) : 0;
    paint();
  }
  async function load() {
    if (state.loading || !state.owner) return;
    state.loading = true; state.error = ""; paint();
    const epoch = state.epoch;
    const reply = await request(API);
    if (!reply || !current(epoch)) return;
    state.loading = false;
    if (reply.status === 200 && reply.data?.ok === true && Array.isArray(reply.data.news)) {
      state.items = reply.data.news.map(item).filter(Boolean);
      // Opening the list has just marked it seen on the server; the dot goes away.
      state.unread = 0;
    } else {
      state.error = "failed";
    }
    paint();
    if (state.focus) {
      const target = nodes.list.querySelector?.(`[data-news-number="${state.focus}"]`);
      if (target?.scrollIntoView) target.scrollIntoView({ block: "start" });
    }
  }
  async function open(focusNumber = 0) {
    const who = owner();
    if (!who) return;
    if (who !== state.owner) { state.owner = who; reset(); }
    state.focus = Number.isInteger(focusNumber) && focusNumber > 0 ? focusNumber : 0;
    state.open = true;
    returnFocus = document.activeElement;
    if (typeof nodes.dialog.showModal === "function") nodes.dialog.showModal(); else nodes.dialog.setAttribute("open", "");
    nodes.button.setAttribute("aria-expanded", "true");
    paint();
    await load();
    (state.focus ? nodes.list : nodes.close).focus?.();
  }
  function close() {
    if (nodes.dialog.open && typeof nodes.dialog.close === "function") nodes.dialog.close();
    else { nodes.dialog.removeAttribute("open"); closed(); }
  }
  function closed() {
    state.open = false;
    nodes.button.setAttribute("aria-expanded", "false");
    if (returnFocus?.isConnected !== false) returnFocus?.focus?.();
  }
  function sync() {
    const next = owner();
    if (next === state.owner) return;
    state.owner = next;
    const wasOpen = state.open;
    reset();
    if (wasOpen && nodes.dialog.open) { nodes.dialog.removeAttribute("open"); }
    state.open = false;
    paint();
    if (next) void refreshUnread();
  }
  function init() {
    const ids = { button: "newsButton", dot: "newsDot", dotText: "newsDotText", dialog: "newsDialog",
      close: "newsClose", list: "newsList", status: "newsStatus" };
    nodes = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, document.getElementById(id)]));
    if (Object.values(nodes).some((node) => !node)) return;
    nodes.button.addEventListener("click", () => void open());
    nodes.close.addEventListener("click", close);
    nodes.dialog.addEventListener("close", closed);
    window.addEventListener("padiem:auth-state", sync);
    window.addEventListener("padiem:localechange", paint);
    window.addEventListener("pagehide", () => { state.owner = ""; reset(); });
    window.addEventListener("pageshow", sync);
    window.PadiemNews = {
      open: (focusNumber) => { void open(Number.isInteger(focusNumber) && focusNumber > 0 ? focusNumber : 0); },
    };
    paint();
    sync();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
