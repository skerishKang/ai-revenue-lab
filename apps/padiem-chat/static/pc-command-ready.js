/* #7975, #7987 — say whether a connected PC can take a command.

   The pairing card (pc-pairing-card.js) owns the device rows and stays at its
   995-line cap. This module only annotates the rows it renders: it reads the
   same /api/pc/pairings answer and matches rows in the card's shown order.

   The server reports what the PC itself last said (#7987), in three words:
     command_ready "ready"     -> 연결됨 · 명령 가능
     command_ready "not_ready" -> 연결됨 · 명령 준비 안 됨, plus a one-line remedy
     command_ready "unknown"   -> the card's own "연결됨", untouched
   Only a PC that is connected now is annotated; with no evidence there is
   nothing to claim and nothing to warn about. */
(function () {
  "use strict";

  var PAIRINGS = "/api/pc/pairings";
  var SECTION_ID = "pcPairingSection";
  // #8003's "ready" copy stays local by Owner decision. The two #7990
  // strings (badge/help) live in the PC-connect locale group via uiT.
  var COPY = {
    ko: { ready: "연결됨 · 명령 가능" },
    en: { ready: "Connected · commands ready" }
  };

  var lastBody = null;
  var painting = false;
  var observer = null;
  var resizeObserver = null;
  var refreshTimer = null;

  function copy() {
    var shared = window.__padiemLocale;
    var lang = shared && typeof shared.getCurrent === "function" ? shared.getCurrent() : "ko";
    return COPY[lang] || COPY.ko;
  }

  function t(key) {
    var ctx = window.PadiemChatAppContext;
    if (ctx && typeof ctx.uiT === "function") return ctx.uiT(key);
    var shared = window.__padiemLocale;
    if (shared && typeof shared.text === "function") return shared.text(key);
    return key;
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function shownLinks(body) {
    var links = body && Array.isArray(body.links) ? body.links : [];
    // The card hides revoked and replaced links before it draws rows. Keep the
    // same order and filter so a badge can be matched to the right row.
    return links.filter(function (link) {
      return link && link.state !== "revoked" && link.state !== "replaced";
    });
  }

  function fitName(row) {
    var name = row.querySelector(".pc-pairing-name");
    var badge = row.querySelector(".pc-pairing-state");
    // Both annotated badges are longer than the card's own "연결됨".
    if (!name || !badge || !row.dataset.commandReady) return;
    var width = row.getBoundingClientRect().width;
    if (width <= 0) return;
    // A hidden card reports zero width, so decide from the real row width as
    // well as measured overflow: a narrow card puts the badge below the name,
    // a wide card keeps the original single line.
    var clipped = name.scrollWidth > name.clientWidth;
    if (clipped || width < 300) {
      row.style.flexWrap = "wrap";
      name.style.flex = "0 0 100%";
      badge.style.marginLeft = "0";
    } else {
      row.style.flexWrap = "";
      name.style.flex = "";
      badge.style.marginLeft = "";
    }
  }

  function clear(row) {
    if (row.dataset.commandReady) row.dataset.commandReady = "";
    row.style.flexWrap = "";
    var name = row.querySelector(".pc-pairing-name");
    if (name) name.style.flex = "";
    var badge = row.querySelector(".pc-pairing-state");
    if (badge) {
      badge.style.marginLeft = "";
      if (badge.dataset.commandReadyOwner === "1") {
        badge.textContent = badge.dataset.previousText || "";
        badge.dataset.state = badge.dataset.previousState || "";
        delete badge.dataset.commandReadyOwner;
        delete badge.dataset.previousText;
        delete badge.dataset.previousState;
      }
    }
  }

  function clearHelp(section) {
    var helps = section.querySelectorAll('[data-pc-command-ready="1"]');
    for (var i = 0; i < helps.length; i++) helps[i].remove();
  }

  function wanted(link) {
    // Only a PC that is connected now can be ready or not ready (#7987).
    var state = link && link.online === true ? link.command_ready : "unknown";
    if (state !== "not_ready" && state !== "ready") return "";
    return state;
  }

  function stale(body) {
    // The card redraws its rows on its own schedule (after every action, when
    // the dialog opens, when the tab comes back). A redrawn row has lost its
    // annotation even though the row count is the same.
    var section = document.getElementById(SECTION_ID);
    if (!section) return false;
    var rows = section.querySelectorAll("ul.pc-pairing-list > li.pc-pairing-link");
    var expected = shownLinks(body);
    var helps = 0;
    for (var i = 0; i < rows.length; i++) {
      var state = wanted(expected[i]);
      if ((rows[i].dataset.commandReady || "") !== state) return true;
      if (state === "not_ready") helps++;
    }
    return section.querySelectorAll('[data-pc-command-ready="1"]').length !== helps;
  }

  function paint(body) {
    if (painting) return;
    painting = true;
    if (observer) observer.disconnect();
    try {
      paintRows(body);
    } finally {
      painting = false;
      if (observer) {
        var section = document.getElementById(SECTION_ID);
        if (section) observer.observe(section, { childList: true, subtree: true });
      }
    }
  }

  function paintRows(body) {
    var section = document.getElementById(SECTION_ID);
    if (!section) return;
    var rows = section.querySelectorAll("ul.pc-pairing-list > li.pc-pairing-link");
    var expected = shownLinks(body);
    var t = copy();
    var notices = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var link = expected[i];
      var state = wanted(link);
      if (!state) {
        clear(row);
        continue;
      }
      if (row.dataset.commandReady !== state) row.dataset.commandReady = state;
      var badge = row.querySelector(".pc-pairing-state");
      if (badge) {
        if (badge.dataset.commandReadyOwner !== "1") {
          badge.dataset.previousText = badge.textContent;
          badge.dataset.previousState = badge.dataset.state || "";
          badge.dataset.commandReadyOwner = "1";
        }
        var text = state === "ready" ? copy().ready : t("pc-command-ready-badge");
        if (badge.textContent !== text) badge.textContent = text;
        if (state === "ready") {
          // Ready keeps the colour the card itself gave a connected PC.
          var own = badge.dataset.previousState || "";
          if (badge.dataset.state !== own) badge.dataset.state = own;
        } else {
          // Reuse the existing muted state style: no new CSS rule or colour literal.
          if (badge.dataset.state !== "offline") badge.dataset.state = "offline";
        }
      }
      fitName(row);
      if (state === "not_ready") {
        notices.push(element("p", "pc-pairing-help", (link.label || "") + ": " + t("pc-command-ready-help")));
      }
    }
    clearHelp(section);
    var list = section.querySelector("ul.pc-pairing-list");
    if (list && notices.length) {
      for (var n = 0; n < notices.length; n++) {
        notices[n].dataset.pcCommandReady = "1";
        list.insertAdjacentElement("afterend", notices[n]);
      }
    }
  }

  function adopt(links) {
    lastBody = { links: links };
    paint(lastBody);
  }

  function fromFlow() {
    // The connect flow keeps the list it last read; take it when it has one.
    var flow = window.PadiemPcConnectFlow;
    var now = flow && typeof flow.current === "function" ? flow.current() : null;
    if (!now || now.read !== "ok" || !Array.isArray(now.links)) return false;
    adopt(now.links);
    return true;
  }

  async function refresh(fresh) {
    // The connect flow owns the one shared read of this list (#7073): asking
    // it joins a read that is already open or reuses the answer it just got,
    // and its state event carries the links here. This module never adds a
    // read of its own to the first screen. `fresh` asks for the server's
    // current answer, for when the card has just redrawn its rows.
    var flow = window.PadiemPcConnectFlow;
    var ask = flow && (fresh === true ? flow.refresh : flow.read);
    if (typeof ask === "function") {
      try {
        await ask();
      } catch (_) {
        return;
      }
      fromFlow();
      return;
    }
    try {
      var response = await fetch(PAIRINGS, {
        credentials: "same-origin", headers: { Accept: "application/json" }
      });
      if (!response.ok) return;
      var payload = await response.json();
      lastBody = payload && payload.body ? payload.body : payload;
      paint(lastBody);
    } catch (_) {
      // A failed read is not evidence of a helper problem. Leave rows alone.
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(function () {
      refreshTimer = null;
      refresh(true);
    }, 200);
  }

  function watch() {
    var section = document.getElementById(SECTION_ID);
    if (!section || typeof MutationObserver === "undefined") return;
    observer = new MutationObserver(function () {
      if (!lastBody || painting || !stale(lastBody)) return;
      // Put the last known words back at once, then read the list again so a
      // helper that came up or went away while the card was closed is shown.
      // Painting is done with the observer disconnected, so this cannot loop.
      paint(lastBody);
      scheduleRefresh();
    });
    observer.observe(section, { childList: true, subtree: true });
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(function () {
        var rows = section.querySelectorAll(
          'li.pc-pairing-link[data-command-ready="not_ready"], li.pc-pairing-link[data-command-ready="ready"]');
        for (var i = 0; i < rows.length; i++) fitName(rows[i]);
      });
      resizeObserver.observe(section);
    }
  }

  function start() {
    watch();
    // Nothing is read here. The connect flow reads the list once for the first
    // screen and after every sign-in change, and announces each answer.
    fromFlow();
    window.addEventListener("padiem:pc-pairing-state", function (event) {
      var detail = event && event.detail ? event.detail : null;
      // A read that failed is not evidence about any PC: rows are left alone.
      if (detail && detail.read === "ok" && Array.isArray(detail.links)) adopt(detail.links);
    });
    window.addEventListener("padiem:localechange", function () {
      if (lastBody) paint(lastBody);
    });
    return { refresh: function () { return refresh(false); }, paint: paint };
  }

  function boot() {
    window.padiemPcCommandReady = start();
  }
  window.__pcReadyBoot = document.readyState;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
