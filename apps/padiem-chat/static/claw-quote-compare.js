(() => {
  "use strict";

  const ROUTE = "/api/claw/manual-intake/quote-compare";
  const ARTIFACT_ROUTE = "/api/claw/manual-intake/artifact/";
  const DOCUMENT_ID = /^doc_[A-Za-z0-9]{32}$/;
  const INTEGER = /^[0-9]{1,15}$/;
  const MIN_SUPPLIERS = 2;
  const MAX_SUPPLIERS = 10;
  const MODES = ["balanced", "lowest_price", "fastest_delivery", "best_cashflow_fit"];
  const CURRENCIES = ["KRW", "USD", "EUR", "JPY", "GBP", "CNY"];

  const COPY = {
    "claw-qc-kicker": "PADIEM CLAW COMPARE",
    "claw-qc-title": "Supplier quote comparison",
    "claw-qc-tagline": "Compare two or more captured quotes without inventing missing facts.",
    "claw-qc-form-aria": "Supplier quote comparison form",
    "claw-qc-mode": "Comparison mode",
    "claw-qc-currency": "Currency",
    "claw-qc-mode-balanced": "Balanced",
    "claw-qc-mode-lowest_price": "Lowest price",
    "claw-qc-mode-fastest_delivery": "Fastest delivery",
    "claw-qc-mode-best_cashflow_fit": "Best payment fit",
    "claw-qc-add": "Add supplier",
    "claw-qc-remove": "Remove supplier",
    "claw-qc-field-name": "Supplier name",
    "claw-qc-field-item": "Item (optional)",
    "claw-qc-field-unit": "Unit price (minor units)",
    "claw-qc-field-quantity": "Quantity (optional)",
    "claw-qc-field-total": "Total (optional)",
    "claw-qc-field-delivery": "Promised delivery date (optional)",
    "claw-qc-field-payment": "Payment terms (optional)",
    "claw-qc-field-due": "Payment days (optional)",
    "claw-qc-field-prepaid": "Prepaid",
    "claw-qc-field-evidence": "Evidence reference (optional)",
    "claw-qc-hint": "Leave unknown facts blank. Lead-time text is never converted into a date.",
    "claw-qc-btn-compare": "Compare quotes",
    "claw-qc-btn-docx": "Save DOCX",
    "claw-qc-btn-download": "Download document",
    "claw-qc-auth-note": "DOCX saving requires a signed-in workspace account.",
    "claw-qc-status-ready": "Enter at least two supplier quotes.",
    "claw-qc-status-running": "Comparing captured quotes...",
    "claw-qc-status-success": "Comparison is ready. Missing facts remain unknown.",
    "claw-qc-status-saved": "DOCX is ready to download.",
    "claw-qc-error-input": "Check each supplier name and enter a positive unit price or total.",
    "claw-qc-error-line": "Check that unit price, quantity, and total agree.",
    "claw-qc-error-generic": "The comparison could not be completed. Check the captured facts and try again.",
    "claw-qc-error-auth": "Sign in to save a DOCX in the workspace.",
    "claw-qc-error-storage": "The document could not be saved. Please try again shortly.",
    "claw-qc-error-download": "The document could not be downloaded. Please try again shortly.",
    "claw-qc-unknown": "Unknown",
    "claw-qc-recommended": "Recommended",
    "claw-qc-advisory": "Deterministic comparison · for reference",
    "claw-qc-supplier": "Supplier",
    "claw-qc-total-heading": "Total",
    "claw-qc-delivery-heading": "Delivery",
    "claw-qc-payment-heading": "Payment",
    "claw-qc-score-heading": "Score",
    "claw-qc-recommendation": "Recommendation",
    "claw-qc-reason-complete": "winner fields complete",
    "claw-qc-reason-unknown": "winner has unknown fields",
    "claw-qc-negotiation": "Negotiation output",
    "claw-qc-draft": "DRAFT",
    "claw-qc-no-negotiation": "No negotiation draft was created from the captured quotes.",
    "claw-qc-no-external": "No sending or purchase action is performed.",
    "claw-qc-field-missing": "Unknown facts",
    "claw-qc-delivery-unknown": "Delivery unknown",
    "claw-qc-payment-unknown": "Payment terms unknown",
    "claw-qc-prepaid": "prepaid",
    "claw-qc-days": "days",
  };

  const ERROR_KEYS = {
    workspace_scope_unavailable: "claw-qc-error-auth",
    workspace_storage_unavailable: "claw-qc-error-storage",
    artifact_storage_failed: "claw-qc-error-storage",
    artifact_generation_failed: "claw-qc-error-storage",
    supplier_unit_price_underivable: "claw-qc-error-line",
    supplier_line_total_mismatch: "claw-qc-error-line",
    fractional_line_total: "claw-qc-error-line",
    invalid_delivery_date: "claw-qc-error-input",
    invalid_payment_terms: "claw-qc-error-input",
    invalid_price: "claw-qc-error-input",
    supplier_price_missing: "claw-qc-error-input",
    supplier_total_must_be_positive: "claw-qc-error-input",
    suppliers_required: "claw-qc-error-input",
    too_many_suppliers: "claw-qc-error-input",
  };

  function text(key, variables) {
    try {
      const value = window.__padiemLocale && window.__padiemLocale.text(key, variables);
      if (value && value !== key) return value;
    } catch (_) {}
    let value = COPY[key] || key;
    if (variables) Object.keys(variables).forEach((name) => { value = value.split(`{${name}}`).join(String(variables[name])); });
    return value;
  }

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function labelFor(key, input) {
    const label = el("label", "claw-qc-field");
    label.htmlFor = input.id;
    const span = el("span", "claw-qc-label", text(key));
    span.dataset.localeKey = key;
    label.append(span, input);
    return label;
  }

  function isAuthenticated() {
    const button = document.getElementById("loginButton");
    return button && button.dataset.authenticated === "true" && button.disabled === false;
  }

  function integerValue(value, positive = false) {
    const raw = String(value || "").trim();
    if (!raw || !INTEGER.test(raw)) return null;
    const parsed = Number(raw);
    if (!Number.isSafeInteger(parsed) || (positive && parsed <= 0)) return null;
    return parsed;
  }

  function formatMoney(value, currency) {
    if (!value || typeof value.amount_minor !== "number") return text("claw-qc-unknown");
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value.amount_minor); }
    catch (_) { return `${value.amount_minor} ${currency}`; }
  }

  function createModule() {
    const section = document.getElementById("clawQuoteCompare");
    const form = document.getElementById("clawQuoteCompareForm");
    const list = document.getElementById("clawQcSuppliers");
    if (!section || !form || !list) return;
    const mode = document.getElementById("clawQcMode");
    const currency = document.getElementById("clawQcCurrency");
    const add = document.getElementById("clawQcAddSupplier");
    const compare = document.getElementById("clawQcCompareBtn");
    const docx = document.getElementById("clawQcDocxBtn");
    const download = document.getElementById("clawQcDownloadBtn");
    const status = document.getElementById("clawQcStatus");
    const result = document.getElementById("clawQcResult");
    const authNote = document.getElementById("clawQcAuthNote");
    const rows = [];
    let sequence = 0;
    let lastPayload = null;
    let lastComparison = null;
    let artifact = null;
    let busy = false;

    function setStatus(key, state = "") {
      status.hidden = !key;
      status.textContent = key ? text(key) : "";
      status.dataset.state = state;
    }

    function input(type, className, id) {
      const node = el("input");
      node.type = type;
      node.className = className;
      node.id = id;
      node.autocomplete = "off";
      return node;
    }

    function addRow() {
      if (rows.length >= MAX_SUPPLIERS) return;
      sequence += 1;
      const id = `sup_${sequence}`;
      const card = el("article", "claw-qc-supplier-card");
      card.setAttribute("role", "listitem");
      const head = el("div", "claw-qc-card-head");
      const title = el("h3", "claw-qc-card-title", `${text("claw-qc-supplier")} ${rows.length + 1}`);
      title.dataset.localeKey = "claw-qc-supplier";
      const remove = el("button", "claw-qc-remove", text("claw-qc-remove"));
      remove.type = "button";
      remove.dataset.localeKey = "claw-qc-remove";
      head.append(title, remove);
      const name = input("text", "claw-qc-name", `clawQcName${sequence}`); name.maxLength = 200;
      const item = input("text", "claw-qc-item", `clawQcItem${sequence}`); item.maxLength = 300;
      const unit = input("text", "claw-qc-unit", `clawQcUnit${sequence}`); unit.inputMode = "numeric";
      const quantity = input("text", "claw-qc-quantity", `clawQcQuantity${sequence}`); quantity.inputMode = "numeric";
      const total = input("text", "claw-qc-total", `clawQcTotal${sequence}`); total.inputMode = "numeric";
      const delivery = input("date", "claw-qc-delivery", `clawQcDelivery${sequence}`);
      const payment = input("text", "claw-qc-payment", `clawQcPayment${sequence}`); payment.maxLength = 300;
      const due = input("text", "claw-qc-due", `clawQcDue${sequence}`); due.inputMode = "numeric";
      const prepaid = input("checkbox", "claw-qc-prepaid", `clawQcPrepaid${sequence}`);
      const evidence = input("text", "claw-qc-evidence", `clawQcEvidence${sequence}`); evidence.maxLength = 256;
      card.append(head,
        labelFor("claw-qc-field-name", name), labelFor("claw-qc-field-item", item),
        labelFor("claw-qc-field-unit", unit), labelFor("claw-qc-field-quantity", quantity),
        labelFor("claw-qc-field-total", total), labelFor("claw-qc-field-delivery", delivery),
        labelFor("claw-qc-field-payment", payment), labelFor("claw-qc-field-due", due),
        labelFor("claw-qc-field-prepaid", prepaid), labelFor("claw-qc-field-evidence", evidence));
      const row = { id, card, name, item, unit, quantity, total, delivery, payment, due, prepaid, evidence };
      rows.push(row); list.append(card);
      remove.addEventListener("click", () => {
        if (rows.length <= MIN_SUPPLIERS) { setStatus("claw-qc-status-ready", "error"); return; }
        rows.splice(rows.indexOf(row), 1); card.remove(); renumber(); invalidate();
      });
      [name, item, unit, quantity, total, delivery, payment, due, prepaid, evidence].forEach((field) => field.addEventListener("input", invalidate));
      renumber();
    }

    function renumber() {
      rows.forEach((row, index) => { row.card.querySelector(".claw-qc-card-title").textContent = `${text("claw-qc-supplier")} ${index + 1}`; });
      add.disabled = rows.length >= MAX_SUPPLIERS;
      add.setAttribute("aria-disabled", String(add.disabled));
    }

    function readRow(row) {
      const name = row.name.value.trim();
      const unit = row.unit.value.trim();
      const total = row.total.value.trim();
      const unitValue = unit ? integerValue(unit, true) : null;
      const totalValue = total ? integerValue(total, true) : null;
      const quantityValue = row.quantity.value.trim() ? integerValue(row.quantity.value, true) : null;
      const dueValue = row.due.value.trim() ? integerValue(row.due.value, false) : null;
      const valid = Boolean(name)
        && ((unit && unitValue !== null) || (total && totalValue !== null))
        && (!unit || unitValue !== null)
        && (!total || totalValue !== null)
        && (!row.quantity.value.trim() || quantityValue !== null)
        && (!row.due.value.trim() || dueValue !== null);
      const entry = { supplier_id: row.id, supplier_label: name };
      if (row.item.value.trim()) entry.item_label = row.item.value.trim();
      if (unit) entry.unit_price_minor = unitValue;
      if (row.quantity.value.trim()) entry.quantity = quantityValue;
      if (total) entry.total_minor = totalValue;
      if (row.delivery.value) entry.promised_delivery_date = row.delivery.value;
      const terms = {};
      if (row.payment.value.trim()) terms.label = row.payment.value.trim();
      if (row.due.value.trim()) terms.due_days = dueValue;
      if (row.prepaid.checked) terms.prepaid = true;
      if (Object.keys(terms).length) entry.payment_terms = terms;
      if (row.evidence.value.trim()) entry.evidence_ref = row.evidence.value.trim();
      return { valid, entry };
    }

    function payload() {
      const entries = rows.map(readRow);
      if (entries.length < MIN_SUPPLIERS || entries.some((row) => !row.valid)) return null;
      return { mode: mode.value, currency: currency.value, suppliers: entries.map((row) => row.entry) };
    }

    function invalidate() {
      artifact = null; lastComparison = null; lastPayload = null; result.hidden = true;
      docx.disabled = true; download.disabled = true; docx.setAttribute("aria-disabled", "true"); download.setAttribute("aria-disabled", "true");
      syncAuth();
    }

    function errorKey(data, response) {
      const code = data && data.error && data.error.code;
      if (ERROR_KEYS[code]) return ERROR_KEYS[code];
      if (response && response.status === 401) return "claw-qc-error-auth";
      return "claw-qc-error-generic";
    }

    async function post(body) {
      const response = await fetch(ROUTE, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body), cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) { const error = new Error(errorKey(data, response)); error.key = errorKey(data, response); throw error; }
      return data;
    }

    function money(value) { return formatMoney(value, lastComparison?.currency || currency.value); }

    function render(comparison) {
      result.replaceChildren(); result.hidden = false;
      const heading = el("h3", "claw-qc-result-title", text("claw-qc-recommendation"));
      const advisory = el("span", "claw-qc-badge", text("claw-qc-advisory"));
      const intro = el("div", "claw-qc-result-head");
      intro.append(heading, advisory);
      result.append(intro);
      const recommendation = el("p", "claw-qc-recommendation-copy", `${text("claw-qc-recommendation")}: ${comparison.recommended_supplier_label || text("claw-qc-unknown")}`);
      result.append(recommendation);
      const reason = (comparison.reason_codes || []).find((value) => value === "winner_fields_complete" || value === "winner_has_unknown_fields");
      if (reason) result.append(el("p", "claw-qc-reason", text(reason === "winner_fields_complete" ? "claw-qc-reason-complete" : "claw-qc-reason-unknown")));
      const grid = el("div", "claw-qc-result-grid");
      ["claw-qc-supplier", "claw-qc-total-heading", "claw-qc-delivery-heading", "claw-qc-payment-heading", "claw-qc-score-heading"].forEach((key) => grid.append(el("div", "claw-qc-grid-heading", text(key))));
      (comparison.suppliers || []).forEach((supplier) => {
        const name = el("div", "claw-qc-result-supplier", supplier.supplier_label || text("claw-qc-unknown"));
        if (supplier.supplier_id === comparison.recommended_supplier_id) name.append(" ", el("strong", "claw-qc-recommended", text("claw-qc-recommended")));
        const delivery = supplier.promised_delivery_date || text("claw-qc-delivery-unknown");
        let terms = supplier.payment_terms_label || (supplier.due_days !== null ? `${supplier.due_days} ${text("claw-qc-days")}` : text("claw-qc-payment-unknown"));
        if (supplier.prepaid === true) terms += ` (${text("claw-qc-prepaid")})`;
        grid.append(name, el("div", "claw-qc-result-value", money(supplier.total)), el("div", "claw-qc-result-value", delivery), el("div", "claw-qc-result-value", terms), el("div", "claw-qc-result-value", `#${supplier.score_basis_points ?? "-"}`));
        if (supplier.unknown_fields && supplier.unknown_fields.length) {
          const unknown = supplier.unknown_fields.map((field) => field === "promised_delivery_date" ? text("claw-qc-field-delivery") : text("claw-qc-field-payment")).join(", ");
          result.append(el("p", "claw-qc-unknown-note", `${text("claw-qc-field-missing")}: ${unknown}`));
        }
      });
      result.append(grid);
      const negotiation = comparison.negotiation;
      const negotiationBox = el("div", "claw-qc-negotiation");
      negotiationBox.append(el("h4", "claw-qc-negotiation-title", text("claw-qc-negotiation")));
      if (negotiation && negotiation.status === "draft_only") {
        negotiationBox.append(el("strong", "claw-qc-draft-badge", text("claw-qc-draft")), el("p", "claw-qc-draft-copy", negotiation.message || text("claw-qc-no-negotiation")));
      } else negotiationBox.append(el("p", "claw-qc-draft-copy", text("claw-qc-no-negotiation")));
      result.append(negotiationBox, el("p", "claw-qc-no-external", text("claw-qc-no-external")));
      syncAuth();
    }

    function syncAuth() {
      const enabled = Boolean(lastComparison && isAuthenticated() && !busy);
      docx.disabled = !enabled; docx.setAttribute("aria-disabled", String(!enabled));
      authNote.hidden = !lastComparison || isAuthenticated();
    }

    async function compareQuotes(event) {
      event.preventDefault(); if (busy) return;
      const body = payload();
      if (!body) { setStatus("claw-qc-error-input", "error"); return; }
      busy = true; compare.disabled = true; setStatus("claw-qc-status-running", "running");
      try { const data = await post(body); lastPayload = body; lastComparison = data.comparison; artifact = null; render(lastComparison); setStatus("claw-qc-status-success", "success"); }
      catch (error) { setStatus(error.key || "claw-qc-error-generic", "error"); }
      finally { busy = false; compare.disabled = false; syncAuth(); }
    }

    async function saveDocx() {
      if (!lastPayload || busy || !isAuthenticated()) { setStatus("claw-qc-error-auth", "error"); return; }
      busy = true; docx.disabled = true; setStatus("claw-qc-status-running", "running");
      try { const data = await post({ ...lastPayload, artifact: "docx" }); artifact = data.artifact || null; lastComparison = data.comparison; render(lastComparison); if (artifact?.document_id) { download.disabled = false; download.setAttribute("aria-disabled", "false"); } setStatus("claw-qc-status-saved", "success"); }
      catch (error) { setStatus(error.key || "claw-qc-error-storage", "error"); }
      finally { busy = false; syncAuth(); }
    }

    async function downloadDocx() {
      if (!artifact || !DOCUMENT_ID.test(String(artifact.document_id))) return;
      try {
        const response = await fetch(`${ARTIFACT_ROUTE}${encodeURIComponent(artifact.document_id)}`, { cache: "no-store" });
        if (!response.ok) throw new Error("download");
        const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
        anchor.href = url; anchor.download = artifact.filename || "quote-comparison.docx"; anchor.rel = "noopener"; document.body.append(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
      } catch (_) { setStatus("claw-qc-error-download", "error"); }
    }

    function syncVisibility() {
      const workspace = document.getElementById("clawWorkspace"); const shell = document.querySelector(".app-shell");
      const show = Boolean(workspace && shell && !workspace.hidden && shell.dataset.state === "claw" && workspace.dataset.view !== "inbox");
      section.hidden = !show;
      if (show) syncAuth();
    }

    MODES.forEach((value) => { const option = el("option", "", text(`claw-qc-mode-${value}`)); option.value = value; option.dataset.localeKey = `claw-qc-mode-${value}`; mode.append(option); });
    CURRENCIES.forEach((value) => { const option = el("option", "", value); option.value = value; currency.append(option); });
    mode.value = "balanced"; currency.value = "KRW";
    addRow(); addRow();
    add.addEventListener("click", addRow); form.addEventListener("submit", compareQuotes); docx.addEventListener("click", saveDocx); download.addEventListener("click", downloadDocx);
    window.addEventListener("padiem:localechange", () => { renumber(); if (lastComparison) render(lastComparison); });
    const workspace = document.getElementById("clawWorkspace"); const shell = document.querySelector(".app-shell"); const login = document.getElementById("loginButton");
    const observer = typeof MutationObserver === "function" ? new MutationObserver(syncVisibility) : null;
    if (observer && workspace) observer.observe(workspace, { attributes: true, attributeFilter: ["hidden", "data-view"] });
    if (observer && shell) observer.observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    if (observer && login) observer.observe(login, { attributes: true, attributeFilter: ["data-authenticated", "disabled"] });
    syncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", createModule, { once: true });
  else createModule();
})();
