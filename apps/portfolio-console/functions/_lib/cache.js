const SNAPSHOT_KEY = "github-status:v1:last-good";
const DEFAULT_EXPIRATION_TTL = 86400;
const runtimeMemory = new Map();

function validRecord(value) {
  return value && value.schemaVersion === 1 && Number.isFinite(value.storedAtMs) && value.snapshot?.schemaVersion === 1;
}
export class MemorySnapshotCache {
  constructor({ now = () => Date.now() } = {}) { this.now = now; this.value = null; }
  async get() { return this.value; }
  async set(snapshot) { this.value = { schemaVersion: 1, snapshot, storedAtMs: this.now() }; }
}
export class RuntimeSnapshotCache {
  constructor({ kv, now = () => Date.now(), memoryStore = runtimeMemory, expirationTtl = DEFAULT_EXPIRATION_TTL } = {}) {
    this.kv = kv; this.now = now; this.memoryStore = memoryStore; this.expirationTtl = expirationTtl;
  }
  async get() {
    const memory = this.memoryStore.get(SNAPSHOT_KEY);
    if (validRecord(memory)) return memory;
    if (!this.kv?.get) return null;
    try {
      const value = await this.kv.get(SNAPSHOT_KEY, { type: "json", cacheTtl: 30 });
      if (!validRecord(value)) return null;
      this.memoryStore.set(SNAPSHOT_KEY, value);
      return value;
    } catch { return null; }
  }
  async set(snapshot) {
    const value = { schemaVersion: 1, snapshot, storedAtMs: this.now() };
    if (!this.kv?.put) throw new Error("KV cache binding is unavailable.");
    await this.kv.put(SNAPSHOT_KEY, JSON.stringify(value), { expirationTtl: this.expirationTtl });
    this.memoryStore.set(SNAPSHOT_KEY, value);
  }
}
export { SNAPSHOT_KEY };
