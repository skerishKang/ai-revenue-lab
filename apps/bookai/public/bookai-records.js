/* Maps the reader's persisted shapes to COM2 record protocol v1. */
(function (root) {
  'use strict';
  const MEMORY = 'storymemory.userMemories.v1', ANN = 'storymemory.annotations.v2';
  const LAYER = 'storymemory.annotations.v1', PROGRESS = 'storymemory.readingProgress.v1';
  function shape(key) {
    if (key === MEMORY || key === ANN) return 'array';
    if (key === LAYER) return 'items';
    if (key === PROGRESS) return 'works';
    if (/^storymemory\.reader(Progress|Resume)\./.test(key)) return 'value';
    return null;
  }
  function parse(value, fallback) { try { return JSON.parse(value) || fallback; } catch (_) { return fallback; } }
  function identity(item, index) {
    return String(item.id || item.clientRecordId || ('legacy-' + index));
  }
  async function id(key, slot) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key + '\n' + slot));
    return 'bookai-' + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
  }
  function book(item, slot, locator) {
    if (item.book_id || item.bookId || item.current_work_key || item.contentId)
      return String(item.book_id || item.bookId || item.current_work_key || item.contentId);
    if (/^bible:/.test(locator)) return 'bible-web';
    if (locator.includes(':')) return locator.split(':')[0];
    return String(item.contentKey || item.book || item.context || slot || 'legacy');
  }
  async function records(key, raw) {
    const mode = shape(key);
    if (!mode || raw === null) return [];
    const data = parse(raw, null);
    if (!data || typeof data !== 'object') return [];
    let pairs;
    if (mode === 'array') pairs = Array.isArray(data) ? data.map((x, i) => [x && identity(x, i), x]) : [];
    else if (mode === 'items') pairs = Array.isArray(data.items) ? data.items.map((x, i) => [x && identity(x, i), x]) : [];
    else if (mode === 'works') pairs = Object.entries(data.works || {});
    else pairs = [['value', data]];
    return Promise.all(pairs.filter(([, x]) => x && typeof x === 'object').map(async ([slot, item]) => {
      const locator = String(item.canonicalLocator || item.canonical_locator || item.locator ||
        item.furthest_read_locator || item.context || item.unit || slot) +
        ((!item.locator && !item.canonicalLocator && Number.isInteger(item.page)) ? ':page:' + item.page : '');
      const kind = key === MEMORY ? (item.kind === 'ai' ? 'ai_chat' : 'note') :
        (key === ANN || key === LAYER) ? (item.kind === 'memo' ? 'note' : 'highlight') : 'progress';
      return {record_id: await id(key, slot), book_id: book(item, slot, locator), locator, kind,
        payload: {_bookai: {key, mode, slot}, value: item},
        updated_at: Math.max(0, Math.trunc(Number(item.updatedAt || item.clientUpdatedAt || item.createdAt) || 0)),
        deleted: false};
    }));
  }
  function valid(record) {
    const p = record && record.payload, meta = p && p._bookai;
    return !!(record && typeof record.record_id === 'string' && record.record_id &&
      typeof record.book_id === 'string' && record.book_id && typeof record.locator === 'string' && record.locator &&
      ['progress','note','highlight','ai_chat'].includes(record.kind) &&
      Number.isSafeInteger(record.updated_at) && record.updated_at >= 0 && typeof record.deleted === 'boolean' &&
      meta && typeof meta.key === 'string' && shape(meta.key) && shape(meta.key) === meta.mode && typeof meta.slot === 'string' &&
      p.value && typeof p.value === 'object' && !Array.isArray(p.value));
  }
  function apply(record, entries) {
    if (!valid(record)) throw new Error('invalid_bookai_record');
    const {key, mode, slot} = record.payload._bookai, item = record.payload.value;
    const data = parse(entries.get(key), mode === 'array' ? [] : mode === 'items' ? {version:1,items:[]} : {version:1,works:{}});
    if (mode === 'value') {
      if (record.deleted) entries.delete(key);
      else entries.set(key, JSON.stringify(item));
    } else if (mode === 'works') {
      if (!data.works || typeof data.works !== 'object') data.works = {};
      if (record.deleted) delete data.works[slot]; else data.works[slot] = item;
      entries.set(key, JSON.stringify(data));
    } else {
      const list = mode === 'array' ? data : data.items;
      if (!Array.isArray(list)) throw new Error('invalid_local_record_shape');
      const idx = list.findIndex((x, i) => x && identity(x, i) === slot);
      if (record.deleted) { if (idx >= 0) list.splice(idx, 1); }
      else if (idx >= 0) list[idx] = item; else list.push(item);
      entries.set(key, JSON.stringify(data));
    }
    // The old reader also maintains a session snapshot. Keep its copies aligned
    // so boot restoration cannot resurrect a remotely deleted note/highlight.
    const unified = parse(entries.get('storymemory.store.v1'), null);
    if (unified) {
      if (key === MEMORY) unified.memories = parse(entries.get(key), []);
      if (key === ANN) unified.annotations = parse(entries.get(key), []);
      if (key.startsWith('storymemory.readerProgress.')) {
        unified.progress = unified.progress || {};
        let context = key.slice('storymemory.readerProgress.'.length);
        try { context = decodeURIComponent(context); } catch (_) {}
        if (record.deleted) delete unified.progress[context];
        else unified.progress[context] = item;
      }
      entries.set('storymemory.store.v1', JSON.stringify(unified));
    }
  }

  // Replay only the edited items over the latest durable shape. A whole-array
  // save must not erase another device's independently added record.
  function patch(entries, key, before, after) {
    const mode=shape(key);
    if(!mode || mode==='value'){
      if(after===null)entries.delete(key);else entries.set(key,after);
      return;
    }
    function pairs(raw){
      const data=parse(raw,mode==='array'?[]:{});
      if(mode==='works')return Object.entries(data.works||{});
      const list=mode==='array'?data:data.items||[];
      return Array.isArray(list)?list.filter(x=>x&&typeof x==='object').map((x,i)=>[identity(x,i),x]):[];
    }
    const old=new Map(pairs(before)), next=new Map(pairs(after));
    for(const [slot,value] of next)if(JSON.stringify(old.get(slot))!==JSON.stringify(value))
      apply({record_id:'local',book_id:'local',locator:'local',kind:'note',updated_at:0,deleted:false,
        payload:{_bookai:{key,mode,slot},value}},entries);
    for(const [slot,value] of old)if(!next.has(slot))
      apply({record_id:'local',book_id:'local',locator:'local',kind:'note',updated_at:0,deleted:true,
        payload:{_bookai:{key,mode,slot},value}},entries);
  }
  root.BookAIRecords = Object.freeze({records, apply, valid, shape, patch});
})(window);
