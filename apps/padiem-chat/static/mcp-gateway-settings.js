// Personal credentials are displayed only after issuance and cleared when this
// dialog closes. All PC authority and approval decisions remain on the server.
(function (root) {
  "use strict";
  const API = "/api/account/mcp";
  const state = { tokens: [], approvals: [], links: [], issued: "", ready: false, busy: false, epoch: 0, status: "mcp-settings-help" };
  let nodes;
  const copy = (key) => root.__padiemLocale?.text(key) || key;
  function element(tag, className, text) {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  async function request(path, method = "GET", payload) {
    const init = {
      method, credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(payload ? { "Content-Type": "application/json" } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {}),
    };
    let reply = await root.fetch(path, init);
    // #6460 4-2: one silent shared-session refresh and one retry when the
    // 15-minute access cookie expired under the screen's 14-minute tick.
    if (reply.status === 401 && window.PadiemSharedSession) {
      if (await window.PadiemSharedSession.refreshOnce()) {
        reply = await root.fetch(path, init);
      }
    }
    return { status: reply.status, body: await reply.json().catch(() => null) };
  }
  function clearIssued() { state.issued = ""; nodes.token.value = ""; nodes.issued.hidden = true; }
  function activeLinks() { return state.links.filter((link) => link.state === "active"); }
  function pcName(id) { return state.links.find((link) => link.mesh_node_id === id)?.label || id; }
  function controls() {
    const canIssue = state.ready && !state.busy && activeLinks().length > 0 && !state.issued;
    for (const key of ["device", "name", "issue"]) nodes[key].disabled = !canIssue;
    nodes.refresh.disabled = state.busy;
    nodes.copy.disabled = !state.issued;
    nodes.status.textContent = copy(state.status);
    nodes.section.setAttribute("aria-busy", String(state.busy));
  }
  function actionButton(label, handler) {
    const button = element("button", "settings-action", copy(label));
    button.type = "button";
    button.disabled = !state.ready || state.busy;
    button.addEventListener("click", handler);
    return button;
  }
  function field(parent, key, value) {
    const line = element("div", "mcp-settings-field");
    line.append(element("strong", "", copy(key)), element("span", "", value));
    parent.append(line);
  }
  function paintDevices() {
    const selected = nodes.device.value, links = activeLinks();
    nodes.device.replaceChildren();
    if (!links.length) nodes.device.append(element("option", "", copy("mcp-settings-no-pc")));
    for (const link of links) {
      const option = element("option", "", link.label || link.mesh_node_id);
      option.value = link.mesh_node_id;
      nodes.device.append(option);
    }
    if (links.some((link) => link.mesh_node_id === selected)) nodes.device.value = selected;
  }
  function paintPcLinks() {
    const list = nodes.pclinks;
    if (!list) return;
    list.replaceChildren();
    if (!activeLinks().length) {
      const row = element("li", "mcp-settings-card");
      row.append(element("span", "", copy("pc-links-empty")));
      list.append(row);
      return;
    }
    for (const link of activeLinks()) {
      const item = element("li", "mcp-settings-card"), detail = element("div", "mcp-settings-detail");
      detail.append(element("strong", "", link.label || link.mesh_node_id));
      const online = element("span", "mcp-settings-status",
        copy(link.online === true ? "pc-links-online" : "pc-links-offline"));
      detail.append(online);
      const actions = element("div", "mcp-settings-actions");
      actions.append(actionButton("pc-links-disconnect", () => { void disconnectLink(link); }));
      item.append(detail, actions);
      list.append(item);
    }
  }
  async function disconnectLink(link) {
    await mutate("/api/pc/pairings/" + encodeURIComponent(link.link_id), "DELETE", undefined, () => true);
    state.links = state.links.filter((row) => row.link_id !== link.link_id);
    paintPcLinks();
  }
  function paintTokens() {
    // One row per connected AI (client name): the most recently used token
    // carries the row's timestamp, and 연결 끊기 revokes every token of that
    // AI in one go.
    nodes.list.replaceChildren();
    const groups = new Map();
    for (const token of state.tokens) {
      if (token.revoked_at) continue;
      const group = groups.get(token.name) || { name: token.name, tokens: [] };
      if (!groups.has(token.name)) groups.set(token.name, group);
      group.tokens.push(token);
    }
    if (!groups.size) {
      nodes.list.append(element("li", "", copy("mcp-settings-empty")));
      return;
    }
    for (const group of groups.values()) {
      const latest = [...group.tokens]
        .filter((token) => token.last_used_at)
        .sort((a, b) => (a.last_used_at < b.last_used_at ? 1 : -1))[0];
      const devices = [...new Set(group.tokens.map((token) => pcName(token.device_id)))];
      const item = element("li", "mcp-settings-card"), detail = element("div", "mcp-settings-detail");
      detail.append(element("strong", "", group.name));
      field(detail, "mcp-settings-device", devices.join(", "));
      field(detail, "mcp-settings-used", latest?.last_used_at || copy("mcp-settings-never"));
      field(detail, "mcp-settings-tokens", String(group.tokens.length));
      item.append(detail);
      item.append(actionButton("mcp-settings-revoke", () => { void revokeGroup(group); }));
      nodes.list.append(item);
    }
  }
  async function revokeGroup(group) {
    // Revoking the AI retires every issued token and, with them, the pending
    // approvals that rode on those tokens — the same cleanup one-by-one
    // revocation did.
    clearIssued();
    for (const token of [...group.tokens]) {
      await mutate("/api/account/mcp/tokens/" + encodeURIComponent(token.id), "DELETE", undefined, () => {
        state.tokens = state.tokens.filter((row) => row.id !== token.id);
        state.approvals = state.approvals.filter((approval) => approval.token_id !== token.id);
        return true;
      });
    }
    state.status = "mcp-settings-revoked";
    paint();
  }
  function paintApprovals() {
    nodes.approvals.replaceChildren();
    // The 확인이 필요한 작업 block only exists while work is waiting.
    const block = nodes.approvalsblock;
    if (block) block.hidden = state.approvals.length === 0;
    if (!state.approvals.length) return;
    for (const approval of state.approvals) {
      const item = element("li", "mcp-settings-card mcp-settings-approval");
      field(item, "mcp-settings-connection", approval.token_name);
      field(item, "mcp-settings-device", pcName(approval.device_id));
      field(item, "mcp-settings-tool", approval.tool_name);
      field(item, "mcp-settings-expires", approval.expires_at);
      // Show the complete exact request, including write content, move destination,
      // deletion path and options. A digest alone is not enough to approve a change.
      const args = approval.arguments || {};
      const labels = { path: "mcp-settings-path", source: "mcp-settings-source", source_path: "mcp-settings-source",
        destination: "mcp-settings-destination", destination_path: "mcp-settings-destination", content: "mcp-settings-content" };
      for (const [key, value] of Object.entries(args)) {
        if (labels[key] && typeof value === "string") field(item, labels[key], value);
      }
      const details = element("details", "mcp-settings-arguments");
      details.open = true;
      details.append(element("summary", "", copy("mcp-settings-exact-request")), element("pre", "", JSON.stringify(args, null, 2)));
      item.append(details);
      if (approval.status === "pending") {
        const actions = element("div", "mcp-settings-actions");
        actions.append(actionButton("mcp-settings-approve", () => { void decide(approval, "approve"); }),
          actionButton("mcp-settings-deny", () => { void decide(approval, "deny"); }));
        item.append(actions);
      } else item.append(element("p", "", copy(approval.status === "approved" ? "mcp-settings-approved" : "mcp-settings-denied")));
      nodes.approvals.append(item);
    }
  }
  function paint() { paintDevices(); paintPcLinks(); paintTokens(); paintApprovals(); controls(); }
  function reset() {
    ++state.epoch;
    state.tokens = []; state.approvals = []; state.links = [];
    state.ready = false; state.busy = false; state.status = "mcp-settings-login";
    nodes.name.value = "";
    clearIssued(); paint();
  }
  async function load() {
    const epoch = ++state.epoch;
    clearIssued();
    state.ready = false; state.busy = true; state.status = "mcp-settings-loading";
    paint();
    try {
      const [tokens, approvals, pairings] = await Promise.all([
        request(API + "/tokens"), request(API + "/approvals"), request("/api/pc/pairings").catch(() => null),
      ]);
      if (epoch !== state.epoch) return;
      state.tokens = []; state.approvals = []; state.links = [];
      if (tokens.status === 401 || approvals.status === 401) state.status = "mcp-settings-login";
      else if (tokens.status !== 200 || tokens.body?.ok !== true || !Array.isArray(tokens.body.tokens)
          || approvals.status !== 200 || approvals.body?.ok !== true || !Array.isArray(approvals.body.approvals)) {
        state.status = "mcp-settings-load-error";
      } else {
        state.tokens = tokens.body.tokens; state.approvals = approvals.body.approvals;
        state.links = pairings?.status === 200 && pairings.body?.ok === true && Array.isArray(pairings.body.links)
          ? pairings.body.links.filter((link) => link && typeof link.mesh_node_id === "string" && link.mesh_node_id) : [];
        state.ready = true;
        state.status = activeLinks().length ? "mcp-settings-ready" : "mcp-settings-no-pc-help";
      }
    } catch (_) {
      if (epoch === state.epoch) {
        state.tokens = []; state.approvals = []; state.links = []; state.status = "mcp-settings-load-error";
      }
    } finally { if (epoch === state.epoch) { state.busy = false; paint(); } }
  }
  async function mutate(path, method, payload, accept) {
    if (!state.ready || state.busy) return;
    const epoch = state.epoch;
    state.busy = true; state.status = "mcp-settings-saving"; paint();
    try {
      const reply = await request(path, method, payload);
      if (epoch !== state.epoch) return;
      if (![200, 201].includes(reply.status) || reply.body?.ok !== true || !accept(reply.body)) {
        state.ready = false;
        state.status = reply.status === 401 ? "mcp-settings-login" : "mcp-settings-save-error";
        if (reply.status === 401) { state.tokens = []; state.approvals = []; state.links = []; clearIssued(); }
      }
    } catch (_) {
      if (epoch === state.epoch) { state.ready = false; state.status = "mcp-settings-save-error"; }
    } finally { if (epoch === state.epoch) { state.busy = false; paint(); } }
  }
  async function issue() {
    const name = nodes.name.value.trim(), device_id = nodes.device.value;
    if (!name || !activeLinks().some((link) => link.mesh_node_id === device_id)) {
      state.status = "mcp-settings-required"; controls(); return;
    }
    if (state.issued) return;
    await mutate(API + "/tokens", "POST", { name, device_id }, (body) => {
      if (typeof body.token !== "string" || !body.token || !body.id) return false;
      // Keep only metadata in the list; the credential never enters a list row.
      state.tokens.unshift({ id: body.id, name: body.name, device_id: body.device_id,
        created_at: body.created_at, last_used_at: body.last_used_at, revoked_at: body.revoked_at });
      state.issued = body.token; nodes.token.value = state.issued; nodes.issued.hidden = false;
      nodes.name.value = ""; state.status = "mcp-settings-issued";
      return true;
    });
  }
  async function revoke(id) {
    clearIssued();
    await mutate(API + "/tokens/" + encodeURIComponent(id), "DELETE", undefined, () => {
      state.tokens = state.tokens.filter((token) => token.id !== id);
      state.approvals = state.approvals.filter((approval) => approval.token_id !== id);
      state.status = "mcp-settings-revoked";
      return true;
    });
  }
  async function decide(approval, decision) {
    await mutate(API + "/approvals/" + encodeURIComponent(approval.id), "POST", { decision, request_digest: approval.request_digest }, (body) => {
      if (!body.approval || body.approval.id !== approval.id || body.approval.request_digest !== approval.request_digest
          || body.approval.status !== (decision === "approve" ? "approved" : "denied")) return false;
      state.approvals = state.approvals.map((entry) => entry.id === approval.id ? body.approval : entry);
      state.status = decision === "approve" ? "mcp-settings-approved" : "mcp-settings-denied";
      return true;
    });
  }
  async function copyToken() {
    if (!state.issued) return;
    const epoch = state.epoch;
    try {
      await root.navigator.clipboard.writeText(state.issued);
      if (epoch === state.epoch && state.issued) state.status = "mcp-settings-copied";
    } catch (_) { if (epoch === state.epoch && state.issued) state.status = "mcp-settings-copy-error"; }
    controls();
  }
  function boot() {
    const byId = (id) => root.document.getElementById(id);
    if (!byId("mcpGatewaySettings")) return;
    nodes = { section: byId("mcpGatewaySettings"),
      approvalsblock: byId("mcpGatewayApprovalsBlock"), pclinks: byId("mcpGatewayPcLinks") };
    for (const name of ["Status", "Endpoint", "Device", "Name", "Issue", "Refresh", "List", "Approvals", "ApprovalsBlock", "PcLinks", "Issued", "Token", "Copy", "Hide", "Editor"]) {
      nodes[name.toLowerCase()] = byId("mcpGateway" + name);
    }
    nodes.endpoint.value = root.location.origin + "/api/mcp";
    nodes.issue.addEventListener("click", () => { void issue(); });
    nodes.refresh.addEventListener("click", () => { void load(); });
    nodes.copy.addEventListener("click", () => { void copyToken(); });
    nodes.hide.addEventListener("click", () => { clearIssued(); state.status = "mcp-settings-ready"; controls(); });
    nodes.editor.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.tagName === "INPUT") event.preventDefault();
    });
    // The module lives in the advanced settings page now: the page open event
    // carries the load, the auth-state reset stays the same.
    root.addEventListener("padiem:advanced-settings-open", () => { void load(); });
    root.addEventListener("padiem:advanced-settings-close", () => { reset(); });
    root.addEventListener("padiem:localechange", paint);
    root.addEventListener("padiem:auth-state", () => { reset(); });
    paint();
  }
  if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})(window);
