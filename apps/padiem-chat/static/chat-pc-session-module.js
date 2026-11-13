(() => {
  "use strict";
  // Presentation only. The server owns session authority and confirmation.
  // No session is discovered from answer text, history or browser storage.
  const cards = new Map();
  const JOB = /^dsp_[0-9a-f]{32}$/;
  const LIMIT = 32768;
  let generation = 0;
  let owner = null;
  let conversation = null;
  const panel = () => document.getElementById("chatPcSessionPanel");
  const cid = () => window.PadiemChatConversationState?.getConversationId?.() || null;
  const identity = () => {
    const auth = window.PadiemAuthSession?.get?.();
    return auth?.authenticated === true ? auth.ownerKey : null;
  };
  const t = (key, vars) => window.__padiemLocale?.text?.("pc-session-" + key, vars) || key;

  function clear() {
    generation += 1;
    for (const card of cards.values()) {
      card.secret.value = "";
      card.input.value = "";
      card.controller?.abort();
    }
    cards.clear();
    const root = panel();
    if (root) { root.replaceChildren(); root.hidden = true; }
    owner = identity();
    conversation = cid();
  }

  function sync(event) {
    const nextOwner = identity(), nextConversation = cid();
    if (nextOwner !== owner || event?.detail?.reset
        || (conversation !== nextConversation && (conversation !== null || cards.size))) clear();
    owner = nextOwner;
    conversation = nextConversation;
  }

  function captureScope() {
    sync();
    return Object.freeze({ generation, owner, conversation });
  }

  function current(scope, responseConversation) {
    return scope && scope.generation === generation && scope.owner && scope.owner === identity()
      && cid() === responseConversation
      && (scope.conversation === null || scope.conversation === responseConversation);
  }

  function element(tag, className, parent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (parent) parent.appendChild(node);
    return node;
  }

  function label(node, key) {
    node.dataset.sessionLabel = key;
    node.textContent = t(key);
  }

  function button(parent, key, handler) {
    const node = element("button", "", parent);
    node.type = "button";
    label(node, key);
    node.addEventListener("click", handler);
    return node;
  }

  function maskedInput(parent, note) {
    // Never expose a textarea until the actual computed mask is verified.
    let field = element("textarea", "pc-session-secret", parent);
    field.hidden = true;
    field.value = "";
    field.style.setProperty("-webkit-text-security", "disc", "important");
    const masked = window.CSS?.supports?.("-webkit-text-security", "disc") === true
      && window.getComputedStyle(field).getPropertyValue("-webkit-text-security") === "disc";
    if (!masked) {
      field.remove();
      field = element("input", "pc-session-secret", parent);
      field.type = "password";
      // Password inputs silently strip line breaks. Refuse that paste instead.
      field.addEventListener("paste", (event) => {
        if (/[\r\n]/.test(event.clipboardData?.getData("text") || "")) {
          event.preventDefault(); field.value = ""; label(note, "multiline-unavailable");
        }
      });
      field.addEventListener("drop", (event) => { event.preventDefault(); field.value = ""; });
    }
    field.hidden = false;
    field.autocomplete = "off";
    field.spellcheck = false;
    field.setAttribute("autocapitalize", "off");
    field.setAttribute("data-lpignore", "true");
    field.setAttribute("aria-label", t("secret"));
    return field;
  }

  function repaint(card) {
    const ended = card.snapshot.alive === false || Boolean(card.snapshot.ended);
    if (ended) { card.secret.value = ""; card.input.value = ""; }
    label(card.state, ended ? "ended" : card.snapshot.status === "waiting_approval" ? "confirm" : "running");
    card.hint.hidden = ended || card.snapshot.prompt_kind !== "secret";
    if (!card.hint.hidden) label(card.hint, "secret-hint");
    for (const node of card.controls) node.disabled = card.busy;
    card.input.disabled = card.busy || ended;
    card.secret.disabled = card.busy || ended;
    card.send.disabled = card.busy || ended;
    card.sendSecret.disabled = card.busy || ended;
    card.stop.disabled = card.busy || ended;
    card.root.setAttribute("aria-busy", String(card.busy));
  }

  function makeCard(job, responseConversation) {
    const root = element("section", "pc-session-card", panel());
    const heading = element("h3", "", root); label(heading, "title");
    const receipt = element("div", "pc-session-receipt", root);
    element("code", "", receipt).textContent = job;
    const card = { root, job, conversation: responseConversation, snapshot: {}, next: 0,
      output: "", busy: false, controller: null, controls: [] };
    button(receipt, "copy", async () => {
      try { await navigator.clipboard.writeText(job); label(card.note, "copied"); }
      catch (_) { label(card.note, "copy-failed"); }
    });
    card.state = element("p", "pc-session-state", root);
    card.state.setAttribute("role", "status");
    card.hint = element("p", "pc-session-note", root);
    card.outputNode = element("pre", "pc-session-output", root);
    card.outputNode.setAttribute("aria-label", t("output"));
    card.outputNode.tabIndex = 0;
    const actions = element("div", "pc-session-actions", root);
    card.controls.push(button(actions, "read", () => request(card, "read")));
    card.controls.push(button(actions, "status", () => request(card, "status")));
    card.stop = button(actions, "stop", () => request(card, "stop"));
    card.controls.push(card.stop);
    const ordinary = element("label", "pc-session-field", root);
    label(element("span", "", ordinary), "input");
    card.input = element("textarea", "", ordinary);
    card.input.rows = 2;
    card.input.setAttribute("aria-label", t("input"));
    card.send = button(root, "send", () => send(card, false));
    const secret = element("label", "pc-session-field", root);
    label(element("span", "", secret), "secret");
    card.note = element("p", "pc-session-note", root);
    card.note.setAttribute("role", "status");
    card.secret = maskedInput(secret, card.note);
    card.sendSecret = button(root, "send-secret", () => send(card, true));
    label(element("p", "pc-session-help", root), "help");
    return card;
  }

  function snapshot(data) {
    if (!data || !["pc_session", "pc_session_confirm"].includes(data.decision_status)
        || typeof data.conversation_id !== "string" || !data.conversation_id) return null;
    const value = data.pc_session;
    if (!value || typeof value !== "object" || !JOB.test(value.job_id)
        || (value.session != null && value.session !== value.job_id.slice(4))) return null;
    const clean = { job_id: value.job_id };
    for (const key of ["status", "code", "ended", "backend", "prompt_kind", "waiting_hint"]) {
      if (typeof value[key] === "string") clean[key] = value[key].slice(0, 120);
    }
    for (const key of ["alive", "ok", "confirmation_required"]) {
      if (typeof value[key] === "boolean") clean[key] = value[key];
    }
    for (const key of ["offset", "next_offset", "end_offset", "exit_code"]) {
      if (Number.isSafeInteger(value[key]) && value[key] >= 0) clean[key] = value[key];
    }
    if (Array.isArray(value.features)) clean.features = value.features.filter((x) => typeof x === "string").slice(0, 20);
    if (typeof value.output === "string") clean.output = value.output.slice(-LIMIT);
    return clean;
  }

  function render(data, scope) {
    const value = snapshot(data);
    if (!value || !panel() || !current(scope, data.conversation_id)) return false;
    let card = cards.get(value.job_id);
    if (!card) {
      card = makeCard(value.job_id, data.conversation_id);
      cards.set(value.job_id, card);
    }
    if (typeof value.output === "string") {
      // Cursors are server byte offsets, never JavaScript string lengths.
      if (Number.isSafeInteger(value.next_offset) && value.next_offset >= card.next) {
        if (value.offset === card.next) card.output += value.output;
        else if (value.offset > card.next || card.next === 0) card.output = value.output;
        card.next = value.next_offset;
        card.output = card.output.slice(-LIMIT);
        card.outputNode.textContent = card.output;
      }
    }
    card.snapshot = { ...card.snapshot, ...value };
    if (data.decision_status === "pc_session_confirm") {
      label(card.note, "confirm");
      if (card.secretChars) card.note.textContent = t("secret-confirm", { count: card.secretChars });
    }
    else if (value.ok === false || value.status === "failed") label(card.note,
      value.code === "pc_session_input_expired" ? "expired" : "failed");
    else { card.note.textContent = ""; delete card.note.dataset.sessionLabel; card.secretChars = 0; }
    repaint(card);
    panel().hidden = false;
    return true;
  }

  async function request(card, op, input) {
    if (card.busy || cards.get(card.job) !== card) return;
    const scope = captureScope();
    if (!current(scope, card.conversation)) return;
    card.busy = true;
    card.controller = new AbortController();
    repaint(card);
    let payload = { conversation_id: card.conversation, job_id: card.job, op,
      offset: card.next, length: LIMIT, ...input };
    if (op === "read" || op === "status") payload.wait_ms = op === "read" ? 1000 : 0;
    try {
      const pending = window.PadiemChatTransport.requestPcSession(payload, card.controller.signal);
      // The transport serializes synchronously. Do not retain a secret draft.
      payload = null; input = null;
      const data = await pending;
      if (current(scope, card.conversation) && cards.get(card.job) === card) render(data, scope);
    } catch (error) {
      if (!current(scope, card.conversation) || cards.get(card.job) !== card) return;
      if (error?.code === "pc_session_disabled" || error?.status === 401 || error?.status === 403) clear();
      else if (error?.name !== "AbortError") label(card.note,
        error?.code === "pc_session_input_expired" ? "expired" : "failed");
    } finally {
      payload = null; input = null;
      card.busy = false; card.controller = null;
      if (cards.get(card.job) === card) repaint(card);
    }
  }

  function send(card, secret) {
    if (card.busy) return;
    const field = secret ? card.secret : card.input;
    let text = field.value;
    // Clear before starting fetch, including validation and failure paths.
    field.value = "";
    if (Array.from(text).length > 4000) { text = ""; label(card.note, "too-long"); return; }
    if (secret && !text) return;
    card.secretChars = secret ? Array.from(text).length : 0;
    void request(card, "input", text ? { text, enter: true, secret } : { key: "enter" });
    text = "";
  }

  function init() {
    sync();
    window.addEventListener("padiem:conversation-state", sync);
    window.addEventListener("padiem:auth-state", sync);
    window.addEventListener("padiem:account-changed", clear);
    window.addEventListener("padiem:auth-changed", clear);
    window.addEventListener("pagehide", clear);
    window.addEventListener("padiem:localechange", () => {
      for (const card of cards.values()) {
        for (const node of card.root.querySelectorAll("[data-session-label]")) label(node, node.dataset.sessionLabel);
        card.input.setAttribute("aria-label", t("input"));
        card.secret.setAttribute("aria-label", t("secret"));
        card.outputNode.setAttribute("aria-label", t("output"));
        repaint(card);
      }
    });
    const shell = document.querySelector(".app-shell");
    if (shell && typeof MutationObserver === "function") new MutationObserver(() => {
      if (!["chat", "claw"].includes(shell.dataset.state)) clear();
    }).observe(shell, { attributes: true, attributeFilter: ["data-state"] });
  }

  window.PadiemChatPcSessionModule = Object.freeze({ captureScope, render, clear });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
