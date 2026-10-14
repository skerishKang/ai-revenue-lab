(() => {
  "use strict";
  const cards = Object.freeze([
    { id: "computer", labelKey: "connector-card-computer", toggle: true, implemented: false },
    { id: "google-drive", labelKey: "connector-card-google-drive", toggle: true, implemented: true, endpoint: "/api/connectors/google/ticket" },
    { id: "github", labelKey: "connector-card-github", toggle: true, implemented: false },
    { id: "web", labelKey: "connector-card-web", toggle: false, implemented: true }
  ]);
  const TOGGLE_IDS = Object.freeze(["computer", "google-drive", "github"]);
  const WEB_ID = "web";
  function capabilityCards() { return cards.map((c) => ({ ...c })); }
  function toggleCards() { return cards.filter((c) => c.toggle).map((c) => ({ ...c })); }
  function nonToggleCards() { return cards.filter((c) => !c.toggle).map((c) => ({ ...c })); }
  function implementedToggleCards() { return cards.filter((c) => c.toggle && c.implemented).map((c) => ({ ...c })); }
  function preparingCards() { return cards.filter((c) => !c.implemented).map((c) => ({ ...c })); }
  function isToggleCard(cardOrId) { const id = typeof cardOrId === "string" ? cardOrId : (cardOrId && cardOrId.id); return TOGGLE_IDS.indexOf(id) !== -1; }
  function isWebCard(cardOrId) { const id = typeof cardOrId === "string" ? cardOrId : (cardOrId && cardOrId.id); return id === WEB_ID; }
  function statusFor(cardOrId, connected) {
    const id = typeof cardOrId === "string" ? cardOrId : (cardOrId && cardOrId.id);
    const card = cards.find((c) => c.id === id);
    if (!card) return "unknown";
    if (!card.implemented) return "preparing";
    if (!card.toggle) return "usable";
    return connected ? "connected" : "disconnected";
  }
  function shouldAttemptConnect(cardOrId) {
    const id = typeof cardOrId === "string" ? cardOrId : (cardOrId && cardOrId.id);
    const card = cards.find((c) => c.id === id);
    return Boolean(card && card.implemented && card.toggle);
  }
function cardById(id) { return cards.find((c) => c.id === id) || null; }
function isImplemented(cardOrId) { const c = typeof cardOrId === "string" ? cardById(cardOrId) : cardOrId; return Boolean(c && c.implemented); }
function isPreparing(cardOrId) { const c = typeof cardOrId === "string" ? cardById(cardOrId) : cardOrId; return Boolean(c && !c.implemented); }

  function toggleButtons(scope) {
    const root = scope || (typeof document === "object" ? document : null);
    if (!root || typeof root.querySelectorAll !== "function") return [];
    return Array.from(root.querySelectorAll("[data-connector-toggle]"));
  }

  function isOn(button) { return Boolean(button) && button.getAttribute("aria-pressed") === "true"; }
  function paintToggle(button, connected) {
    if (!button) return;
    button.textContent = connected ? "ON" : "OFF";
    button.setAttribute("aria-pressed", connected ? "true" : "false");
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }

  /* OFF -> connect attempt, ON -> disconnect confirm. Preparing cards keep a
     hidden, disabled toggle and never attempt a connection. */
  function bindConnectorToggles(options = {}) {
    const dialog = options.disconnectDialog || null;
    const onConnect = typeof options.onConnect === "function" ? options.onConnect : () => {};
    const onDisconnect = typeof options.onDisconnect === "function" ? options.onDisconnect : () => {};
    const scope = options.scope || (typeof document === "object" ? document : null);
    toggleButtons(scope).forEach((button) => {
      const id = button.dataset.connectorToggle;
      // Web and every other non-toggle surface keeps its button out of the
      // layout entirely; preparing cards keep it hidden and disabled.
      if (!isToggleCard(id) || !isImplemented(id)) {
        button.hidden = true;
        button.disabled = true;
        button.textContent = "OFF";
        button.setAttribute("aria-pressed", "false");
        button.removeAttribute("aria-busy");
        return;
      }
      button.hidden = false;
      button.disabled = false;
      button.addEventListener("click", () => {
        if (isOn(button)) {
          wireDisconnectDialog();
          if (dialog && typeof dialog.showModal === "function") {
            dialog.dataset.connectorId = id;
            dialog.showModal();
          }
          return;
        }
        button.disabled = true;
        button.textContent = "\u2026";
        button.setAttribute("aria-busy", "true");
        onConnect(id);
      });
    });
    // A choice click is the decision, not a "close" event: a modal's close can
    // be observed late or dropped, and its returnValue outlives the dialog, so
    // a dismissal must never be able to replay an earlier confirmation.
    function wireDisconnectDialog() {
      if (!dialog || typeof dialog.querySelectorAll !== "function") return;
      Array.from(dialog.querySelectorAll("[value]")).forEach((choice) => {
        const value = choice.getAttribute("value") || "";
        const handler = () => {
          if (value !== "confirm") return;
          const id = dialog.dataset.connectorId;
          if (!id) return;
          dialog.dataset.disconnectedId = id;
          const target = toggleButtons(scope).find((b) => b.dataset.connectorToggle === id);
          paintToggle(target, false);
          onDisconnect(id);
        };
        if (!choice.__padiemBound) {
          choice.__padiemBound = true;
          choice.addEventListener("click", handler);
        }
      });
    }
    if (!dialog || typeof dialog.addEventListener !== "function") return { isOn, paintToggle };
    dialog.addEventListener("close", () => {
      // Cleanup only: the disconnect decision was already taken on the button.
      delete dialog.dataset.connectorId;
      delete dialog.dataset.disconnectedId;
    });
    return { isOn, paintToggle };
  }

  const api = Object.freeze({ cards: capabilityCards(), capabilityCards, toggleCards, nonToggleCards, implementedToggleCards, preparingCards, isToggleCard, isWebCard, statusFor, shouldAttemptConnect, isImplemented, isPreparing, toggleButtons, isOn, paintToggle, bindConnectorToggles, TOGGLE_IDS, WEB_ID });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") window.PadiemConnectorCapabilityCards = api;
})();
