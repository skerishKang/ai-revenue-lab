"""#5034 LOCAL4 — the common notification inbox (static contracts + real JS).

Two layers, mirroring the established presentation-slice style.

1. Static structural contracts over the real markup, stylesheet, locale tables
   and app.js source: the sidebar bell is the one common entry, the panel is a
   separate module, every new key exists in both ko and en, the module touches
   only the existing /api/claw/inbox/{alerts,tasks} contract, renders server
   text through textContent only, adds no polling loop and reuses the Glass
   tokens.

2. A Node harness that executes the REAL notification-inbox.js against a minimal
   DOM shim with a recording fetch and proves behavior:
   - SIGNED_IN_ENTRY / GUEST_HIDDEN: the bell follows the signed-in state and a
     guest never issues a request.
   - OPEN_RENDERS_UNREAD_ONLY: only "active" alerts count as unread.
   - EMPTY_VS_ERROR: an empty list and a failed lookup render different copy.
   - MARK_READ_EXACT_CONTRACT: the PATCH body is exactly the one status key the
     server accepts, with the existing content types.
   - MARK_READ_FAILURE_IS_TRUTHFUL: a failed update is surfaced as a lookup
     failure, never rewritten optimistically.
   - RESULT_NAV_INBOX / RESULT_NAV_CONVERSATION: a result opens the existing
     product surface through the existing read-only handles.
   - AUTH_LOSS_CLEARS: nothing from a previous session survives a sign-out.
   - LOCALE_EN: the copy follows the locale.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_HTML = STATIC / "index.html"
APP_JS = STATIC / "app.js"
LOCALE_JS = STATIC / "locale.js"
MODULE_JS = STATIC / "notification-inbox.js"
MODULE_CSS = STATIC / "notification-inbox.css"

BELL_ID = "notificationsBellButton"
BADGE_ID = "notificationInboxBadge"
PANEL_ID = "notificationInbox"
NEW_KEYS = (
    "sidebar-actions-group",
    "notification-inbox-bell",
    "notification-inbox-bell-unread",
    "notification-inbox-title",
    "notification-inbox-close",
    "notification-inbox-alerts-section",
    "notification-inbox-tasks-section",
    "notification-inbox-tasks-empty",
    "notification-inbox-open",
    "notification-inbox-read",
    "notification-inbox-restore",
    "notification-inbox-unread",
    "notification-inbox-severity-info",
    "notification-inbox-severity-warn",
    "notification-inbox-severity-critical",
    "notification-inbox-task-open",
    "notification-inbox-task-done",
    "notification-inbox-task-cancelled",
)
REUSED_KEYS = (
    "claw-inbox-loading",
    "claw-inbox-error",
    "claw-inbox-empty-alerts",
    "claw-inbox-help",
    "retry",
)

_CASES = (
    "SIGNED_IN_ENTRY",
    "GUEST_HIDDEN",
    "OPEN_RENDERS_UNREAD_ONLY",
    "EMPTY_VS_ERROR",
    "MARK_READ_EXACT_CONTRACT",
    "MARK_READ_FAILURE_IS_TRUTHFUL",
    "RESULT_NAV_INBOX",
    "RESULT_NAV_CONVERSATION",
    "RESULT_NAV_RUN",
    "AUTH_LOSS_CLEARS",
    "LOCALE_EN",
)

LOCALES = {
    "ko": {
        "sidebar-actions-group": "새 채팅, 대화 검색, 알림함",
        "notification-inbox-bell": "알림함",
        "notification-inbox-bell-unread": "알림함, 읽지 않은 {count}개",
        "notification-inbox-title": "알림함",
        "notification-inbox-close": "알림함 닫기",
        "notification-inbox-alerts-section": "알림",
        "notification-inbox-tasks-section": "작업 결과",
        "notification-inbox-tasks-empty": "최근 작업 결과가 없습니다.",
        "notification-inbox-open": "열기",
        "notification-inbox-read": "읽음 처리",
        "notification-inbox-restore": "읽지 않음으로 되돌리기",
        "notification-inbox-unread": "읽지 않음",
        "notification-inbox-severity-info": "정보",
        "notification-inbox-severity-warn": "주의",
        "notification-inbox-severity-critical": "긴급",
        "notification-inbox-task-open": "진행 중",
        "notification-inbox-task-done": "완료",
        "notification-inbox-task-cancelled": "취소됨",
        "claw-inbox-loading": "불러오는 중…",
        "claw-inbox-error": "목록을 불러오지 못했습니다. 다시 시도해 주세요.",
        "claw-inbox-empty-alerts": "최근 알림이 없습니다.",
        "claw-inbox-help": "최근 항목만 표시되며 현재 로그인 계정과 워크스페이스 범위 안에서만 조회됩니다.",
        "retry": "다시 시도",
    },
    "en": {
        "sidebar-actions-group": "New chat, conversation search, notifications",
        "notification-inbox-bell": "Notifications",
        "notification-inbox-bell-unread": "Notifications, {count} unread",
        "notification-inbox-title": "Notifications",
        "notification-inbox-close": "Close notifications",
        "notification-inbox-alerts-section": "Alerts",
        "notification-inbox-tasks-section": "Task results",
        "notification-inbox-tasks-empty": "No recent task results.",
        "notification-inbox-open": "Open",
        "notification-inbox-read": "Mark as read",
        "notification-inbox-restore": "Mark as unread",
        "notification-inbox-unread": "Unread",
        "notification-inbox-severity-info": "Info",
        "notification-inbox-severity-warn": "Warning",
        "notification-inbox-severity-critical": "Critical",
        "notification-inbox-task-open": "In progress",
        "notification-inbox-task-done": "Done",
        "notification-inbox-task-cancelled": "Cancelled",
        "claw-inbox-loading": "Loading…",
        "claw-inbox-error": "Could not load the inbox. Please try again.",
        "claw-inbox-empty-alerts": "No recent alerts.",
        "claw-inbox-help": "Only recent items are shown, scoped to the signed-in account and current workspace.",
        "retry": "Try again",
    },
}

_HARNESS = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");

const MODULE_SOURCE = fs.readFileSync(process.argv[2], "utf8");
const KO_EMPTY_ALERTS = "최근 알림이 없습니다.";
const KO_ERROR = "목록을 불러오지 못했습니다. 다시 시도해 주세요.";
const CONVERSATION_ID = "chat_" + "0".repeat(32);
const RUN_REF_ID = "sched_run_" + "c".repeat(64);
const ALERTS_URL = "/api/claw/inbox/alerts?limit=20";
const TASKS_URL = "/api/claw/inbox/tasks?limit=20";

function fixture(items) {
  return { status: 200, json: { ok: true, kind: "alerts", limit: 20, items: items } };
}

const ALERTS_TWO_ACTIVE_ONE_DISMISSED = {
  [ALERTS_URL]: fixture([
    { alert_id: "alert_a", title: "첫 번째 알림", severity: "warn", status: "active", created_at: "2026-10-24T01:00:00+00:00" },
    { alert_id: "alert_b", title: "두 번째 알림", severity: "critical", status: "active", created_at: "2026-10-24T02:00:00+00:00" },
    { alert_id: "alert_c", title: "읽은 알림", severity: "info", status: "dismissed", created_at: "2026-10-24T03:00:00+00:00" },
  ]),
  [TASKS_URL]: { status: 200, json: { ok: true, kind: "tasks", limit: 20, items: [] } },
};

const EMPTY_ALERTS_FAILED_TASKS = {
  [ALERTS_URL]: fixture([]),
  [TASKS_URL]: 503,
};

const MARK_READ_SCRIPT = {
  [ALERTS_URL]: fixture([
    { alert_id: "alert_a", title: "첫 번째 알림", severity: "warn", status: "active", created_at: "2026-10-24T01:00:00+00:00" },
  ]),
  "/api/claw/inbox/alerts/alert_a": { status: 200, json: { ok: true, kind: "alerts", item: {} } },
  [TASKS_URL]: { status: 200, json: { ok: true, kind: "tasks", limit: 20, items: [] } },
};

const MARK_READ_FAIL_SCRIPT = {
  [ALERTS_URL]: fixture([
    { alert_id: "alert_a", title: "첫 번째 알림", severity: "warn", status: "active", created_at: "2026-10-24T01:00:00+00:00" },
  ]),
  "/api/claw/inbox/alerts/alert_a": 503,
  [TASKS_URL]: { status: 200, json: { ok: true, kind: "tasks", limit: 20, items: [] } },
};

const CONVERSATION_REF_SCRIPT = {
  [ALERTS_URL]: fixture([
    { alert_id: "alert_a", title: "대화 결과 알림", severity: "info", status: "active", created_at: "2026-10-24T01:00:00+00:00", linked_refs: [CONVERSATION_ID] },
  ]),
  [TASKS_URL]: { status: 200, json: { ok: true, kind: "tasks", limit: 20, items: [] } },
};

const RUN_REF_SCRIPT = {
  [ALERTS_URL]: fixture([
    { alert_id: "alert_run", title: "예약 작업 완료", severity: "info", status: "active", created_at: "2026-10-24T01:00:00+00:00", linked_refs: [RUN_REF_ID, "rule-1"] },
  ]),
  [TASKS_URL]: { status: 200, json: { ok: true, kind: "tasks", limit: 20, items: [] } },
};

function makeClassList() {
  const set = new Set();
  return {
    add: (...names) => { names.forEach((name) => set.add(name)); },
    remove: (...names) => { names.forEach((name) => set.delete(name)); },
    contains: (name) => set.has(name),
    toString: () => [...set].join(" "),
  };
}

class El {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.classList = makeClassList();
    this._listeners = {};
    this._text = "";
    this._hidden = false;
    this._focused = false;
    this.parentElement = null;
    this.className = "";
    this.id = "";
  }

  append(...nodes) {
    for (const node of nodes) { node.parentElement = this; this.children.push(node); }
    return nodes;
  }

  replaceChildren(...nodes) {
    this.children = [];
    return this.append(...nodes);
  }

  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }

  setAttribute(name, value) {
    const text = String(value);
    this.attributes[name] = text;
    if (name === "class") this.className = text;
    if (name === "id") this.id = text;
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      this.dataset[key] = text;
    }
  }

  getAttribute(name) {
    if (name === "id" && this.id) return this.id;
    if (name === "hidden") return this._hidden ? "hidden" : null;
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  removeAttribute(name) { delete this.attributes[name]; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }

  addEventListener(type, handler) {
    (this._listeners[type] = this._listeners[type] || []).push(handler);
  }

  removeEventListener() {}

  click() {
    this.emit("click", { preventDefault() {}, stopPropagation() {}, bubbles: true });
  }

  emit(type, extra) {
    for (const handler of (this._listeners[type] || []).slice()) {
      handler(Object.assign({ type, target: this, currentTarget: this }, extra || {}));
    }
  }

  focus() { this._focused = true; }

  querySelector(selector) {
    const found = this.querySelectorAll(selector);
    return found.length ? found[0] : null;
  }

  querySelectorAll(selector) { return select(this, selector); }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get hidden() { return this._hidden; }
  set hidden(value) { this._hidden = Boolean(value); }
}

function matches(element, selector) {
  if (selector.startsWith(".")) return element.className.split(/\s+/).includes(selector.slice(1));
  if (selector.startsWith("#")) return element.id === selector.slice(1);
  return false;
}

function select(root, selector) {
  const found = [];
  const walk = (node) => {
    for (const child of node.children || []) {
      if (matches(child, selector)) found.push(child);
      walk(child);
    }
  };
  walk(root);
  return found;
}

function makeDocument(bell, badge, loginButton) {
  const document = {
    readyState: "complete",
    documentElement: { lang: "ko" },
    body: new El("body"),
    _listeners: {},
    createElement: (tag) => new El(tag),
    getElementById: (id) => {
      if (id === "notificationsBellButton") return bell;
      if (id === "notificationInboxBadge") return badge;
      if (id === "loginButton") return loginButton;
      return null;
    },
    addEventListener: (type, handler) => {
      (document._listeners[type] = document._listeners[type] || []).push(handler);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return document;
}

function makeWindow(language) {
  const locale = {
    getCurrent: () => language,
    text: (key, variables) => {
      let value = LOCALES[language][key];
      if (value === undefined) value = key;
      if (variables) {
        Object.entries(variables).forEach(([name, replacement]) => {
          value = value.split(`{${name}}`).join(String(replacement));
        });
      }
      return value;
    },
  };
  const window = {
    _listeners: {},
    __padiemLocale: locale,
    addEventListener: (type, handler) => {
      (window._listeners[type] = window._listeners[type] || []).push(handler);
    },
    dispatchEvent: (event) => {
      for (const handler of (window._listeners[event.type] || []).slice()) handler(event);
    },
  };
  return window;
}

class CustomEvent {
  constructor(type, init) {
    this.type = String(type);
    this.detail = init ? init.detail || null : null;
  }
}

function makeFetch(scripted) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({
      url: String(url),
      method: (init && init.method) || "GET",
      headers: (init && init.headers) || null,
      body: init ? init.body : null,
    });
    const value = Object.prototype.hasOwnProperty.call(scripted, String(url))
      ? scripted[String(url)]
      : 500;
    const status = typeof value === "number" ? value : (value.status || 200);
    const json = typeof value === "number" ? null : value.json;
    return { ok: status >= 200 && status < 400, status, json: async () => json };
  };
  return { fetch, calls };
}

async function flush(turns) {
  for (let i = 0; i < (turns || 60); i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function run(spec) {
  const bell = new El("button");
  bell.id = "notificationsBellButton";
  const badge = new El("span");
  badge.id = "notificationInboxBadge";
  const loginButton = new El("button");
  loginButton.id = "loginButton";
  loginButton.hidden = !spec.signedIn;

  const window = makeWindow(spec.language || "ko");
  const seamCalls = [];
  window.PadiemInboxOpener = {
    open: (kind, id) => { seamCalls.push({ handle: "inbox", kind, id }); return true; },
  };
  window.PadiemChatConversationOpener = {
    open: (id) => { seamCalls.push({ handle: "conversation", id }); return true; },
  };
  window.addEventListener("padiem:calendar-open-link", (event) => {
    const detail = event && event.detail ? event.detail : {};
    seamCalls.push({ handle: "linkback", kind: detail.kind, id: detail.targetId });
  });
  const recorder = makeFetch(spec.scripted);
  const document = makeDocument(bell, badge, loginButton);
  const sandbox = {
    console, Intl, Date, JSON, Math, RegExp, String, Number, Array, Object, Boolean, Promise,
    encodeURIComponent, URLSearchParams, TextEncoder, TextDecoder,
    CustomEvent, setImmediate,
    window, document, fetch: recorder.fetch,
  };
  vm.createContext(sandbox);
  vm.runInContext(MODULE_SOURCE, sandbox, { filename: "notification-inbox.js" });
  return { window, document, bell, badge, loginButton, calls: recorder.calls, seamCalls };
}

function read(ctx) {
  const panel = panelOf(ctx.document);
  const lists = panel ? select(panel, ".notification-inbox-list") : [];
  const statuses = panel ? select(panel, ".notification-inbox-status") : [];
  const groups = lists.map((list) => {
    const items = select(list, ".notification-inbox-item");
    const actions = select(list, ".notification-inbox-item-action");
    return {
      listId: list.id,
      count: items.length,
      texts: items.map((item) => item.textContent),
      buttons: actions.map((action) => action.textContent),
    };
  });
  return {
    bellHidden: ctx.bell.hidden,
    bellAriaLabel: ctx.bell.getAttribute("aria-label"),
    bellExpanded: ctx.bell.getAttribute("aria-expanded"),
    badgeHidden: ctx.badge.hidden,
    badgeText: ctx.badge.textContent,
    panelExists: panel ? true : false,
    panelHidden: panel ? panel.hidden : null,
    statusTexts: statuses.map((status) => status.textContent),
    retryHidden: select(panel, ".notification-inbox-action")[0] ? select(panel, ".notification-inbox-action")[0].hidden : null,
    groups,
    fetchCalls: ctx.calls,
    seamCalls: ctx.seamCalls,
  };
}

function panelOf(document) {
  const found = select(document.body, "#notificationInbox");
  return found.length ? found[0] : null;
}

function clickAlertAction(ctx, index) {
  const panel = panelOf(ctx.document);
  const lists = select(panel, ".notification-inbox-list");
  const actions = select(lists[0], ".notification-inbox-item-action");
  actions[index].click();
  return actions[index];
}

function allCallsInbox(ctx) {
  return ctx.calls.every((call) => call.url.startsWith("/api/claw/inbox/"));
}

async function main() {
  const results = [];

  {
    const ctx = run({ signedIn: true, scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    const seen = read(ctx);
    results.push({
      name: "SIGNED_IN_ENTRY",
      ok: seen.bellHidden === false && seen.badgeHidden === false && seen.badgeText === "2"
        && seen.bellExpanded === "false" && seen.panelExists && seen.panelHidden === true,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: false, scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    const seen = read(ctx);
    results.push({
      name: "GUEST_HIDDEN",
      ok: seen.bellHidden === true && seen.fetchCalls.length === 0,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    ctx.bell.click();
    await flush();
    const seen = read(ctx);
    const alerts = seen.groups[0];
    results.push({
      name: "OPEN_RENDERS_UNREAD_ONLY",
      ok: seen.panelHidden === false && alerts.count === 3 && alerts.texts.length === 3
        && seen.badgeText === "2"
        && alerts.texts.join("|").indexOf("읽지 않음") !== -1,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: EMPTY_ALERTS_FAILED_TASKS });
    await flush();
    ctx.bell.click();
    await flush();
    const seen = read(ctx);
    results.push({
      name: "EMPTY_VS_ERROR",
      ok: seen.statusTexts[0] === KO_EMPTY_ALERTS && seen.statusTexts[1] === KO_ERROR
        && seen.retryHidden === false && seen.groups.every((group) => group.count === 0),
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: MARK_READ_SCRIPT });
    await flush();
    ctx.bell.click();
    await flush();
    clickAlertAction(ctx, 1);
    await flush();
    const seen = read(ctx);
    const patches = seen.fetchCalls.filter((call) => call.method === "PATCH");
    let parsed = null;
    try { parsed = JSON.parse(patches[0] ? patches[0].body : ""); } catch (_) { parsed = null; }
    results.push({
      name: "MARK_READ_EXACT_CONTRACT",
      ok: patches.length === 1
        && patches[0].url === "/api/claw/inbox/alerts/alert_a"
        && JSON.stringify(parsed) === JSON.stringify({ status: "dismissed" })
        && JSON.stringify(patches[0].headers) === JSON.stringify({ Accept: "application/json", "Content-Type": "application/json" })
        && allCallsInbox(ctx),
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: MARK_READ_FAIL_SCRIPT });
    await flush();
    ctx.bell.click();
    await flush();
    clickAlertAction(ctx, 1);
    await flush();
    const seen = read(ctx);
    results.push({
      name: "MARK_READ_FAILURE_IS_TRUTHFUL",
      ok: seen.statusTexts[0] === KO_ERROR && seen.groups[0].count === 0,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    ctx.bell.click();
    await flush();
    clickAlertAction(ctx, 0);
    await flush();
    const seen = read(ctx);
    const opened = seen.seamCalls.find((call) => call.handle === "inbox");
    results.push({
      name: "RESULT_NAV_INBOX",
      ok: Boolean(opened) && opened.kind === "alerts" && opened.id === "alert_a" && seen.panelHidden === true,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: CONVERSATION_REF_SCRIPT });
    await flush();
    ctx.bell.click();
    await flush();
    clickAlertAction(ctx, 0);
    await flush();
    const seen = read(ctx);
    const conversation = seen.seamCalls.find((call) => call.handle === "conversation");
    const inbox = seen.seamCalls.find((call) => call.handle === "inbox");
    results.push({
      name: "RESULT_NAV_CONVERSATION",
      ok: Boolean(conversation) && conversation.id === CONVERSATION_ID && !inbox && seen.panelHidden === true,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: RUN_REF_SCRIPT });
    await flush();
    ctx.bell.click();
    await flush();
    clickAlertAction(ctx, 0);
    await flush();
    const seen = read(ctx);
    const linkback = seen.seamCalls.find((call) => call.handle === "linkback");
    const inbox = seen.seamCalls.find((call) => call.handle === "inbox");
    results.push({
      name: "RESULT_NAV_RUN",
      ok: Boolean(linkback) && linkback.kind === "run" && linkback.id === RUN_REF_ID && !inbox && seen.panelHidden === true,
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    ctx.bell.click();
    await flush();
    ctx.window.dispatchEvent(new CustomEvent("padiem:auth-state", { detail: { authenticated: false } }));
    await flush();
    const seen = read(ctx);
    results.push({
      name: "AUTH_LOSS_CLEARS",
      ok: seen.panelHidden === true && seen.badgeText === "" && seen.bellHidden === true
        && seen.groups.every((group) => group.count === 0),
      detail: seen,
    });
  }

  {
    const ctx = run({ signedIn: true, language: "en", scripted: ALERTS_TWO_ACTIVE_ONE_DISMISSED });
    await flush();
    ctx.bell.click();
    await flush();
    const seen = read(ctx);
    results.push({
      name: "LOCALE_EN",
      ok: seen.bellAriaLabel === "Notifications, 2 unread" && seen.statusTexts.length === 2
        && seen.statusTexts[0] === "",
      detail: seen,
    });
  }

  console.log(JSON.stringify(results));
}

main().catch((error) => {
  console.error(String((error && error.stack) || error));
  process.exit(1);
});
'''

HARNESS_PROLOGUE = "const LOCALES = " + json.dumps(LOCALES, ensure_ascii=False) + ";\n"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_index_declares_one_common_notification_entry() -> None:
    html = _read(INDEX_HTML)

    assert html.count('id="' + BELL_ID + '"') == 1, "the sidebar bell must be declared exactly once"
    line_match = re.search(
        r"^[^<]*<button[^>]*id=\"" + BELL_ID + r"\".*$",
        html,
        re.MULTILINE,
    )
    assert line_match, "the sidebar bell button is missing"
    bell = line_match.group(0)

    for required in (
        r'type="button"',
        r'\bhidden\b',
        r'aria-haspopup="dialog"',
        r'aria-expanded="false"',
        r'aria-controls="' + PANEL_ID + r'"',
        r'data-locale-key="notification-inbox-bell"',
        r'data-locale-aria-label="notification-inbox-bell"',
        r'data-locale-title="notification-inbox-bell"',
        'id="' + BADGE_ID + r'"',
    ):
        assert re.search(required, bell), (required, bell)

    group_match = re.search(
        r"<div class=\"sidebar-actions-row[^\"]*\"[^>]*role=\"group\"[^>]*>.*?</div>",
        html,
        re.DOTALL,
    )
    assert group_match, "the bell must live in the sidebar actions row"
    assert BELL_ID in group_match.group(0), "the bell is not inside the sidebar actions row"


def test_index_wires_the_module_once_after_the_app_shell() -> None:
    html = _read(INDEX_HTML)
    assert html.count('href="./notification-inbox.css"') == 1
    assert html.count('src="./notification-inbox.js"') == 1
    css_pos = html.index('href="./notification-inbox.css"')
    app_pos = html.index('src="./app.js"')
    module_pos = html.index('src="./notification-inbox.js"')
    assert css_pos < app_pos < module_pos


def test_locale_carries_every_key_in_both_languages() -> None:
    locale = _read(LOCALE_JS)
    for key in NEW_KEYS + REUSED_KEYS:
        hits = re.findall(r'["\']' + re.escape(key) + r'["\']\s*:\s*["\']([^"\']+)["\']', locale)
        assert len(hits) >= 2, f"{key} needs ko and en: {hits}"
        assert all(value.strip() for value in hits), f"{key} has an empty copy"
        assert all(value != key for value in hits), f"{key} is untranslated"


def test_module_copy_is_entirely_backed_by_locale_keys() -> None:
    locale = _read(LOCALE_JS)
    used = set(NEW_KEYS + REUSED_KEYS)
    used |= set(re.findall(r'text\("([^"]+)"', _read(MODULE_JS)))
    missing = sorted(key for key in used if f'"{key}":' not in locale)
    assert not missing, missing


def test_app_shell_exposes_only_a_read_only_inbox_seam() -> None:
    app = _read(APP_JS)
    seam = re.search(r"window\.PadiemInboxOpener = Object\.freeze\(\{(.*?)\}\);", app, re.DOTALL)
    assert seam, "the Claw inbox seam is missing"
    body = seam.group(1)
    assert "openClawInboxTarget" in body
    assert "!authState.authenticated" in body
    assert app.count("window.PadiemInboxOpener = Object.freeze(") == 1
    assert "fetch(" not in body, "the seam must not issue a request"


def test_cold_start_push_link_reuses_the_existing_run_target_once() -> None:
    """A push click can arrive before any view exists, so the URL carries it.

    The reference must be consumed only for a proven owner, exactly once, and it
    must open the run target the calendar link-back already owns instead of a
    second navigation authority.
    """
    app = _read(APP_JS)
    block = re.search(
        r"let pendingNotificationRunId = \"\";(.*?)openClawRunTarget\(notificationRunId\);",
        app,
        re.DOTALL,
    )
    assert block, "the Web Push cold-start link is missing"
    body = block.group(1)
    assert 'params.get("notify") === "run"' in body
    assert 'params.get("run_id")' in body
    assert "NOTIFICATION_RUN_REF.test(candidate)" in body
    assert "if (authenticated && pendingNotificationRunId)" in app
    assert "pendingNotificationRunId = \"\"" in body
    assert 'remaining.delete("notify")' in body and 'remaining.delete("run_id")' in body
    assert "window.history.replaceState" in body
    assert app.count("openClawRunTarget(notificationRunId)") == 1
    assert "window.PadiemNotification" not in app, "no second opener authority is allowed"
    assert "navigator.serviceWorker" not in app, "push registration stays in its own module"


def test_module_touches_only_the_existing_inbox_contract() -> None:
    module = _read(MODULE_JS)
    assert "/api/claw/inbox/alerts" in module
    assert "/api/claw/inbox/tasks" in module
    paths = sorted(set(re.findall(r"[/]api[A-Za-z0-9_.?/-]*", module)))
    unexpected = [path for path in paths if not path.startswith("/api/claw/inbox/")]
    assert not unexpected, unexpected
    assert "PATCH" in module
    assert "no-store" in module
    for forbidden in ("subscription", "serviceWorker", "PushManager", "requestPermission"):
        assert forbidden not in module, forbidden
    assert "fetch(" in module


def test_module_renders_server_text_without_html_injection() -> None:
    module = _read(MODULE_JS)
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert forbidden not in module, forbidden


def test_module_adds_no_polling_loop() -> None:
    module = _read(MODULE_JS)
    for forbidden in ("setInterval", "setTimeout"):
        assert forbidden not in module, forbidden
    assert module.count("addEventListener") >= 5


def test_module_honours_session_and_locale_boundaries() -> None:
    module = _read(MODULE_JS)
    for event in ("padiem:auth-state", "padiem:auth-changed", "padiem:account-changed", "padiem:localechange"):
        assert event in module, event
    for required in ("Escape", "aria-live", "aria-modal", "aria-expanded", "tabindex"):
        assert required in module, required


def test_css_reuses_the_glass_tokens_and_all_three_widths() -> None:
    css = _read(MODULE_CSS)
    for token in ("var(--glass", "var(--card-bg", "var(--accent", "var(--focus-ring", "var(--muted", "var(--line", "var(--text"):
        assert token in css, token
    for width in ("max-width: 620px", "min-width: 761px) and (max-width: 920px)", "min-width: 1440px"):
        assert width in css, width
    assert "prefers-reduced-motion" in css
    assert "44px" in css, "the 390px band keeps a 44px touch target"
    assert "[hidden]" in css, "hidden state is explicit"


def test_real_notification_inbox_node_behavior() -> None:
    if shutil.which("node") is None:
        pytest.skip("Node unavailable locally; required B62 Linux CI browser test")
    harness = Path(tempfile.mkdtemp(prefix="notification-inbox-")) / "harness.cjs"
    harness.write_text(HARNESS_PROLOGUE + _HARNESS, encoding="utf-8", newline="\n")
    result = subprocess.run(
        ["node", str(harness), str(MODULE_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = json.loads(result.stdout.strip().splitlines()[-1])
    assert not [case for case in cases if not case.get("ok")], json.dumps(
        [case for case in cases if not case.get("ok")], ensure_ascii=False, indent=2
    )
    assert {case["name"] for case in cases} == set(_CASES)
