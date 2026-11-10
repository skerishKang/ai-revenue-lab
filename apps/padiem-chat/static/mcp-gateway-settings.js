// External AI (MCP OAuth) connections are now grouped per AI client:
// GET /api/account/mcp/oauth/clients returns client_id-based bundles, so
// repeated connections from the same AI appear as one card. A single
// "연결 해지" button revokes every active grant that this owner holds for
// that AI client. The individual token rows survive as a collapsed detail
// so they can still be inspected later. Personal (PAT) tokens are shown
// separately below because they have no AI client and are revoked one by one.
(function (root) {
  "use strict";
  const API = "/api/account/mcp";
  const CLIENTS_API = "/api/account/mcp/oauth/clients";
  const state = {
    tokens: [], approvals: [], links: [], clients: [],
    issued: "", ready: false, busy: false, epoch: 0,
    status: "mcp-settings-loading", clientsReady: false,
  };
  let nodes;
  const copy = (key, variables) => root.__padiemLocale?.text(key, variables) || key;
  const element = (tag, className, text) => {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const formatDateTime = (iso) => {
    if (!iso) return copy("mcp-settings-never");
    try {
      const d = new Date(iso);
      return d.toLocaleString("ko-KR", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch (_) {
      return iso;
    }
  };
  async function request(path, method = "GET", payload) {
    const init = {
      method, credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(payload ? { "Content-Type": "application/json" } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {}),
    };
    let reply = await root.fetch(path, init);
    if (reply.status === 401 && window.PadiemSharedSession) {
      if (await window.PadiemSharedSession.refreshOnce()) {
        reply = await root.fetch(path, init);
      }
    }
    return { status: reply.status, body: await reply.json().catch(() => null) };
  }
  function clearIssued() { state.issued = ""; if (nodes.token) nodes.token.value = ""; if (nodes.issued) nodes.issued.hidden = true; }
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
  function revokeButton(client) {
    const button = element("button", "settings-action settings-action-danger mcp-gateway-client-revoke", copy("mcp-ai-revoke"));
    button.type = "button";
    button.disabled = !state.ready || state.busy;
    button.dataset.clientId = client.client_id;
    button.addEventListener("click", () => { void revokeClient(client); });
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
      /* #7366: the chip carries its state so the CSS can draw the same state
       * dot the Chat composer PC chip uses (green online, grey offline). */
      online.dataset.state = link.online === true ? "online" : "offline";
      detail.append(online);
      const actions = element("div", "mcp-settings-actions");
      actions.append(actionButton("pc-links-disconnect", () => { void disconnectLink(link); }));
      item.append(detail, actions);
      list.append(item);
    }
  }
  function paintClients() {
    const list = nodes.clients;
    if (!list) return;
    list.replaceChildren();
    if (!state.clientsReady) {
      // Empty, failed and signed-out are three different states: a signed-out
      // visitor must not be told "no AI is connected", and a failed read must
      // offer a retry instead of pretending the list is empty.
      if (state.status === "mcp-settings-login") {
        const row = element("li", "mcp-gateway-client-login");
        row.append(element("p", "", copy("mcp-settings-login")));
        list.append(row);
      } else if (state.status === "mcp-settings-loading" || state.status === "mcp-settings-saving") {
        const row = element("li", "mcp-gateway-client-empty");
        row.append(element("p", "", copy("mcp-ai-loading")));
        list.append(row);
      } else {
        const row = element("li", "mcp-gateway-client-error");
        row.append(element("p", "", copy("mcp-ai-load-error")));
        const retry = element("button", "settings-action mcp-ai-primary mcp-gateway-client-retry", copy("mcp-ai-retry"));
        retry.type = "button";
        retry.addEventListener("click", () => { void load(); });
        row.append(retry);
        list.append(row);
      }
      return;
    }
    if (!state.clients.length) {
      const row = element("li", "mcp-gateway-client-empty");
      row.append(element("p", "", copy("mcp-ai-empty")));
      list.append(row);
      return;
    }
    for (const client of state.clients) {
      // The grouped API is the authority for counts, devices and the last use:
      // it stays truthful even when the individual token list is not loaded.
      const count = Number.isInteger(client.active_grants) ? client.active_grants : 0;
      const devices = Array.isArray(client.devices) ? client.devices : [];
      const item = element("li", "mcp-gateway-client-card");
      const info = element("div", "mcp-gateway-client-info");
      info.append(element("h4", "mcp-gateway-client-name", client.client_name || client.client_id));
      const meta = element("div", "mcp-gateway-client-meta");
      const countItem = element("div", "mcp-gateway-client-meta-item");
      countItem.append(element("span", "", copy("mcp-ai-connection-count", { count })));
      meta.append(countItem);
      const deviceItem = element("div", "mcp-gateway-client-meta-item");
      deviceItem.append(element("span", "", copy("mcp-ai-device-count", { count: devices.length })));
      meta.append(deviceItem);
      const usedItem = element("div", "mcp-gateway-client-meta-item");
      usedItem.append(element("span", "", copy("mcp-ai-token-used")));
      usedItem.append(element("span", "", `: ${formatDateTime(client.last_used_at)}`));
      meta.append(usedItem);
      info.append(meta);
      item.append(info);
      const actions = element("div", "mcp-gateway-client-actions");
      const more = element("button", "mcp-gateway-client-more", copy("mcp-ai-details"));
      more.type = "button";
      more.setAttribute("aria-expanded", "false");
      more.addEventListener("click", () => {
        // The grouped API carries the per-client detail (devices, scopes,
        // first grant, latest grant) — the individual token rows stay in the
        // collapsed legacy list below, not on the default screen.
        const existing = item.querySelector(".mcp-gateway-client-detail");
        if (existing) {
          existing.remove();
          more.textContent = copy("mcp-ai-details");
          more.setAttribute("aria-expanded", "false");
          return;
        }
        const detail = element("details", "mcp-gateway-client-detail");
        detail.open = true;
        detail.append(element("summary", "", copy("mcp-ai-show-details")));
        const ul = element("ul", "");
        for (const device of devices) {
          const li = element("li", "");
          li.append(element("strong", "", copy("mcp-settings-device")));
          li.append(element("span", "", pcName(device)));
          ul.append(li);
        }
        const createdLi = element("li", "");
        createdLi.append(element("strong", "", copy("mcp-settings-created")));
        createdLi.append(element("span", "", formatDateTime(client.created_at)));
        ul.append(createdLi);
        const latestLi = element("li", "");
        latestLi.append(element("strong", "", copy("mcp-ai-token-connected")));
        latestLi.append(element("span", "", formatDateTime(client.latest_grant_at)));
        ul.append(latestLi);
        detail.append(ul);
        item.append(detail);
        more.textContent = copy("mcp-ai-hidden-details");
        more.setAttribute("aria-expanded", "true");
      });
      actions.append(more);
      actions.append(revokeButton(client));
      item.append(actions);
      list.append(item);
    }
  }
  function paintTokens() {
    nodes.list.replaceChildren();
    const groups = new Map();
    for (const token of state.tokens) {
      if (token.client_id) continue;
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
      const expiry = group.tokens
        .map((token) => token.expires_at)
        .filter((value) => typeof value === "string" && value)
        .sort()[0];
      if (expiry) field(detail, "mcp-settings-token-expires", formatDateTime(expiry));
      item.append(detail);
      item.append(actionButton("mcp-settings-revoke", () => { void revokeGroup(group); }));
      nodes.list.append(item);
    }
  }
  async function confirmRevoke(message) {
    // The shared first-party dialog is the product's confirmation surface;
    // the native confirm stays only as a fallback for a bare module load.
    const dialog = root.PadiemConfirmDialog;
    if (dialog && typeof dialog.confirm === "function") {
      return await dialog.confirm({
        title: copy("mcp-ai-revoke-title"),
        message,
        confirmLabel: copy("mcp-ai-revoke"),
        cancelLabel: copy("cancel"),
      });
    }
    return Boolean((root.nativeConfirm ?? root.confirm)(message));
  }
  async function revokeClient(client) {
    const count = Number.isInteger(client.active_grants) ? client.active_grants : 0;
    const confirmText = count > 0
      ? copy("mcp-ai-revoke-confirm", { count })
      : copy("mcp-ai-revoke-confirm-default");
    if (!await confirmRevoke(confirmText)) return;
    clearIssued();
    await mutate(CLIENTS_API + "/" + encodeURIComponent(client.client_id), "DELETE", undefined, () => {
      state.clients = state.clients.filter((c) => c.client_id !== client.client_id);
      return true;
    });
    if (state.ready) state.status = "mcp-ai-revoked";
    paint();
  }
  async function revokeGroup(group) {
    clearIssued();
    for (const token of [...group.tokens]) {
      await mutate(API + "/tokens/" + encodeURIComponent(token.id), "DELETE", undefined, () => {
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
    const block = nodes.approvalsblock;
    if (block) block.hidden = state.approvals.length === 0;
    if (!state.approvals.length) return;
    for (const approval of state.approvals) {
      const item = element("li", "mcp-settings-card mcp-settings-approval");
      field(item, "mcp-settings-connection", approval.token_name);
      field(item, "mcp-settings-device", pcName(approval.device_id));
      field(item, "mcp-settings-tool", approval.tool_name);
      field(item, "mcp-settings-expires", approval.expires_at);
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
  function paint() { paintDevices(); paintPcLinks(); paintClients(); paintTokens(); paintApprovals(); controls(); }
  function reset() {
    ++state.epoch;
    state.tokens = []; state.approvals = []; state.links = []; state.clients = [];
    state.ready = false; state.busy = false; state.clientsReady = false;
    state.status = "mcp-settings-login";
    nodes.name.value = "";
    clearIssued(); paint();
  }
  async function load() {
    const epoch = ++state.epoch;
    clearIssued();
    state.ready = false; state.busy = true; state.clientsReady = false;
    state.status = "mcp-settings-loading";
    paint();
    try {
      const [tokens, approvals, pairings] = await Promise.all([
        request(API + "/tokens"), request(API + "/approvals"), request("/api/pc/pairings").catch(() => null),
      ]);
      if (epoch !== state.epoch) return;
      if (tokens.status === 401 || approvals.status === 401) {
        state.status = "mcp-settings-login";
      } else if (tokens.status !== 200 || tokens.body?.ok !== true || !Array.isArray(tokens.body.tokens)
          || approvals.status !== 200 || approvals.body?.ok !== true || !Array.isArray(approvals.body.approvals)) {
        state.status = "mcp-settings-load-error";
      } else {
        state.tokens = tokens.body.tokens; state.approvals = approvals.body.approvals;
        state.links = pairings?.status === 200 && pairings.body?.ok === true && Array.isArray(pairings.body.links)
          ? pairings.body.links.filter((link) => link && typeof link.mesh_node_id === "string" && link.mesh_node_id) : [];
        state.ready = true;
        try {
          const clients = await request(CLIENTS_API);
          if (epoch !== state.epoch) return;
          if (clients.status === 401) {
            state.status = "mcp-settings-login";
          } else if (clients.status !== 200 || clients.body?.ok !== true || !Array.isArray(clients.body.clients)) {
            state.status = "mcp-settings-load-error";
          } else {
            state.clients = clients.body.clients;
            state.clientsReady = true;
            state.status = activeLinks().length ? "mcp-settings-ready" : "mcp-settings-no-pc-help";
          }
        } catch (_) {
          state.status = "mcp-settings-load-error";
        }
      }
    } catch (_) {
      if (epoch === state.epoch) {
        state.tokens = []; state.approvals = []; state.links = []; state.clients = [];
        state.clientsReady = false;
        state.status = "mcp-settings-load-error";
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
        if (reply.status === 401) { state.tokens = []; state.approvals = []; state.links = []; state.clients = []; state.clientsReady = false; clearIssued(); }
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
      state.tokens.unshift({ id: body.id, name: body.name, device_id: body.device_id,
        created_at: body.created_at, expires_at: body.expires_at,
        last_used_at: body.last_used_at, revoked_at: body.revoked_at });
      state.issued = body.token; nodes.token.value = state.issued; if (nodes.issued) nodes.issued.hidden = false;
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
      approvalsblock: byId("mcpGatewayApprovalsBlock"), pclinks: byId("mcpGatewayPcLinks"),
      clients: byId("mcpGatewayClientsList"), status: byId("mcpGatewayStatus"),
      list: byId("mcpGatewayList"),
      refresh: byId("mcpGatewayRefresh"),
      approvals: byId("mcpGatewayApprovals"), issued: byId("mcpGatewayIssued"), token: byId("mcpGatewayToken"),
      copy: byId("mcpGatewayCopy"), hide: byId("mcpGatewayHide"), editor: byId("mcpGatewayEditor"),
      name: byId("mcpGatewayName"), device: byId("mcpGatewayDevice"),
      issue: byId("mcpGatewayIssue"),
      endpoint: byId("mcpGatewayEndpoint") };
    nodes.endpoint.value = root.location.origin + "/api/mcp";
    nodes.issue.addEventListener("click", () => { void issue(); });
    nodes.refresh.addEventListener("click", () => { void load(); });
    nodes.copy.addEventListener("click", () => { void copyToken(); });
    nodes.hide.addEventListener("click", () => { clearIssued(); state.status = "mcp-settings-ready"; controls(); });
    nodes.editor.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.tagName === "INPUT") event.preventDefault();
    });
    root.addEventListener("padiem:advanced-settings-open", () => { void load(); });
    root.addEventListener("padiem:advanced-settings-close", () => { reset(); });
    root.addEventListener("padiem:localechange", paint);
    root.addEventListener("padiem:auth-state", () => { reset(); });
    paint();
  }
  if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})(typeof window !== "undefined" ? window : this);
