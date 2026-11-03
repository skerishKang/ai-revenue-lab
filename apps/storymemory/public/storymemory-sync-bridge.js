/* Bridge the legacy localStorage record shapes to the optional account sync client. */
(function () {
  'use strict';
  const PROGRESS_PREFIX = 'storymemory.readerProgress.';
  const RESUME_PREFIX = 'storymemory.readerResume.';
  const ANNOTATIONS_KEY = 'storymemory.annotations.v2';
  const EXACT_ANNOTATIONS_KEY = 'storymemory.annotations.v1';
  const NOTES_KEY = 'storymemory.userMemories.v1';
  const TOMBSTONES_KEY = 'storymemory.syncTombstones.v1';
  const DEVICE_KEY = 'storymemory.installationId.v1';

  function read(key, fallback) {
    try { const value = JSON.parse(localStorage.getItem(key) || 'null'); return value == null ? fallback : value; } catch { return fallback; }
  }
  function timestamp(value) {
    const number = Number(value);
    return Number.isSafeInteger(number) && number > 0 ? number : Date.now();
  }
  function scopeType(type) { return type === 'progress' ? 'progress' : type === 'bookmark' ? 'bookmarks' : 'annotations'; }
  function recordId(type, item) {
    if (item?.clientRecordId) return item.clientRecordId;
    if (typeof window.storyMemorySyncRecordMeta === 'function') return window.storyMemorySyncRecordMeta(type, item?.id)?.recordId || String(item?.id || '');
    return String(item?.id || '');
  }
  function recordMeta(type, id) {
    return typeof window.storyMemorySyncRecordMeta === 'function' ? window.storyMemorySyncRecordMeta(type, id) : null;
  }
  function localIdForRecord(type, id) {
    return typeof window.localStoryMemorySyncIdForRecord === 'function' ? window.localStoryMemorySyncIdForRecord(type, id) : null;
  }
  function setRecordMeta(type, id, record, updatedAt) {
    if (typeof window.setStoryMemorySyncRecordMeta === 'function') window.setStoryMemorySyncRecordMeta(type, id, record, updatedAt);
  }
  function announceLocalChange() {
    try { if (typeof window.dispatchEvent === 'function' && typeof CustomEvent === 'function') window.dispatchEvent(new CustomEvent('storymemory-local-records-changed')); } catch { /* local data remains saved */ }
  }
  function rememberDeletedAnnotationItems(before, after) {
    const current = new Set(after.map((item) => item.id));
    const tombstones = read(TOMBSTONES_KEY, []);
    const rows = Array.isArray(tombstones) ? tombstones : [];
    const originalLength = rows.length;
    for (const item of before) if (!current.has(item.id)) {
      const type = item.kind === 'bookmark' ? 'bookmark' : 'annotation';
      const id = recordId(type, item);
      if (id) rows.push({ kind: type, clientRecordId: id, deletedAt: Date.now() });
    }
    if (rows.length !== originalLength) {
      try { localStorage.setItem(TOMBSTONES_KEY, JSON.stringify(rows.slice(-300))); } catch { /* source store remains authoritative */ }
    }
  }
  function normalizeLegacyRecordIds() {
    const deviceId = localStorage.getItem(DEVICE_KEY);
    if (!deviceId) return;
    const prefix = deviceId + ':';
    for (const [key, kind] of [[ANNOTATIONS_KEY, 'annotation'], [NOTES_KEY, 'memory']]) {
      const rows = read(key, []);
      if (!Array.isArray(rows)) continue;
      let changed = false;
      for (const item of rows) {
        if (!item?.clientRecordId?.startsWith(prefix)) continue;
        const rest = item.clientRecordId.slice(prefix.length), separator = rest.indexOf(':');
        const oldKind = separator >= 0 ? rest.slice(0, separator) : kind;
        const localId = separator >= 0 ? rest.slice(separator + 1) : String(item.id || rest);
        item.clientRecordId = typeof clientRecordId === 'function' ? clientRecordId(oldKind, localId) : ('rec-' + Math.random().toString(36).slice(2));
        changed = true;
      }
      if (changed) try { localStorage.setItem(key, JSON.stringify(rows)); } catch { /* source records remain available */ }
    }
    const tombstones = read(TOMBSTONES_KEY, []);
    if (!Array.isArray(tombstones)) return;
    let changed = false;
    for (const item of tombstones) {
      if (!item?.clientRecordId?.startsWith(prefix)) continue;
      const rest = item.clientRecordId.slice(prefix.length), separator = rest.indexOf(':');
      const oldKind = separator >= 0 ? rest.slice(0, separator) : item.kind;
      const localId = separator >= 0 ? rest.slice(separator + 1) : rest;
      item.clientRecordId = typeof clientRecordId === 'function' ? clientRecordId(oldKind, localId) : ('rec-' + Math.random().toString(36).slice(2));
      changed = true;
    }
    if (changed) try { localStorage.setItem(TOMBSTONES_KEY, JSON.stringify(tombstones)); } catch { /* keep deletion metadata for a later retry */ }
  }
  let applyingRemote = false;
  function installExactAnnotationStoreBridge() {
    const store = window.__smAnnotationStoreModuleV1;
    if (!store || typeof store.save !== 'function' || store.save.__storyMemorySyncWrapped) return;
    const originalSave = store.save.bind(store), originalLoad = store.load.bind(store);
    const wrapped = function (items) {
      const before = originalLoad();
      const result = originalSave(items);
      const after = originalLoad();
      if (!applyingRemote) {
        const oldById = new Map(before.map((item) => [item.id, JSON.stringify(item)]));
        for (const item of after) if (oldById.get(item.id) !== JSON.stringify(item) && typeof window.touchStoryMemorySyncRecord === 'function') {
          window.touchStoryMemorySyncRecord(item.kind === 'bookmark' ? 'bookmark' : 'annotation', item.id);
        }
        rememberDeletedAnnotationItems(before, after);
        announceLocalChange();
      }
      return result;
    };
    wrapped.__storyMemorySyncWrapped = true;
    store.save = wrapped;
  }
  installExactAnnotationStoreBridge();
  function comparePosition(left = {}, right = {}) {
    const chapter = Number(left.chapter || left.unitOrdinal || 0) - Number(right.chapter || right.unitOrdinal || 0);
    return chapter || Number(left.page || 0) - Number(right.page || 0);
  }
  function putProgress(map, record) {
    const existing = map.get(record.id);
    if (!existing) {
      record.data.furthest = record.data.furthest || { chapter: record.data.chapter || 0, page: record.data.page || 0 };
      map.set(record.id, record);
      return;
    }
    const oldPosition = existing.data.furthest || existing.data;
    const newPosition = record.data.furthest || record.data;
    const furthest = comparePosition(newPosition, oldPosition) > 0 ? newPosition : oldPosition;
    const resume = record.updatedAt >= existing.updatedAt ? record : existing;
    map.set(record.id, { ...resume, data: { ...resume.data, furthest: { chapter: Number(furthest.chapter || furthest.unitOrdinal || 0), page: Number(furthest.page || 0) } } });
  }
  function collect(scopes = ['progress', 'annotations', 'bookmarks']) {
    normalizeLegacyRecordIds();
    const allowed = new Set(scopes), rows = [], progressRows = new Map();
    if (allowed.has('progress')) {
      for (let index = 0; index < localStorage.length; index++) {
        const key = localStorage.key(index) || '';
        if (!key.startsWith(PROGRESS_PREFIX)) continue;
        const context = decodeURIComponent(key.slice(PROGRESS_PREFIX.length));
        const row = read(key, null);
        if (!row || (row.readerKind === 'bible' && row.authoritative === false)) continue;
        const book = row.bibleVolume || context.replace(/\s+\d+장$/, '');
        const chapter = Number(row.unitOrdinal || context.match(/\s(\d+)장$/)?.[1] || 0);
        const workKey = row.bibleVolume || row.contentId || book || context;
        const id = 'progress:' + encodeURIComponent(String(workKey)) + ':' + String(row.contentVersionKey || '');
        putProgress(progressRows, { type: 'progress', id, updatedAt: timestamp(row.updatedAt), data: {
          context, contentId: row.contentId || null, book, chapter, page: Number(row.page || 0),
          updatedAt: timestamp(row.updatedAt), readerKind: row.readerKind || null, mode: row.mode || 'page',
          scrollRatio: Number(row.scrollRatio || 0), canonicalLocator: row.canonicalLocator || null,
          sourceSequence: Number.isFinite(Number(row.sourceSequence)) ? Number(row.sourceSequence) : null,
          unitKey: row.unitKey || null, contentVersionKey: row.contentVersionKey || null,
          bibleVolume: row.bibleVolume || null, unitOrdinal: Number(row.unitOrdinal || chapter || 0),
          furthest: { chapter: Number(row.furthest?.chapter || row.furthest?.unitOrdinal || chapter), page: Number(row.furthest?.page ?? row.page ?? 0) }
        } });
      }
      for (let index = 0; index < localStorage.length; index++) {
        const key = localStorage.key(index) || '';
        if (!key.startsWith(RESUME_PREFIX)) continue;
        const row = read(key, null);
        if (!row || row.authoritative === false) continue;
        const book = row.bibleVolume || row.contentTitle || row.contentId || 'reader';
        const context = row.bibleVolume ? `${row.bibleVolume} ${Number(row.unitOrdinal || 1)}장` : String(row.context || row.contentTitle || book);
        const workKey = row.bibleVolume || row.contentId || book;
        const id = 'progress:' + encodeURIComponent(String(workKey)) + ':' + String(row.contentVersionKey || '');
        const previous = progressRows.get(id);
        const merged = {
          context, contentId: row.contentId || null, book,
          chapter: Number(row.unitOrdinal || previous?.data?.chapter || 0), page: Number(row.page || previous?.data?.page || 0),
          updatedAt: timestamp(row.updatedAt), readerKind: row.readerKind || previous?.data?.readerKind || null,
          mode: row.mode || previous?.data?.mode || 'page', scrollRatio: Number(row.scrollRatio || 0),
          canonicalLocator: row.canonicalLocator || null,
          sourceSequence: Number.isFinite(Number(row.sourceSequence)) ? Number(row.sourceSequence) : null,
          unitKey: row.unitKey || null, contentVersionKey: row.contentVersionKey || null,
          bibleVolume: row.bibleVolume || null, unitOrdinal: Number(row.unitOrdinal || 0),
          furthest: { chapter: Number(row.furthest?.chapter || row.furthest?.unitOrdinal || row.unitOrdinal || 0), page: Number(row.furthest?.page ?? row.page ?? 0) }
        };
        putProgress(progressRows, { type: 'progress', id, updatedAt: merged.updatedAt, data: merged });
      }
      rows.push(...progressRows.values());
    }

    if (allowed.has('annotations') || allowed.has('bookmarks')) {
      const annotations = read(ANNOTATIONS_KEY, []);
      if (Array.isArray(annotations)) for (const item of annotations) {
        const bookmark = item?.type === 'bookmark' || item?.kind === 'bookmark';
        const type = bookmark ? 'bookmark' : 'annotation';
        if (!allowed.has(scopeType(type))) continue;
        const id = item.clientRecordId || (typeof clientRecordId === 'function' ? clientRecordId(bookmark ? 'bookmark' : 'annotation', item.id) : item.id);
        if (!id) continue;
        const data = bookmark ? {
          context: item.context || '', page: Number(item.page || 0), source: item.source || '',
          locator: item.canonicalLocator || null, canonicalLocator: item.canonicalLocator || null,
          title: item.title || '', note: item.note || '', updatedAt: timestamp(item.clientUpdatedAt || item.updatedAt || item.createdAt)
        } : {
          context: item.context || '', page: Number(item.page || 0), verse: item.verse || '', source: item.source || '',
          locator: item.canonicalLocator || null, canonicalLocator: item.canonicalLocator || null,
          text: item.text || '', color: item.color || item.type || '', updatedAt: timestamp(item.clientUpdatedAt || item.updatedAt || item.createdAt)
        };
        rows.push({ type, id, updatedAt: timestamp(item.clientUpdatedAt || item.updatedAt || item.createdAt), data });
      }
      if (allowed.has('annotations')) {
        const notes = read(NOTES_KEY, []);
        if (Array.isArray(notes)) for (const item of notes) {
          if (!item || item.kind !== 'note' || item.subtype === 'bookmark') continue;
          const id = recordId('note', item) || (typeof clientRecordId === 'function' ? clientRecordId('memory', item.id) : item.id);
          if (!id) continue;
          const meta = recordMeta('note', item.id);
          rows.push({ type: 'note', id, updatedAt: timestamp(item.clientUpdatedAt || meta?.updatedAt || item.updatedAt || item.createdAt), data: {
            context: item.context || '', page: Number(item.page || 0), source: item.source || '', quote: item.quote || '',
            title: item.title || '', body: item.body || '', updatedAt: timestamp(item.clientUpdatedAt || item.updatedAt || item.createdAt)
          } });
        }
      }
    }

    if (allowed.has('annotations') || allowed.has('bookmarks')) {
      const parsed = read(EXACT_ANNOTATIONS_KEY, null);
      const exactItems = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.items) ? parsed.items : [];
      for (const item of exactItems) {
        if (!item?.id || !item?.kind) continue;
        const type = item.kind === 'bookmark' ? 'bookmark' : 'annotation';
        if (!allowed.has(scopeType(type))) continue;
        const id = recordId(type, item);
        if (!id) continue;
        const meta = recordMeta(type, item.id);
        const updatedAt = timestamp(meta?.updatedAt || item.updatedAt || item.createdAt);
        const context = item.label || item.unit || item.locator || '';
        rows.push({ type, id, updatedAt, data: type === 'bookmark' ? {
          context, page: 0, source: context, locator: item.locator || '', canonicalLocator: item.locator || null,
          title: context, itemId: item.id, annotationStore: 'v1', unit: item.unit || '', updatedAt
        } : {
          context, page: 0, source: context, locator: item.locator || '', canonicalLocator: item.locator || null,
          text: item.text || '', note: item.note || '', color: item.color || item.kind, itemId: item.id,
          annotationStore: 'v1', kind: item.kind, unit: item.unit || '', startOffset: Number(item.start || 0),
          endOffset: Number(item.end || 0), updatedAt
        } });
      }
    }

    const tombstones = read(TOMBSTONES_KEY, []);
    if (Array.isArray(tombstones)) for (const item of tombstones) {
      const type = item?.kind === 'bookmark' ? 'bookmark' : item?.kind === 'note' ? 'note' : item?.kind === 'annotation' ? 'annotation' : null;
      if (!type || !allowed.has(scopeType(type)) || !item.clientRecordId) continue;
      rows.push({ type, id: item.clientRecordId, updatedAt: timestamp(item.deletedAt), deleted: true });
    }
    return rows;
  }

  function applyRemote(records) {
    if (!Array.isArray(records)) return;
    let annotations = read(ANNOTATIONS_KEY, []), notes = read(NOTES_KEY, []);
    if (!Array.isArray(annotations)) annotations = [];
    if (!Array.isArray(notes)) notes = [];
    let annotationsChanged = false, notesChanged = false;
    for (const record of records) {
      if (!record || !record.type || !record.id) continue;
      const data = record.data || {};
      if (record.type === 'progress') {
        if (record.deleted) continue;
        const context = String(data.context || (data.book ? `${data.book} ${Number(data.chapter || 1)}장` : ''));
        if (!context) continue;
        const key = PROGRESS_PREFIX + encodeURIComponent(context);
        localStorage.setItem(key, JSON.stringify({ ...read(key, {}), ...data, updatedAt: timestamp(record.updatedAt) }));
        try {
          const content = window.storyMemoryResolveContent?.({ contentId: data.contentId }) || window.storyMemoryResolveContent?.(data.contentId) || null;
          if (content && typeof window.storyMemoryWriteResumeRecord === 'function') window.storyMemoryWriteResumeRecord(content, { ...data, updatedAt: timestamp(record.updatedAt) }, data.bibleVolume || null);
        } catch { /* legacy local position remains available */ }
        continue;
      }
      if (record.type === 'annotation' || record.type === 'bookmark') {
        if (record.deleted) {
          const exactStore = window.__smAnnotationStoreModuleV1;
          const exactItems = exactStore?.load?.() || [];
          const mappedLocalId = localIdForRecord(record.type, record.id);
          if (exactStore && exactItems.some((item) => item.id === mappedLocalId)) {
            applyingRemote = true;
            try { exactStore.save(exactItems.filter((item) => item.id !== mappedLocalId)); } finally { applyingRemote = false; }
          }
          const before = annotations.length;
          annotations = annotations.filter((item) => item.clientRecordId !== record.id);
          annotationsChanged ||= annotations.length !== before;
          continue;
        }
        if (data.annotationStore === 'v1') {
          const exactStore = window.__smAnnotationStoreModuleV1;
          if (exactStore?.load && exactStore?.save && typeof data.locator === 'string') {
            const exactItems = exactStore.load();
            const mappedLocalId = localIdForRecord(record.type, record.id);
            let localId = mappedLocalId || data.itemId || ('remote-' + Math.random().toString(36).slice(2, 18));
            const collision = exactItems.find((item) => item.id === localId && recordId(record.type, item) !== record.id);
            if (collision) localId = 'remote-' + Math.random().toString(36).slice(2, 18);
            const item = record.type === 'bookmark' ? {
              id: localId, kind: 'bookmark', locator: data.locator, unit: data.unit || data.locator.split(':').slice(0, 4).join(':'),
              createdAt: timestamp(data.createdAt || record.updatedAt), ...(data.conflictOf ? { conflictOf: data.conflictOf } : {})
            } : {
              id: localId, kind: ['highlight', 'underline', 'memo'].includes(data.kind) ? data.kind : 'highlight',
              locator: data.locator, unit: data.unit || data.locator.split(':').slice(0, 4).join(':'),
              start: Number(data.startOffset || 0), end: Number(data.endOffset || 0), text: data.text || '',
              ...(data.color ? { color: data.color } : {}), ...(data.note ? { note: data.note } : {}), ...(data.conflictOf ? { conflictOf: data.conflictOf } : {}),
              createdAt: timestamp(data.createdAt || record.updatedAt)
            };
            const next = exactItems.filter((row) => row.id !== localId && recordId(record.type, row) !== record.id);
            next.push(item);
            setRecordMeta(record.type, localId, record.id, record.updatedAt);
            applyingRemote = true;
            try { exactStore.save(next); } finally { applyingRemote = false; }
            continue;
          }
        }
        const existing = annotations.find((item) => item.clientRecordId === record.id);
        const row = {
          ...(existing || {}), id: existing?.id || ('remote-' + record.id), clientRecordId: record.id,
          clientUpdatedAt: timestamp(record.updatedAt), context: data.context || '', page: Number(data.page || 0),
          verse: data.verse || '', source: (data.conflictOf ? '충돌 사본 · ' : '') + (data.source || data.context || ''),
          canonicalLocator: data.canonicalLocator || data.locator || null, text: data.text || '',
          type: record.type === 'bookmark' ? 'bookmark' : (data.color === 'underline' ? 'annot-line' : String(data.color || 'hl-yellow')),
          ...(data.conflictOf ? { conflictOf: data.conflictOf } : {})
        };
        if (existing) Object.assign(existing, row); else annotations.push(row);
        annotationsChanged = true;
        continue;
      }
      if (record.type === 'note') {
        if (record.deleted) {
          const before = notes.length;
          notes = notes.filter((item) => item.clientRecordId !== record.id);
          notesChanged ||= notes.length !== before;
          continue;
        }
        const existing = notes.find((item) => item.clientRecordId === record.id);
        const title = (data.conflictOf ? '[충돌 사본] ' : '') + (data.title || '내 메모');
        const row = {
          ...(existing || {}), id: existing?.id || ('remote-' + record.id), kind: 'note', clientRecordId: record.id,
          clientUpdatedAt: timestamp(record.updatedAt), context: data.context || '', page: Number(data.page || 0),
          source: data.source || data.context || '', quote: data.quote || '', title, body: data.body || '', updatedAt: timestamp(record.updatedAt),
          ...(data.conflictOf ? { conflictOf: data.conflictOf } : {})
        };
        if (existing) Object.assign(existing, row); else notes.push(row);
        notesChanged = true;
      }
    }
    if (annotationsChanged) {
      localStorage.setItem(ANNOTATIONS_KEY, JSON.stringify(annotations.slice(-80)));
      window.syncAnnotationStats?.();
      window.renderAnnotationMemoryList?.();
    }
    if (notesChanged) {
      localStorage.setItem(NOTES_KEY, JSON.stringify(notes.slice(-120)));
      window.renderUserMemoryList?.();
    }
    if ((annotationsChanged || notesChanged) && typeof window.scheduleUnifiedPersist === 'function') window.scheduleUnifiedPersist();
  }

  window.storyMemoryCollectLocalSyncRecords = collect;
  window.storyMemoryApplyRemoteSyncRecords = applyRemote;
})();
