const SNAPSHOT_KEY = "github-status:v1:last-good";
const DEFAULT_EXPIRATION_TTL = 86400;
const runtimeMemory = new Map();

function validRecord(value) {
  return value && value.schemaVersion === 1 && Number.isFinite(value.storedAtMs) && (value.snapshot?.schemaVersion === 1 || value.snapshot?.schemaVersion === 2);
}
function snapshotRecord(snapshot, storedAtMs) {
  return { schemaVersion: 1, snapshot, storedAtMs };
}
export class MemorySnapshotCache {
  constructor({ now = () => Date.now() } = {}) { this.now = now; this.value = null; }
  async get() { return this.value; }
  setMemory(snapshot) { this.value = snapshotRecord(snapshot, this.now()); return this.value; }
  async persist() { return { persisted: true, errorCode: null }; }
  async set(snapshot) { const record = this.setMemory(snapshot); await this.persist(record); return { persisted: true, errorCode: null }; }
}
export class RuntimeSnapshotCache {
  constructor({ kv, now = () => Date.now(), memoryStore = runtimeMemory, expirationTtl = DEFAULT_EXPIRATION_TTL } = {}) {
    this.kv = kv; this.now = now; this.memoryStore = memoryStore; this.expirationTtl = expirationTtl;
  }
  async get() {
    const memory = this.memoryStore.get(SNAPSHOT_KEY);
    if (validRecord(memory)) return memory;
    if (!this.kv?.get) return null;
    const value = await this.kv.get(SNAPSHOT_KEY, { type: "json", cacheTtl: 30 });
    if (!validRecord(value)) return null;
    this.memoryStore.set(SNAPSHOT_KEY, value);
    return value;
  }
  setMemory(snapshot) {
    const value = snapshotRecord(snapshot, this.now());
    this.memoryStore.set(SNAPSHOT_KEY, value);
    return value;
  }
  async persist(record) {
    if (!this.kv?.put) throw new Error("KV cache binding is unavailable.");
    if (!validRecord(record)) throw new Error("Snapshot cache record is invalid.");
    await this.kv.put(SNAPSHOT_KEY, JSON.stringify(record), { expirationTtl: this.expirationTtl });
    return { persisted: true, errorCode: null };
  }
  async set(snapshot) {
    const record = this.setMemory(snapshot);
    try {
      return await this.persist(record);
    } catch {
      return { persisted: false, errorCode: "CACHE_WRITE_FAILED" };
    }
  }
}
export { SNAPSHOT_KEY };
