// Account-owned settings only. The server attaches these rules to PC execution;
// this module never adds authority to a chat request or keeps it in local storage.
(function (root) {
  "use strict";
  const API = "/api/account/pc-delegations";
  const PAIRINGS = "/api/pc/pairings";
  const ACTIONS = ["write", "move", "delete"];
  const state = { rules: [], links: [], ready: false, busy: false, epoch: 0, status: "pc-delegation-empty" };
  let nodes;

  function copy(key) { return root.__padiemLocale?.text(key) || key; }
  function element(tag, className, text) {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  async function request(url, method = "GET", payload) {
    const response = await root.fetch(url, {
      method, credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(payload ? { "Content-Type": "application/json" } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {}),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }
  function validRules(body) { return body?.ok === true && body.version === 1 && Array.isArray(body.rules); }
  function activeLinks() { return state.links.filter((link) => link.state === "active"); }
  function paintControls() {
    const enabled = state.ready && !state.busy;
    const canAdd = enabled && activeLinks().length > 0;
    for (const name of ["device", "folder", "actions", "mode", "add"]) nodes[name].disabled = !canAdd;
    nodes.refresh.disabled = state.busy;
    nodes.status.textContent = copy(state.status);
    nodes.section.setAttribute("aria-busy", String(state.busy));
  }
  function paintDevices() {
    const selected = nodes.device.value;
    const links = activeLinks();
    nodes.device.replaceChildren();
    if (!links.length) {
      nodes.device.append(element("option", "", copy("pc-delegation-no-pc")));
      return;
    }
    for (const link of links) {
      const option = element("option", "", link.label || copy("pc-delegation-pc"));
      option.value = link.mesh_node_id;
      nodes.device.append(option);
    }
    if (links.some((link) => link.mesh_node_id === selected)) nodes.device.value = selected;
  }
  function paintList() {
    nodes.list.replaceChildren();
    if (!state.rules.length) {
      nodes.list.append(element("li", "pc-delegation-empty", copy("pc-delegation-empty")));
      return;
    }
    for (const rule of state.rules) {
      const item = element("li", "pc-delegation-rule");
      item.dataset.enabled = String(rule.enabled);
      const detail = element("div", "pc-delegation-rule-copy");
      const pc = state.links.find((link) => link.mesh_node_id === rule.device_id);
      detail.append(element("strong", "", pc?.label || copy("pc-delegation-pc")));
      detail.append(element("span", "", rule.folder));
      const actions = (rule.actions || []).filter((action) => ACTIONS.includes(action));
      detail.append(element("small", "", actions.map((action) => copy("pc-delegation-" + action)).join(" · ")));
      detail.append(element("small", "", copy(rule.enabled ? "pc-delegation-" + rule.mode : "pc-delegation-off")));
      const toggle = element("button", "settings-action", copy(rule.enabled ? "pc-delegation-disable" : "pc-delegation-enable"));
      toggle.type = "button";
      toggle.disabled = !state.ready || state.busy;
      toggle.addEventListener("click", () => { void save(state.rules.map((entry) => entry.id === rule.id ? { ...entry, enabled: !entry.enabled } : entry)); });
      item.append(detail, toggle);
      nodes.list.append(item);
    }
  }
  function paint() { paintDevices(); paintList(); paintControls(); }

  async function load() {
    const epoch = ++state.epoch;
    state.busy = true;
    state.ready = false;
    state.status = "pc-delegation-loading";
    paintControls();
    try {
      const [settings, pairings] = await Promise.all([request(API), request(PAIRINGS).catch(() => null)]);
      if (epoch !== state.epoch) return;
      state.rules = [];
      state.links = [];
      if (settings.status === 401) state.status = "pc-delegation-login";
      else if (settings.status !== 200 || !validRules(settings.body)) state.status = "pc-delegation-load-error";
      else {
        state.ready = true;
        state.rules = settings.body.rules;
        const links = pairings?.status === 200 && pairings.body?.ok === true && Array.isArray(pairings.body.links) ? pairings.body.links : [];
        state.links = links.filter((link) => link && typeof link.mesh_node_id === "string" && link.mesh_node_id);
        state.status = activeLinks().length ? "pc-delegation-ready" : "pc-delegation-no-pc-help";
      }
    } catch (_) {
      if (epoch !== state.epoch) return;
      state.rules = [];
      state.links = [];
      state.status = "pc-delegation-load-error";
    } finally {
      if (epoch === state.epoch) { state.busy = false; paint(); }
    }
  }
  async function save(rules) {
    if (!state.ready || state.busy) return false;
    const epoch = state.epoch;
    state.busy = true;
    state.status = "pc-delegation-saving";
    paint();
    try {
      const reply = await request(API, "PUT", { version: 1, rules });
      if (epoch !== state.epoch) return false;
      if (reply.status !== 200 || !validRules(reply.body)) {
        state.status = reply.status === 401 ? "pc-delegation-login" : "pc-delegation-save-error";
        state.ready = false;
        if (reply.status === 401) { state.ready = false; state.rules = []; state.links = []; }
        return false;
      }
      state.rules = reply.body.rules;
      state.status = "pc-delegation-saved";
      return true;
    } catch (_) {
      if (epoch === state.epoch) { state.ready = false; state.status = "pc-delegation-save-error"; }
      return false;
    } finally {
      if (epoch === state.epoch) { state.busy = false; paint(); }
    }
  }
  async function addRule() {
    const actions = ACTIONS.filter((action) => nodes[action].checked);
    const folder = nodes.folder.value.trim();
    if (!folder || !actions.length || !nodes.device.value) {
      state.status = "pc-delegation-required";
      paintControls();
      return;
    }
    const saved = await save([...state.rules, {
      id: root.crypto.randomUUID(), device_id: nodes.device.value, folder,
      actions, mode: nodes.mode.value, enabled: true,
    }]);
    if (saved) { nodes.folder.value = ""; for (const action of ACTIONS) nodes[action].checked = false; }
  }
  function boot() {
    const byId = (id) => root.document.getElementById(id);
    const section = byId("pcDelegationSettings");
    if (!section) return;
    nodes = { section, dialog: byId("settingsDialog"), status: byId("pcDelegationStatus"),
      device: byId("pcDelegationDevice"), folder: byId("pcDelegationFolder"), actions: byId("pcDelegationActions"),
      mode: byId("pcDelegationMode"), add: byId("pcDelegationAdd"), refresh: byId("pcDelegationRefresh"),
      list: byId("pcDelegationList"), editor: byId("pcDelegationEditor"),
      write: byId("pcDelegationWrite"), move: byId("pcDelegationMove"), delete: byId("pcDelegationDelete") };
    nodes.add.addEventListener("click", () => { void addRule(); });
    nodes.refresh.addEventListener("click", () => { void load(); });
    nodes.editor.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.tagName === "INPUT") event.preventDefault();
    });
    if (typeof root.MutationObserver === "function") new root.MutationObserver(() => {
      if (nodes.dialog.open) void load();
    }).observe(nodes.dialog, { attributes: true, attributeFilter: ["open"] });
    root.addEventListener("padiem:localechange", paint);
    root.addEventListener("padiem:auth-state", () => {
      ++state.epoch;
      state.ready = false;
      state.rules = [];
      state.links = [];
      state.busy = false;
      state.status = "pc-delegation-login";
      paint();
      if (nodes.dialog.open) void load();
    });
    paint();
    if (nodes.dialog.open) void load();
  }
  if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})(window);
