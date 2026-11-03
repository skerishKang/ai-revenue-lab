const encoder = new TextEncoder();
const SCOPES = new Set(["progress", "annotations", "bookmarks"]);
const TYPES = new Set(["progress", "annotation", "note", "bookmark"]);
const INTERNAL_DELETE_PATH = "/internal/account-delete";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}

function sameOrigin(request) {
  const url = new URL(request.url);
  const origin = request.headers.get("origin");
  return !origin || origin === url.origin;
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype;
}

function parseScopes(value) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !SCOPES.has(item))) return null;
  return [...new Set(value)].sort();
}

function scopeForType(type) {
  if (type === "progress") return "progress";
  if (type === "bookmark") return "bookmarks";
  return "annotations";
}

function validIdentifier(value, max = 512) {
  return typeof value === "string" && value.length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value);
}

function validDeviceId(value) {
  return typeof value === "string" && /^[A-Za-z0-9:_-]{1,160}$/.test(value);
}

function validData(type, value) {
  if (!plainObject(value)) return false;
  const allowed = {
    progress: new Set(["context", "contentId", "book", "chapter", "page", "updatedAt", "readerKind", "mode", "scrollRatio", "canonicalLocator", "sourceSequence", "unitKey", "contentVersionKey", "bibleVolume", "unitOrdinal", "furthest", "conflictOf"]),
    annotation: new Set(["context", "page", "verse", "source", "locator", "canonicalLocator", "text", "note", "color", "selectedTextHash", "startOffset", "endOffset", "updatedAt", "createdAt", "conflictOf", "annotationStore", "itemId", "kind", "unit"]),
    note: new Set(["context", "page", "source", "quote", "title", "body", "updatedAt", "conflictOf"]),
    bookmark: new Set(["context", "page", "source", "locator", "canonicalLocator", "title", "note", "updatedAt", "createdAt", "conflictOf", "annotationStore", "itemId", "unit"])
  }[type];
  if (!allowed || Object.keys(value).some((key) => !allowed.has(key))) return false;
  for (const [key, item] of Object.entries(value)) {
    if (item === null) continue;
    if (["page", "chapter", "unitOrdinal", "sourceSequence", "startOffset", "endOffset", "updatedAt"].includes(key) && !Number.isFinite(Number(item))) return false;
    if (["scrollRatio"].includes(key) && (!Number.isFinite(Number(item)) || Number(item) < 0 || Number(item) > 1)) return false;
    if (key === "furthest" && (!plainObject(item) || Object.keys(item).some((field) => !["chapter", "page"].includes(field)) || Object.values(item).some((field) => !Number.isFinite(Number(field))))) return false;
    if (!(["furthest", "resume"].includes(key)) && typeof item !== "string" && typeof item !== "number" && typeof item !== "boolean") return false;
  }
  return true;
}

function validChange(input) {
  if (!plainObject(input) || Object.keys(input).some((key) => !["type", "id", "updatedAt", "baseRevision", "deleted", "data"].includes(key))) return null;
  if (!TYPES.has(input.type) || !validIdentifier(input.id) || !Number.isSafeInteger(input.updatedAt) || input.updatedAt < 1 ||
      (input.baseRevision !== undefined && (!Number.isSafeInteger(input.baseRevision) || input.baseRevision < 0)) ||
      (input.deleted !== undefined && typeof input.deleted !== "boolean")) return null;
  if (input.deleted === true) {
    if (input.data !== undefined) return null;
  } else if (!validData(input.type, input.data)) return null;
  return {
    type: input.type,
    id: input.id,
    updatedAt: input.updatedAt,
    baseRevision: input.baseRevision ?? 0,
    deleted: input.deleted === true,
    data: input.deleted === true ? null : input.data
  };
}

function rowToRecord(row) {
  let data = null;
  try { data = row.data_json ? JSON.parse(row.data_json) : null; } catch { data = null; }
  return {
    type: row.record_type,
    id: row.record_id,
    updatedAt: Number(row.client_updated_at),
    deviceId: row.device_id,
    revision: Number(row.revision),
    deleted: Number(row.is_deleted) === 1,
    data
  };
}

function publicRecord(record) {
  const { deviceId, ...visible } = record;
  return visible;
}

function compareVersion(left, right) {
  if (left.updatedAt !== right.updatedAt) return left.updatedAt > right.updatedAt ? 1 : -1;
  return left.deviceId === right.deviceId ? 0 : left.deviceId > right.deviceId ? 1 : -1;
}

function comparePosition(left = {}, right = {}) {
  const chapter = Number(left.chapter || left.unitOrdinal || 0) - Number(right.chapter || right.unitOrdinal || 0);
  if (chapter) return chapter;
  return Number(left.page || 0) - Number(right.page || 0);
}

function mergeProgress(existing, incoming) {
  if (!existing || existing.deleted) return incoming;
  const previous = existing.data || {};
  const next = incoming.data || {};
  const oldFurthest = previous.furthest || previous;
  const newFurthest = next.furthest || next;
  const furthest = comparePosition(newFurthest, oldFurthest) > 0 ? newFurthest : oldFurthest;
  const winner = compareVersion(incoming, existing) >= 0 ? incoming : existing;
  return {
    ...winner,
    type: incoming.type,
    id: incoming.id,
    revision: existing.revision + 1,
    deleted: false,
    data: { ...(winner.data || {}), furthest: { chapter: Number(furthest.chapter || furthest.unitOrdinal || 0), page: Number(furthest.page || 0) } }
  };
}

function hex(bytes) { return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, "0")).join(""); }

async function digestHex(value) {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

async function verifyDeleteSignature(request, secret, currentSeconds) {
  const atText = request.headers.get("x-padiem-service-at") || "";
  const serviceId = request.headers.get("x-padiem-service-id") || "";
  const presented = request.headers.get("x-padiem-service-proof") || "";
  if (typeof secret !== "string" || secret.length < 32 || request.method !== "POST" ||
      request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json" ||
      !/^(0|[1-9][0-9]{0,10})$/.test(atText) || !Number.isSafeInteger(Number(atText)) ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(serviceId) ||
      !/^v2=[a-f0-9]{64}$/.test(presented) || Math.abs(currentSeconds - Number(atText)) > 300) return null;
  const declaredLength = Number(request.headers.get("content-length") || "0");
  if (declaredLength > 512) return null;
  const raw = new Uint8Array(await request.arrayBuffer());
  if (!raw.length || raw.byteLength > 512 || (declaredLength && declaredLength !== raw.byteLength)) return null;
  const path = new URL(request.url).pathname;
  if (new URL(request.url).search) return null;
  const canonical = new Uint8Array([
    ...encoder.encode("v2\nPOST\n"), ...encoder.encode(path), 10,
    ...encoder.encode(atText), 10, ...encoder.encode(serviceId), 10, ...raw
  ]);
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const expected = "v2=" + hex(await crypto.subtle.sign("HMAC", key, canonical));
  let mismatch = expected.length ^ presented.length;
  for (let index = 0; index < Math.min(expected.length, presented.length); index++) mismatch |= expected.charCodeAt(index) ^ presented.charCodeAt(index);
  if (mismatch) return null;
  let payload;
  try { payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); } catch { return null; }
  if (!plainObject(payload) || Object.keys(payload).length !== 2 ||
      !/^sub_[A-Za-z0-9_-]{1,128}$/.test(payload.account_id || "") ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(payload.operation_id || "")) return null;
  return { serviceId, payload, at: Number(atText) };
}

export function createStoryMemorySync({ auth, now = () => Date.now() } = {}) {
  async function authenticated(request, env) {
    const session = await auth?.authenticate?.(request, env);
    return typeof session?.subject === "string" ? session.subject : null;
  }

  async function readPreference(db, subject, deviceId) {
    const row = await db.prepare("SELECT scopes_json FROM storymemory_sync_preferences WHERE user_id = ? AND device_id = ?").bind(subject, deviceId).first();
    try { return parseScopes(JSON.parse(row?.scopes_json || "[]")) || []; } catch { return []; }
  }

  async function readRecord(db, subject, type, id) {
    return db.prepare("SELECT user_id, record_type, record_id, data_json, client_updated_at, device_id, revision, is_deleted, updated_at FROM storymemory_sync_records WHERE user_id = ? AND record_type = ? AND record_id = ?")
      .bind(subject, type, id).first();
  }

  async function writeRecord(db, subject, record) {
    await db.prepare(`INSERT INTO storymemory_sync_records
      (user_id, record_type, record_id, data_json, client_updated_at, device_id, revision, is_deleted, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(user_id, record_type, record_id) DO UPDATE SET
        data_json = excluded.data_json, client_updated_at = excluded.client_updated_at,
        device_id = excluded.device_id, revision = excluded.revision,
        is_deleted = excluded.is_deleted, updated_at = excluded.updated_at`)
      .bind(subject, record.type, record.id, record.deleted ? null : JSON.stringify(record.data), record.updatedAt, record.deviceId, record.revision, record.deleted ? 1 : 0, now()).run();
  }

  async function accountDelete(request, env) {
    const verified = await verifyDeleteSignature(request, env?.STORYMEMORY_ACCOUNT_DELETE_RPC_SECRET, Math.floor(now() / 1000));
    if (!verified) return json({ error: "unauthorized" }, 401);
    const db = env?.STORYMEMORY_DB;
    if (!db) return json({ error: "sync_preparing", message: "동기화 준비 중" }, 503);
    try {
    const { serviceId, payload } = verified;
    const accountHash = await digestHex(payload.account_id);
    const priorOperation = await db.prepare("SELECT account_hash, status FROM storymemory_sync_delete_receipts WHERE operation_id = ?")
      .bind(payload.operation_id).first();
    if (priorOperation) {
      if (priorOperation.account_hash === accountHash && priorOperation.status === "complete") return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
      return json({ error: "request_replayed" }, 409);
    }
    const existing = await db.prepare("SELECT operation_id, account_hash, status FROM storymemory_sync_delete_receipts WHERE service_id = ?")
      .bind(serviceId).first();
    if (existing) {
      if (existing.operation_id === payload.operation_id && existing.account_hash === accountHash && existing.status === "complete") return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
      return json({ error: "request_replayed" }, 409);
    }
    const createdAt = now();
    try {
      await db.batch([
        db.prepare("INSERT OR IGNORE INTO storymemory_sync_delete_receipts (service_id, operation_id, account_hash, status, created_at, completed_at) VALUES (?, ?, ?, 'pending', ?, NULL)").bind(serviceId, payload.operation_id, accountHash, createdAt),
        db.prepare("DELETE FROM storymemory_sync_records WHERE user_id = ? AND EXISTS (SELECT 1 FROM storymemory_sync_delete_receipts WHERE service_id = ? AND operation_id = ? AND account_hash = ? AND status = 'pending')").bind(payload.account_id, serviceId, payload.operation_id, accountHash),
        db.prepare("DELETE FROM storymemory_sync_preferences WHERE user_id = ? AND EXISTS (SELECT 1 FROM storymemory_sync_delete_receipts WHERE service_id = ? AND operation_id = ? AND account_hash = ? AND status = 'pending')").bind(payload.account_id, serviceId, payload.operation_id, accountHash),
        db.prepare("UPDATE storymemory_sync_delete_receipts SET status = 'complete', completed_at = ? WHERE service_id = ? AND operation_id = ? AND account_hash = ? AND status = 'pending'").bind(createdAt, serviceId, payload.operation_id, accountHash)
      ]);
    } catch {
      return json({ error: "account_delete_unavailable" }, 503);
    }
    const receipt = await db.prepare("SELECT operation_id, account_hash, status FROM storymemory_sync_delete_receipts WHERE service_id = ?").bind(serviceId).first();
    if (receipt?.operation_id === payload.operation_id && receipt?.account_hash === accountHash && receipt?.status === "complete") return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
    const racedOperation = await db.prepare("SELECT account_hash, status FROM storymemory_sync_delete_receipts WHERE operation_id = ?").bind(payload.operation_id).first();
    if (racedOperation?.account_hash === accountHash && racedOperation?.status === "complete") return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
    return json({ error: "request_replayed" }, 409);
    } catch {
      return json({ error: "account_delete_unavailable" }, 503);
    }
  }

  async function handle(request, env) {
    const url = new URL(request.url);
    if (url.pathname === INTERNAL_DELETE_PATH) {
      if (request.headers.has("origin")) return json({ error: "invalid_origin" }, 403);
      return accountDelete(request, env);
    }
    if (!url.pathname.startsWith("/api/sync/")) return null;
    if (!sameOrigin(request)) return json({ error: "cross_origin_forbidden" }, 403);
    if (request.method !== "GET" && request.headers.get("origin") !== url.origin) return json({ error: "invalid_origin" }, 403);
    const subject = await authenticated(request, env);
    if (!subject) return json({ error: "not_authenticated" }, 401);
    if (env?.STORYMEMORY_SYNC_ENABLED !== "true") {
      if (url.pathname === "/api/sync/status" && request.method === "GET") return json({ enabled: false, ready: false });
      return json({ error: "tool_not_enabled" }, 404);
    }
    const db = env?.STORYMEMORY_DB;
    if (!db) return json({ error: "sync_preparing", message: "동기화 준비 중", enabled: true, ready: false }, 503);
    const deviceId = request.headers.get("x-storymemory-device-id") || "";
    if (!validDeviceId(deviceId)) return json({ error: "invalid_device" }, 400);

    try {
    if (url.pathname === "/api/sync/status") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      const scopes = await readPreference(db, subject, deviceId);
      return json({ enabled: true, ready: true, consentedScopes: scopes, migrationRequired: scopes.length === 0 });
    }

    if (url.pathname === "/api/sync/snapshot") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      const scopes = await readPreference(db, subject, deviceId);
      if (!scopes.length) return json({ error: "migration_required" }, 409);
      const requested = url.searchParams.get("scopes") ? url.searchParams.get("scopes").split(",") : scopes;
      if (requested.some((scope) => !SCOPES.has(scope) || !scopes.includes(scope))) return json({ error: "scope_not_allowed" }, 403);
      const types = [...TYPES].filter((type) => requested.includes(scopeForType(type)));
      const placeholders = types.map(() => "?").join(",");
      const result = await db.prepare(`SELECT user_id, record_type, record_id, data_json, client_updated_at, device_id, revision, is_deleted, updated_at FROM storymemory_sync_records WHERE user_id = ? AND record_type IN (${placeholders}) ORDER BY record_type, record_id`)
        .bind(subject, ...types).all();
      return json({ records: (result?.results || []).map(rowToRecord).map(publicRecord) });
    }

    if (url.pathname === "/api/sync/consent") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      if (request.headers.get("origin") !== url.origin) return json({ error: "invalid_origin" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
      if (!plainObject(body) || Object.keys(body).length !== 1) return json({ error: "invalid_request" }, 400);
      const scopes = parseScopes(body.scopes);
      if (!scopes?.length) return json({ error: "invalid_scopes" }, 400);
      await db.prepare(`INSERT INTO storymemory_sync_preferences (user_id, device_id, scopes_json, updated_at)
        VALUES (?, ?, ?, ?) ON CONFLICT(user_id, device_id) DO UPDATE SET scopes_json = excluded.scopes_json, updated_at = excluded.updated_at`)
        .bind(subject, deviceId, JSON.stringify(scopes), now()).run();
      return json({ ok: true, scopes });
    }

    if (url.pathname === "/api/sync/changes") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      if (request.headers.get("origin") !== url.origin) return json({ error: "invalid_origin" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
      if (!plainObject(body) || !["migration", "sync"].includes(body.mode) ||
          Object.keys(body).some((key) => !(body.mode === "migration" ? ["mode", "scopes", "record"] : ["mode", "record"]).includes(key))) return json({ error: "invalid_request" }, 400);
      const input = validChange(body.record);
      if (!input) return json({ error: "invalid_record" }, 400);
      const allowedScopes = await readPreference(db, subject, deviceId);
      const requestedScopes = body.mode === "migration" ? parseScopes(body.scopes) : null;
      if (body.mode === "migration" && (!requestedScopes?.length || !requestedScopes.includes(scopeForType(input.type)))) return json({ error: "scope_not_selected" }, 403);
      if (body.mode === "sync" && !allowedScopes.includes(scopeForType(input.type))) return json({ error: "migration_required" }, 409);
      if (body.mode === "migration" && allowedScopes.length && !allowedScopes.includes(scopeForType(input.type))) return json({ error: "migration_already_complete" }, 409);
      const currentRow = await readRecord(db, subject, input.type, input.id);
      const current = currentRow ? rowToRecord(currentRow) : null;
      const incoming = { ...input, deviceId, revision: (current?.revision || 0) + 1 };

      if (current?.deleted && !input.deleted && input.baseRevision !== current.revision) {
        return json({ ok: true, conflict: false, record: publicRecord(current) });
      }

      const identical = current && current.deleted === input.deleted && JSON.stringify(current.data) === JSON.stringify(input.data);
      if (identical) return json({ ok: true, conflict: false, record: publicRecord(current) });

      if (input.type === "progress" && !input.deleted) {
        const merged = mergeProgress(current, incoming);
        if (current && current.deleted) merged.revision = current.revision + 1;
        await writeRecord(db, subject, merged);
        return json({ ok: true, conflict: false, record: publicRecord(merged) });
      }

      const staleBase = current && input.baseRevision !== current.revision;
      if (staleBase && current.deviceId !== deviceId && !current.deleted && !input.deleted) {
        const incomingWins = compareVersion(incoming, current) > 0;
        const loser = incomingWins ? current : incoming;
        const conflictId = input.id + "~conflict~" + loser.deviceId + "~" + loser.updatedAt;
        const conflict = {
          ...loser,
          id: conflictId,
          data: { ...loser.data, conflictOf: input.id },
          revision: (await readRecord(db, subject, input.type, conflictId))?.revision + 1 || 1
        };
        await writeRecord(db, subject, conflict);
        let winner = current;
        if (incomingWins) {
          await writeRecord(db, subject, incoming);
          winner = incoming;
        }
        return json({ ok: true, conflict: true, record: publicRecord(winner), conflictCopy: publicRecord(conflict) });
      }
      if (current && compareVersion(incoming, current) < 0) return json({ ok: true, conflict: false, record: publicRecord(current) });
      await writeRecord(db, subject, incoming);
      return json({ ok: true, conflict: false, record: publicRecord(incoming) });
    }

    return json({ error: "not_found" }, 404);
    } catch {
      return json({ error: "sync_preparing", message: "동기화 준비 중", enabled: true, ready: false }, 503);
    }
  }

  return handle;
}
