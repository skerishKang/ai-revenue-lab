/* Durable automatic synchronization with the BookAI / COM2 v1 API.
   Credentials and request signatures remain in the Worker. */
(function (root) {
  'use strict';
  const db = root.BookAILocalDB, endpoint = '/api/bookai/records';
  const enc = new TextEncoder(), MAX_BYTES = 5 * 1024 * 1024;
  let running = null, timer = null, controller = null, epoch = 0;
  let observedAccount = null, rerun = false, booted = false, fullPullRequired = true, lastResult = {state:'idle'};
  const ready = Promise.resolve(root.BookAIReady).then(() => { booted = true; });
  function account() {
    return root.BookAISession?.isAuthenticated()
      ? root.BookAISession.getAccountId?.() || null : null;
  }
  function assertSession(id, generation) {
    if (account() !== id || generation !== epoch) throw Error('session_changed');
  }
  function schedule(delay = 500) {
    clearTimeout(timer);
    timer = setTimeout(() => { timer = null; syncNow(); }, delay);
  }
  async function request(path, options, id, generation) {
    assertSession(id, generation);
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 15000);
    try {
      const response = await fetch(path, {
        ...options, credentials:'same-origin', cache:'no-store', signal:controller.signal
      });
      assertSession(id, generation);
      if (!response.ok) throw Error(response.status === 401 ? 'session_expired' : 'sync_unavailable');
      const data = await response.json();
      assertSession(id, generation);
      return data;
    } finally { clearTimeout(timeout); controller = null; }
  }
  async function pull(id, generation, fromStart = false) {
    let since = fromStart ? 0 : await db.cursor(id);
    if (!Number.isSafeInteger(since) || since < 0) since = 0;
    // Replay the last millisecond: several records may share a timestamp,
    // including a record uploaded after the previous pull finished.
    since = Math.max(0, since - 1);
    let limit = 500, incomplete = null;
    for (;;) {
      const data = await request(endpoint + '?since=' + since + '&limit=' + limit,
        {method:'GET'}, id, generation);
      if (!Array.isArray(data.records) || !Number.isSafeInteger(data.next_since) ||
          data.next_since < since || typeof data.more !== 'boolean') throw Error('invalid_sync_response');
      // Timestamp zero is valid for legacy records; the overlap/doubling loop
      // below can finish that bucket without requiring a negative cursor.
      if (data.more && !data.records.length) throw Error('sync_cursor_not_advancing');
      assertSession(id, generation);
      await db.merge(id, data.records);
      assertSession(id, generation);
      if (!data.more) { await db.setCursor(id, data.next_since); return; }
      // Never advance beyond a partially received timestamp. Re-read its
      // boundary with a larger limit until all equal-time records fit.
      const boundary = Math.max(0, data.next_since - 1);
      if (boundary > since) {
        await db.setCursor(id, boundary);
        since = boundary; limit = 500; incomplete = null;
      } else {
        if (incomplete && incomplete.next === data.next_since &&
            data.records.length <= incomplete.count) throw Error('sync_cursor_page_limit');
        incomplete = {next:data.next_since,count:data.records.length};
        limit *= 2;
        if (!Number.isSafeInteger(limit)) throw Error('sync_cursor_page_limit');
      }
    }
  }
  function batches(records) {
    const result = [], oversized = [];
    let rows = [], size = enc.encode('{"records":[]}').length;
    for (const record of records) {
      const bytes = enc.encode(JSON.stringify(record)).length;
      if (bytes + enc.encode('{"records":[]}').length > MAX_BYTES) {
        oversized.push(record.record_id); continue;
      }
      if (size + bytes + (rows.length ? 1 : 0) > MAX_BYTES) {
        result.push(rows); rows = []; size = enc.encode('{"records":[]}').length;
      }
      size += bytes + (rows.length ? 1 : 0); rows.push(record);
    }
    if (rows.length) result.push(rows);
    return {batches:result,oversized};
  }
  async function run(id, generation, fromStart) {
    lastResult = {state:'syncing'};
    await db.flush();
    assertSession(id, generation);
    await db.bindAccount(id);
    await pull(id, generation, fromStart);
    const pending = await db.pending(id), upload = batches(pending);
    for (const batch of upload.batches) {
      const data = await request(endpoint, {
        method:'POST', headers:{'content-type':'application/json'},
        body:JSON.stringify({records:batch})
      }, id, generation);
      const ids = new Set(batch.map(row => row.record_id));
      if (!Number.isSafeInteger(data.accepted) || data.accepted < 0 ||
          !Array.isArray(data.kept_newer) ||
          data.kept_newer.some(value => typeof value !== 'string' || !ids.has(value)) ||
          new Set(data.kept_newer).size !== data.kept_newer.length ||
          data.accepted + data.kept_newer.length !== batch.length) throw Error('invalid_sync_response');
      const kept = new Set(data.kept_newer);
      assertSession(id, generation);
      await db.acknowledge(id, batch.filter(row => !kept.has(row.record_id)));
      if (kept.size) {
        // A winning remote revision can predate this device's cursor.
        // Download it before acknowledging the rejected local revision.
        await pull(id, generation, true);
        assertSession(id, generation);
        await db.acknowledge(id, batch.filter(row => kept.has(row.record_id)), data.kept_newer);
      }
    }
    // Offline uploads can have timestamps older than an already advanced cursor.
    // Reconcile all records after an upload; ordinary edit checks remain incremental.
    await pull(id, generation, upload.batches.length > 0);
    lastResult = upload.oversized.length
      ? {state:'queued',reason:'record_exceeds_sync_limit',remaining:upload.oversized.length}
      : {state:'synced',at:Date.now(),uploaded:pending.length};
    return lastResult;
  }
  function syncNow() {
    if (!booted) return ready.then(syncNow);
    clearTimeout(timer); timer = null;
    if (running) { rerun = true; return running; }
    const id = account();
    if (!id || navigator.onLine === false) {
      lastResult = {state:id ? 'offline' : 'local'};
      return Promise.resolve(lastResult);
    }
    const generation = epoch, fromStart = fullPullRequired;
    fullPullRequired = false;
    running = run(id, generation, fromStart).catch(error => {
      if (fromStart) fullPullRequired = true;
      lastResult = {state:'queued',reason:error.message || 'sync_unavailable'};
      return lastResult;
    }).finally(() => {
      running = null;
      if (rerun) { rerun = false; schedule(); }
    });
    return running;
  }
  function sessionChanged() {
    const id = account();
    if (id !== observedAccount) {
      observedAccount = id; epoch++; fullPullRequired = true; controller?.abort();
    }
    if (id) schedule(0);
  }
  async function reconnect() {
    if (navigator.onLine === false) return;
    // v1 orders by client updated_at, not server arrival. Full reconciliation
    // on startup, reconnect and each poll catches delayed offline uploads.
    fullPullRequired = true;
    try { await root.BookAISession?.refresh(); } catch (_) {}
    schedule(0);
  }
  root.addEventListener('bookai-session', sessionChanged);
  root.addEventListener('bookai-storage-change', () => schedule());
  root.addEventListener('online', reconnect);
  root.addEventListener('pageshow', reconnect);
  root.BookAISync = Object.freeze({syncNow, status:() => ({...lastResult})});
  ready.then(() => { setInterval(reconnect, 30000); sessionChanged(); }).catch(() => {
    lastResult = {state:'queued',reason:'storage_not_ready'};
  });
})(window);