import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { DatabaseSync } from "node:sqlite";
import { createStoryMemorySync } from "../public/storymemory-sync.mjs";
import { createStoryMemorySyncClient } from "../public/storymemory-sync-ui.mjs";

const ORIGIN = "https://storymemory-padiem.pages.dev";
const USER_A = "sub_sync-user-a";
const USER_B = "sub_sync-user-b";

class LocalStorage {
  constructor(seed = {}) { this.values = new Map(Object.entries(seed)); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(String(key), String(value)); }
  removeItem(key) { this.values.delete(key); }
  key(index) { return [...this.values.keys()][index] ?? null; }
  get length() { return this.values.size; }
  dump() { return Object.fromEntries(this.values); }
}

class LocalD1 {
  constructor(sql) { this.db = new DatabaseSync(":memory:"); this.db.exec(sql); }
  prepare(sql) {
    const owner = this;
    return {
      sql, values: [],
      bind(...values) { return { ...this, values }; },
      async first() { return owner.db.prepare(sql).get(...this.values) || null; },
      async all() { return { results: owner.db.prepare(sql).all(...this.values) }; },
      async run() { return owner.db.prepare(sql).run(...this.values); }
    };
  }
  async batch(statements) {
    this.db.exec("BEGIN");
    try {
      const results = statements.map((statement) => this.db.prepare(statement.sql).run(...statement.values));
      this.db.exec("COMMIT");
      return results;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
}

async function fixture({ enabled = true, binding = true, now = 1_800_000_000_000 } = {}) {
  const migration = await readFile(new URL("../migrations/0001_storymemory_reading_sync.sql", import.meta.url), "utf8");
  const db = binding ? new LocalD1(migration) : null;
  const auth = {
    async authenticate(request) {
      const cookie = request.headers.get("cookie") || "";
      const value = cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("session="))?.slice(8);
      return value ? { subject: value } : null;
    }
  };
  const handler = createStoryMemorySync({ auth, now: () => now });
  const env = { STORYMEMORY_SYNC_ENABLED: enabled ? "true" : "false", STORYMEMORY_DB: db };
  async function api(path, { user = USER_A, device = "device-a", method = "GET", body, headers = {}, omitOrigin = false } = {}) {
    const requestHeaders = new Headers(headers);
    requestHeaders.set("cookie", "session=" + user);
    requestHeaders.set("x-storymemory-device-id", device);
    if (!omitOrigin) requestHeaders.set("origin", ORIGIN);
    if (body !== undefined) requestHeaders.set("content-type", "application/json");
    const response = await handler(new Request(new URL(path, ORIGIN), { method, headers: requestHeaders, body: body === undefined ? undefined : JSON.stringify(body) }), env);
    return response;
  }
  return { db, handler, env, api, now };
}

function browserFetcher(fx, getUser = () => USER_A, getDevice = () => "device-a") {
  return async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("cookie", "session=" + getUser());
    headers.set("origin", ORIGIN);
    headers.set("x-storymemory-device-id", getDevice());
    return fx.handler(new Request(new URL(path, ORIGIN), { ...options, headers }), fx.env);
  };
}

function storedRows(db, user, type = null) {
  const sql = type
    ? "SELECT record_type, record_id, data_json, revision, is_deleted FROM storymemory_sync_records WHERE user_id = ? AND record_type = ? ORDER BY record_id"
    : "SELECT record_type, record_id, data_json, revision, is_deleted FROM storymemory_sync_records WHERE user_id = ? ORDER BY record_type, record_id";
  return type ? db.db.prepare(sql).all(user, type) : db.db.prepare(sql).all(user);
}

function sample(type = "note", id = "note-1", body = "내 메모") {
  const data = type === "progress"
    ? { context: "요한복음 3장", contentId: "bible:john", book: "요한복음", chapter: 3, page: 2, updatedAt: 100, unitOrdinal: 3, furthest: { chapter: 3, page: 2 } }
    : type === "note"
      ? { context: "요한복음 3장", page: 2, source: "요한복음 3장", quote: "구절", title: "메모", body, updatedAt: 100 }
      : { context: "요한복음 3장", page: 2, source: "요한복음 3장", canonicalLocator: "bible:john:3:16", text: "구절", color: "hl-yellow", updatedAt: 100 };
  return { type, id, updatedAt: 100, data };
}

test("local migration creates all D1 tables from the app migration", async () => {
  const migration = await readFile(new URL("../migrations/0001_storymemory_reading_sync.sql", import.meta.url), "utf8");
  const db = new LocalD1(migration);
  const names = db.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'storymemory_sync_%' ORDER BY name").all().map((row) => row.name);
  assert.deepEqual(names, ["storymemory_sync_delete_receipts", "storymemory_sync_preferences", "storymemory_sync_records"]);
  assert.ok(db.db.prepare("PRAGMA table_info(storymemory_sync_records)").all().some((row) => row.name === "device_id"));
});

test("local adapter groups a book's chapters, keeps its furthest position, and excludes AI Memory", async () => {
  const storage = new LocalStorage({
    "storymemory.installationId.v1": "legacy-installation-secret",
    ["storymemory.readerProgress." + encodeURIComponent("요한복음 3장")]: JSON.stringify({ context: "요한복음 3장", contentId: "bible:john", bibleVolume: "요한복음", readerKind: "bible", unitOrdinal: 3, page: 5, updatedAt: 200, authoritative: true }),
    ["storymemory.readerProgress." + encodeURIComponent("요한복음 4장")]: JSON.stringify({ context: "요한복음 4장", contentId: "bible:john", bibleVolume: "요한복음", readerKind: "bible", unitOrdinal: 4, page: 1, updatedAt: 100, authoritative: true }),
    ["storymemory.readerResume." + encodeURIComponent("bible:john")]: JSON.stringify({ contentId: "bible:john", bibleVolume: "요한복음", readerKind: "bible", unitOrdinal: 5, page: 2, updatedAt: 250, authoritative: true }),
    "storymemory.annotations.v2": JSON.stringify([
      { id: "ann-1", type: "hl-yellow", text: "표시 문장", context: "요한복음 3장", page: 1, updatedAt: 150 },
      { id: "book-1", type: "bookmark", title: "책갈피", context: "요한복음 3장", page: 2, updatedAt: 160 }
    ]),
    "storymemory.userMemories.v1": JSON.stringify([
      { id: "note-1", clientRecordId: "legacy-installation-secret:memory:note-1", kind: "note", body: "일반 메모", context: "요한복음 3장", updatedAt: 170 },
      { id: "ai-1", kind: "ai", body: "AI Memory", context: "요한복음 3장", updatedAt: 180 }
    ])
  });
  const source = await readFile(new URL("../public/storymemory-sync-bridge.js", import.meta.url), "utf8");
  const window = {};
  vm.runInNewContext(source, { window, localStorage: storage, Date });
  const records = window.storyMemoryCollectLocalSyncRecords(["progress", "annotations", "bookmarks"]);
  const progress = records.filter((row) => row.type === "progress");
  assert.equal(progress.length, 1);
  assert.equal(progress[0].data.chapter, 5);
  assert.equal(progress[0].data.page, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(progress[0].data.furthest)), { chapter: 5, page: 2 });
  assert.deepEqual(JSON.parse(JSON.stringify(records.map((row) => row.type))).sort(), ["annotation", "bookmark", "note", "progress"]);
  assert.equal(records.some((row) => JSON.stringify(row).includes("AI Memory")), false);
  assert.equal(records.some((row) => row.id.includes("legacy-installation-secret")), false);
});

test("exact locator annotation store syncs bookmarks and memo annotations, preserves remote IDs, and emits deletion tombstones", async () => {
  const storage = new LocalStorage({
    "storymemory.annotations.v1": JSON.stringify({ version: 1, items: [
      { id: "bk-local", kind: "bookmark", locator: "bible:eng:GEN:1:1", unit: "bible:eng:GEN:1", label: "창세기 1장", createdAt: 120 },
      { id: "memo-local", kind: "memo", locator: "bible:eng:GEN:1:1", unit: "bible:eng:GEN:1", start: 0, end: 4, text: "처음", note: "따로 적은 메모", createdAt: 130 }
    ] }),
    "storymemory.userMemories.v1": JSON.stringify([{ id: "bookmark-memory", kind: "note", subtype: "bookmark", body: "", updatedAt: 140 }])
  });
  const values = new Map();
  const store = {
    load() { const value = JSON.parse(storage.getItem("storymemory.annotations.v1") || "{}"); return Array.isArray(value.items) ? value.items : []; },
    save(items) { storage.setItem("storymemory.annotations.v1", JSON.stringify({ version: 1, items })); }
  };
  const window = {
    __smAnnotationStoreModuleV1: store,
    storyMemorySyncRecordMeta(type, id) {
      const key = type + ":" + id;
      if (!values.has(key)) values.set(key, { recordId: "opaque-" + type + "-" + id, updatedAt: 100 });
      return values.get(key);
    },
    setStoryMemorySyncRecordMeta(type, id, recordId, updatedAt) { values.set(type + ":" + id, { recordId, updatedAt }); },
    localStoryMemorySyncIdForRecord(type, recordId) {
      for (const [key, row] of values) if (key.startsWith(type + ":") && row.recordId === recordId) return key.slice(type.length + 1);
      return null;
    },
    touchStoryMemorySyncRecord(type, id) { const row = this.storyMemorySyncRecordMeta(type, id); row.updatedAt = 200; },
    dispatchEvent() {}
  };
  const source = await readFile(new URL("../public/storymemory-sync-bridge.js", import.meta.url), "utf8");
  vm.runInNewContext(source, { window, localStorage: storage, Date, CustomEvent: class {} });
  let records = window.storyMemoryCollectLocalSyncRecords(["annotations", "bookmarks"]);
  assert.equal(records.some((row) => row.type === "note"), false);
  assert.deepEqual(JSON.parse(JSON.stringify(records.map((row) => row.type))).sort(), ["annotation", "bookmark"]);
  const memo = records.find((row) => row.type === "annotation");
  assert.equal(memo.data.note, "따로 적은 메모");
  assert.equal(memo.data.annotationStore, "v1");

  store.save(store.load().filter((row) => row.id !== "bk-local"));
  records = window.storyMemoryCollectLocalSyncRecords(["annotations", "bookmarks"]);
  assert.ok(records.some((row) => row.type === "bookmark" && row.deleted), JSON.stringify(records));

  await window.storyMemoryApplyRemoteSyncRecords([{ type: "bookmark", id: "remote-bookmark", updatedAt: 300, deleted: false, data: {
    annotationStore: "v1", itemId: "remote-bk", locator: "bible:eng:GEN:2:1", unit: "bible:eng:GEN:2", context: "창세기 2장", conflictOf: "base-bookmark"
  } }]);
  const savedItems = store.load();
  assert.equal(savedItems.some((row) => row.id === "remote-bk" && row.kind === "bookmark"), true);
  assert.equal(savedItems.find((row) => row.id === "remote-bk").conflictOf, "base-bookmark");
  assert.equal(window.storyMemoryCollectLocalSyncRecords(["bookmarks"]).some((row) => row.id === "remote-bookmark"), true);
});

test("missing D1 binding returns 503 and never changes the browser's local record", async () => {
  const fx = await fixture({ binding: false });
  const local = new LocalStorage({ "storymemory.userMemories.v1": JSON.stringify([{ id: "n1", body: "local remains" }]) });
  const before = local.getItem("storymemory.userMemories.v1");
  const response = await fx.api("/api/sync/status");
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "sync_preparing", message: "동기화 준비 중", enabled: true, ready: false });
  assert.equal(local.getItem("storymemory.userMemories.v1"), before);
  fx.env.STORYMEMORY_DB = new LocalD1("");
  const schemaNotReady = await fx.api("/api/sync/status");
  assert.equal(schemaNotReady.status, 503);
  assert.match((await schemaNotReady.json()).message, /동기화 준비 중/);
  assert.equal(local.getItem("storymemory.userMemories.v1"), before);
});

test("sync endpoints reject requests without a verified login session", async () => {
  const fx = await fixture();
  const response = await fx.handler(new Request(new URL("/api/sync/status", ORIGIN), { headers: { "x-storymemory-device-id": "device-a" } }), fx.env);
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { error: "not_authenticated" });
});

test("sync client refreshes an expired HttpOnly session through same-origin auth status", async () => {
  const calls = [];
  let statusCalls = 0;
  const client = createStoryMemorySyncClient({
    storage: new LocalStorage(), deviceId: "device-a",
    fetcher: async (path, options) => {
      calls.push({ path, method: options.method });
      if (path === "/api/sync/status" && statusCalls++ === 0) return Response.json({ error: "not_authenticated" }, { status: 401 });
      if (path === "/auth/status") return Response.json({ configured: true, authenticated: true });
      return Response.json({ enabled: true, ready: true, consentedScopes: [], migrationRequired: true });
    }
  });
  assert.equal((await client.refreshStatus()).ready, true);
  assert.deepEqual(calls.map((item) => item.path), ["/api/sync/status", "/auth/status", "/api/sync/status"]);
});

test("first migration uploads only selected scope, reports progress, and persists consent", async () => {
  const fx = await fixture();
  const storage = new LocalStorage();
  const pushed = [];
  const client = createStoryMemorySyncClient({
    fetcher: browserFetcher(fx), storage, deviceId: "device-a",
    getRecords: async () => [sample("progress", "progress:john:3"), sample("note"), sample("annotation", "ann-1")],
    applyRemote: async (rows) => pushed.push(...rows)
  });
  const progress = [];
  const result = await client.migrate(["progress"], { onProgress: (row) => progress.push(row) });
  assert.deepEqual(result.scopes, ["progress"]);
  assert.deepEqual(progress, [{ completed: 1, total: 1 }]);
  assert.equal(storedRows(fx.db, USER_A).length, 1);
  assert.ok(pushed.some((row) => row.type === "progress"));
  assert.ok(!pushed.some((row) => row.type === "note"));
  assert.deepEqual(client.currentStatus().consentedScopes, ["progress"]);
});

test("migration cancellation preserves local records and retry completes idempotently", async () => {
  const fx = await fixture();
  const storage = new LocalStorage({ "storymemory.userMemories.v1": "local source" });
  const source = [sample("note", "n1"), sample("note", "n2", "다른 메모")];
  const client = createStoryMemorySyncClient({ fetcher: browserFetcher(fx), storage, deviceId: "device-a", getRecords: async () => source });
  await assert.rejects(client.migrate(["annotations"], { onProgress: () => { void client.cancel(); } }), (error) => error.name === "AbortError");
  assert.equal(storage.getItem("storymemory.userMemories.v1"), "local source");
  assert.equal(storedRows(fx.db, USER_A, "note").length, 1);
  await client.migrate(["annotations"]);
  assert.equal(storedRows(fx.db, USER_A, "note").length, 2);
  assert.equal(storedRows(fx.db, USER_A, "note").find((row) => row.record_id === "n1").revision, 1);
  assert.deepEqual(client.currentStatus().consentedScopes, ["annotations"]);
});

test("network failure leaves a retryable migration queue and retry completes", async () => {
  const fx = await fixture();
  const storage = new LocalStorage();
  let failSecond = true;
  let changeCalls = 0;
  const baseFetch = browserFetcher(fx);
  const fetcher = async (path, options) => {
    if (path === "/api/sync/changes" && ++changeCalls === 2 && failSecond) throw new TypeError("offline");
    return baseFetch(path, options);
  };
  const client = createStoryMemorySyncClient({ fetcher, storage, deviceId: "device-a", getRecords: async () => [sample("note", "n1"), sample("note", "n2")] });
  await assert.rejects(client.migrate(["annotations"]), /offline/);
  assert.ok(JSON.parse(storage.getItem("storymemory.syncQueue.v2")).pending.some((item) => item.id === "n2"));
  failSecond = false;
  await client.migrate(["annotations"]);
  assert.equal(storedRows(fx.db, USER_A, "note").length, 2);
});

test("retry remains valid when upload and consent succeeded before the snapshot failed", async () => {
  const fx = await fixture();
  const storage = new LocalStorage();
  const baseFetch = browserFetcher(fx);
  let consented = false, failSnapshot = true;
  const fetcher = async (path, options) => {
    if (path === "/api/sync/consent") {
      const response = await baseFetch(path, options);
      consented = true;
      return response;
    }
    if (path.startsWith("/api/sync/snapshot") && consented && failSnapshot) {
      failSnapshot = false;
      throw new TypeError("temporary network failure");
    }
    return baseFetch(path, options);
  };
  const client = createStoryMemorySyncClient({ fetcher, storage, deviceId: "device-a", getRecords: async () => [sample("note", "snapshot-retry")] });
  await assert.rejects(client.migrate(["annotations"]), /temporary network failure/);
  assert.deepEqual(client.currentStatus().consentedScopes, ["annotations"]);
  await client.migrate(["annotations"]);
  assert.equal(storedRows(fx.db, USER_A, "note").length, 1);
});

test("two-device stale note edits preserve a conflict copy and break equal-time ties by device id", async () => {
  const fx = await fixture();
  const recordA = sample("note", "shared-note", "기기 A 내용");
  recordA.updatedAt = 100;
  const migratedA = await fx.api("/api/sync/changes", { method: "POST", device: "device-a", body: { mode: "migration", scopes: ["annotations"], record: recordA } });
  assert.equal(migratedA.status, 200);
  await fx.api("/api/sync/consent", { method: "POST", device: "device-a", body: { scopes: ["annotations"] } });
  const recordB = sample("note", "shared-note", "기기 B 내용");
  recordB.updatedAt = 100;
  const migratedB = await fx.api("/api/sync/changes", { method: "POST", device: "device-b", body: { mode: "migration", scopes: ["annotations"], record: recordB } });
  const body = await migratedB.json();
  assert.equal(body.conflict, true);
  assert.equal("deviceId" in body.record, false);
  assert.equal("deviceId" in body.conflictCopy, false);
  assert.equal(body.record.data.body, "기기 B 내용");
  await fx.api("/api/sync/consent", { method: "POST", device: "device-b", body: { scopes: ["annotations"] } });
  const snapshot = await fx.api("/api/sync/snapshot?scopes=annotations", { device: "device-a" });
  assert.equal((await snapshot.json()).records.some((row) => "deviceId" in row), false);
  const notes = storedRows(fx.db, USER_A, "note");
  assert.equal(notes.length, 2);
  assert.equal(notes.find((row) => row.record_id === "shared-note").data_json.includes("기기 B 내용"), true);
  assert.ok(notes.some((row) => row.record_id.includes("~conflict~device-a~100")));
});

test("a stale offline edit cannot revive a server tombstone", async () => {
  const fx = await fixture();
  await fx.api("/api/sync/changes", { device: "device-a", method: "POST", body: { mode: "migration", scopes: ["annotations"], record: sample("note", "note-delete-race", "기존 메모") } });
  await fx.api("/api/sync/consent", { device: "device-a", method: "POST", body: { scopes: ["annotations"] } });
  const removed = await fx.api("/api/sync/changes", { device: "device-b", method: "POST", body: { mode: "migration", scopes: ["annotations"], record: {
    type: "note", id: "note-delete-race", updatedAt: 200, baseRevision: 1, deleted: true
  } } });
  assert.equal(removed.status, 200);
  const revived = await fx.api("/api/sync/changes", { device: "device-a", method: "POST", body: { mode: "sync", record: {
    ...sample("note", "note-delete-race", "오프라인 수정"), updatedAt: 999, baseRevision: 1
  } } });
  assert.equal(revived.status, 200);
  assert.equal((await revived.json()).record.deleted, true);
  assert.equal(storedRows(fx.db, USER_A, "note")[0].is_deleted, 1);
});

test("flush keeps dirty local content through its pre-send snapshot and applies the conflict snapshot afterward", async () => {
  const fx = await fixture();
  const serverCopy = sample("note", "note-race", "서버의 이전 메모");
  await fx.api("/api/sync/changes", { user: USER_A, device: "device-b", method: "POST", body: { mode: "migration", scopes: ["annotations"], record: serverCopy } });
  await fx.api("/api/sync/consent", { user: USER_A, device: "device-a", method: "POST", body: { scopes: ["annotations"] } });
  const localCopy = sample("note", "note-race", "이 기기에서 수정한 메모");
  localCopy.updatedAt = 200;
  localCopy.data.updatedAt = 200;
  const localRecords = [localCopy];
  const applied = [];
  const client = createStoryMemorySyncClient({
    fetcher: browserFetcher(fx), storage: new LocalStorage(), deviceId: "device-a",
    getRecords: async () => localRecords,
    applyRemote: async (rows) => {
      applied.push(...rows);
      for (const row of rows) if (row.type === "note" && !row.deleted) {
        const item = { type: row.type, id: row.id, updatedAt: row.updatedAt, data: row.data };
        const index = localRecords.findIndex((current) => current.id === row.id);
        if (index >= 0) localRecords[index] = item; else localRecords.push(item);
      }
    }
  });
  const result = await client.flush();
  assert.equal(result.sent, 1);
  assert.equal(applied.length, 2);
  assert.equal(localRecords.find((row) => row.id === "note-race").data.body, "이 기기에서 수정한 메모");
  assert.equal(storedRows(fx.db, USER_A, "note").length, 2);
});

test("reading position keeps the furthest chapter/page while resume follows the newer device edit", async () => {
  const fx = await fixture();
  const first = sample("progress", "progress:john");
  first.updatedAt = 100;
  first.data.chapter = 4;
  first.data.page = 3;
  first.data.furthest = { chapter: 4, page: 3 };
  await fx.api("/api/sync/changes", { method: "POST", device: "device-a", body: { mode: "migration", scopes: ["progress"], record: first } });
  const second = sample("progress", "progress:john");
  second.updatedAt = 200;
  second.data.chapter = 2;
  second.data.page = 1;
  second.data.furthest = { chapter: 2, page: 1 };
  await fx.api("/api/sync/changes", { method: "POST", device: "device-b", body: { mode: "migration", scopes: ["progress"], record: second } });
  const saved = JSON.parse(storedRows(fx.db, USER_A, "progress")[0].data_json);
  assert.equal(saved.chapter, 2);
  assert.equal(saved.page, 1);
  assert.deepEqual(saved.furthest, { chapter: 4, page: 3 });
});

test("users cannot read another account's records and browser-supplied identity is ignored", async () => {
  const fx = await fixture();
  const wrongScope = await fx.api("/api/sync/changes", { method: "POST", body: { mode: "migration", scopes: ["progress"], record: sample("note", "not-selected") } });
  assert.equal(wrongScope.status, 403);
  const pushed = await fx.api("/api/sync/changes", { method: "POST", user: USER_A, body: { mode: "migration", scopes: ["annotations"], record: sample("note", "only-a") } });
  assert.equal(pushed.status, 200);
  await fx.api("/api/sync/consent", { method: "POST", user: USER_A, body: { scopes: ["annotations"] } });
  await fx.api("/api/sync/consent", { method: "POST", user: USER_B, body: { scopes: ["annotations"] } });
  const response = await fx.api("/api/sync/snapshot", { user: USER_B, headers: { "x-user-id": USER_A } });
  assert.deepEqual(await response.json(), { records: [] });
});

test("offline local edits queue only identifiers and send when connectivity returns", async () => {
  const fx = await fixture();
  const storage = new LocalStorage();
  let online = true;
  let records = [sample("note", "offline-note", "처음 내용")];
  const client = createStoryMemorySyncClient({ fetcher: browserFetcher(fx), storage, deviceId: "device-a", getRecords: async () => records, isOnline: () => online });
  await client.migrate(["annotations"]);
  records = [sample("note", "offline-note", "오프라인 변경")];
  online = false;
  assert.deepEqual(await client.flush(), { sent: 0, queued: 1 });
  const queued = storage.getItem("storymemory.syncQueue.v2");
  assert.match(queued, /offline-note/);
  assert.doesNotMatch(queued, /오프라인 변경/);
  online = true;
  const result = await client.flush();
  assert.equal(result.sent, 1);
  const row = storedRows(fx.db, USER_A, "note").find((item) => item.record_id === "offline-note");
  assert.match(row.data_json, /오프라인 변경/);
  storage.setItem("storymemory.userMemories.v1", "local remains on logout");
  client.clearQueueOnLogout();
  assert.equal(storage.getItem("storymemory.userMemories.v1"), "local remains on logout");
  assert.deepEqual(JSON.parse(storage.getItem("storymemory.syncQueue.v2")), { pending: [], hashes: {}, revisions: {} });
});

test("switch off retains local-only behavior and exposes no sync operations", async () => {
  const fx = await fixture({ enabled: false });
  const local = new LocalStorage({ "storymemory.readerProgress.test": "kept" });
  const before = local.dump();
  const status = await fx.api("/api/sync/status");
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { enabled: false, ready: false });
  const write = await fx.api("/api/sync/changes", { method: "POST", body: { mode: "migration", record: sample("note") } });
  assert.equal(write.status, 404);
  assert.deepEqual(local.dump(), before);
});

test("account deletion verifies the #6773 v2 signature, deletes user rows, and is replay safe", async () => {
  const fx = await fixture();
  const secret = "test-only-secret-with-more-than-32-bytes";
  fx.env.STORYMEMORY_ACCOUNT_DELETE_RPC_SECRET = secret;
  await fx.api("/api/sync/changes", { method: "POST", body: { mode: "migration", scopes: ["annotations"], record: sample("note", "delete-me") } });
  await fx.api("/api/sync/consent", { method: "POST", body: { scopes: ["annotations"] } });
  const at = Math.floor(fx.now / 1000), serviceId = "123e4567-e89b-42d3-a456-426614174000", retryServiceId = "123e4567-e89b-42d3-a456-426614174002", operationId = "123e4567-e89b-42d3-a456-426614174001";
  const body = JSON.stringify({ account_id: USER_A, operation_id: operationId });
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  async function requestFor(id, proofOverride = null) {
    const canonical = `v2\nPOST\n/internal/account-delete\n${at}\n${id}\n${body}`;
    const proof = proofOverride || ("v2=" + [...new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(canonical)))].map((value) => value.toString(16).padStart(2, "0")).join(""));
    const headers = { "content-type": "application/json", "content-length": String(new TextEncoder().encode(body).length), "x-padiem-service-at": String(at), "x-padiem-service-id": id, "x-padiem-service-proof": proof };
    return fx.handler(new Request(new URL("/internal/account-delete", ORIGIN), { method: "POST", headers, body }), fx.env);
  }
  const deleted = await requestFor(serviceId);
  assert.equal(deleted.status, 204);
  assert.equal(storedRows(fx.db, USER_A).length, 0);
  fx.db.db.prepare("INSERT INTO storymemory_sync_records (user_id, record_type, record_id, client_updated_at, device_id, revision, is_deleted, updated_at) VALUES (?, 'note', 'later-row', 100, 'device-a', 1, 0, 100)").run(USER_A);
  const replay = await requestFor(serviceId);
  assert.equal(replay.status, 204);
  assert.equal(storedRows(fx.db, USER_A).length, 1);
  const newServiceIdRetry = await requestFor(retryServiceId);
  assert.equal(newServiceIdRetry.status, 204);
  assert.equal(storedRows(fx.db, USER_A).length, 1);
  const invalid = await requestFor("123e4567-e89b-42d3-a456-426614174003", "v2=" + "0".repeat(64));
  assert.equal(invalid.status, 401);
  const receipt = fx.db.db.prepare("SELECT account_hash, status FROM storymemory_sync_delete_receipts WHERE service_id = ?").get(serviceId);
  assert.equal(receipt.status, "complete");
  assert.equal(receipt.account_hash.includes(USER_A), false);
});

test("sync handler does not log credentials or note content", async () => {
  const fx = await fixture();
  const calls = [];
  const original = console.log;
  console.log = (...args) => calls.push(args.join(" "));
  try {
    const response = await fx.api("/api/sync/changes", { method: "POST", headers: { cookie: "session=" + USER_A + "; access=sentinel-token" }, body: { mode: "migration", scopes: ["annotations"], record: sample("note", "private-note", "private-note-body-sentinel") } });
    assert.equal(response.status, 200);
  } finally { console.log = original; }
  const source = await readFile(new URL("../public/storymemory-sync.mjs", import.meta.url), "utf8");
  const clientSource = await readFile(new URL("../public/storymemory-sync-ui.mjs", import.meta.url), "utf8");
  assert.deepEqual(calls, []);
  assert.doesNotMatch(source + clientSource, /console\.(?:log|info|warn|error)\s*\(/);
});
