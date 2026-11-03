const QUEUE_KEY = "storymemory.syncQueue.v2";
const DEVICE_KEY = "storymemory.installationId.v1";
const SCOPES = ["progress", "annotations", "bookmarks"];

function readJson(storage, key, fallback) {
  try {
    const value = JSON.parse(storage.getItem(key) || "null");
    return value && typeof value === "object" && !Array.isArray(value) ? value : fallback;
  } catch { return fallback; }
}

function keyFor(record) { return record.type + "\u001f" + record.id; }
function scopeFor(record) {
  return record.type === "progress" ? "progress" : record.type === "bookmark" ? "bookmarks" : "annotations";
}
async function recordDigest(record) {
  const bytes = new TextEncoder().encode(JSON.stringify(record));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function createStoryMemorySyncClient({
  fetcher = fetch,
  storage = globalThis.localStorage,
  getRecords = () => [],
  applyRemote = () => {},
  deviceId,
  isOnline = () => globalThis.navigator?.onLine !== false
} = {}) {
  const localDevice = deviceId || (() => {
    let value = storage?.getItem(DEVICE_KEY);
    if (!value) {
      value = globalThis.crypto?.randomUUID?.() || "inst-" + Date.now() + "-" + Math.random().toString(36).slice(2);
      try { storage?.setItem(DEVICE_KEY, value); } catch { /* local reading remains available */ }
    }
    return value;
  })();
  let status = { enabled: false, ready: false, consentedScopes: [] };
  let flushPromise = null;
  let abortController = null;

  function loadState() {
    const state = readJson(storage, QUEUE_KEY, {});
    return { pending: Array.isArray(state.pending) ? state.pending : [], hashes: state.hashes || {}, revisions: state.revisions || {} };
  }
  function saveState(state) {
    try { storage?.setItem(QUEUE_KEY, JSON.stringify(state)); } catch { /* local records remain the source of truth */ }
  }
  function headers(extra = {}) {
    return { accept: "application/json", "x-storymemory-device-id": localDevice, ...extra };
  }
  async function request(path, { method = "GET", body, signal } = {}) {
    const init = {
      method, credentials: "same-origin", cache: "no-store", signal,
      headers: headers(body === undefined ? {} : { "content-type": "application/json" }),
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    };
    let response = await fetcher(path, init);
    if (response.status === 401) {
      try {
        const authResponse = await fetcher("/auth/status", { method: "GET", credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" } });
        const authStatus = await authResponse.json();
        if (authResponse.ok && authStatus?.authenticated === true) response = await fetcher(path, init);
      } catch { /* the original 401 remains the result */ }
    }
    let payload = null;
    try { payload = await response.json(); } catch { /* callers only use a stable error code */ }
    if (!response.ok && !(response.status === 503 && payload?.error === "sync_preparing")) {
      const error = new Error(payload?.error || "sync_request_failed");
      error.status = response.status;
      throw error;
    }
    return { response, payload: payload || {} };
  }
  async function refreshStatus() {
    const result = await request("/api/sync/status");
    status = {
      enabled: result.payload.enabled === true,
      ready: result.payload.ready === true,
      consentedScopes: Array.isArray(result.payload.consentedScopes) ? result.payload.consentedScopes.filter((x) => SCOPES.includes(x)) : [],
      migrationRequired: result.payload.migrationRequired === true,
      message: result.payload.message || null
    };
    return status;
  }
  async function snapshot(scopes = status.consentedScopes) {
    const query = encodeURIComponent(scopes.join(","));
    const result = await request("/api/sync/snapshot?scopes=" + query);
    return Array.isArray(result.payload.records) ? result.payload.records : [];
  }
  function rememberServerRecord(state, record) {
    if (!record || typeof record.type !== "string" || typeof record.id !== "string") return;
    const key = keyFor(record);
    state.revisions[key] = Number(record.revision || 0);
    if (record.deleted) delete state.hashes[key];
  }
  async function saveRemoteSnapshot(scopes, { preserveKeys = [] } = {}) {
    const rows = await snapshot(scopes);
    const state = loadState();
    for (const record of rows) rememberServerRecord(state, record);
    saveState(state);
    const preserve = preserveKeys instanceof Set ? preserveKeys : new Set(preserveKeys);
    await applyRemote(rows.filter((record) => !preserve.has(keyFor(record))));
    return rows;
  }
  async function sendRecord(record, mode, signal, baseRevisionOverride, scopes = null) {
    const state = loadState();
    const key = keyFor(record);
    const pendingKey = { type: record.type, id: record.id };
    state.pending = state.pending.filter((item) => !(item.type === pendingKey.type && item.id === pendingKey.id));
    const pendingIndex = state.pending.findIndex((item) => item.type === pendingKey.type && item.id === pendingKey.id);
    if (pendingIndex >= 0) state.pending.splice(pendingIndex, 1);
    state.pending.push({ ...pendingKey, baseRevision: Number(baseRevisionOverride ?? state.revisions[key] ?? 0) });
    saveState(state);
    const result = await request("/api/sync/changes", {
      method: "POST", signal,
      body: { mode, ...(scopes ? { scopes } : {}), record: { ...record, baseRevision: Number(baseRevisionOverride ?? state.revisions[key] ?? 0) } }
    });
    const latest = loadState();
    rememberServerRecord(latest, result.payload.record);
    latest.pending = latest.pending.filter((item) => !(item.type === record.type && item.id === record.id));
    saveState(latest);
    return result.payload;
  }
  async function queueLocalChanges(scopes) {
    const state = loadState();
    const records = (await getRecords(scopes)).filter((record) => scopes.includes(scopeFor(record)));
    for (const record of records) {
      const key = keyFor(record);
      if (state.hashes[key] === await recordDigest(record) || state.pending.some((item) => keyFor(item) === key)) continue;
      state.pending.push({ type: record.type, id: record.id, baseRevision: Number(state.revisions[key] || 0) });
    }
    saveState(state);
    return state.pending.length;
  }
  async function migrate(scopes, { signal, onProgress } = {}) {
    const selected = [...new Set(scopes)].filter((scope) => SCOPES.includes(scope)).sort();
    if (!selected.length) throw new Error("sync_scope_required");
    await refreshStatus();
    if (!status.enabled) throw new Error("sync_disabled");
    if (!status.ready) throw new Error("sync_preparing");
    abortController = new AbortController();
    const activeSignal = signal || abortController.signal;
    const records = (await getRecords(selected)).filter((record) => selected.includes(scopeFor(record)));
    let completed = 0;
    try {
      for (const record of records) {
        if (activeSignal.aborted) throw new DOMException("Aborted", "AbortError");
        await sendRecord(record, "migration", activeSignal, undefined, selected);
        completed++;
        onProgress?.({ completed, total: records.length });
      }
      await request("/api/sync/consent", { method: "POST", signal: activeSignal, body: { scopes: selected } });
      await refreshStatus();
      await saveRemoteSnapshot(status.consentedScopes);
      return { completed, scopes: status.consentedScopes };
    } finally {
      abortController = null;
    }
  }
  async function cancel() {
    abortController?.abort();
  }
  async function flush() {
    if (flushPromise) return flushPromise;
    flushPromise = (async () => {
      if (!isOnline()) {
        if (status.enabled && status.consentedScopes.length) return { sent: 0, queued: await queueLocalChanges(status.consentedScopes) };
        return { sent: 0, queued: loadState().pending.length };
      }
      try { await refreshStatus(); }
      catch {
        if (status.enabled && status.consentedScopes.length) return { sent: 0, queued: await queueLocalChanges(status.consentedScopes) };
        return { sent: 0, queued: loadState().pending.length };
      }
      if (!status.enabled || !status.ready || !status.consentedScopes.length) return { sent: 0, queued: loadState().pending.length };
      const state = loadState();
      const records = (await getRecords(status.consentedScopes)).filter((record) => status.consentedScopes.includes(scopeFor(record)));
      const byKey = new Map(records.map((record) => [keyFor(record), record]));
      const outgoing = new Map();
      for (const record of records) {
        const key = keyFor(record), serialized = await recordDigest(record);
        const pendingItem = state.pending.find((item) => keyFor(item) === key);
        if (state.hashes[key] !== serialized || pendingItem) {
          outgoing.set(key, { record, serialized, baseRevision: Number(pendingItem?.baseRevision ?? state.revisions[key] ?? 0) });
          if (!pendingItem) state.pending.push({ type: record.type, id: record.id, baseRevision: Number(state.revisions[key] || 0) });
        }
      }
      saveState(state);
      if (!isOnline()) return { sent: 0, queued: state.pending.length };
      const localChanges = new Set(outgoing.keys());
      try { await saveRemoteSnapshot(status.consentedScopes, { preserveKeys: localChanges }); }
      catch { return { sent: 0, queued: loadState().pending.length }; }
      let sent = 0;
      const sentKeys = new Set();
      for (const [key, item] of outgoing) {
        const { record, baseRevision } = item;
        if (!isOnline()) break;
        try {
          await sendRecord(record, "sync", undefined, baseRevision);
          sentKeys.add(key);
          sent++;
        } catch (error) {
          if (error?.name === "AbortError") throw error;
          break;
        }
      }
      if (isOnline()) {
        const pendingKeys = new Set(loadState().pending.map(keyFor));
        try { await saveRemoteSnapshot(status.consentedScopes, { preserveKeys: pendingKeys }); } catch { /* local changes and pending IDs remain available for retry */ }
      }
      const finalRows = await getRecords(status.consentedScopes);
      const finalByKey = new Map(finalRows.map((record) => [keyFor(record), record]));
      const fresh = loadState();
      for (const key of sentKeys) {
        const current = finalByKey.get(key);
        if (current) fresh.hashes[key] = await recordDigest(current);
      }
      fresh.pending = fresh.pending.filter((item) => byKey.has(keyFor(item)));
      saveState(fresh);
      return { sent, queued: fresh.pending.length };
    })().finally(() => { flushPromise = null; });
    return flushPromise;
  }
  function clearQueueOnLogout() {
    saveState({ pending: [], hashes: {}, revisions: {} });
    status = { enabled: false, ready: false, consentedScopes: [] };
    void cancel();
  }
  function currentStatus() { return { ...status, consentedScopes: [...status.consentedScopes] }; }
  return { refreshStatus, migrate, cancel, flush, snapshot, saveRemoteSnapshot, clearQueueOnLogout, currentStatus };
}

function installSyncUI() {
  const workspace = document.getElementById("storyMemorySyncWorkspace");
  if (!workspace || typeof window.storyMemoryCollectLocalSyncRecords !== "function") return;
  const statusText = document.getElementById("storyMemorySyncStatus");
  const migration = document.getElementById("storyMemorySyncMigration");
  const start = document.getElementById("storyMemorySyncStart");
  const retry = document.getElementById("storyMemorySyncRetry");
  const cancel = document.getElementById("storyMemorySyncCancel");
  const later = document.getElementById("storyMemorySyncLater");
  let migrationDismissed = false;
  let busy = false;
  let lastError = "";
  let lastSelectedScopes = [];
  const client = createStoryMemorySyncClient({
    getRecords: async (scopes) => window.storyMemoryCollectLocalSyncRecords(scopes),
    applyRemote: async (rows) => window.storyMemoryApplyRemoteSyncRecords?.(rows)
  });
  window.storyMemorySyncClient = client;
  for (const name of ["saveAnnotations", "saveUserMemories", "saveReaderProgress", "storyMemoryWriteResumeRecord"]) {
    const original = window[name];
    if (typeof original !== "function" || original.__storyMemorySyncNotified) continue;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      window.dispatchEvent(new CustomEvent("storymemory-local-records-changed"));
      return result;
    };
    wrapped.__storyMemorySyncNotified = true;
    window[name] = wrapped;
  }

  function selectedScopes() {
    return [...workspace.querySelectorAll("input[data-sync-scope]:checked")].map((item) => item.dataset.syncScope);
  }
  function render({ error = lastError, progress = null } = {}) {
    if (error) lastError = error;
    const auth = window.getStoryMemoryAuthState?.() || {};
    const current = client.currentStatus();
    const enabled = auth.serverSyncEnabled === true && auth.authenticated === true;
    workspace.hidden = !enabled;
    if (!enabled) return;
    const hasConsent = current.consentedScopes.length > 0;
    migration.hidden = (hasConsent && !error) || migrationDismissed;
    start.disabled = busy || !current.ready || selectedScopes().length === 0;
    start.hidden = Boolean(error);
    retry.hidden = !error;
    cancel.hidden = !busy;
    later.hidden = busy;
    if (busy) statusText.textContent = `이전 중 ${progress?.completed ?? 0}/${progress?.total ?? 0}`;
    else if (error) statusText.textContent = error === "sync_preparing" ? "동기화 준비 중입니다. 이 기기의 기록은 계속 저장됩니다." : "이전이 끝나지 않았습니다. 원본은 이 기기에 남아 있습니다. 다시 시도할 수 있습니다.";
    else if (!current.ready) statusText.textContent = "동기화 준비 중입니다. 이 기기의 기록은 계속 저장됩니다.";
    else if (hasConsent) statusText.textContent = "선택한 기록을 이 계정과 동기화합니다.";
    else statusText.textContent = "이 기기의 기록은 아직 계정에 옮기지 않았습니다.";
  }
  async function beginMigration() {
    const scopes = selectedScopes();
    lastSelectedScopes = scopes;
    lastError = "";
    let completed = false;
    busy = true; render();
    try {
      await client.migrate(scopes, { onProgress: (progress) => render({ progress }) });
      completed = true;
      migrationDismissed = true;
      render();
    } catch (error) {
      lastError = error?.name === "AbortError" ? "sync_cancelled" : (error?.message || "sync_failed");
      workspace.querySelectorAll("input[data-sync-scope]").forEach((input) => { input.checked = lastSelectedScopes.includes(input.dataset.syncScope); });
      render({ error: lastError });
    } finally {
      busy = false;
      render();
      if (completed) void client.flush();
    }
  }
  start.addEventListener("click", beginMigration);
  retry.addEventListener("click", beginMigration);
  cancel.addEventListener("click", () => { void client.cancel(); });
  later.addEventListener("click", () => { migrationDismissed = true; render(); });
  workspace.querySelectorAll("input[data-sync-scope]").forEach((input) => input.addEventListener("change", () => render()));
  window.addEventListener("storymemory-auth-state", async (event) => {
    const auth = event.detail || {};
    if (!auth.authenticated) {
      if (auth.loggedOut === true) client.clearQueueOnLogout();
      render();
      return;
    }
    if (auth.serverSyncEnabled !== true) { render(); return; }
    try { await client.refreshStatus(); } catch { /* local reading remains available */ }
    render();
    if (client.currentStatus().consentedScopes.length) void client.flush();
    else window.openStoryMemoryAuth?.();
  });
  window.addEventListener("storymemory-local-records-changed", () => {
    const auth = window.getStoryMemoryAuthState?.() || {};
    if (!busy && auth.authenticated && auth.serverSyncEnabled && client.currentStatus().consentedScopes.length) void client.flush();
  });
  window.addEventListener("storymemory-auth-gate-open", () => { migrationDismissed = false; render(); });
  window.addEventListener("online", () => { void client.flush(); });
  const auth = window.getStoryMemoryAuthState?.() || {};
  if (auth.authenticated && auth.serverSyncEnabled) {
    void client.refreshStatus().then(() => {
      render();
      if (client.currentStatus().consentedScopes.length) return client.flush();
      window.openStoryMemoryAuth?.();
    }).catch(() => render());
  } else render();
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installSyncUI, { once: true });
  else installSyncUI();
}
