/* #7975 — mark a connected PC whose last user-mode command could not run.

   The pairing card (pc-pairing-card.js) owns the device rows and stays at its
   995-line cap. This module only annotates the rows it renders: it reads the
   same /api/pc/pairings answer, matches rows in the card's shown order, and
   adds a plain-language badge plus a one-line remedy for links the server
   reports as command_ready: "not_ready". A link with no history stays
   "연결됨" — there is no evidence to warn about. */
(function () {
  "use strict";

  var PAIRINGS = "/api/pc/pairings";
  var SECTION_ID = "pcPairingSection";
  var COPY = {
    ko: {
      badge: "연결됨 · 명령 준비 안 됨",
      help: "이 PC 에 Windows 로 로그인돼 있는지 확인하고, PC 도우미를 다시 설치해 주세요."
    },
    en: {
      badge: "Connected · commands not ready",
      help: "Check that Windows is signed in on this PC, then reinstall the PC helper."
    }
  };

  var lastBody = null;
  var painting = false;
  var observer = null;
  var resizeObserver = null;
  var lastRowCount = -1;

  function copy() {
    var shared = window.__padiemLocale;
    var lang = shared && typeof shared.getCurrent === "function" ? shared.getCurrent() : "ko";
    return COPY[lang] || COPY.ko;
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
    if (!name || !badge || row.dataset.commandReady !== "not_ready") return;
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

  function rowCount() {
    var section = document.getElementById(SECTION_ID);
    return section ? section.querySelectorAll("ul.pc-pairing-list > li.pc-pairing-link").length : -1;
  }

  function paint(body) {
    if (painting) return;
    painting = true;
    if (observer) observer.disconnect();
    try {
      paintRows(body);
    } finally {
      lastRowCount = rowCount();
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
      if (!link || link.command_ready !== "not_ready") {
        clear(row);
        continue;
      }
      if (row.dataset.commandReady !== "not_ready") row.dataset.commandReady = "not_ready";
      var badge = row.querySelector(".pc-pairing-state");
      if (badge) {
        if (badge.dataset.commandReadyOwner !== "1") {
          badge.dataset.previousText = badge.textContent;
          badge.dataset.previousState = badge.dataset.state || "";
          badge.dataset.commandReadyOwner = "1";
        }
        if (badge.textContent !== t.badge) badge.textContent = t.badge;
        // Reuse the existing muted state style: no new CSS rule or colour literal.
        if (badge.dataset.state !== "offline") badge.dataset.state = "offline";
      }
      fitName(row);
      notices.push(element("p", "pc-pairing-help", (link.label || "") + ": " + t.help));
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

  async function refresh() {
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

  function watch() {
    var section = document.getElementById(SECTION_ID);
    if (!section || typeof MutationObserver === "undefined") return;
    observer = new MutationObserver(function () {
      if (!lastBody || rowCount() === lastRowCount) return;
      paint(lastBody);
    });
    observer.observe(section, { childList: true, subtree: true });
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(function () {
        var rows = section.querySelectorAll('li.pc-pairing-link[data-command-ready="not_ready"]');
        for (var i = 0; i < rows.length; i++) fitName(rows[i]);
      });
      resizeObserver.observe(section);
    }
  }

  function start() {
    watch();
    refresh();
    window.addEventListener("padiem:pc-pairing-state", refresh);
    window.addEventListener("padiem:auth-state", refresh);
    window.addEventListener("padiem:localechange", refresh);
    return { refresh: refresh, paint: paint };
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
