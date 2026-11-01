/* BookAI storage foundation. Not wired into the reader until all synchronous
   storage call sites can be switched safely. Legacy values are never deleted. */
(function (root) {
  'use strict';
  const NAME = 'bookai-local-v1';
  const STORE = 'entries';
  const META = 'meta';
  const MARKER = 'legacy-localstorage-migrated-v1';
  const allowed = key => key.startsWith('storymemory.') &&
    !/^storymemory\.(authBridgeState|installationId|syncState|syncTombstones)\./.test(key);
  function open() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        db.createObjectStore(STORE);
        db.createObjectStore(META);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('indexeddb_blocked'));
    });
  }
  function complete(tx) {
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onabort = tx.onerror = () => reject(tx.error || new Error('indexeddb_failed'));
    });
  }
  async function migrate(storage) {
    const db = await open();
    try {
      const entries = [];
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key && allowed(key)) entries.push([key, storage.getItem(key)]);
      }
      const tx = db.transaction([STORE, META], 'readwrite');
      const done = complete(tx);
      const marker = tx.objectStore(META).get(MARKER);
      marker.onsuccess = () => {
        if (marker.result) return;
        for (const [key, value] of entries) if (value !== null) tx.objectStore(STORE).put(value, key);
        tx.objectStore(META).put(true, MARKER);
      };
      await done;
      return { preserved: entries.length };
    } finally { db.close(); }
  }
  async function get(key) {
    const db = await open();
    try {
      const tx = db.transaction(STORE, 'readonly');
      const done = complete(tx);
      const request = tx.objectStore(STORE).get(key);
      await done;
      return request.result === undefined ? null : request.result;
    } finally { db.close(); }
  }
  async function set(key, value) {
    if (!allowed(key) || typeof value !== 'string') throw new Error('invalid_entry');
    const db = await open();
    try {
      const tx = db.transaction(STORE, 'readwrite');
      const done = complete(tx);
      tx.objectStore(STORE).put(value, key);
      await done;
    } finally { db.close(); }
  }
  root.BookAILocalDB = Object.freeze({ migrate, get, set });
})(window);
