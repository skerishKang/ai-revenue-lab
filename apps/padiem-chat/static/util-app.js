/*
 * #7460 · Util app shell, hash routing, first-screen card list & tool screens.
 *
 * File boundary: all Util behaviour lives in static/util-*.js and util-*.css.
 * app.js only exposes window.PadiemAppSwitch (openChat / openClaw) and gains
 * no Util logic (R5 #7216).
 *
 * Single manifest: cards, tool-screen chips and the sidebar submenu all render
 * from window.PadiemUtilManifest (static/util-manifest.js).
 *
 * Routes (hash):
 *   #util          → first screen (card list; big "Padiem Util / 유틸" header shown)
 *   #util/<id>     → dedicated tool screen (big Util header hidden; "‹ 유틸" back
 *                    link + tool big title + 1-line desc + tool chip bar +
 *                    PC left-input / right-result, Phone top / bottom)
 * Legacy #util-<id>, #util/claw-quote, #util/claw-excel and #util?tool=<id>
 * bookmarks resolve cleanly to the canonical #util/<id> route.
 */
(() => {
  "use strict";

  const LEGACY_TOOL_ALIASES = Object.freeze({
    "claw-quote": "quote",
    "claw-excel": "excel",
  });

  function manifest() {
    return window.PadiemUtilManifest || null;
  }

  function routePrefix() {
    const reg = manifest();
    return reg && reg.ROUTE_PREFIX ? reg.ROUTE_PREFIX : "#util";
  }

  function tools() {
    const reg = manifest();
    return reg && Array.isArray(reg.TOOLS) ? reg.TOOLS : [];
  }

  function toolIds() {
    const reg = manifest();
    return reg && Array.isArray(reg.TOOL_IDS) ? reg.TOOL_IDS : [];
  }

  function getTool(id) {
    const reg = manifest();
    return reg && typeof reg.getTool === "function" ? reg.getTool(id) : null;
  }

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function copy(tool) {
    const locale = lang();
    return (tool && tool[locale]) || (tool && tool.ko) || { title: "", chip: "", desc: "" };
  }

  function listHref() {
    const reg = manifest();
    return reg && typeof reg.listHref === "function" ? reg.listHref() : routePrefix();
  }

  function toolHref(id) {
    const reg = manifest();
    return reg && typeof reg.toolHref === "function" ? reg.toolHref(id) : routePrefix() + "/" + id;
  }

  function resolveCandidateId(rawId) {
    const cleaned = String(rawId || "").trim().replace(/\/+$/, "");
    if (!cleaned) return null;
    const mapped = LEGACY_TOOL_ALIASES[cleaned] || cleaned;
    return getTool(mapped) ? mapped : null;
  }

  function parseHash(hash) {
    const prefix = routePrefix();
    const value = String(hash || "");
    if (!value.startsWith(prefix)) return null;
    const rest = value.slice(prefix.length);
    if (rest === "" || rest === "/") return { screen: "list" };
    if (rest.startsWith("/")) {
      const qIndex = rest.indexOf("?");
      const rawPath = qIndex >= 0 ? rest.slice(1, qIndex) : rest.slice(1);
      const queryPart = qIndex >= 0 ? rest.slice(qIndex) : "";
      const id = resolveCandidateId(rawPath);
      if (!id) return { screen: "invalid" };
      const modeMatch = /(?:^\?|&)mode=(form|chat)(?:&|$)/i.exec(queryPart);
      const mode = modeMatch ? modeMatch[1].toLowerCase() : null;
      const canonical = toolHref(id);
      const alias = queryPart === "" && value !== canonical;
      return { screen: "tool", id: id, mode: mode, canonical: canonical, alias: alias };
    }
    if (rest.startsWith("-")) {
      const id = resolveCandidateId(rest.slice(1));
      return id
        ? { screen: "tool", id: id, canonical: toolHref(id), alias: true }
        : { screen: "invalid" };
    }
    if (rest.startsWith("?")) {
      const match = /(?:^\?|&)tool=([a-z0-9_-]+)/i.exec(rest);
      const id = match ? resolveCandidateId(match[1]) : null;
      return id
        ? { screen: "tool", id: id, canonical: toolHref(id), alias: true }
        : { screen: "invalid" };
    }
    return null;
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function buildCard(tool) {
    const text = copy(tool);
    const item = element("li", "util-card-item");
    const button = element("button", "util-card");
    button.type = "button";
    button.setAttribute("data-util-route", toolHref(tool.id));
    button.setAttribute("data-util-card", tool.id);
    button.setAttribute("aria-label", text.title + " — " + text.desc);
    const icon = element("span", "util-card-icon", tool.icon);
    icon.setAttribute("aria-hidden", "true");
    const cta = element("span", "util-card-cta", "→");
    cta.setAttribute("aria-hidden", "true");
    button.appendChild(icon);
    button.appendChild(element("span", "util-card-title", text.title));
    button.appendChild(element("span", "util-card-desc", text.desc));
    button.appendChild(cta);
    item.appendChild(button);
    return item;
  }

  function renderList() {
    const list = element("ul", "util-card-grid");
    list.setAttribute("aria-label", lang() === "en" ? "Util tools" : "유틸 도구");
    tools().forEach((tool) => list.appendChild(buildCard(tool)));
    return list;
  }

  function renderChips(activeId) {
    const bar = element("nav", "util-tool-chips");
    bar.setAttribute("aria-label", lang() === "en" ? "Switch util tool" : "유틸 도구 전환");
    tools().forEach((tool) => {
      const text = copy(tool);
      const chip = element("button", "util-tool-chip", text.chip || text.title);
      chip.type = "button";
      chip.setAttribute("data-util-chip", tool.id);
      chip.setAttribute("data-util-route", toolHref(tool.id));
      chip.setAttribute("aria-current", tool.id === activeId ? "page" : "false");
      bar.appendChild(chip);
    });
    return bar;
  }

  function buildPendingWorkbench(tool) {
    const locale = lang();
    const wrap = element("div", "util-tool-workbench");
    wrap.setAttribute("data-util-form", tool.id);

    const inputPane = element("div", "util-pane-input");
    inputPane.setAttribute("data-util-pane", "input");
    const formBox = element("div", "util-form");
    (tool.fields || []).forEach((fieldSpec) => {
      const label = element("label", "util-field");
      const labelCopy = (fieldSpec.label && (fieldSpec.label[locale] || fieldSpec.label.ko)) || fieldSpec.key;
      label.appendChild(element("span", "util-field-label", labelCopy));
      let control;
      if (fieldSpec.type === "textarea") {
        control = element("textarea", "util-input");
        control.rows = fieldSpec.rows || 3;
      } else {
        control = element("input", "util-input");
        control.type = fieldSpec.type === "file" ? "file" : "text";
        if (fieldSpec.accept) control.accept = fieldSpec.accept;
      }
      control.disabled = true;
      const placeholderCopy = fieldSpec.placeholder && (fieldSpec.placeholder[locale] || fieldSpec.placeholder.ko);
      if (placeholderCopy && fieldSpec.type !== "file") control.placeholder = placeholderCopy;
      label.appendChild(control);
      formBox.appendChild(label);
    });
    const noteText = locale === "en"
      ? "Dedicated workbook open & review backend is being connected. Input and review results appear side by side here."
      : "전용 백엔드 연결을 준비 중입니다. 연결 후 이 화면에서 XLSX 원본 선택과 검토 결과를 바로 다룹니다.";
    formBox.appendChild(element("p", "util-tool-placeholder", noteText));
    inputPane.appendChild(formBox);

    const resultPane = element("section", "util-result util-pane-result");
    resultPane.setAttribute("data-util-pane", "result");
    resultPane.appendChild(element("h4", "util-result-title", locale === "en" ? "Review output" : "검토 결과"));
    const output = element("div", "util-result-output");
    output.setAttribute("data-empty", "true");
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", locale === "en" ? "Review output" : "검토 결과");
    output.textContent = locale === "en"
      ? "Sheet summary, formula checks and cell review notes will appear here."
      : "파일을 열면 시트 요약·수식 점검·검토 메모가 이 결과 칸에 표시됩니다.";
    resultPane.appendChild(output);

    wrap.appendChild(inputPane);
    wrap.appendChild(resultPane);
    return wrap;
  }

  function mountPdfmdPanel(body) {
    const panel = element("div", "util-panel");
    panel.id = "utilPdfmdPanel";
    body.setAttribute("data-util-mounted", "pdfmd");
    body.appendChild(panel);
    if (typeof window.initPdfMdUtility === "function") {
      try { window.initPdfMdUtility(panel); } catch (_) { /* the panel keeps its first paint */ }
    }
    return panel;
  }

  function renderTool(id, initialMode) {
    const tool = getTool(id);
    if (!tool) return null;
    const text = copy(tool);
    const screen = element("div", "util-tool-screen");
    screen.setAttribute("data-util-tool", tool.id);

    const header = element("header", "standalone-view-header util-tool-header");
    const headerGroup = element("div", "util-tool-header-group");
    const back = element("a", "util-tool-back");
    back.setAttribute("href", listHref());
    const chevron = element("span", "util-tool-back-mark", "‹");
    chevron.setAttribute("aria-hidden", "true");
    back.appendChild(chevron);
    back.appendChild(document.createTextNode(" "));
    back.appendChild(element("span", null, lang() === "en" ? "Util" : "유틸"));

    const heading = element("h2", "standalone-view-title util-tool-heading", text.title);
    heading.id = "utilToolHeading";
    heading.setAttribute("tabindex", "-1");
    const desc = element("p", "standalone-view-tagline util-tool-desc", text.desc);

    headerGroup.appendChild(back);
    headerGroup.appendChild(heading);
    headerGroup.appendChild(desc);
    header.appendChild(headerGroup);

    const chips = renderChips(tool.id);

    const body = element("div", "util-tool-body");
    body.setAttribute("role", "region");
    body.setAttribute("aria-labelledby", "utilToolHeading");
    if (initialMode === "chat" || initialMode === "form") {
      body.setAttribute("data-util-initial-mode", initialMode);
    }
    if (tool.id === "pdfmd") {
      mountPdfmdPanel(body);
    } else {
      const quoteMounted = tool.id === "quote"
        && Boolean(
          window.PadiemUtilQuote
          && typeof window.PadiemUtilQuote.mount === "function"
          && window.PadiemUtilQuote.mount(body)
        );
      // #7500: the Excel screen mounts its own dedicated review module
      // (util-excel.js) instead of the pending workbench placeholder.
      const excelMounted = tool.id === "excel"
        && Boolean(
          window.PadiemUtilExcel
          && typeof window.PadiemUtilExcel.mount === "function"
          && window.PadiemUtilExcel.mount(body)
        );
      const mounted = (quoteMounted || excelMounted) || Boolean(
        window.PadiemUtilTools
        && typeof window.PadiemUtilTools.mount === "function"
        && window.PadiemUtilTools.mount(tool.id, body)
      );
      if (!mounted) {
        body.setAttribute("data-util-mounted", "form");
        body.appendChild(buildPendingWorkbench(tool));
      }
    }

    screen.appendChild(header);
    screen.appendChild(chips);
    screen.appendChild(body);
    return screen;
  }

  const els = {};
  let bound = false;
  let firstRoute = true;

  function meetingCaptureEntry() {
    return document.getElementById("meetingNavButton");
  }

  function parkMeetingCaptureEntry() {
    const entry = meetingCaptureEntry();
    const host = document.getElementById("meetingCaptureHost");
    if (!entry) return;
    if (host && entry.parentElement !== host) host.appendChild(entry);
  }

  function mountMeetingCaptureEntry() {
    const entry = meetingCaptureEntry();
    const body = els.root ? els.root.querySelector(".util-tool-body") : null;
    if (!entry || !body) return;
    body.appendChild(entry);
  }

  function utilVisible() {
    return Boolean(els.shell && els.shell.dataset.state === "util");
  }

  function syncSidebar() {
    ["newChatButton", "clawNavButton"].forEach((id) => {
      const button = document.getElementById(id);
      if (button) button.setAttribute("aria-current", "false");
    });
    const utilNav = document.getElementById("utilNavButton");
    if (utilNav) utilNav.setAttribute("aria-current", "page");
  }

  function setFirstScreenHeaderVisible(visible) {
    if (els.utilHeader) els.utilHeader.hidden = !visible;
    if (els.utilView) {
      els.utilView.dataset.utilScreen = visible ? "list" : "tool";
      els.utilView.setAttribute("aria-labelledby", visible ? "utilTitle" : "utilToolHeading");
    }
  }

  function showUtilShell() {
    if (!els.shell) return;
    els.shell.dataset.state = "util";
    if (els.utilView) els.utilView.hidden = false;
    syncSidebar();
  }

  function hideUtilShell() {
    parkMeetingCaptureEntry();
    setFirstScreenHeaderVisible(true);
    if (els.utilView) els.utilView.hidden = true;
  }

  function setUtilHeading(langValue) {
    if (els.utilTitle) els.utilTitle.textContent = langValue === "en" ? "Util" : "유틸";
    if (els.utilKicker) els.utilKicker.textContent = "Padiem Util";
    if (els.utilTagline) {
      els.utilTagline.textContent = langValue === "en"
        ? "Everyday document & promo tools"
        : "자주 쓰는 문서·홍보 도구 모음";
    }
  }

  function replaceHashSilently(nextHash) {
    try {
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname + window.location.search + (nextHash || "")
      );
    } catch (_) { /* sandboxed history never blocks rendering */ }
  }

  function notifyRoute(parsed) {
    if (typeof CustomEvent !== "function" || typeof window.dispatchEvent !== "function") return;
    try {
      window.dispatchEvent(new CustomEvent("padiem:util-route", { detail: parsed }));
    } catch (_) { /* optional notification */ }
  }

  function renderRoute(options) {
    const opts = options || {};
    const parsed = parseHash(window.location.hash);
    if (!parsed) return false;
    showUtilShell();
    setUtilHeading(lang());
    if (parsed.screen === "invalid") {
      replaceHashSilently(listHref());
      if (!els.root) return false;
      parkMeetingCaptureEntry();
      setFirstScreenHeaderVisible(true);
      els.root.replaceChildren(renderList());
      notifyRoute({ screen: "list" });
      return true;
    }
    if (!els.root) return false;
    parkMeetingCaptureEntry();
    if (parsed.screen === "list") {
      setFirstScreenHeaderVisible(true);
      els.root.replaceChildren(renderList());
      if (opts.focus && els.utilTitle && typeof els.utilTitle.focus === "function") {
        els.utilTitle.setAttribute("tabindex", "-1");
        els.utilTitle.focus({ preventScroll: true });
      }
      notifyRoute(parsed);
      return true;
    }
    if (parsed.alias && parsed.canonical) {
      replaceHashSilently(parsed.canonical);
    }
    setFirstScreenHeaderVisible(false);
    const markup = renderTool(parsed.id, parsed.mode);
    if (!markup) return false;
    els.root.replaceChildren(markup);
    if (parsed.id === "meeting") mountMeetingCaptureEntry();
    if (opts.focus) {
      const heading = document.getElementById("utilToolHeading");
      if (heading && typeof heading.focus === "function") heading.focus({ preventScroll: true });
    }
    notifyRoute(parsed);
    return true;
  }

  function navigate(hash) {
    const target = String(hash || "");
    if (String(window.location.hash || "") === target) {
      renderRoute({ focus: false });
      return;
    }
    window.location.hash = target;
  }

  function onHashChange() {
    const hash = String(window.location.hash || "");
    if (parseHash(hash)) {
      renderRoute({ focus: !firstRoute });
      firstRoute = false;
      return;
    }
    if (hash === "#claw" || hash === "#padiem-claw") {
      hideUtilShell();
      if (window.PadiemAppSwitch && window.PadiemAppSwitch.openClaw) window.PadiemAppSwitch.openClaw();
      return;
    }
    if (utilVisible()) {
      hideUtilShell();
      if (!hash && window.PadiemAppSwitch && window.PadiemAppSwitch.openChat) {
        window.PadiemAppSwitch.openChat();
      }
    }
  }

  function bind() {
    if (bound) return;
    bound = true;
    els.root = document.getElementById("utilAppRoot");
    els.utilView = document.getElementById("utilView");
    els.utilHeader = els.utilView && typeof els.utilView.querySelector === "function"
      ? els.utilView.querySelector(".util-header")
      : null;
    els.shell = document.querySelector(".app-shell");
    els.utilTitle = document.getElementById("utilTitle");
    els.utilKicker = document.getElementById("utilKicker");
    els.utilTagline = document.getElementById("utilTagline");
    if (els.root) {
      els.root.addEventListener("click", (event) => {
        const target = event.target && typeof event.target.closest === "function"
          ? event.target.closest("[data-util-route]")
          : null;
        if (!target) return;
        event.preventDefault();
        navigate(target.getAttribute("data-util-route"));
      });
    }
    if (els.shell && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (els.shell.dataset.state !== "util" && els.utilView && !els.utilView.hidden) {
          hideUtilShell();
          if (parseHash(window.location.hash)) {
            replaceHashSilently("");
          }
        }
      }).observe(els.shell, { attributes: true, attributeFilter: ["data-state"] });
    }
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("padiem:localechange", () => {
      if (parseHash(window.location.hash)) renderRoute({ focus: false });
    });
  }

  function boot() {
    bind();
    if (!els.root) return;
    if (parseHash(window.location.hash)) {
      renderRoute({ focus: false });
      firstRoute = false;
    }
    window.PadiemUtilApp = Object.freeze({
      ROUTE_PREFIX: routePrefix(),
      TOOL_IDS: toolIds(),
      tools: tools(),
      parseHash: parseHash,
      renderList: renderList,
      renderChips: renderChips,
      renderTool: renderTool,
      navigate: navigate,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
