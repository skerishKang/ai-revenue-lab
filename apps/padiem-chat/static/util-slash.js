/*
 * #7461 · Slash commands in the Chat composer ("/" suggests Util tools).
 *
 * File boundary: lives in static/util-slash.js (+ util-slash.css); app.js is
 * untouched (R5 #7216). The only interception point is the document capture
 * phase, so whenever this module does not act, the existing composer handlers
 * in app.js keep their exact flow (no preventDefault, no stopPropagation).
 *
 * Contract:
 * - The command list is read ONLY from window.PadiemUtilManifest
 *   (static/util-manifest.js): tool.slashCommand + tool.name/tool.desc.
 * - Acts on the Chat conversation screens only — the empty conversation
 *   (.app-shell[data-state="home"]) and an ongoing conversation
 *   (data-state="chat", set by chat-conversation-module/message-lifecycle);
 *   never on Claw ("claw"), Util, meeting or connectors states.
 * - Korean/CJK IME composition (event.isComposing or keyCode 229) is never
 *   intercepted: Enter and arrows pass through while composing; only the
 *   settled post-composition keydown is judged.
 * - Enter is intercepted only when the composer value is exactly a manifest
 *   "/명령", or when a suggestion row is picked from the open list (Enter on
 *   the highlighted row, click/tap on a row). Any other "/..." text or a
 *   plain Enter keeps the app.js flow untouched.
 * - Picking a command navigates to the tool's #util/<id>?mode=chat deep link,
 *   so auth, tier and usage keep each tool screen's existing path.
 */
(() => {
  "use strict";

  const COPY = Object.freeze({
    ko: Object.freeze({
      menuLabel: "유틸 단축 명령",
    }),
    en: Object.freeze({
      menuLabel: "Util slash commands",
    }),
  });

  const MENU_ID = "utilSlashMenu";
  // The Chat conversation surface owns two states: the empty conversation
  // ("home", app.js) and an ongoing conversation ("chat", set by
  // chat-conversation-module.js / message-lifecycle.js). Claw uses "claw".
  const CHAT_STATES = Object.freeze(["home", "chat"]);

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key) {
    const table = COPY[lang()] || COPY.ko;
    return table[key] !== undefined ? table[key] : COPY.ko[key];
  }

  function localized(entry) {
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[lang()] || entry.ko || "";
  }

  function shellState() {
    const shell = document.querySelector(".app-shell");
    return shell && shell.dataset ? String(shell.dataset.state || "") : "";
  }

  function isChatConversation() {
    return CHAT_STATES.indexOf(shellState()) >= 0;
  }

  // Commands come from the frozen manifest only, in manifest order.
  function commands() {
    const reg = window.PadiemUtilManifest;
    if (!reg || !Array.isArray(reg.TOOLS)) return [];
    const out = [];
    reg.TOOLS.forEach((tool) => {
      const command = tool && typeof tool.slashCommand === "string" ? tool.slashCommand.trim() : "";
      if (!command.startsWith("/")) return;
      out.push({
        id: String(tool.id || ""),
        command: command,
        title: localized(tool.name),
        desc: localized(tool.desc),
      });
    });
    return out;
  }

  // A slash query is "/" plus non-whitespace only: "…/ mid-sentence" or
  // "multi word" text never opens the menu and never matches a command.
  function isSlashQuery(value) {
    return /^\/\S*$/.test(String(value || ""));
  }

  function filterCommands(value, list) {
    const query = String(value || "").toLowerCase();
    if (!isSlashQuery(query) || query.length < 1) return [];
    return list.filter((item) => item.command.toLowerCase().startsWith(query));
  }

  function exactCommand(value, list) {
    const query = String(value || "").toLowerCase();
    if (!isSlashQuery(query)) return null;
    return list.find((item) => item.command.toLowerCase() === query) || null;
  }

  let menu = null;
  let input = null;
  let bound = false;
  let items = [];
  let activeIndex = -1;

  function ensureMenu() {
    if (menu && menu.isConnected) return menu;
    const host = document.getElementById("composerForm");
    if (!host) return null;
    menu = document.createElement("div");
    menu.className = "util-slash-menu";
    menu.id = MENU_ID;
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", t("menuLabel"));
    menu.hidden = true;
    // Selecting a suggestion must not blur the composer textarea: the row
    // reacts on pointerdown-kept focus and acts on the click that follows.
    menu.addEventListener("pointerdown", (event) => {
      if (typeof event.preventDefault === "function") event.preventDefault();
    });
    menu.addEventListener("click", (event) => {
      const row = event.target instanceof Element
        ? event.target.closest("[data-util-slash-index]")
        : null;
      if (!row) return;
      const index = Number(row.getAttribute("data-util-slash-index"));
      if (!Number.isInteger(index) || index < 0 || index >= items.length) return;
      pick(items[index]);
    });
    host.insertBefore(menu, host.firstChild);
    return menu;
  }

  function close() {
    items = [];
    activeIndex = -1;
    if (menu) {
      menu.hidden = true;
      menu.replaceChildren();
    }
    if (input) {
      input.removeAttribute("aria-controls");
      input.setAttribute("aria-expanded", "false");
    }
  }

  function setActive(index) {
    if (!menu || !items.length) return;
    activeIndex = (index + items.length) % items.length;
    Array.prototype.forEach.call(menu.children, (row, i) => {
      const selected = i === activeIndex;
      row.setAttribute("aria-selected", selected ? "true" : "false");
      row.classList.toggle("is-active", selected);
    });
    const active = menu.children[activeIndex];
    if (active && typeof active.scrollIntoView === "function") {
      active.scrollIntoView({ block: "nearest" });
    }
  }

  function render(list) {
    const host = ensureMenu();
    if (!host || !input) return;
    items = list;
    activeIndex = list.length ? 0 : -1;
    host.replaceChildren();
    if (!list.length) {
      close();
      return;
    }
    list.forEach((item, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "util-slash-item";
      row.setAttribute("role", "option");
      row.tabIndex = -1;
      row.setAttribute("data-util-slash-index", String(index));
      row.setAttribute("aria-selected", index === activeIndex ? "true" : "false");
      row.classList.toggle("is-active", index === activeIndex);
      row.title = item.desc;
      const command = document.createElement("span");
      command.className = "util-slash-item-command";
      command.textContent = item.command;
      const title = document.createElement("span");
      title.className = "util-slash-item-title";
      title.textContent = item.title;
      const desc = document.createElement("span");
      desc.className = "util-slash-item-desc";
      desc.textContent = item.desc;
      row.appendChild(command);
      row.appendChild(title);
      row.appendChild(desc);
      host.appendChild(row);
    });
    host.hidden = false;
    host.setAttribute("aria-label", t("menuLabel"));
    input.setAttribute("aria-controls", host.id);
    input.setAttribute("aria-expanded", "true");
  }

  function refresh() {
    if (!input || !input.isConnected) return;
    if (!isChatConversation()) {
      close();
      return;
    }
    const list = filterCommands(input.value, commands());
    if (!list.length) {
      close();
      return;
    }
    const previous = activeIndex >= 0 && activeIndex < items.length ? items[activeIndex].id : null;
    render(list);
    if (previous) {
      const found = list.findIndex((item) => item.id === previous);
      if (found >= 0) setActive(found);
    }
  }

  function openToolChat(item) {
    const reg = window.PadiemUtilManifest;
    if (!reg || typeof reg.toolHref !== "function" || !reg.getTool || !reg.getTool(item.id)) {
      return false;
    }
    if (input) input.value = "";
    close();
    window.location.hash = reg.toolHref(item.id) + "?mode=chat";
    return true;
  }

  function pick(item) {
    if (!item) return;
    openToolChat(item);
  }

  function onKeyDownCapture(event) {
    if (!event || !input || event.target !== input || !input.isConnected) return;
    if (!isChatConversation()) {
      if (items.length) close();
      return;
    }
    // Korean/CJK composition in flight (isComposing, or the engines that only
    // emit keyCode 229): Enter and arrows belong to the IME. Never intercept.
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter") {
      if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
      const exact = exactCommand(input.value, commands());
      if (exact) {
        event.preventDefault();
        event.stopPropagation();
        openToolChat(exact);
        return;
      }
      if (items.length && activeIndex >= 0 && items[activeIndex]) {
        // Picking the highlighted row of the open suggestion list.
        event.preventDefault();
        event.stopPropagation();
        openToolChat(items[activeIndex]);
        return;
      }
      return; // plain Enter or an unmatched "/..." → app.js flow untouched
    }
    if (!items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(activeIndex + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(activeIndex - 1);
      return;
    }
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key === "Tab") close();
  }

  function bind() {
    if (bound) return;
    const form = document.getElementById("composerForm");
    const node = document.getElementById("messageInput");
    if (!form || !node) return;
    bound = true;
    input = node;
    input.setAttribute("aria-expanded", "false");
    document.addEventListener("keydown", onKeyDownCapture, true);
    input.addEventListener("input", refresh);
    input.addEventListener("focus", refresh);
    input.addEventListener("blur", close);
    // The composer is shared across Chat/Claw; the menu must not survive a
    // screen switch (Chat → Claw → Chat).
    const shell = document.querySelector(".app-shell");
    if (shell && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (!isChatConversation()) close();
      }).observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    }
    window.addEventListener("padiem:localechange", () => {
      if (items.length) refresh();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind, { once: true });
  } else {
    bind();
  }

  window.PadiemUtilSlash = Object.freeze({
    refresh: refresh,
    close: close,
    commands: commands,
  });
})();
