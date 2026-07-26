const CACHE_KEY = "https://portfolio-console.internal/github-status/v1";
const memoryStore = new Map();

export class MemorySnapshotCache {
  constructor({ now = () => Date.now() } = {}) {
    this.now = now;
    this.value = null;
  }

  async get() {
    return this.value;
  }

  async set(snapshot) {
    this.value = { snapshot, storedAtMs: this.now() };
  }
}

export class RuntimeSnapshotCache {
  constructor({ cacheApi = globalThis.caches?.default, now = () => Date.now() } = {}) {
    this.cacheApi = cacheApi;
    this.now = now;
  }

  async get() {
    const memory = memoryStore.get(CACHE_KEY);
    if (memory) return memory;
    if (!this.cacheApi) return null;
    try {
      const response = await this.cacheApi.match(new Request(CACHE_KEY));
      if (!response) return null;
      const value = await response.json();
      if (!value?.snapshot || !Number.isFinite(value?.storedAtMs)) return null;
      memoryStore.set(CACHE_KEY, value);
      return value;
    } catch {
      return null;
    }
  }

  async set(snapshot) {
    const value = { snapshot, storedAtMs: this.now() };
    memoryStore.set(CACHE_KEY, value);
    if (!this.cacheApi) return;
    try {
      const response = new Response(JSON.stringify(value), {
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "max-age=86400"
        }
      });
      await this.cacheApi.put(new Request(CACHE_KEY), response);
    } catch {
      // Cache API is optional. Module memory remains the safe best-effort fallback.
    }
  }
}
