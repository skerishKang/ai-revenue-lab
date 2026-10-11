/* #3790: read-only model name inventory; never mutates the B62/Claw composer. */
(() => {
  "use strict";
  const open = document.getElementById("ownerModelPreviewOpen");
  const modal = document.getElementById("ownerModelPreviewDialog");
  const close = document.getElementById("ownerModelPreviewClose");
  const list = document.getElementById("ownerModelPreviewList");
  const status = document.getElementById("ownerModelPreviewStatus");
  if (!open || !modal || !close || !list || !status) return;

  // Cross-check the four exact owner-confirmed B14 identities, not a user-
  // or provider-supplied "model list". This is a subset, not a full catalog.
  const GOOGLE_OWNER_IDS = new Set([
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
  ]);
  let sequence = 0;
  function translated(key) {
    return window.__padiemLocale?.text(key) || key;
  }
  function resetStatus(message) {
    status.textContent = message;
    list.replaceChildren();
  }
  function makeRow(data) {
    const item = document.createElement("li");
    item.className = "owner-model-preview-item";
    const names = document.createElement("div");
    names.className = "owner-model-preview-names";
    const prefix = document.createElement("span");
    prefix.className = "owner-model-preview-prefix";
    prefix.textContent = data.product_name_prefix;
    const individualName = document.createElement("strong");
    individualName.className = "owner-model-preview-name";
    individualName.textContent = data.individual_model_name;
    names.append(prefix, individualName);
    const availability = document.createElement("span");
    availability.className = "owner-model-preview-hold";
    availability.textContent = translated("owner-model-preview-hold");
    item.append(names, availability);
    return item;
  }
  function validate(payload) {
    return payload &&
      payload.scope === "owner_confirmed_google_subset" &&
      payload.complete_inventory === false &&
      payload.execution_enabled === false &&
      Array.isArray(payload.model_names) &&
      payload.model_names.length === GOOGLE_OWNER_IDS.size &&
      new Set(payload.model_names.map((entry) => entry?.model_id)).size === GOOGLE_OWNER_IDS.size &&
      payload.model_names.every((entry) =>
        entry &&
        GOOGLE_OWNER_IDS.has(entry.model_id) &&
        entry.owner_selected === true &&
        entry.customer_selectable === false &&
        entry.product_name_prefix === "파디엠플러스" &&
        typeof entry.individual_model_name === "string" &&
        entry.individual_model_name.length > 0 &&
        entry.individual_model_name.length <= 100
      );
  }
  async function load() {
    const current = ++sequence;
    resetStatus(translated("owner-model-preview-loading"));
    try {
      const response = await fetch("/api/models/owner-name-preview", {
        method: "GET", credentials: "same-origin", cache: "no-store"
      });
      if (!response.ok) throw new Error("owner_model_preview_unavailable");
      const payload = await response.json();
      if (!validate(payload)) throw new Error("owner_model_preview_invalid");
      if (current !== sequence || !modal.open) return;
      const rows = payload.model_names.map(makeRow);
      list.replaceChildren(...rows);
      status.textContent = "";
    } catch (_error) {
      if (current !== sequence || !modal.open) return;
      resetStatus(translated("owner-model-preview-unavailable"));
    }
  }
  function show() {
    if (modal.open) return;
    if (typeof modal.showModal === "function") modal.showModal();
    else modal.setAttribute("open", "");
    open.setAttribute("aria-expanded", "true");
    void load();
  }
  function hide() {
    ++sequence;
    if (typeof modal.close === "function") modal.close();
    else modal.removeAttribute("open");
    open.setAttribute("aria-expanded", "false");
    open.focus();
  }
  open.addEventListener("click", show);
  close.addEventListener("click", hide);
  modal.addEventListener("close", () => {
    ++sequence;
    open.setAttribute("aria-expanded", "false");
  });
  modal.addEventListener("cancel", () => {
    ++sequence;
    open.setAttribute("aria-expanded", "false");
  });
  window.addEventListener("padiem:localechange", () => {
    list.querySelectorAll(".owner-model-preview-hold").forEach((node) => {
      node.textContent = translated("owner-model-preview-hold");
    });
  });
})();
