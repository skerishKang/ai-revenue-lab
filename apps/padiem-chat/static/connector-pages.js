// Connector pages — the Connectors screen keeps one line per connector and
// opens a dedicated page for the one you picked. The card elements themselves
// (their listeners, their endpoints, their state writers) are MOVED, never
// rebuilt: this module adds routing and layout, never connection authority.
(() => {
  "use strict";

  const VIEW_ID = "connectorsView";
  const GRID_ID = "connectorsGrid";
  const DETAIL_ID = "connectorDetail";
  const detailed = { card: null, home: null };

  function byId(id) { return document.getElementById(id); }

  function cards() {
    const grid = byId(GRID_ID);
    return grid ? Array.from(grid.querySelectorAll(".capability-card")) : [];
  }

  function connectorId(card) {
    return String(card.dataset.connector || card.id || "").replace(/^connector/, "") || card.id || "connector";
  }

  function nameOf(card) {
    const strong = card.querySelector("strong");
    return strong ? strong.textContent.trim() : "";
  }

  function markOf(card) {
    return String(card.dataset.serviceMark || "");
  }

  // Every tile and detail page speaks only the shared four-state vocabulary.
  // The card's own dataset is the state owner; this map translates it and
  // never copies a raw sentence (no “workspace”, no long server prose).
  function stateOf(card) {
    if (card.querySelector(".capability-soon")) return "soon";
    const raw = String(card.dataset.connectorStatus || "").toLowerCase();
    if (raw === "connected") return "connected";
    if (raw === "not_connected" || raw === "disconnected") return "disconnected";
    if (raw === "connecting" || raw === "loading" || raw === "preparing" || raw === "") return "checking";
    return "failed";
  }

  function statusText(card) {
    const state = stateOf(card);
    if (state === "soon") return "곧 지원돼요";
    const vocab = window.PadiemConnectorVocabulary;
    return vocab ? (vocab.status(state) || "") : "";
  }

  function syncTile(card) {
    const line = card.querySelector(".connector-tile-status");
    if (!line) return;
    const text = statusText(card);
    if (line.textContent !== text) line.textContent = text;
  }

  function makeTiles() {
    if (!byId(GRID_ID)) return;
    cards().forEach((card) => {
      if (!card.classList.contains("connector-tile")) card.classList.add("connector-tile");
      if (!card.querySelector(".connector-tile-status")) {
        const line = document.createElement("span");
        line.className = "connector-tile-status";
        line.setAttribute("role", "status");
        const strong = card.querySelector("strong");
        if (strong) strong.after(line); else card.appendChild(line);
        card.setAttribute("tabindex", card.getAttribute("tabindex") || "0");
        card.setAttribute("role", "button");
      }
      syncTile(card);
    });
  }

  function groupAdvanced(card) {
    if (card.dataset.advancedGrouped) return;
    const alternate = card.querySelector("details.pc-pairing-alternate");
    if (!alternate || !alternate.parentNode) return;
    const advanced = document.createElement("details");
    advanced.className = "pc-connector-advanced";
    const summary = document.createElement("summary");
    summary.className = "pc-connector-advanced-summary";
    summary.textContent = "고급 설정";
    // Order: page head → connect → PC list → advanced at the very bottom.
    advanced.append(summary, alternate);
    card.appendChild(advanced);
    card.dataset.advancedGrouped = "1";
  }

  function setHash(value) {
    try { history.replaceState(null, "", value); } catch (_) {}
  }

  function openDetail(card) {
    const detail = byId(DETAIL_ID);
    const grid = byId(GRID_ID);
    const body = byId("connectorDetailBody");
    if (!detail || !grid || !body || !card) return;
    if (detailed.card === card) return;
    if (detailed.card) closeDetail(true);
    makeTiles();
    detailed.card = card;
    detailed.home = { parent: card.parentNode, next: card.nextSibling };
    body.appendChild(card);
    grid.hidden = true;
    detail.hidden = false;

    const title = byId("connectorDetailTitle");
    if (title) title.textContent = nameOf(card);
    const mark = byId("connectorDetailMark");
    if (mark) mark.textContent = markOf(card);
    const actions = byId("connectorDetailActions");
    const computer = card.dataset.connector === "computer" || card.id === "connectorComputerCard";
    if (actions) actions.hidden = !computer;
    syncDetailStatus(card);
    syncDetailRetry(card);
    if (computer) groupAdvanced(card);
    setHash("#connectors/" + connectorId(card));
  }

  function syncDetailStatus(card) {
    const status = byId("connectorDetailStatus");
    if (!status) return;
    // One row of truth: the shared vocabulary, plus how many PCs are linked
    // when at least one is (the page head reads “● 3대 연결됨”).
    const rows = card.querySelectorAll(".pc-pairing-link").length;
    const vocab = window.PadiemConnectorVocabulary;
    if (rows > 0 && vocab) {
      const ko = !String(document.documentElement.lang || "ko").toLowerCase().startsWith("en");
      const line = ko ? "● " + rows + "대 연결됨" : "● " + rows + " connected";
      if (status.textContent !== line) status.textContent = line;
      return;
    }
    const text = statusText(card);
    if (status.textContent !== text) status.textContent = text;
  }

  function syncDetailRetry(card) {
    let link = byId("connectorDetailRetry");
    const failed = stateOf(card) === "failed";
    if (!failed) { if (link) link.remove(); return; }
    if (link) return;
    const actions = byId("connectorDetailActions");
    if (!actions) return;
    link = document.createElement("button");
    link.type = "button";
    link.id = "connectorDetailRetry";
    link.className = "connector-detail-retry";
    link.textContent = "다시 확인";
    link.addEventListener("click", () => {
      const original = card.querySelector("#clawComputerDeviceStatusButton");
      if (original) original.click();
    });
    actions.appendChild(link);
  }

  function closeDetail(keepHash) {
    const detail = byId(DETAIL_ID);
    const grid = byId(GRID_ID);
    if (!detailed.card || !detail || !grid) return;
    const { card, home } = detailed;
    if (home && home.parent) {
      if (home.next && home.next.parentNode === home.parent) home.parent.insertBefore(card, home.next);
      else home.parent.appendChild(card);
    }
    detailed.card = null;
    detailed.home = null;
    detail.hidden = true;
    grid.hidden = false;
    makeTiles();
    if (!keepHash) setHash("#connectors");
  }

  function handleHash() {
    const view = byId(VIEW_ID);
    if (!view || view.hidden) return;
    const match = /^#connectors\/(.+)$/.exec(String(location.hash || ""));
    if (!match) { closeDetail(true); return; }
    const id = decodeURIComponent(match[1]);
    const card = cards().find((item) => connectorId(item) === id || item.dataset.connector === id || item.id === id);
    if (card) openDetail(card);
  }

  document.addEventListener("click", (event) => {
    const view = byId(VIEW_ID);
    if (!view || view.hidden) return;
    const back = event.target.closest && event.target.closest("#connectorDetailBack");
    if (back) { closeDetail(false); return; }
    if (event.target.closest && event.target.closest("#connectorDetailConnect")) {
      const flow = window.PadiemPcConnectFlow;
      if (flow && typeof flow.openModal === "function") flow.openModal();
      return;
    }
    if (detailed.card) return;
    const tile = event.target.closest && event.target.closest(".connector-tile");
    if (!tile) return;
    if (event.target.closest("button, a, input, select, textarea, summary")) return;
    openDetail(tile);
  });

  document.addEventListener("keydown", (event) => {
    if (detailed.card || event.key !== "Enter" && event.key !== " ") return;
    const tile = event.target.closest && event.target.closest(".connector-tile");
    if (!tile) return;
    event.preventDefault();
    openDetail(tile);
  });

  window.addEventListener("hashchange", handleHash);

  // The grid is moved into the view on first open; build the tiles then and
  // keep their one-line status in step with the nodes that own the truth.
  const observer = new MutationObserver(() => {
    makeTiles();
    if (detailed.card) {
      syncDetailStatus(detailed.card);
      syncDetailRetry(detailed.card);
      return;
    }
    const view = byId(VIEW_ID);
    if (view && !view.hidden && /^#connectors\//.test(String(location.hash || ""))) handleHash();
  });
  const start = () => {
    const host = byId(VIEW_ID) || document.body;
    observer.observe(host, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden", "data-connector-status"] });
    makeTiles();
    handleHash();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();

  window.PadiemConnectorPages = Object.freeze({
    open: (id) => {
      const card = cards().find((item) => item.dataset.connector === id || connectorId(item) === id);
      if (card) openDetail(card);
    },
    close: () => closeDetail(false),
    current: () => (detailed.card ? connectorId(detailed.card) : null),
  });
})();
