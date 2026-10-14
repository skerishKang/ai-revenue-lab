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
  const api = Object.freeze({ cards: capabilityCards(), capabilityCards, toggleCards, nonToggleCards, implementedToggleCards, preparingCards, isToggleCard, isWebCard, statusFor, shouldAttemptConnect, TOGGLE_IDS, WEB_ID });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") window.PadiemConnectorCapabilityCards = api;
})();
