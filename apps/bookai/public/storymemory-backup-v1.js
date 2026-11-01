(function (root) {
  'use strict';
  // A deliberately explicit list: authentication, device IDs and sync state never leave the device.
  const keys = new Set([
    'storymemory.store.v1', 'storymemory.annotations.v1', 'storymemory.annotations.v2',
    'storymemory.readingProgress.v1', 'storymemory.readerSettings.v1',
    'storymemory.contextEntityLedger.v1', 'storymemory.recallState.v1',
    'storymemory.userMemories.v1', 'storymemory.pinnedEntities.v1',
    'storymemory.activityEvents.v1', 'storymemory.journalFilters.v1',
    'storymemory.motionFactor', 'storymemory.lastHighlightClass', 'storymemory.libraryOrder.v1'
  ]);
  const allowed = key => keys.has(key) || key.startsWith('storymemory.readerProgress.') || key.startsWith('storymemory.readerResume.');
  const limit = 5 * 1024 * 1024;
  function snapshot(storage) {
    const data = Object.create(null);
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (allowed(key)) data[key] = storage.getItem(key);
    }
    return {format:'storymemory-backup', version:1, data};
  }
  function parse(text) {
    if (typeof text !== 'string' || text.length > limit) throw new Error('invalid_size');
    const obj = JSON.parse(text);
    if (!obj || obj.format !== 'storymemory-backup' || obj.version !== 1 ||
        !obj.data || typeof obj.data !== 'object' || Array.isArray(obj.data)) throw new Error('invalid_format');
    const entries = Object.entries(obj.data);
    if (entries.length > 2000 || entries.some(([k,v]) => !allowed(k) || typeof v !== 'string' || k.length > 1000))
      throw new Error('invalid_data');
    for (const [key,value] of entries) {
      if (!['storymemory.motionFactor','storymemory.lastHighlightClass','storymemory.libraryOrder.v1'].includes(key)) {
        const parsed = JSON.parse(value);
        if (!parsed || typeof parsed !== 'object') throw new Error('invalid_data');
      }
    }
    return entries;
  }
  function restore(storage, text) {
    const entries = parse(text);
    const previous = entries.map(([key]) => [key,storage.getItem(key)]);
    const written = [];
    try { for (const [key,value] of entries) { storage.setItem(key,value); written.push(key); } }
    catch (error) {
      const changed = new Set(written);
      let rollbackFailed = false;
      // Release space used by all new values before restoring the previous ones.
      for (const [key] of previous) if (changed.has(key)) {
        try { storage.removeItem(key); } catch (_) { rollbackFailed = true; }
      }
      for (const [key,value] of previous) if (changed.has(key) && value !== null) {
        try { storage.setItem(key,value); } catch (_) { rollbackFailed = true; }
      }
      if (rollbackFailed) throw new Error('backup_rollback_failed', {cause:error});
      throw error;
    }
  }
  const api = {snapshot, restore};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.StoryMemoryBackup = api;
})(typeof window === 'undefined' ? null : window);
