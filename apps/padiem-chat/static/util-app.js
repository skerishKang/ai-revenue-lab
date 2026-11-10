/*
 * #7173 · Util app (third app switch: Chat | Claw | Util).
 *
 * File boundary: every Util behaviour lives here (and in util-app.css).
 * app.js only exposes the two existing navigation entry points it already
 * owns (window.PadiemAppSwitch) — no Util logic is added to app.js.
 *
 * Routes (hash):
 *   #util        → the card list (first screen)
 *   #util/<id>   → the tool's own screen inside the Util app
 * Back/forward and refresh restore the same screen from the hash.
 */
(() => {
  "use strict";

  const ROUTE_PREFIX = "#util";
  const TOOLS = Object.freeze([
    Object.freeze({
      id: "speech", icon: "✎",
      ko: { title: "축사·인사말", desc: "행사 축사·인사말 초안 생성·저장" },
      en: { title: "Congratulatory address", desc: "Draft and save an address for an event" },
    }),
    Object.freeze({
      id: "sns", icon: "✦",
      ko: { title: "SNS 홍보", desc: "블로그·페이스북·인스타그램 초안" },
      en: { title: "SNS promo", desc: "Drafts for a blog, Facebook or Instagram" },
    }),
    Object.freeze({
      id: "meeting", icon: "▥",
      ko: { title: "회의정리·활동집", desc: "회의 요약·책/활동집 누적 생성" },
      en: { title: "Meeting notes", desc: "Summaries and an accumulating activity book" },
    }),
    Object.freeze({
      id: "pdfmd", icon: "⇩",
      ko: { title: "PDF → Markdown", desc: "PDF·ZIP을 Markdown으로 변환·비교·다운로드" },
      en: { title: "PDF → Markdown", desc: "Convert, compare and download Markdown from PDF/ZIP" },
    }),
    Object.freeze({
      id: "quote", icon: "◇",
      ko: { title: "견적서 초안", desc: "요청을 붙이면 견적서·발주서·답장 초안 — 서버에서 생성" },
      en: { title: "Quote draft", desc: "Draft a quotation, purchase order and reply from a request" },
    }),
    Object.freeze({
      id: "excel", icon: "▦",
      ko: { title: "Excel 열기/검토", desc: "XLSX 원본을 이 화면에서 열어 검토·작업" },
      en: { title: "Excel open & review", desc: "Open an XLSX file here to review and work on it" },
    }),
  ]);
  const TOOL_BY_ID = new Map(TOOLS.map((tool) => [tool.id, tool]));
  const TOOL_IDS = Object.freeze(TOOLS.map((tool) => tool.id));

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function copy(tool) {
    return tool[lang()] || tool.ko;
  }

  function parseHash(hash) {
    const value = String(hash || "");
    if (!value.startsWith(ROUTE_PREFIX)) return null;
    const rest = value.slice(ROUTE_PREFIX.length);
    if (rest === "" || rest === "/") return { screen: "list" };
    if (!rest.startsWith("/")) return { screen: "invalid" };
    const id = rest.slice(1);
    return TOOL_BY_ID.has(id) ? { screen: "tool", id } : { screen: "invalid" };
  }

  function listHref() {
    return ROUTE_PREFIX;
  }

  function toolHref(id) {
    return ROUTE_PREFIX + "/" + id;
  }

  function esc(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
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
    TOOLS.forEach((tool) => list.appendChild(buildCard(tool)));
    return list;
  }

  function renderTool(id) {
    const tool = TOOL_BY_ID.get(id);
    if (!tool) return null;
    const text = copy(tool);
    const screen = element("div", "util-tool-screen");
    screen.setAttribute("data-util-tool", tool.id);
    const back = element("a", "util-tool-back");
    back.setAttribute("href", listHref());
    back.appendChild(document.createTextNode("← "));
    back.appendChild(element("span", null, lang() === "en" ? "Util" : "유틸"));
    const heading = element("h3", "util-tool-heading", text.title);
    heading.id = "utilToolHeading";
    heading.setAttribute("tabindex", "-1");
    const body = element("div", "util-tool-body");
    body.setAttribute("role", "region");
    body.setAttribute("aria-labelledby", "utilToolHeading");
    // PR2: the three council-family tools mount their own screen from
    // util-tools.js. The other three keep the placeholder until their PR.
    const mounted = Boolean(
      window.PadiemUtilTools
      && typeof window.PadiemUtilTools.mount === "function"
      && window.PadiemUtilTools.mount(tool.id, body)
    );
    if (!mounted) {
      const placeholder = lang() === "en"
        ? "This tool screen is being prepared. Input and results land here in the next step."
        : "도구 화면을 준비 중입니다. 다음 단계에서 이 화면에 입력과 결과가 추가됩니다.";
      body.appendChild(element("p", "util-tool-placeholder", placeholder));
    }
    screen.appendChild(back);
    screen.appendChild(heading);
    screen.appendChild(element("p", "util-tool-desc", text.desc));
    screen.appendChild(body);
    return screen;
  }

  const els = {};
  let bound = false;
  let firstRoute = true;
  let pdfInitialized = false;

  function legacyPdfPanel() {
    return document.getElementById("utilPdfmdPanel");
  }

  function parkLegacyPdfPanel() {
    const panel = legacyPdfPanel();
    const host = document.getElementById("utilPdfmdHost");
    if (!panel) return;
    if (host && panel.parentElement !== host) host.appendChild(panel);
    panel.hidden = true;
  }

  function mountLegacyPdfPanel() {
    const panel = legacyPdfPanel();
    const body = els.root ? els.root.querySelector(".util-tool-body") : null;
    if (!panel || !body) return;
    body.appendChild(panel);
    panel.hidden = false;
    if (!pdfInitialized && typeof window.initPdfMdUtility === "function") {
      try { window.initPdfMdUtility(panel); } catch (_) { /* first render wins */ }
      pdfInitialized = true;
    }
  }

  function utilVisible() {
    return Boolean(els.shell && els.shell.dataset.state === "util");
  }

  function syncSidebar() {
    // The app switch owns the top-level state; the retired sidebar entry stays
    // hidden, and no other sidebar row may keep claiming "current".
    ["newChatButton", "clawNavButton"].forEach((id) => {
      const button = document.getElementById(id);
      if (button) button.setAttribute("aria-current", "false");
    });
    const utilNav = document.getElementById("utilNavButton");
    if (utilNav) utilNav.setAttribute("aria-current", "page");
  }

  function showUtilShell() {
    if (!els.shell) return;
    els.shell.dataset.state = "util";
    if (els.utilView) els.utilView.hidden = false;
    syncTabs("util");
    syncSidebar();
  }

  function hideUtilShell() {
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

  function syncTabs(active) {
    if (!els.switchButtons) return;
    els.switchButtons.forEach((button) => {
      button.setAttribute("aria-current", button.dataset.app === active ? "page" : "false");
    });
  }

  function currentApp() {
    if (utilVisible()) return "util";
    if (String(window.location.hash || "") === "#claw") return "claw";
    if (els.shell && els.shell.dataset.state === "claw") return "claw";
    return "chat";
  }

  function renderRoute(options) {
    const opts = options || {};
    const parsed = parseHash(window.location.hash);
    if (!parsed) return false;
    showUtilShell();
    setUtilHeading(lang());
    if (parsed.screen === "invalid") {
      try {
        window.history.replaceState(
          window.history.state, "",
          window.location.pathname + window.location.search + listHref(),
        );
      } catch (_) { /* a sandboxed history must not stop the list render */ }
      if (!els.root) return false;
      parkLegacyPdfPanel();
      els.root.replaceChildren(renderList());
      return true;
    }
    if (!els.root) return false;
    parkLegacyPdfPanel();
    if (parsed.screen === "list") {
      els.root.replaceChildren(renderList());
      if (opts.focus && els.utilTitle && typeof els.utilTitle.focus === "function") {
        els.utilTitle.setAttribute("tabindex", "-1");
        els.utilTitle.focus({ preventScroll: true });
      }
      return true;
    }
    const markup = renderTool(parsed.id);
    if (!markup) return false;
    els.root.replaceChildren(markup);
    if (parsed.id === "pdfmd") mountLegacyPdfPanel();
    if (opts.focus) {
      const heading = document.getElementById("utilToolHeading");
      if (heading && typeof heading.focus === "function") heading.focus({ preventScroll: true });
    }
    return true;
  }

  function navigate(hash) {
    // One history entry per navigation so Back returns to the previous screen.
    window.location.hash = hash;
  }

  function onHashChange() {
    const hash = String(window.location.hash || "");
    if (parseHash(hash)) {
      renderRoute({ focus: !firstRoute });
      firstRoute = false;
      return;
    }
    if (hash === "#claw") {
      hideUtilShell();
      if (window.PadiemAppSwitch && window.PadiemAppSwitch.openClaw) window.PadiemAppSwitch.openClaw();
      syncTabs("claw");
      return;
    }
    if (utilVisible()) {
      hideUtilShell();
      if (window.PadiemAppSwitch && window.PadiemAppSwitch.openChat) window.PadiemAppSwitch.openChat();
      syncTabs("chat");
    }
  }

  function bind() {
    if (bound) return;
    bound = true;
    els.root = document.getElementById("utilAppRoot");
    els.utilView = document.getElementById("utilView");
    els.shell = document.querySelector(".app-shell");
    els.utilTitle = document.getElementById("utilTitle");
    els.utilKicker = document.getElementById("utilKicker");
    els.utilTagline = document.getElementById("utilTagline");
    const switchRoot = document.getElementById("appSwitch");
    els.switchButtons = switchRoot ? Array.from(switchRoot.querySelectorAll("[data-app]")) : [];
    els.switchButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const app = button.dataset.app;
        if (app === "util") {
          if (!parseHash(window.location.hash)) navigate(ROUTE_PREFIX);
          else renderRoute({ focus: false });
          return;
        }
        hideUtilShell();
        if (app === "claw") {
          if (window.PadiemAppSwitch && window.PadiemAppSwitch.openClaw) window.PadiemAppSwitch.openClaw();
          syncTabs("claw");
          return;
        }
        try {
          window.history.replaceState(
            window.history.state, "",
            window.location.pathname + window.location.search,
          );
        } catch (_) { /* history is optional for the Chat tab */ }
        if (window.PadiemAppSwitch && window.PadiemAppSwitch.openChat) window.PadiemAppSwitch.openChat();
        syncTabs("chat");
      });
    });
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
    } else {
      syncTabs(currentApp());
    }
    window.PadiemUtilApp = Object.freeze({
      ROUTE_PREFIX, TOOL_IDS, tools: TOOLS, parseHash, renderList, renderTool, navigate,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
